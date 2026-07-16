"""Integration tests: the CLI over a small mixed-format fixture directory."""

import json
from pathlib import Path

from app.ingestion.cli import main

_JSON_RECORDS = [
    {
        "patient_id": "SRC-1",
        "mrn": "123",
        "given_name": "Avery",
        "family_name": "Kestrel",
        "dob": "1984-03-02",
        "gender": "F",
        "record_id": "J-1",
        "record_type": "note",
        "record_date": "2024-05-01",
        "title": "Visit note",
        "text": "Stable on current therapy.",
    },
    # Conflicts with the CSV record below: same source patient ID, other MRN.
    {
        "patient_id": "SRC-2",
        "mrn": "999",
        "given_name": "Rowan",
        "family_name": "Falk",
        "record_id": "J-2",
        "record_type": "note",
        "record_date": "2024-06-01",
        "title": "Conflicting note",
        "text": "This record presents a contradictory identifier.",
    },
]

_CSV_CONTENT = (
    "patient_id,mrn,given_name,family_name,dob,gender,record_id,record_type,"
    "record_date,title,text\n"
    'SRC-2,456,Rowan,Falk,1975-11-19,M,C-1,lab,2024-04-15,Panel,"All values normal."\n'
    "SRC-3,,,,,,C-2,note,2024-04-20,No identity,This record has no MRN.\n"
)

_TEXT_CONTENT = (
    "PATIENT_ID: SRC-1\n"
    "MRN: MRN-000123\n"
    "NAME: Avery Kestrel\n"
    "DOB: 03/02/1984\n"
    "GENDER: Female\n"
    "RECORD_ID: J-1\n"
    "RECORD_TYPE: progress note\n"
    "RECORD_DATE: 05/01/2024\n"
    "TITLE: Visit   note\n"
    "TEXT: Stable on current therapy.\n"
    "\n"
    "MRN: 3310\n"
    "NAME: Priya Ramanathan\n"
    "RECORD_ID: t-2\n"
    "RECORD_TYPE: note\n"
    "RECORD_DATE: 2024-07-01\n"
    "TITLE: Multiline note\n"
    "TEXT: First line of the note.\n"
    "Second line continues here.\n"
)


def _build_fixture(root: Path) -> Path:
    inputs = root / "inputs"
    inputs.mkdir()
    (inputs / "a.json").write_text(json.dumps(_JSON_RECORDS), encoding="utf-8")
    (inputs / "b.csv").write_text(_CSV_CONTENT, encoding="utf-8")
    (inputs / "c.txt").write_text(_TEXT_CONTENT, encoding="utf-8")
    (inputs / "ignored.xml").write_text("<x/>", encoding="utf-8")
    return inputs


def _load(path: Path) -> dict[str, object]:
    data: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return data


def test_mixed_format_ingestion_end_to_end(tmp_path: Path) -> None:
    inputs = _build_fixture(tmp_path)
    out = tmp_path / "out"

    exit_code = main([str(inputs), "--output-dir", str(out)])

    assert exit_code == 0
    report = _load(out / "ingestion_report.json")
    counts = report["counts"]
    assert isinstance(counts, dict)
    # Raw: 2 JSON + 2 CSV + 2 text = 6.
    assert counts["raw_records"] == 6
    # The text copy of J-1 is an exact duplicate of the JSON record.
    assert counts["duplicate_records"] == 1
    # The record with no MRN is rejected.
    assert counts["rejected_records"] == 1
    # SRC-2 maps to two different MRNs: quarantined conflict.
    assert counts["identity_conflicts"] == 1
    assert counts["accepted_records"] == 3
    assert counts["accepted_patients"] == 3
    assert counts["files_skipped"] == 1

    patients = _load(out / "patients.json")["patients"]
    assert isinstance(patients, list)
    # a.json processes before b.csv, so SRC-2 is first established with MRN 999
    # and the CSV record presenting MRN 456 is the quarantined conflict.
    assert [p["patient_id"] for p in patients] == ["PAT-000123", "PAT-000999", "PAT-003310"]

    records = _load(out / "records.json")["records"]
    assert isinstance(records, list)
    multiline = next(r for r in records if r["record_id"] == "T-2")
    assert "\n" in multiline["text"]


def test_repeated_runs_produce_identical_output(tmp_path: Path) -> None:
    inputs = _build_fixture(tmp_path)
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"

    assert main([str(inputs), "--output-dir", str(out1)]) == 0
    assert main([str(inputs), "--output-dir", str(out2)]) == 0

    for name in ("patients.json", "records.json", "ingestion_report.json"):
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes()


def test_nonexistent_input_path_returns_nonzero(tmp_path: Path) -> None:
    exit_code = main([str(tmp_path / "missing"), "--output-dir", str(tmp_path / "out")])
    assert exit_code == 1


def test_directory_with_no_supported_files_returns_nonzero(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "notes.docx").write_text("x", encoding="utf-8")
    exit_code = main([str(inputs), "--output-dir", str(tmp_path / "out")])
    assert exit_code == 1
