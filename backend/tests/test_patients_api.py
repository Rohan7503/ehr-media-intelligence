"""API tests for GET /patients/{patient_id}."""

import base64
import json
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.patients import get_session
from app.domain.patient import Patient
from app.domain.record import ClinicalRecord, RecordType
from app.fhir.mapper import map_patient_bundle
from app.main import create_app
from app.persistence.repositories.bundles import BundleRepository
from app.summarization.cache import SummaryCacheKey, SummaryRepository
from app.summarization.summary import (
    Confidence,
    SummaryDraft,
    build_clinical_summary,
    render_summary,
)

PatientFactory = Callable[..., Patient]
RecordFactory = Callable[..., ClinicalRecord]

_NOTE_TEXT = "Patient stable on therapy.\nBP 128/82 at today's visit."


def _store_bundle(
    session: Session,
    patient: Patient,
    records: list[ClinicalRecord],
    *,
    bundle_hash: str = "hash-1",
    valid: bool = True,
) -> None:
    mapped = map_patient_bundle(patient, records)
    bundle_json = json.dumps(mapped.bundle.model_dump(mode="json", exclude_none=True))
    BundleRepository(session).upsert_bundle_and_report(
        patient_id=patient.patient_id,
        bundle_id=mapped.bundle_id,
        bundle_hash=bundle_hash,
        bundle_json=bundle_json,
        fhir_version="4.0.1",
        model_namespace="R4B",
        valid=valid,
        report_json="{}",
    )


def _store_summary(session: Session, patient_id: str, bundle_hash: str) -> None:
    draft = SummaryDraft(
        chief_concern="Hypertension follow-up",
        key_diagnoses=["Essential hypertension"],
        recent_media_records=["Not documented"],
        flagged_anomalies=["Not documented"],
        confidence=Confidence.MEDIUM,
        source_resource_ids=["res-1"],
    )
    summary = build_clinical_summary(patient_id, draft)
    SummaryRepository(session).store(
        SummaryCacheKey(patient_id, bundle_hash, "test-model", "clinical-summary-v1"),
        summary_json=summary.model_dump_json(),
        rendered_text=render_summary(summary),
        word_count=summary.word_count,
    )


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_patient_detail_success_with_summary(
    client: TestClient, session: Session, make_patient: PatientFactory, make_record: RecordFactory
) -> None:
    patient = make_patient()
    records = [
        make_record(record_id="D1", record_type=RecordType.DOCUMENT, text=_NOTE_TEXT),
        make_record(
            record_id="R1",
            record_type=RecordType.DIAGNOSTIC_REPORT,
            title="Lipid panel",
            encounter_id="ENC-1",
        ),
    ]
    _store_bundle(session, patient, records, bundle_hash="hash-1")
    _store_summary(session, patient.patient_id, "hash-1")

    response = client.get(f"/patients/{patient.patient_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["patient_id"] == patient.patient_id
    assert body["patient_name"] == "Avery Kestrel"
    assert body["mrn"] == "MRN-000123"
    assert body["date_of_birth"] == "1984-03-02"
    assert body["gender"] == "female"
    assert body["bundle_valid"] is True
    assert body["summary"]["chief_concern"] == "Hypertension follow-up"
    assert body["summary_confidence"] == "medium"
    assert body["summary_disclaimer"] == body["summary"]["disclaimer"]
    assert len(body["resources"]) == 2


def test_resource_text_is_readable_without_base64(
    client: TestClient, session: Session, make_patient: PatientFactory, make_record: RecordFactory
) -> None:
    patient = make_patient()
    _store_bundle(
        session, patient, [make_record(record_id="D1", text=_NOTE_TEXT)], bundle_hash="hash-1"
    )
    response = client.get(f"/patients/{patient.patient_id}")
    assert response.status_code == 200
    doc = next(r for r in response.json()["resources"] if r["resource_type"] == "DocumentReference")
    assert _NOTE_TEXT in doc["text"]
    encoded = base64.b64encode(_NOTE_TEXT.encode("utf-8")).decode("ascii")
    assert encoded not in json.dumps(response.json())


def test_missing_summary_returns_null(
    client: TestClient, session: Session, make_patient: PatientFactory, make_record: RecordFactory
) -> None:
    patient = make_patient()
    _store_bundle(session, patient, [make_record(record_id="D1")], bundle_hash="hash-1")
    response = client.get(f"/patients/{patient.patient_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["summary"] is None
    assert body["summary_confidence"] is None
    assert body["summary_disclaimer"] is None
    assert len(body["resources"]) == 1


def test_unknown_patient_returns_404(client: TestClient) -> None:
    response = client.get("/patients/PAT-UNKNOWN")
    assert response.status_code == 404
    assert response.json()["detail"] == "patient not found"


def test_invalid_bundle_is_treated_as_not_found(
    client: TestClient, session: Session, make_patient: PatientFactory, make_record: RecordFactory
) -> None:
    patient = make_patient()
    _store_bundle(session, patient, [make_record(record_id="D1")], valid=False)
    response = client.get(f"/patients/{patient.patient_id}")
    assert response.status_code == 404
