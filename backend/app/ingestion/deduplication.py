"""Content fingerprinting and exact-duplicate detection.

The fingerprint is a SHA-256 hash over the content-identifying fields of a
record after normalization, so formatting-only differences between sources
(date formats, whitespace, line endings, MRN styling) produce the same
fingerprint. The first occurrence in deterministic processing order is kept
as canonical; later occurrences are reported as duplicates.
"""

import hashlib
import json
from datetime import date, datetime

from pydantic import BaseModel

from app.domain.record import RecordType
from app.ingestion.normalizers import collapse_whitespace


class DuplicateRecord(BaseModel):
    """A structured report of one record excluded as an exact duplicate."""

    fingerprint: str
    source_file: str
    source_record_id: str | None = None
    duplicate_of_record_id: str
    duplicate_of_source_file: str
    reason: str


def record_fingerprint(
    *,
    mrn: str,
    record_type: RecordType,
    record_date: date | datetime | None,
    title: str,
    text: str,
    encounter_id: str | None,
    diagnostic_code: str | None,
) -> str:
    """Compute the stable SHA-256 content fingerprint for a record.

    Inputs are expected to be normalized already; title whitespace is
    collapsed and only the date part of a date-time is used so that
    formatting-only differences cannot change the hash.
    """
    if isinstance(record_date, datetime):
        date_part = record_date.date().isoformat()
    elif isinstance(record_date, date):
        date_part = record_date.isoformat()
    else:
        date_part = ""
    payload = {
        "mrn": mrn,
        "record_type": record_type.value,
        "record_date": date_part,
        "title": collapse_whitespace(title),
        "text": text,
        "encounter_id": encounter_id or "",
        "diagnostic_code": diagnostic_code or "",
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DuplicateIndex:
    """Tracks fingerprints of accepted records in processing order."""

    def __init__(self) -> None:
        self._seen: dict[str, tuple[str, str]] = {}

    def lookup(self, fingerprint: str) -> tuple[str, str] | None:
        """Return ``(record_id, source_file)`` of the canonical record, if any."""
        return self._seen.get(fingerprint)

    def register(self, fingerprint: str, record_id: str, source_file: str) -> None:
        """Register an accepted record as canonical for its fingerprint."""
        self._seen.setdefault(fingerprint, (record_id, source_file))
