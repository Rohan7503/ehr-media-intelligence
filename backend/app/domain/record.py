"""Canonical clinical record model."""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.domain.audit import AuditEntry


class SourceFormat(StrEnum):
    """Format of the source file a record was ingested from."""

    JSON = "json"
    CSV = "csv"
    TEXT = "text"


class RecordType(StrEnum):
    """Kind of clinical record.

    ``DOCUMENT`` records will later map to FHIR DocumentReference resources;
    ``DIAGNOSTIC_REPORT`` records will later map to FHIR DiagnosticReport
    resources. No FHIR resources are created during ingestion.
    """

    DOCUMENT = "document"
    DIAGNOSTIC_REPORT = "diagnostic_report"


class ClinicalRecord(BaseModel):
    """A normalized clinical record linked to a canonical patient.

    ``fingerprint`` is a SHA-256 hash over the content-identifying fields and
    is stable across formatting-only differences between sources; it drives
    exact-duplicate detection.
    """

    record_id: str
    source_record_id: str | None = None
    source_file: str
    source_format: SourceFormat
    patient_id: str
    encounter_id: str | None = None
    record_type: RecordType
    title: str
    text: str
    record_date: date | datetime | None = None
    diagnostic_code: str | None = None
    fingerprint: str
    audit: list[AuditEntry] = Field(default_factory=list)
