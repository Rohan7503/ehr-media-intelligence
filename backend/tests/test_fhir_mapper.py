"""Tests for canonical-to-FHIR resource mapping."""

import base64
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from app.domain.patient import Gender, Patient
from app.domain.record import ClinicalRecord, RecordType
from app.fhir import constants
from app.fhir.mapper import (
    map_diagnostic_report,
    map_document_reference,
    map_encounter,
    map_patient,
    map_patient_bundle,
)

PatientFactory = Callable[..., Patient]
RecordFactory = Callable[..., ClinicalRecord]


def _dump(resource: Any) -> dict[str, Any]:
    dumped: dict[str, Any] = resource.model_dump(mode="json", exclude_none=True)
    return dumped


class TestPatientMapping:
    def test_complete_demographics(self, make_patient: PatientFactory) -> None:
        result = _dump(map_patient(make_patient()))
        assert result["resourceType"] == "Patient"
        assert result["gender"] == "female"
        assert result["birthDate"] == "1984-03-02"
        assert result["name"][0]["family"] == "Kestrel"
        assert result["name"][0]["given"] == ["Avery"]

    def test_missing_optional_demographics_are_omitted(self, make_patient: PatientFactory) -> None:
        patient = make_patient(
            given_name=None, family_name=None, birth_date=None, gender=Gender.UNKNOWN
        )
        result = _dump(map_patient(patient))
        assert "name" not in result
        assert "birthDate" not in result
        assert result["gender"] == "unknown"

    def test_mrn_identifier_mapping(self, make_patient: PatientFactory) -> None:
        result = _dump(map_patient(make_patient()))
        identifier = result["identifier"][0]
        assert identifier["system"] == constants.MRN_SYSTEM
        assert identifier["value"] == "MRN-000123"
        assert identifier["type"]["coding"][0]["code"] == "MR"

    def test_only_given_name_present(self, make_patient: PatientFactory) -> None:
        result = _dump(map_patient(make_patient(family_name=None)))
        assert result["name"][0]["given"] == ["Avery"]
        assert "family" not in result["name"][0]


