"""Tests for the FHIR pipeline orchestration."""

from collections.abc import Callable

import pytest
from fhir.resources.R4B.patient import Patient as FHIRPatient
from sqlalchemy.orm import Session

import app.fhir.pipeline as pipeline_module
from app.domain.patient import Patient
from app.domain.record import ClinicalRecord, RecordType
from app.fhir.mapper import map_patient_bundle
from app.fhir.pipeline import run_fhir_pipeline
from app.ingestion.pipeline import PipelineCounts, PipelineResult

PatientFactory = Callable[..., Patient]
RecordFactory = Callable[..., ClinicalRecord]


def _ingestion(patients: list[Patient], records: list[ClinicalRecord]) -> PipelineResult:
    counts = PipelineCounts(
        files_processed=1,
        files_skipped=0,
        files_failed=0,
        raw_records=len(records),
        accepted_patients=len(patients),
        accepted_records=len(records),
        duplicate_records=0,
        rejected_records=0,
        identity_conflicts=0,
    )
    return PipelineResult(
        patients=patients,
        records=records,
        duplicates=[],
        rejected=[],
        conflicts=[],
        skipped_files=[],
        file_errors=[],
        counts=counts,
    )


def test_one_bundle_per_patient_and_counts(
    session: Session, make_patient: PatientFactory, make_record: RecordFactory
) -> None:
    patient_a = make_patient(patient_id="PAT-000123", mrn="MRN-000123")
    patient_b = make_patient(patient_id="PAT-000456", mrn="MRN-000456")
    records = [
        make_record(record_id="A1", patient_id="PAT-000123"),
        make_record(
            record_id="B1",
            patient_id="PAT-000456",
            record_type=RecordType.DIAGNOSTIC_REPORT,
            encounter_id="ENC-1",
        ),
    ]
    report = run_fhir_pipeline(_ingestion([patient_a, patient_b], records), session=session)
    assert report.bundle_count == 2
    assert report.valid_bundle_count == 2
    assert report.invalid_bundle_count == 0
    assert report.resource_totals["Patient"] == 2
    assert report.resource_totals["DocumentReference"] == 1
    assert report.resource_totals["DiagnosticReport"] == 1
    assert len(report.storage_results) == 2


def test_pipeline_continues_when_one_patient_fails(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    make_patient: PatientFactory,
    make_record: RecordFactory,
) -> None:
    good = make_patient(patient_id="PAT-000123", mrn="MRN-000123")
    bad = make_patient(patient_id="PAT-000999", mrn="MRN-000999")
    records = [
        make_record(record_id="G1", patient_id="PAT-000123"),
        make_record(record_id="X1", patient_id="PAT-000999"),
    ]

    def flaky(patient: Patient, recs: list[ClinicalRecord]) -> object:
        if patient.patient_id == "PAT-000999":
            FHIRPatient(birthDate="not-a-date")  # raises a real ValidationError
        return map_patient_bundle(patient, recs)

    monkeypatch.setattr(pipeline_module, "map_patient_bundle", flaky)

    report = run_fhir_pipeline(_ingestion([good, bad], records), session=session)
    assert report.bundle_count == 2
    assert report.valid_bundle_count == 1
    assert report.invalid_bundle_count == 1
    # The good patient was still stored; the failing one was not.
    assert len(report.storage_results) == 1
    failing = next(v for v in report.validations if v.patient_id == "PAT-000999")
    assert not failing.valid
    assert any(issue.code == "mapping-failed" for issue in failing.issues)


def test_pipeline_does_not_mutate_ingestion_result(
    session: Session, make_patient: PatientFactory, make_record: RecordFactory
) -> None:
    ingestion = _ingestion([make_patient()], [make_record(record_id="A1")])
    before = ingestion.model_dump(mode="json")
    run_fhir_pipeline(ingestion, session=session)
    assert ingestion.model_dump(mode="json") == before
