"""FHIR pipeline: map, validate, persist, and optionally export Bundles.

Consumes the ingestion :class:`PipelineResult` (accepted patients and records
only, never mutated) and produces one Bundle per patient. Each Bundle is
validated by all layers and persisted idempotently. If one patient fails to
map or validate, the others still process; the aggregate report records the
failure.
"""

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.domain.patient import Patient
from app.domain.record import ClinicalRecord
from app.fhir.mapper import MappedBundle, map_patient_bundle
from app.fhir.report import (
    FHIRPipelineReport,
    PatientBundleValidation,
    StorageResult,
    ValidationIssue,
)
from app.fhir.validator import validate_bundle
from app.ingestion.pipeline import PipelineResult
from app.persistence.repositories.bundles import BundleRepository


def canonical_json(payload: dict[str, object]) -> str:
    """Compact, sorted JSON used for hashing and storage."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def pretty_json(payload: dict[str, object]) -> str:
    """Readable, sorted JSON with a trailing newline for file export."""
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _bundle_hash(canonical: str) -> str:
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_fhir_pipeline(
    ingestion: PipelineResult,
    *,
    session: Session,
    export_dir: Path | None = None,
) -> FHIRPipelineReport:
    """Map, validate, persist, and optionally export one Bundle per patient."""
    repository = BundleRepository(session)

    records_by_patient: dict[str, list[ClinicalRecord]] = defaultdict(list)
    for record in ingestion.records:
        records_by_patient[record.patient_id].append(record)

    if export_dir is not None:
        export_dir.mkdir(parents=True, exist_ok=True)

    report = FHIRPipelineReport(patient_count=len(ingestion.patients))
    resource_totals: dict[str, int] = defaultdict(int)

    for patient in sorted(ingestion.patients, key=lambda p: p.patient_id):
        patient_records = records_by_patient.get(patient.patient_id, [])
        mapped, validation = _map_and_validate(patient, patient_records)
        report.validations.append(validation)
        report.bundle_count += 1
        if validation.valid:
            report.valid_bundle_count += 1
        else:
            report.invalid_bundle_count += 1
        for resource_type, count in validation.resource_counts.items():
            resource_totals[resource_type] += count

        if mapped is None:
            # Mapping failed; the failure is recorded, nothing to persist.
            continue
        bundle_json = mapped.bundle.model_dump(mode="json", exclude_none=True)
        canonical = canonical_json(bundle_json)
        report_json = canonical_json(validation.model_dump(mode="json"))
        outcome = repository.upsert_bundle_and_report(
            patient_id=validation.patient_id,
            bundle_id=validation.bundle_id,
            bundle_hash=_bundle_hash(canonical),
            bundle_json=canonical,
            fhir_version=validation.fhir_version,
            model_namespace=validation.model_namespace,
            valid=validation.valid,
            report_json=report_json,
        )
        report.storage_results.append(
            StorageResult(
                patient_id=validation.patient_id,
                bundle_id=validation.bundle_id,
                outcome=outcome,
            )
        )
        if export_dir is not None:
            (export_dir / f"bundle_{validation.patient_id}.json").write_text(
                pretty_json(bundle_json), encoding="utf-8", newline="\n"
            )

    report.resource_totals = dict(sorted(resource_totals.items()))
    return report


def _map_and_validate(
    patient: Patient, records: list[ClinicalRecord]
) -> tuple[MappedBundle | None, PatientBundleValidation]:
    """Map and validate one patient's Bundle, converting failures to issues."""
    try:
        mapped = map_patient_bundle(patient, records)
    except ValidationError as exc:
        validation = PatientBundleValidation(
            patient_id=patient.patient_id,
            bundle_id="",
            valid=False,
            issues=[
                ValidationIssue(
                    severity="error",
                    code="mapping-failed",
                    message=f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}",
                    validator="fhir.resources",
                    location=".".join(str(p) for p in error["loc"]),
                )
                for error in exc.errors()
            ],
        )
        return None, validation
    return mapped, validate_bundle(mapped)