class TestEncounterMapping:
    def test_period_spans_earliest_to_latest_record_date(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        records = [
            make_record(record_id="A", record_date=date(2024, 5, 1), encounter_id="ENC-1"),
            make_record(record_id="B", record_date=date(2024, 3, 2), encounter_id="ENC-1"),
            make_record(
                record_id="C", record_date=datetime(2024, 6, 9, 10, 0), encounter_id="ENC-1"
            ),
        ]
        result = _dump(map_encounter(make_patient(), "ENC-1", records))
        assert result["status"] == "finished"
        assert result["class"]["code"] == "AMB"
        assert result["period"] == {"start": "2024-03-02", "end": "2024-06-09"}
        assert result["subject"]["reference"].startswith("urn:uuid:")

    def test_period_omitted_when_no_record_has_a_date(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        records = [make_record(record_id="A", record_date=None, encounter_id="ENC-1")]
        result = _dump(map_encounter(make_patient(), "ENC-1", records))
        assert "period" not in result

    def test_encounters_created_once_per_unique_id(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        records = [
            make_record(record_id="A", encounter_id="ENC-1"),
            make_record(record_id="B", encounter_id="ENC-1"),
            make_record(
                record_id="C", encounter_id="ENC-2", record_type=RecordType.DIAGNOSTIC_REPORT
            ),
        ]
        bundle = _dump(map_patient_bundle(make_patient(), records).bundle)
        encounters = [
            e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Encounter"
        ]
        assert len(encounters) == 2


class TestDocumentReferenceMapping:
    def test_document_mapping_fields(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        record = make_record(encounter_id="ENC-1", title="Primary care follow-up")
        result = _dump(map_document_reference(make_patient(), record, encounter_id="ENC-1"))
        assert result["resourceType"] == "DocumentReference"
        assert result["status"] == "current"
        assert result["type"]["text"] == "Primary care follow-up"
        assert result["subject"]["reference"].startswith("urn:uuid:")
        assert result["context"]["period"]["start"] == "2024-05-01"
        assert result["context"]["encounter"][0]["reference"].startswith("urn:uuid:")

    def test_attachment_base64_round_trip(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        text = "Line one.\nBP: 132/84 recorded.\nLine three."
        record = make_record(text=text, title="Note")
        result = _dump(map_document_reference(make_patient(), record, encounter_id=None))
        attachment = result["content"][0]["attachment"]
        assert attachment["contentType"] == "text/plain"
        assert attachment["title"] == "Note"
        decoded = base64.b64decode(attachment["data"]).decode("utf-8")
        assert decoded == text

    def test_document_without_date_or_encounter_has_no_context(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        record = make_record(record_date=None, encounter_id=None)
        result = _dump(map_document_reference(make_patient(), record, encounter_id=None))
        assert "context" not in result


class TestDiagnosticReportMapping:
    def test_diagnostic_mapping_fields(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        record = make_record(
            record_type=RecordType.DIAGNOSTIC_REPORT,
            title="Lipid panel",
            diagnostic_code="LIPID",
            encounter_id="ENC-9",
            text="Fasting lipid panel processed.",
        )
        result = _dump(map_diagnostic_report(make_patient(), record, encounter_id="ENC-9"))
        assert result["resourceType"] == "DiagnosticReport"
        assert result["status"] == "final"
        assert result["code"]["text"] == "Lipid panel"
        assert result["effectiveDateTime"] == "2024-05-01"
        assert result["conclusion"] == "Fasting lipid panel processed."
        assert result["encounter"]["reference"].startswith("urn:uuid:")

    def test_source_diagnostic_code_preserved_without_terminology_claim(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        record = make_record(record_type=RecordType.DIAGNOSTIC_REPORT, diagnostic_code="CMP")
        result = _dump(map_diagnostic_report(make_patient(), record, encounter_id=None))
        identifier = result["identifier"][0]
        assert identifier["system"] == constants.SOURCE_DIAGNOSTIC_CODE_SYSTEM
        assert identifier["value"] == "CMP"
        # code carries the human title as text only, no external coding system.
        assert "coding" not in result["code"]

    def test_diagnostic_without_date_or_encounter(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        record = make_record(
            record_type=RecordType.DIAGNOSTIC_REPORT, record_date=None, encounter_id=None
        )
        result = _dump(map_diagnostic_report(make_patient(), record, encounter_id=None))
        assert "effectiveDateTime" not in result
        assert "encounter" not in result


class TestBundleMapping:
    def test_one_bundle_per_patient_with_all_resources(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        records = [
            make_record(record_id="D1", record_type=RecordType.DOCUMENT),
            make_record(
                record_id="R1", record_type=RecordType.DIAGNOSTIC_REPORT, encounter_id="ENC-1"
            ),
        ]
        mapped = map_patient_bundle(make_patient(), records)
        bundle = _dump(mapped.bundle)
        assert bundle["type"] == "collection"
        types = [e["resource"]["resourceType"] for e in bundle["entry"]]
        assert types.count("Patient") == 1
        assert types.count("DocumentReference") == 1
        assert types.count("DiagnosticReport") == 1
        assert types.count("Encounter") == 1
        assert len(mapped.expected_record_ids) == 2

    def test_deterministic_ordering(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        records = [
            make_record(
                record_id="LATE", record_date=date(2024, 12, 1), record_type=RecordType.DOCUMENT
            ),
            make_record(
                record_id="UNDATED",
                record_date=None,
                record_type=RecordType.DOCUMENT,
                encounter_id="ENC-1",
            ),
            make_record(
                record_id="EARLY",
                record_date=date(2024, 1, 1),
                record_type=RecordType.DIAGNOSTIC_REPORT,
                encounter_id="ENC-1",
            ),
        ]
        bundle = _dump(map_patient_bundle(make_patient(), records).bundle)
        types = [e["resource"]["resourceType"] for e in bundle["entry"]]
        assert types[0] == "Patient"
        assert types[1] == "Encounter"
        # Clinical resources: dated (EARLY 2024-01, LATE 2024-12) then undated.
        clinical = [
            e["resource"]
            for e in bundle["entry"][2:]
            if e["resource"]["resourceType"] != "Encounter"
        ]
        titles = [
            r.get("effectiveDateTime") or r.get("context", {}).get("period", {}).get("start")
            for r in clinical
        ]
        assert titles == ["2024-01-01", "2024-12-01", None]

    def test_bundle_is_byte_identical_across_runs(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        records = [make_record(record_id="D1"), make_record(record_id="D2", title="Second")]
        first = _dump(map_patient_bundle(make_patient(), records).bundle)
        second = _dump(map_patient_bundle(make_patient(), records).bundle)
        assert first == second
