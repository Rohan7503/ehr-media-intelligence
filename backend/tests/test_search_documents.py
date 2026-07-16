"""Tests for deterministic index-document construction."""

import json
from collections.abc import Callable

from app.domain.patient import Patient
from app.domain.record import ClinicalRecord, RecordType
from app.fhir.mapper import map_patient_bundle
from app.search.documents import (
    KIND_RESOURCE,
    KIND_SUMMARY,
    build_resource_documents,
    build_summary_documents,
)
from app.summarization.cache_models import SummaryCacheRow

PatientFactory = Callable[..., Patient]
RecordFactory = Callable[..., ClinicalRecord]


def _bundle_json(patient: Patient, records: list[ClinicalRecord]) -> str:
    bundle = map_patient_bundle(patient, records).bundle
    return json.dumps(bundle.model_dump(mode="json", exclude_none=True))


def test_resource_documents_are_deterministic(
    make_patient: PatientFactory, make_record: RecordFactory
) -> None:
    records = [
        make_record(record_id="D1", record_type=RecordType.DOCUMENT, title="Chest X-ray note"),
        make_record(
            record_id="R1",
            record_type=RecordType.DIAGNOSTIC_REPORT,
            title="Lipid panel",
            encounter_id="ENC-1",
        ),
    ]
    bundle_json = _bundle_json(make_patient(), records)
    first = build_resource_documents("PAT-000123", "hash-1", bundle_json)
    second = build_resource_documents("PAT-000123", "hash-1", bundle_json)

    assert [d.doc_id for d in first] == [d.doc_id for d in second]
    assert all(d.doc_id.startswith("resource:") for d in first)
    assert [d.with_content_hash()["content_hash"] for d in first] == [
        d.with_content_hash()["content_hash"] for d in second
    ]
    doc = next(d for d in first if d.metadata["resource_type"] == "DocumentReference")
    assert doc.metadata["document_kind"] == KIND_RESOURCE
    assert doc.metadata["patient_id"] == "PAT-000123"
    assert doc.metadata["patient_name"] == "Avery Kestrel"
    assert doc.metadata["mrn"] == "MRN-000123"
    assert doc.metadata["bundle_hash"] == "hash-1"
    assert doc.metadata["record_date"] == "2024-05-01"
    # Readable text, not JSON or base64.
    assert "Chest X-ray note" in doc.text
    assert "eyJ" not in doc.text


def test_undated_resource_omits_record_date(
    make_patient: PatientFactory, make_record: RecordFactory
) -> None:
    bundle_json = _bundle_json(make_patient(), [make_record(record_id="D1", record_date=None)])
    docs = build_resource_documents("PAT-000123", "hash-1", bundle_json)
    assert "record_date" not in docs[0].metadata


def test_summary_documents_carry_required_metadata() -> None:
    row = SummaryCacheRow(
        patient_id="PAT-000123",
        record_hash="hash-1",
        model_name="claude-sonnet-5",
        prompt_version="clinical-summary-v1",
        summary_json="{}",
        rendered_text="Chief concern: hypertension.",
        word_count=3,
    )
    docs = build_summary_documents([row])
    assert len(docs) == 1
    doc = docs[0]
    assert doc.doc_id == ("summary:PAT-000123:hash-1:claude-sonnet-5:clinical-summary-v1")
    assert doc.metadata["document_kind"] == KIND_SUMMARY
    assert doc.metadata["bundle_hash"] == "hash-1"
    assert doc.metadata["model_name"] == "claude-sonnet-5"
    assert doc.metadata["prompt_version"] == "clinical-summary-v1"
    assert doc.text == "Chief concern: hypertension."
