"""Service-level tests for cached summarization with a fake provider."""

import json
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.domain.patient import Patient
from app.domain.record import ClinicalRecord
from app.fhir.mapper import map_patient_bundle
from app.persistence.repositories.bundles import BundleRepository
from app.summarization.cache import SummaryRepository
from app.summarization.errors import ProviderError
from app.summarization.service import SummarizationService
from app.summarization.summary import NOT_DOCUMENTED

PatientFactory = Callable[..., Patient]
RecordFactory = Callable[..., ClinicalRecord]

MODEL = "test-model"


class FakeProvider:
    """Records call count and returns a preset structured response."""

    def __init__(self, response: dict[str, Any] | None = None, error: Exception | None = None):
        self._response = response or {}
        self._error = error
        self.calls = 0

    def generate(self, *, system: str, user: str) -> dict[str, Any]:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return dict(self._response)


def _store_bundle(
    session: Session,
    patient: Patient,
    records: list[ClinicalRecord],
    *,
    bundle_hash: str = "hash-1",
) -> tuple[str, list[str]]:
    mapped = map_patient_bundle(patient, records)
    bundle_json = json.dumps(mapped.bundle.model_dump(mode="json", exclude_none=True))
    resource_ids = [entry["resource"]["id"] for entry in json.loads(bundle_json)["entry"]]
    BundleRepository(session).upsert_bundle_and_report(
        patient_id=patient.patient_id,
        bundle_id=mapped.bundle_id,
        bundle_hash=bundle_hash,
        bundle_json=bundle_json,
        fhir_version="4.0.1",
        model_namespace="R4B",
        valid=True,
        report_json="{}",
    )
    return bundle_hash, resource_ids


def _good_response(cited: str) -> dict[str, Any]:
    return {
        "chief_concern": "Hypertension follow-up",
        "key_diagnoses": ["Essential hypertension"],
        "recent_media_records": [NOT_DOCUMENTED],
        "flagged_anomalies": [NOT_DOCUMENTED],
        "confidence": "medium",
        "source_resource_ids": [cited],
    }


def _service(session: Session, provider: FakeProvider) -> SummarizationService:
    return SummarizationService(session=session, provider=provider, model_name=MODEL)


def test_cache_miss_generates_and_stores(
    session: Session, make_patient: PatientFactory, make_record: RecordFactory
) -> None:
    patient = make_patient()
    _, resource_ids = _store_bundle(session, patient, [make_record(record_id="D1")])
    provider = FakeProvider(_good_response(resource_ids[0]))

    result = _service(session, provider).summarize_patient(patient.patient_id)

    assert result.status == "generated"
    assert provider.calls == 1
    assert result.summary is not None
    assert SummaryRepository(session).count() == 1


def test_cache_hit_avoids_provider_call(
    session: Session, make_patient: PatientFactory, make_record: RecordFactory
) -> None:
    patient = make_patient()
    _, resource_ids = _store_bundle(session, patient, [make_record(record_id="D1")])
    first_provider = FakeProvider(_good_response(resource_ids[0]))
    _service(session, first_provider).summarize_patient(patient.patient_id)

    second_provider = FakeProvider(_good_response(resource_ids[0]))
    result = _service(session, second_provider).summarize_patient(patient.patient_id)

    assert result.status == "cached"
    assert second_provider.calls == 0


def test_bundle_hash_change_regenerates(
    session: Session, make_patient: PatientFactory, make_record: RecordFactory
) -> None:
    patient = make_patient()
    _, resource_ids = _store_bundle(
        session, patient, [make_record(record_id="D1")], bundle_hash="hash-1"
    )
    provider = FakeProvider(_good_response(resource_ids[0]))
    _service(session, provider).summarize_patient(patient.patient_id)

    # A new Bundle hash for the same patient must trigger regeneration and keep
    # the historical cache row.
    _, new_ids = _store_bundle(
        session, patient, [make_record(record_id="D1")], bundle_hash="hash-2"
    )
    provider2 = FakeProvider(_good_response(new_ids[0]))
    result = _service(session, provider2).summarize_patient(patient.patient_id)

    assert result.status == "generated"
    assert provider2.calls == 1
    assert SummaryRepository(session).count() == 2


def test_word_limit_rejection_not_cached(
    session: Session, make_patient: PatientFactory, make_record: RecordFactory
) -> None:
    patient = make_patient()
    _, resource_ids = _store_bundle(session, patient, [make_record(record_id="D1")])
    huge = _good_response(resource_ids[0])
    huge["chief_concern"] = " ".join(["word"] * 210)
    provider = FakeProvider(huge)

    result = _service(session, provider).summarize_patient(patient.patient_id)

    assert result.status == "failed"
    assert result.error is not None and "limit" in result.error
    assert SummaryRepository(session).count() == 0


def test_malformed_response_reported_cleanly(
    session: Session, make_patient: PatientFactory, make_record: RecordFactory
) -> None:
    patient = make_patient()
    _store_bundle(session, patient, [make_record(record_id="D1")])
    # Missing required fields -> schema validation fails.
    provider = FakeProvider({"chief_concern": "only this"})

    result = _service(session, provider).summarize_patient(patient.patient_id)

    assert result.status == "failed"
    assert result.error is not None and "schema" in result.error
    assert SummaryRepository(session).count() == 0


def test_provider_error_reported_cleanly(
    session: Session, make_patient: PatientFactory, make_record: RecordFactory
) -> None:
    patient = make_patient()
    _store_bundle(session, patient, [make_record(record_id="D1")])
    provider = FakeProvider(error=ProviderError("Anthropic rate limit exceeded"))

    result = _service(session, provider).summarize_patient(patient.patient_id)

    assert result.status == "failed"
    assert result.error is not None and "rate limit" in result.error


def test_invalid_cited_ids_fail_quality(
    session: Session, make_patient: PatientFactory, make_record: RecordFactory
) -> None:
    patient = make_patient()
    _store_bundle(session, patient, [make_record(record_id="D1")])
    provider = FakeProvider(_good_response("nonexistent-id"))

    result = _service(session, provider).summarize_patient(patient.patient_id)

    assert result.status == "failed"
    assert result.quality is not None and not result.quality.valid
    assert SummaryRepository(session).count() == 0


def test_full_flow_with_report(
    session: Session, make_patient: PatientFactory, make_record: RecordFactory
) -> None:
    patient_a = make_patient(patient_id="PAT-000123", mrn="MRN-000123")
    patient_b = make_patient(patient_id="PAT-000456", mrn="MRN-000456")
    _, ids_a = _store_bundle(session, patient_a, [make_record(record_id="A1")])
    _store_bundle(session, patient_b, [make_record(record_id="B1", patient_id="PAT-000456")])
    # The provider cites a resource from A's bundle for both patients. B's own
    # bundle lacks that id, so B fails its citation check while A succeeds —
    # demonstrating per-patient outcomes and continuation after one failure.
    provider = FakeProvider(_good_response(ids_a[0]))
    report = _service(session, provider).summarize([patient_a.patient_id, patient_b.patient_id])

    assert report.generated == 1
    assert report.failed == 1
    statuses = {r.patient_id: r.status for r in report.results}
    assert statuses["PAT-000123"] == "generated"
    assert statuses["PAT-000456"] == "failed"


def test_skips_patient_without_valid_bundle(session: Session) -> None:
    provider = FakeProvider(_good_response("x"))
    result = _service(session, provider).summarize_patient("PAT-UNKNOWN")
    assert result.status == "skipped"
    assert provider.calls == 0
