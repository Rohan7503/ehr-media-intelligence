"""Unit tests for the JSON, CSV, and plain-text loaders."""

import json
from pathlib import Path

import pytest

from app.ingestion.errors import MalformedFileError
from app.ingestion.loaders.csv_loader import load_csv_records
from app.ingestion.loaders.json_loader import load_json_records
from app.ingestion.loaders.text_loader import load_text_records


class TestJsonLoader:
    def test_top_level_array(self, tmp_path: Path) -> None:
        path = tmp_path / "a.json"
        path.write_text(json.dumps([{"mrn": "1", "text": "note"}]), encoding="utf-8")
        records = load_json_records(path, "a.json")
        assert len(records) == 1
        assert records[0].fields == {"mrn": "1", "text": "note"}

    def test_object_with_records_array(self, tmp_path: Path) -> None:
        path = tmp_path / "b.json"
        path.write_text(
            json.dumps({"export": "x", "records": [{"note_text": "hi", "note_id": "N1"}]}),
            encoding="utf-8",
        )
        records = load_json_records(path, "b.json")
        assert records[0].fields == {"text": "hi", "record_id": "N1"}

    def test_alias_keys_and_scalars(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        path.write_text(
            json.dumps([{"medical_record_number": 123, "Sex": "F", "ignored_key": "x"}]),
            encoding="utf-8",
        )
        records = load_json_records(path, "c.json")
        assert records[0].fields == {"mrn": "123", "gender": "F"}

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(MalformedFileError):
            load_json_records(path, "bad.json")

    def test_wrong_top_level_structure_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "wrong.json"
        path.write_text(json.dumps({"data": []}), encoding="utf-8")
        with pytest.raises(MalformedFileError):
            load_json_records(path, "wrong.json")

    def test_non_object_entry_flagged(self, tmp_path: Path) -> None:
        path = tmp_path / "entry.json"
        path.write_text(json.dumps([["not", "an", "object"]]), encoding="utf-8")
        records = load_json_records(path, "entry.json")
        assert records[0].issues

    def test_nested_value_flagged(self, tmp_path: Path) -> None:
        path = tmp_path / "nested.json"
        path.write_text(json.dumps([{"text": {"nested": True}}]), encoding="utf-8")
        records = load_json_records(path, "nested.json")
        assert any("unsupported nested value" in issue for issue in records[0].issues)


class TestCsvLoader:
    def test_alias_headers(self, tmp_path: Path) -> None:
        path = tmp_path / "a.csv"
        path.write_text(
            "Patient ID,Medical Record Number,Note Text,Date of Service\n"
            "SRC-1,123,Note body,2024-01-05\n",
            encoding="utf-8",
        )
        records = load_csv_records(path, "a.csv")
        assert records[0].fields == {
            "patient_id": "SRC-1",
            "mrn": "123",
            "text": "Note body",
            "record_date": "2024-01-05",
        }

    def test_empty_cells_omitted_and_blank_rows_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "b.csv"
        path.write_text("mrn,text\n123,\n,\n456,note\n", encoding="utf-8")
        records = load_csv_records(path, "b.csv")
        assert [r.fields for r in records] == [{"mrn": "123"}, {"mrn": "456", "text": "note"}]

    def test_missing_header_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.csv"
        path.write_text("", encoding="utf-8")
        with pytest.raises(MalformedFileError):
            load_csv_records(path, "empty.csv")

    def test_no_recognized_columns_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "cols.csv"
        path.write_text("foo,bar\n1,2\n", encoding="utf-8")
        with pytest.raises(MalformedFileError):
            load_csv_records(path, "cols.csv")


class TestTextLoader:
    def test_multiline_text_until_blank_line(self, tmp_path: Path) -> None:
        path = tmp_path / "notes.txt"
        path.write_text(
            "MRN: 123\n"
            "RECORD_TYPE: note\n"
            "TITLE: Visit note\n"
            "TEXT: First line.\n"
            "BP: 132/84 recorded today.\n"
            "Third line.\n"
            "\n"
            "MRN: 456\n"
            "TEXT: Second record.\n",
            encoding="utf-8",
        )
        records = load_text_records(path, "notes.txt")
        assert len(records) == 2
        assert records[0].fields["text"] == "First line.\nBP: 132/84 recorded today.\nThird line."
        assert records[1].fields == {"mrn": "456", "text": "Second record."}

    def test_name_and_metadata_headers(self, tmp_path: Path) -> None:
        path = tmp_path / "n.txt"
        path.write_text(
            "PATIENT_ID: SRC-9\nMRN: 55\nNAME: Avery Kestrel\nDOB: 1984-03-02\n"
            "GENDER: F\nRECORD_ID: T-1\nRECORD_DATE: 2024-05-01\nTEXT: Body.\n",
            encoding="utf-8",
        )
        records = load_text_records(path, "n.txt")
        assert records[0].fields["full_name"] == "Avery Kestrel"
        assert records[0].fields["record_id"] == "T-1"

    def test_unknown_key_and_stray_line_flagged(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.txt"
        path.write_text(
            "MRN: 1\nWEIRD_KEY: x\nstray line without header\nTEXT: Body.\n",
            encoding="utf-8",
        )
        records = load_text_records(path, "bad.txt")
        assert len(records[0].issues) == 2
