"""Tests for deterministic FHIR evidence extraction."""

import json
from collections.abc import Callable

from app.domain.patient import Patient
from app.domain.record import ClinicalRecord, RecordType
from app.fhir.mapper import map_patient_bundle
from app.summarization.evidence import extract_patient_evidence

PatientFactory = Callable[..., Patient]
RecordFactory = Callable[..., ClinicalRecord]


def _bundle_json(patient: Patient, records: list[ClinicalRecord]) -> str:
    bundle = map_patient_bundle(patient, records).bundle
    return json.dumps(bundle.model_dump(mode="json", exclude_none=True))


def test_extracts_decoded_text_and_retains_ids(
    make_patient: PatientFactory, make_record: RecordFactory
) -> None:
    records = [
        make_record(
            record_id="D1",
            record_type=RecordType.DOCUMENT,
            title="Primary care follow-up",
            text="Patient stable.\nBP 128/82.",
        ),
        make_record(
            record_id="R1",
            record_type=RecordType.DIAGNOSTIC_REPORT,
            title="Lipid panel",
            text="Fasting lipid panel processed.",
            encounter_id="ENC-1",
        ),
    ]
    evidence = extract_patient_evidence("PAT-000123", _bundle_json(make_patient(), records))

    assert evidence.patient_id == "PAT-000123"
    assert {r.resource_type for r in evidence.records} == {
        "DocumentReference",
        "DiagnosticReport",
    }
    doc = next(r for r in evidence.records if r.resource_type == "DocumentReference")
    assert doc.text == "Patient stable.\nBP 128/82."
    assert doc.title == "Primary care follow-up"
    assert doc.date == "2024-05-01"
    diag = next(r for r in evidence.records if r.resource_type == "DiagnosticReport")
    assert diag.text == "Fasting lipid panel processed."
    # Patient + Encounter + 2 clinical resources are all recorded for citation.
    assert len(evidence.resource_ids) == 4


def test_no_base64_payload_leaks_into_evidence(
    make_patient: PatientFactory, make_record: RecordFactory
) -> None:
    bundle_json = _bundle_json(
        make_patient(), [make_record(record_id="D1", text="Readable note text.")]
    )
    evidence = extract_patient_evidence("PAT-000123", bundle_json)
    serialized = evidence.model_dump_json()
    # The raw base64 attachment data must not appear in the compact evidence.
    import base64

    encoded = base64.b64encode(b"Readable note text.").decode("ascii")
    assert encoded not in serialized
    assert "Readable note text." in serialized
