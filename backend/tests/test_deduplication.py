"""Unit tests for record fingerprinting and the duplicate index."""

from datetime import date, datetime

from app.domain.record import RecordType
from app.ingestion.deduplication import DuplicateIndex, record_fingerprint
from app.ingestion.normalizers import normalize_multiline_text


def _fingerprint(**overrides: object) -> str:
    base: dict[str, object] = {
        "mrn": "MRN-000123",
        "record_type": RecordType.DOCUMENT,
        "record_date": date(2024, 3, 5),
        "title": "Visit note",
        "text": "Body of the note.",
        "encounter_id": None,
        "diagnostic_code": None,
    }
    base.update(overrides)
    return record_fingerprint(**base)  # type: ignore[arg-type]


def test_fingerprint_is_deterministic() -> None:
    assert _fingerprint() == _fingerprint()
    assert len(_fingerprint()) == 64


def test_fingerprint_stable_across_formatting_only_differences() -> None:
    original = _fingerprint()
    assert _fingerprint(title="  Visit   note ") == original
    assert _fingerprint(record_date=datetime(2024, 3, 5, 9, 30)) == original
    crlf_text = normalize_multiline_text("Body of the note.\r\n")
    assert _fingerprint(text=crlf_text) == original


def test_fingerprint_changes_with_content() -> None:
    original = _fingerprint()
    assert _fingerprint(text="Different body.") != original
    assert _fingerprint(mrn="MRN-000456") != original
    assert _fingerprint(record_type=RecordType.DIAGNOSTIC_REPORT) != original
    assert _fingerprint(record_date=date(2024, 3, 6)) != original


def test_duplicate_index_keeps_first_occurrence() -> None:
    index = DuplicateIndex()
    assert index.lookup("fp") is None
    index.register("fp", "REC-1", "a.json")
    index.register("fp", "REC-2", "b.csv")
    assert index.lookup("fp") == ("REC-1", "a.json")
