"""Unit tests for pipeline behavior on small in-memory fixture files."""

import json
from pathlib import Path

import pytest

from app.ingestion.errors import IngestionError, UnsupportedFormatError
from app.ingestion.pipeline import PipelineResult, run_pipeline

_VALID_RECORD: dict[str, str] = {
    "patient_id": "SRC-1",
    "mrn": "123",
    "given_name": "Avery",
    "family_name": "Kestrel",
    "dob": "1984-03-02",
    "gender": "F",
    "record_id": "R-1",
    "record_type": "note",
    "record_date": "2024-05-01",
    "title": "Visit note",
    "text": "Stable on current therapy.",
}


def _write_json(path: Path, records: list[dict[str, str]]) -> None:
    path.write_text(json.dumps(records), encoding="utf-8")


def _run(tmp_path: Path) -> PipelineResult:
    return run_pipeline([tmp_path])


def test_missing_record_id_derives_deterministic_id(tmp_path: Path) -> None:
    record = {k: v for k, v in _VALID_RECORD.items() if k != "record_id"}
    _write_json(tmp_path / "a.json", [record])
    result = _run(tmp_path)
    accepted = result.records[0]
    assert accepted.record_id == f"REC-{accepted.fingerprint[:12].upper()}"
    assert any(entry.rule == "record_id.derived" for entry in accepted.audit)


def test_missing_optional_fields_accepted_and_audited(tmp_path: Path) -> None:
    record = {k: v for k, v in _VALID_RECORD.items() if k not in ("dob", "gender", "record_date")}
    _write_json(tmp_path / "a.json", [record])
    result = _run(tmp_path)
    assert result.counts.accepted_records == 1
    patient = result.patients[0]
    assert patient.birth_date is None
    assert patient.gender.value == "unknown"
    record_audit_rules = {entry.rule for entry in result.records[0].audit}
    assert "field.missing" in record_audit_rules


def test_exact_duplicate_within_one_file(tmp_path: Path) -> None:
    _write_json(tmp_path / "a.json", [_VALID_RECORD, dict(_VALID_RECORD)])
    result = _run(tmp_path)
    assert result.counts.accepted_records == 1
    assert result.counts.duplicate_records == 1
    assert result.duplicates[0].duplicate_of_record_id == "R-1"


def test_duplicate_across_formats(tmp_path: Path) -> None:
    _write_json(tmp_path / "b.json", [_VALID_RECORD])
    headers = list(_VALID_RECORD)
    csv_record = dict(_VALID_RECORD, mrn="MRN-000123", record_date="05/01/2024")
    (tmp_path / "a.csv").write_text(
        ",".join(headers) + "\n" + ",".join(csv_record[h] for h in headers) + "\n",
        encoding="utf-8",
    )
    result = _run(tmp_path)
    assert result.counts.accepted_records == 1
    assert result.counts.duplicate_records == 1
    duplicate = result.duplicates[0]
    # a.csv sorts before b.json, so the CSV copy is canonical.
    assert duplicate.source_file == "b.json"
    assert duplicate.duplicate_of_source_file == "a.csv"


def test_conflicting_patient_identifiers_are_quarantined(tmp_path: Path) -> None:
    conflicting = dict(
        _VALID_RECORD,
        mrn="456",
        record_id="R-2",
        title="Second note",
        text="Different content.",
    )
    _write_json(tmp_path / "a.json", [_VALID_RECORD, conflicting])
    result = _run(tmp_path)
    assert result.counts.accepted_records == 1
    assert result.counts.identity_conflicts == 1
    conflict = result.conflicts[0]
    assert conflict.conflict_type == "source_patient_id_mrn_mismatch"
    assert conflict.source_record_id == "R-2"


def test_invalid_record_does_not_fail_the_run(tmp_path: Path) -> None:
    no_text = dict(_VALID_RECORD, record_id="R-2", text="  ")
    no_identity = {k: v for k, v in dict(_VALID_RECORD, record_id="R-3").items() if k != "mrn"}
    unknown_type = dict(_VALID_RECORD, record_id="R-4", record_type="billing-summary")
    _write_json(tmp_path / "a.json", [_VALID_RECORD, no_text, no_identity, unknown_type])
    result = _run(tmp_path)
    assert result.counts.accepted_records == 1
    assert result.counts.rejected_records == 3
    reasons = " | ".join(r for rec in result.rejected for r in rec.reasons)
    assert "no meaningful clinical text" in reasons
    assert "insufficient patient identity" in reasons
    assert "unknown record type" in reasons


def test_malformed_file_is_reported_but_other_files_process(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text("{broken", encoding="utf-8")
    _write_json(tmp_path / "good.json", [_VALID_RECORD])
    result = _run(tmp_path)
    assert result.counts.files_failed == 1
    assert result.counts.accepted_records == 1
    assert "bad.json" in result.file_errors[0].source_file


def test_unsupported_files_are_skipped_with_reason(tmp_path: Path) -> None:
    (tmp_path / "readme.md").write_text("notes", encoding="utf-8")
    _write_json(tmp_path / "a.json", [_VALID_RECORD])
    result = _run(tmp_path)
    assert result.counts.files_skipped == 1
    assert result.skipped_files[0].source_file == "readme.md"


def test_audit_entries_generated_for_modified_fields(tmp_path: Path) -> None:
    messy = dict(
        _VALID_RECORD,
        mrn="mrn 00123",
        gender="Female",
        record_date="05/01/2024",
        title="  Visit   note ",
    )
    _write_json(tmp_path / "a.json", [messy])
    result = _run(tmp_path)
    rules = {entry.rule for entry in result.records[0].audit}
    assert {
        "mrn.normalized",
        "gender.normalized",
        "date.parsed",
        "title.whitespace_collapsed",
    } <= rules


def test_invalid_date_flagged_not_rejected(tmp_path: Path) -> None:
    record = dict(_VALID_RECORD, record_date="2/30/2024")
    _write_json(tmp_path / "a.json", [record])
    result = _run(tmp_path)
    assert result.counts.accepted_records == 1
    accepted = result.records[0]
    assert accepted.record_date is None
    assert any(entry.rule == "date.invalid" for entry in accepted.audit)


def test_nonexistent_path_raises(tmp_path: Path) -> None:
    with pytest.raises(IngestionError):
        run_pipeline([tmp_path / "missing"])


def test_no_supported_files_raises(tmp_path: Path) -> None:
    (tmp_path / "readme.md").write_text("x", encoding="utf-8")
    with pytest.raises(UnsupportedFormatError):
        run_pipeline([tmp_path])
