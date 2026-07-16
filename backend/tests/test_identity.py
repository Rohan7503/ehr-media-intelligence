"""Unit tests for conservative patient identity resolution."""

from datetime import date

import pytest

from app.domain.patient import Gender
from app.ingestion.identity import (
    IdentityConflictError,
    IdentityRegistry,
    PatientCandidate,
)


def _candidate(**overrides: object) -> PatientCandidate:
    base: dict[str, object] = {
        "mrn": "MRN-000123",
        "source_patient_id": "SRC-1",
        "given_name": "Avery",
        "family_name": "Kestrel",
        "birth_date": date(1984, 3, 2),
        "gender": Gender.FEMALE,
    }
    base.update(overrides)
    return PatientCandidate(**base)  # type: ignore[arg-type]


def test_same_mrn_resolves_to_same_patient() -> None:
    registry = IdentityRegistry()
    first = registry.resolve(_candidate(), source_file="a.json", source_record_id="R1")
    second = registry.resolve(_candidate(), source_file="b.csv", source_record_id="R2")
    assert first is second
    assert first.patient_id == "PAT-000123"


def test_source_patient_id_with_two_mrns_is_a_conflict() -> None:
    registry = IdentityRegistry()
    registry.resolve(_candidate(), source_file="a.json", source_record_id="R1")
    with pytest.raises(IdentityConflictError) as excinfo:
        registry.resolve(_candidate(mrn="MRN-000456"), source_file="b.csv", source_record_id="R2")
    conflict = excinfo.value.conflict
    assert conflict.conflict_type == "source_patient_id_mrn_mismatch"
    assert conflict.existing_mrn == "MRN-000123"
    assert conflict.mrn == "MRN-000456"


def test_mrn_with_different_birth_date_is_a_conflict() -> None:
    registry = IdentityRegistry()
    registry.resolve(_candidate(), source_file="a.json", source_record_id="R1")
    with pytest.raises(IdentityConflictError) as excinfo:
        registry.resolve(
            _candidate(source_patient_id="SRC-2", birth_date=date(1990, 1, 1)),
            source_file="b.csv",
            source_record_id="R2",
        )
    assert excinfo.value.conflict.conflict_type == "mrn_demographics_mismatch"


def test_mrn_with_different_family_name_is_a_conflict() -> None:
    registry = IdentityRegistry()
    registry.resolve(_candidate(), source_file="a.json", source_record_id="R1")
    with pytest.raises(IdentityConflictError):
        registry.resolve(
            _candidate(source_patient_id="SRC-2", family_name="Voss"),
            source_file="b.csv",
            source_record_id="R2",
        )


def test_conflict_leaves_registry_unchanged() -> None:
    registry = IdentityRegistry()
    registry.resolve(_candidate(), source_file="a.json", source_record_id="R1")
    with pytest.raises(IdentityConflictError):
        registry.resolve(_candidate(mrn="MRN-000456"), source_file="b.csv", source_record_id="R2")
    assert len(registry.patients()) == 1


def test_compatible_records_backfill_missing_demographics() -> None:
    registry = IdentityRegistry()
    patient = registry.resolve(
        _candidate(birth_date=None, gender=Gender.UNKNOWN),
        source_file="a.json",
        source_record_id="R1",
    )
    assert patient.birth_date is None
    registry.resolve(_candidate(), source_file="b.csv", source_record_id="R2")
    assert patient.birth_date == date(1984, 3, 2)
    assert patient.gender is Gender.FEMALE
    rules = [entry.rule for entry in patient.audit]
    assert rules.count("patient.field_backfilled") >= 2


def test_gender_mismatch_is_audited_not_merged() -> None:
    registry = IdentityRegistry()
    patient = registry.resolve(_candidate(), source_file="a.json", source_record_id="R1")
    registry.resolve(_candidate(gender=Gender.MALE), source_file="b.csv", source_record_id="R2")
    assert patient.gender is Gender.FEMALE
    assert any(entry.rule == "gender.mismatch_ignored" for entry in patient.audit)


def test_identical_names_with_different_mrns_never_merge() -> None:
    registry = IdentityRegistry()
    registry.resolve(
        _candidate(source_patient_id=None), source_file="a.json", source_record_id="R1"
    )
    registry.resolve(
        _candidate(source_patient_id=None, mrn="MRN-000999"),
        source_file="b.csv",
        source_record_id="R2",
    )
    assert len(registry.patients()) == 2


def test_new_source_patient_id_is_recorded() -> None:
    registry = IdentityRegistry()
    patient = registry.resolve(_candidate(), source_file="a.json", source_record_id="R1")
    registry.resolve(
        _candidate(source_patient_id="SRC-9"), source_file="b.csv", source_record_id="R2"
    )
    assert patient.source_patient_ids == ["SRC-1", "SRC-9"]
