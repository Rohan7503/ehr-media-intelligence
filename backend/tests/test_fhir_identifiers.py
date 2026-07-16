"""Tests for deterministic FHIR identifiers and full URLs."""

import re
from collections.abc import Callable

from app.domain.patient import Patient
from app.domain.record import ClinicalRecord, RecordType
from app.fhir.identifiers import (
    encounter_resource_id,
    full_url,
    patient_resource_id,
    record_resource_id,
)

PatientFactory = Callable[..., Patient]
RecordFactory = Callable[..., ClinicalRecord]

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$")
_FHIR_ID_RE = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")


def test_patient_id_is_deterministic_uuid5() -> None:
    first = patient_resource_id("PAT-000123")
    second = patient_resource_id("PAT-000123")
    assert first == second
    assert _UUID_RE.match(first)
    assert _FHIR_ID_RE.match(first)


def test_distinct_inputs_produce_distinct_ids() -> None:
    assert patient_resource_id("PAT-000123") != patient_resource_id("PAT-000456")
    assert encounter_resource_id("PAT-1", "ENC-1") != encounter_resource_id("PAT-1", "ENC-2")


def test_document_and_diagnostic_ids_never_collide(make_record: RecordFactory) -> None:
    doc = make_record(record_id="X", record_type=RecordType.DOCUMENT)
    diag = make_record(record_id="X", record_type=RecordType.DIAGNOSTIC_REPORT)
    assert record_resource_id(doc) != record_resource_id(diag)


def test_full_url_is_urn_uuid(make_patient: PatientFactory) -> None:
    resource_id = patient_resource_id("PAT-000123")
    assert full_url(resource_id) == f"urn:uuid:{resource_id}"
