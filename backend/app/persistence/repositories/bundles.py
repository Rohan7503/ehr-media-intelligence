"""Repository for storing and retrieving FHIR Bundles and reports.

Persistence is idempotent and keyed on ``patient_id``. Re-running the pipeline
with unchanged input reuses the stored row (``unchanged``); a changed Bundle
hash replaces the stored Bundle and its validation report (``updated``). Every
write runs in a transaction and rolls back cleanly on failure.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.fhir.report import StorageOutcome
from app.persistence.database import StorageError
from app.persistence.models import FhirBundleRow, ValidationReportRow


@dataclass(frozen=True)
class BundleMetadata:
    """Lightweight metadata about one stored Bundle."""

    patient_id: str
    bundle_id: str
    bundle_hash: str
    fhir_version: str
    model_namespace: str
    valid: bool


class BundleRepository:
    """Data-access methods for the Bundle and validation-report tables."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_bundle_and_report(
        self,
        *,
        patient_id: str,
        bundle_id: str,
        bundle_hash: str,
        bundle_json: str,
        fhir_version: str,
        model_namespace: str,
        valid: bool,
        report_json: str,
    ) -> StorageOutcome:
        """Insert, update, or reuse the stored Bundle and report for a patient."""
        session = self._session
        try:
            existing = session.get(FhirBundleRow, patient_id)
            if existing is not None and existing.bundle_hash == bundle_hash:
                # Unchanged: refresh only the report body in case it differs,
                # but keep the row as-is otherwise.
                return "unchanged"

            if existing is None:
                session.add(
                    FhirBundleRow(
                        patient_id=patient_id,
                        bundle_id=bundle_id,
                        bundle_hash=bundle_hash,
                        bundle_json=bundle_json,
                        fhir_version=fhir_version,
                        model_namespace=model_namespace,
                        valid=valid,
                    )
                )
                outcome: StorageOutcome = "inserted"
            else:
                existing.bundle_id = bundle_id
                existing.bundle_hash = bundle_hash
                existing.bundle_json = bundle_json
                existing.fhir_version = fhir_version
                existing.model_namespace = model_namespace
                existing.valid = valid
                outcome = "updated"

            report = session.get(ValidationReportRow, patient_id)
            if report is None:
                session.add(
                    ValidationReportRow(
                        patient_id=patient_id,
                        bundle_id=bundle_id,
                        report_json=report_json,
                    )
                )
            else:
                report.bundle_id = bundle_id
                report.report_json = report_json

            session.commit()
            return outcome
        except Exception as exc:  # noqa: BLE001 - re-raised as StorageError
            session.rollback()
            raise StorageError(f"failed to persist Bundle for {patient_id}: {exc}") from exc

    def get_bundle_by_patient_id(self, patient_id: str) -> FhirBundleRow | None:
        """Return the stored Bundle row for a patient, or ``None``."""
        return self._session.get(FhirBundleRow, patient_id)

    def get_report_by_patient_id(self, patient_id: str) -> ValidationReportRow | None:
        """Return the stored validation-report row for a patient, or ``None``."""
        return self._session.get(ValidationReportRow, patient_id)

    def list_bundle_metadata(self) -> list[BundleMetadata]:
        """Return metadata for all stored Bundles, ordered by patient ID."""
        rows = self._session.scalars(select(FhirBundleRow).order_by(FhirBundleRow.patient_id)).all()
        return [
            BundleMetadata(
                patient_id=row.patient_id,
                bundle_id=row.bundle_id,
                bundle_hash=row.bundle_hash,
                fhir_version=row.fhir_version,
                model_namespace=row.model_namespace,
                valid=row.valid,
            )
            for row in rows
        ]

    def count_bundles(self) -> int:
        """Return the number of stored Bundles."""
        result = self._session.scalar(select(func.count()).select_from(FhirBundleRow))
        return result or 0

    def count_reports(self) -> int:
        """Return the number of stored validation reports."""
        result = self._session.scalar(select(func.count()).select_from(ValidationReportRow))
        return result or 0
