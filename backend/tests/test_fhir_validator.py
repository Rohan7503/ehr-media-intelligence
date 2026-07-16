"""Tests for the three validation layers."""

import copy
from collections.abc import Callable

from app.domain.patient import Patient
from app.domain.record import ClinicalRecord, RecordType
from app.fhir.compatibility import check_bundle_compatibility
from app.fhir.mapper import MappedBundle, map_patient_bundle
from app.fhir.validator import (
    _validate_reference_integrity,
    count_resources,
    validate_bundle,
)

PatientFactory = Callable[..., Patient]
RecordFactory = Callable[..., ClinicalRecord]


def _mapped(make_patient: PatientFactory, make_record: RecordFactory) -> MappedBundle:
    records = [
        make_record(record_id="D1", record_type=RecordType.DOCUMENT),
        make_record(record_id="R1", record_type=RecordType.DIAGNOSTIC_REPORT, encounter_id="ENC-1"),
    ]
    return map_patient_bundle(make_patient(), records)


def _codes(mapped: MappedBundle, bundle_json: dict[str, object]) -> set[str]:
    return {issue.code for issue in _validate_reference_integrity(bundle_json, mapped)}


class TestValidBundle:
    def test_valid_bundle_has_no_issues(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        result = validate_bundle(_mapped(make_patient, make_record))
        assert result.valid
        assert result.issues == []

    def test_resource_counts(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        mapped = _mapped(make_patient, make_record)
        counts = count_resources(mapped.bundle.model_dump(mode="json", exclude_none=True))
        assert counts == {
            "Patient": 1,
            "Encounter": 1,
            "DocumentReference": 1,
            "DiagnosticReport": 1,
        }


class TestReferenceResolution:
    def test_subject_and_encounter_references_resolve(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        mapped = _mapped(make_patient, make_record)
        bundle_json = mapped.bundle.model_dump(mode="json", exclude_none=True)
        assert _codes(mapped, bundle_json) == set()

    def test_broken_subject_reference_detected(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        mapped = _mapped(make_patient, make_record)
        bundle_json = mapped.bundle.model_dump(mode="json", exclude_none=True)
        for entry in bundle_json["entry"]:
            resource = entry["resource"]
            if resource["resourceType"] == "DocumentReference":
                resource["subject"]["reference"] = "urn:uuid:00000000-0000-0000-0000-000000000000"
        assert "unresolved-subject" in _codes(mapped, bundle_json)

    def test_broken_encounter_reference_detected(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        mapped = _mapped(make_patient, make_record)
        bundle_json = mapped.bundle.model_dump(mode="json", exclude_none=True)
        for entry in bundle_json["entry"]:
            resource = entry["resource"]
            if resource["resourceType"] == "DiagnosticReport":
                resource["encounter"]["reference"] = "urn:uuid:11111111-1111-1111-1111-111111111111"
        assert "unresolved-encounter" in _codes(mapped, bundle_json)

    def test_duplicate_resource_id_detected(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        mapped = _mapped(make_patient, make_record)
        bundle_json = mapped.bundle.model_dump(mode="json", exclude_none=True)
        entries = bundle_json["entry"]
        entries.append(copy.deepcopy(entries[1]))
        codes = _codes(mapped, bundle_json)
        assert "duplicate-resource-id" in codes
        assert "duplicate-fullurl" in codes

    def test_missing_resource_id_detected(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        mapped = _mapped(make_patient, make_record)
        bundle_json = mapped.bundle.model_dump(mode="json", exclude_none=True)
        del bundle_json["entry"][1]["resource"]["id"]
        assert "missing-resource-id" in _codes(mapped, bundle_json)

    def test_unexpected_clinical_resource_detected(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        mapped = _mapped(make_patient, make_record)
        bundle_json = mapped.bundle.model_dump(mode="json", exclude_none=True)
        extra = copy.deepcopy(bundle_json["entry"][-1])
        extra["resource"]["id"] = "99999999-9999-5999-9999-999999999999"
        extra["fullUrl"] = "urn:uuid:99999999-9999-5999-9999-999999999999"
        bundle_json["entry"].append(extra)
        codes = _codes(mapped, bundle_json)
        assert "unexpected-clinical-resource" in codes


class TestLibraryValidation:
    def test_pydantic_validation_error_becomes_structured_issue(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        from app.fhir.validator import _validate_with_library

        mapped = _mapped(make_patient, make_record)
        bundle_json = mapped.bundle.model_dump(mode="json", exclude_none=True)
        # Corrupt a required field so library re-validation fails.
        for entry in bundle_json["entry"]:
            if entry["resource"]["resourceType"] == "DiagnosticReport":
                del entry["resource"]["code"]
        issues = _validate_with_library(bundle_json)
        assert issues
        assert all(issue.validator == "fhir.resources" for issue in issues)
        assert all(issue.severity == "error" for issue in issues)


class TestR4CompatibilityGuard:
    def test_clean_bundle_passes_guard(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        mapped = _mapped(make_patient, make_record)
        bundle_json = mapped.bundle.model_dump(mode="json", exclude_none=True)
        assert check_bundle_compatibility(bundle_json) == []

    def test_disallowed_field_rejected(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        mapped = _mapped(make_patient, make_record)
        bundle_json = mapped.bundle.model_dump(mode="json", exclude_none=True)
        bundle_json["entry"][0]["resource"]["instantiatesCanonical"] = ["x"]
        issues = check_bundle_compatibility(bundle_json)
        assert any(issue.code == "disallowed-field" for issue in issues)
        assert all(issue.validator == "r4_compatibility" for issue in issues)

    def test_unsupported_resource_type_rejected(
        self, make_patient: PatientFactory, make_record: RecordFactory
    ) -> None:
        mapped = _mapped(make_patient, make_record)
        bundle_json = mapped.bundle.model_dump(mode="json", exclude_none=True)
        bundle_json["entry"][0]["resource"]["resourceType"] = "Practitioner"
        issues = check_bundle_compatibility(bundle_json)
        assert any(issue.code == "unsupported-resource-type" for issue in issues)
