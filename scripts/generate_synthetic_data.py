#!/usr/bin/env python3
"""Deterministic generator for synthetic EHR fixture files.

Writes JSON, CSV, and plain-text source files under ``data/synthetic/``.
Everything is fabricated: names, identifiers, dates, and clinical details are
fictional and must never be replaced with real patient data.

The output is fully deterministic — no randomness, no timestamps — so
repeated runs produce byte-identical files. The dataset deliberately includes
messy variants (mixed date formats, alternate gender codes, alternate MRN
styles, missing fields), exact duplicates across formats, identity conflicts,
and invalid records, so the ingestion pipeline has real work to do.

Usage::

    python scripts/generate_synthetic_data.py [--output-dir data/synthetic]

Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date, timedelta
from pathlib import Path

BASE_DATE = date(2023, 1, 10)
DATE_STEP_DAYS = 13

DOC_TYPE_VARIANTS = ["note", "progress note", "document", "clinical note"]
DIAG_TYPE_VARIANTS = ["lab", "diagnostic_report", "imaging", "lab report"]

# One entry per patient: identity variants exercise the normalizers.
PATIENTS: list[dict[str, object]] = [
    {
        "num": 1,
        "source_id": "SRC-001",
        "mrn_variants": ["123", "mrn 00123", "MRN-000123"],
        "given": "Avery",
        "family": "Kestrel",
        "dob": "1984-03-02",
        "gender_variants": ["F", "Female", "female"],
        "condition": "hypertension",
        "target": ("json", 1),
    },
    {
        "num": 2,
        "source_id": "SRC-002",
        "mrn_variants": ["456", "00456"],
        "given": "Rowan",
        "family": "Falk",
        "dob": "1975-11-19",
        "gender_variants": ["M", "Male"],
        "condition": "type 2 diabetes",
        "target": ("json", 1),
    },
    {
        "num": 3,
        "source_id": "SRC-003",
        "mrn_variants": ["ab-123", "AB 123", "AB123"],
        "given": "Imani",
        "family": "Solano",
        "dob": "1990-07-04",
        "gender_variants": ["F", "female"],
        "condition": "asthma",
        "target": ("json", 2),
    },
    {
        "num": 4,
        "source_id": "SRC-004",
        "mrn_variants": ["789", "0789"],
        "given": "Theo",
        "family": "Marchetti",
        "dob": "1968-02-28",
        "gender_variants": ["male", "M"],
        "condition": "osteoarthritis",
        "target": ("csv", 1),
    },
    {
        "num": 5,
        "source_id": "SRC-005",
        "mrn_variants": ["1042"],
        "given": "Nadia",
        "family": "Verhoeven",
        "dob": "2001-12-11",
        "gender_variants": ["X", "nonbinary"],
        "condition": "migraine",
        "target": ("csv", 2),
    },
    {
        "num": 6,
        "source_id": "SRC-006",
        "mrn_variants": ["2205", "22 05"],
        "given": "Silas",
        "family": "Okonkwo",
        "dob": "1957-06-30",
        "gender_variants": ["M", "male"],
        "condition": "atrial fibrillation",
        "target": ("csv", 2),
    },
    {
        "num": 7,
        "source_id": "SRC-007",
        "mrn_variants": ["3310", "33-10"],
        "given": "Priya",
        "family": "Ramanathan",
        "dob": None,  # deliberately never provided
        "gender_variants": ["F"],
        "condition": "hypothyroidism",
        "target": ("text", 1),
    },
    {
        "num": 8,
        "source_id": "SRC-008",
        "mrn_variants": ["4470"],
        "given": "Jonas",
        "family": "Lindqvist",
        "dob": "1979-04-22",
        "gender_variants": ["U", "unknown"],
        "condition": "chronic sinusitis",
        "target": ("text", 2),
    },
]

# Seven record templates per patient: 4 documents + 3 diagnostic reports.
TEMPLATES: list[dict[str, object]] = [
    {
        "title": "Primary care follow-up",
        "kind": "document",
        "code": None,
        "lines": [
            "Patient seen for routine follow-up of {condition}.",
            "Reports adherence to the current care plan.",
            "Plan: continue current management and recheck in three months.",
        ],
    },
    {
        "title": "Comprehensive metabolic panel",
        "kind": "diagnostic",
        "code": "CMP",
        "lines": [
            "Comprehensive metabolic panel collected at the morning draw.",
            "Indication: monitoring for {condition}.",
            "All analytes within the laboratory reference intervals.",
        ],
    },
    {
        "title": "Specialist consultation",
        "kind": "document",
        "code": None,
        "lines": [
            "Consultation requested for ongoing {condition}.",
            "History reviewed with the patient in clinic today.",
            "Impression discussed; follow-up arranged with the referring provider.",
        ],
    },
    {
        "title": "Chest X-ray report",
        "kind": "diagnostic",
        "code": "XR-CHEST",
        "lines": [
            "Two-view chest radiograph obtained.",
            "Indication: baseline imaging in the context of {condition}.",
            "No acute cardiopulmonary findings.",
        ],
    },
    {
        "title": "Medication review",
        "kind": "document",
        "code": None,
        "lines": [
            "Medication list reconciled during today's visit.",
            "No adverse effects reported for current {condition} therapy.",
            "Refills issued for ninety days.",
        ],
    },
    {
        "title": "Lipid panel",
        "kind": "diagnostic",
        "code": "LIPID",
        "lines": [
            "Fasting lipid panel processed.",
            "Indication: cardiovascular risk assessment alongside {condition}.",
            "Values compared against the prior result on file.",
        ],
    },
    {
        "title": "Telehealth check-in",
        "kind": "document",
        "code": None,
        "lines": [
            "Brief telehealth visit completed for {condition} monitoring.",
            "Patient had no new concerns during the call.",
            "Next in-person visit confirmed.",
        ],
    },
]

_ID_PREFIX = {"json": "JR", "csv": "CR", "text": "TR"}


def format_date(value: date, mode: int) -> str:
    """Render a date in one of the supported source formats."""
    if mode == 0:
        return value.isoformat()
    if mode == 1:
        return value.strftime("%m/%d/%Y")
    if mode == 2:
        return value.strftime("%d-%m-%Y")
    return value.isoformat() + "T09:30:00"


def build_core_records() -> list[dict[str, object]]:
    """Build the 56 core records (8 patients x 7 templates)."""
    records: list[dict[str, object]] = []
    for pidx, patient in enumerate(PATIENTS):
        fmt, _batch = patient["target"]  # type: ignore[misc]
        prefix = _ID_PREFIX[str(fmt)]
        mrn_variants = list(patient["mrn_variants"])  # type: ignore[arg-type]
        gender_variants = list(patient["gender_variants"])  # type: ignore[arg-type]
        num = int(patient["num"])  # type: ignore[arg-type]
        for ridx, template in enumerate(TEMPLATES):
            g = pidx * len(TEMPLATES) + ridx
            record_date = BASE_DATE + timedelta(days=DATE_STEP_DAYS * g)
            kind = str(template["kind"])
            if kind == "document":
                record_type = DOC_TYPE_VARIANTS[(pidx + ridx) % len(DOC_TYPE_VARIANTS)]
                encounter_id = None
            else:
                record_type = DIAG_TYPE_VARIANTS[(pidx + ridx) % len(DIAG_TYPE_VARIANTS)]
                encounter_id = f"ENC-{num:02d}{ridx:02d}"
            dob_raw = patient["dob"]
            dob = format_date(date.fromisoformat(str(dob_raw)), ridx % 3) if dob_raw else None
            record_id: str | None = f"{prefix}-{num:02d}{ridx:02d}"
            if fmt == "text":
                record_id = record_id.lower()  # exercises record_id normalization
            lines = [str(line).format(condition=patient["condition"]) for line in template["lines"]]
            joiner = " " if fmt == "csv" else "\n"
            records.append(
                {
                    "patient_id": patient["source_id"],
                    "mrn": mrn_variants[ridx % len(mrn_variants)],
                    "given_name": patient["given"],
                    "family_name": patient["family"],
                    "dob": dob,
                    "gender": gender_variants[ridx % len(gender_variants)],
                    "record_id": record_id,
                    "encounter_id": encounter_id,
                    "record_type": record_type,
                    "record_date": format_date(record_date, g % 4),
                    "title": str(template["title"]),
                    "text": joiner.join(lines),
                    "diagnostic_code": template["code"],
                    "_patient_num": num,
                    "_ridx": ridx,
                }
            )
    return records


def apply_edge_cases(records: list[dict[str, object]]) -> None:
    """Deliberately degrade specific core records to exercise the pipeline."""

    def pick(num: int, ridx: int) -> dict[str, object]:
        return next(r for r in records if r["_patient_num"] == num and r["_ridx"] == ridx)

    pick(1, 2)["record_id"] = None  # missing record ID -> derived deterministically
    pick(2, 0)["gender"] = None  # missing gender -> unknown, later backfilled
    pick(4, 3)["record_date"] = None  # missing record date -> flagged
    pick(5, 1)["record_date"] = "2/30/2024"  # impossible date -> flagged, not guessed
    pick(7, 0)["title"] = None  # missing title -> derived from first text line
    pick(8, 0)["dob"] = "31/31/1979"  # invalid DOB -> flagged, later backfilled


def build_extras(core: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    """Duplicates, identity conflicts, and invalid records."""

    def pick(num: int, ridx: int) -> dict[str, object]:
        return next(r for r in core if r["_patient_num"] == num and r["_ridx"] == ridx)

    # D1: exact duplicate of a CSV record, re-exported in JSON with
    # formatting-only differences (MRN style, date format).
    d1 = dict(pick(4, 0))
    d1.update({"mrn": "MRN-000789", "record_date": "2023-10-10", "gender": "M"})

    # D2: exact duplicate of a JSON record, re-exported as text with a
    # differently formatted date and extra title whitespace.
    d2 = dict(pick(1, 0))
    d2.update({"mrn": "MRN-000123", "record_date": "01/10/2023", "title": " Primary care   follow-up "})

    # D3: exact duplicate of a text record in a later text file. The original
    # has no title, so both derive the same title from the text.
    d3 = dict(pick(7, 0))
    d3.update({"mrn": "3310", "record_id": "tr-0700"})

    c1a = {
        "patient_id": "SRC-050",
        "mrn": "555",
        "given_name": "Mara",
        "family_name": "Voss",
        "dob": "1980-01-01",
        "gender": "F",
        "record_id": "CR-C1A0",
        "encounter_id": None,
        "record_type": "note",
        "record_date": "2024-02-15",
        "title": "Dermatology consultation",
        "text": "Evaluation of a stable, longstanding skin finding. No change in appearance reported.",
        "diagnostic_code": None,
    }
    # Same source patient ID as c1a but a different MRN -> quarantined conflict.
    c1b = {
        "patient_id": "SRC-050",
        "mrn": "556",
        "given_name": "Mara",
        "family_name": "Voss",
        "dob": "1980-01-01",
        "gender": "F",
        "record_id": "JR-C1B0",
        "encounter_id": None,
        "record_type": "note",
        "record_date": "2024-03-20",
        "title": "Dermatology follow-up",
        "text": "Follow-up of the previously documented skin finding.\nNo new symptoms reported.",
        "diagnostic_code": None,
    }
    c2a = {
        "patient_id": "SRC-060",
        "mrn": "888",
        "given_name": "Elio",
        "family_name": "Brandt",
        "dob": "1962-08-09",
        "gender": "M",
        "record_id": "CR-C2A0",
        "encounter_id": "ENC-C2A0",
        "record_type": "lab",
        "record_date": "03/05/2024",
        "title": "Complete blood count",
        "text": "Complete blood count within normal limits for age.",
        "diagnostic_code": "CBC",
    }
    # Same MRN as c2a but a different date of birth -> quarantined conflict.
    c2b = {
        "patient_id": "SRC-061",
        "mrn": "888",
        "given_name": "Elio",
        "family_name": "Brandt",
        "dob": "1966-03-14",
        "gender": "M",
        "record_id": "tr-c2b0",
        "encounter_id": None,
        "record_type": "note",
        "record_date": "2024-07-02",
        "title": "Annual wellness visit",
        "text": "Annual wellness visit completed.\nPreventive screenings reviewed and up to date.",
        "diagnostic_code": None,
    }
    # r1: no MRN or patient ID -> rejected (insufficient identity).
    r1 = {
        "patient_id": None,
        "mrn": None,
        "given_name": None,
        "family_name": None,
        "full_name": "Casey Whitlock",
        "dob": None,
        "gender": "F",
        "record_id": "tr-r100",
        "encounter_id": None,
        "record_type": "note",
        "record_date": "2024-08-10",
        "title": "Walk-in visit",
        "text": "Walk-in visit note received without a usable patient identifier.",
        "diagnostic_code": None,
    }
    # r2: no meaningful clinical text -> rejected.
    r2 = {
        "patient_id": "SRC-090",
        "mrn": "919",
        "given_name": "Sana",
        "family_name": "Petrov",
        "dob": "1993-05-27",
        "gender": "F",
        "record_id": "CR-R200",
        "encounter_id": None,
        "record_type": "note",
        "record_date": "2024-09-01",
        "title": "Empty note",
        "text": "N/A",
        "diagnostic_code": None,
    }
    # r3: unrecognized record type -> rejected rather than misclassified.
    r3 = {
        "patient_id": "SRC-091",
        "mrn": "920",
        "given_name": "Milo",
        "family_name": "Arden",
        "dob": "1988-10-30",
        "gender": "M",
        "record_id": "JR-R300",
        "encounter_id": None,
        "record_type": "billing-summary",
        "record_date": "2024-09-15",
        "title": "Statement",
        "text": "Quarterly account statement exported alongside clinical notes in error.",
        "diagnostic_code": None,
    }
    return {
        "d1": [d1],
        "d2": [d2],
        "d3": [d3],
        "c1a": [c1a],
        "c1b": [c1b],
        "c2a": [c2a],
        "c2b": [c2b],
        "r1": [r1],
        "r2": [r2],
        "r3": [r3],
    }


def _clean(record: dict[str, object]) -> dict[str, object]:
    return {k: v for k, v in record.items() if not k.startswith("_")}


CANONICAL_JSON_KEYS = [
    "patient_id",
    "mrn",
    "given_name",
    "family_name",
    "dob",
    "gender",
    "record_id",
    "encounter_id",
    "record_type",
    "record_date",
    "title",
    "text",
    "diagnostic_code",
]

ALIAS_JSON_KEYS = {
    "patient_id": "source_patient_id",
    "mrn": "medical_record_number",
    "given_name": "first_name",
    "family_name": "last_name",
    "dob": "birth_date",
    "gender": "sex",
    "record_id": "note_id",
    "encounter_id": "visit_id",
    "record_type": "note_type",
    "record_date": "date_of_service",
    "title": "subject",
    "text": "note_text",
    "diagnostic_code": "icd_code",
}

CSV_HEADERS_CANONICAL = CANONICAL_JSON_KEYS

CSV_HEADERS_ALIAS = [
    "Patient ID",
    "Medical Record Number",
    "First Name",
    "Surname",
    "Birth Date",
    "Sex",
    "Note ID",
    "Visit ID",
    "Note Type",
    "Date of Service",
    "Subject",
    "Note Text",
    "ICD Code",
]

TEXT_KEY_ORDER = [
    ("patient_id", "PATIENT_ID"),
    ("mrn", "MRN"),
    ("full_name", "NAME"),
    ("dob", "DOB"),
    ("gender", "GENDER"),
    ("record_id", "RECORD_ID"),
    ("encounter_id", "ENCOUNTER_ID"),
    ("record_type", "RECORD_TYPE"),
    ("record_date", "RECORD_DATE"),
    ("diagnostic_code", "DIAGNOSTIC_CODE"),
    ("title", "TITLE"),
]


def write_json(path: Path, records: list[dict[str, object]], *, wrapped: bool, alias: bool) -> None:
    payload_records = []
    for record in records:
        cleaned = _clean(record)
        entry: dict[str, object] = {}
        for key in CANONICAL_JSON_KEYS:
            value = cleaned.get(key)
            if value is None:
                continue
            out_key = ALIAS_JSON_KEYS[key] if alias else key
            entry[out_key] = value
        payload_records.append(entry)
    payload: object = (
        {"export": "synthetic-ehr-export", "records": payload_records}
        if wrapped
        else payload_records
    )
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, ensure_ascii=False))
        handle.write("\n")


def write_csv(path: Path, records: list[dict[str, object]], *, alias: bool) -> None:
    headers = CSV_HEADERS_ALIAS if alias else CSV_HEADERS_CANONICAL
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(headers)
        for record in records:
            cleaned = _clean(record)
            row = []
            for key in CANONICAL_JSON_KEYS:
                value = cleaned.get(key)
                row.append("" if value is None else str(value))
            writer.writerow(row)


def write_text(path: Path, records: list[dict[str, object]]) -> None:
    blocks: list[str] = []
    for record in records:
        cleaned = _clean(record)
        if "full_name" not in cleaned and cleaned.get("given_name"):
            cleaned["full_name"] = f"{cleaned['given_name']} {cleaned['family_name']}"
        lines: list[str] = []
        for key, header in TEXT_KEY_ORDER:
            value = cleaned.get(key)
            if value is not None:
                lines.append(f"{header}: {value}")
        text = str(cleaned["text"])
        text_lines = text.split("\n")
        lines.append(f"TEXT: {text_lines[0]}")
        lines.extend(text_lines[1:])
        blocks.append("\n".join(lines))
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n\n".join(blocks))
        handle.write("\n")


def generate(output_dir: Path) -> dict[str, int]:
    core = build_core_records()
    apply_edge_cases(core)
    extras = build_extras(core)

    def core_for(fmt: str, batch: int) -> list[dict[str, object]]:
        selected = []
        for pidx, patient in enumerate(PATIENTS):
            if patient["target"] == (fmt, batch):
                selected.extend(core[pidx * len(TEMPLATES) : (pidx + 1) * len(TEMPLATES)])
        return selected

    json_dir = output_dir / "json"
    csv_dir = output_dir / "csv"
    text_dir = output_dir / "text"
    for directory in (json_dir, csv_dir, text_dir):
        directory.mkdir(parents=True, exist_ok=True)

    json_1 = core_for("json", 1) + extras["d1"] + extras["r3"]
    json_2 = core_for("json", 2) + extras["c1b"]
    csv_1 = core_for("csv", 1) + extras["c1a"]
    csv_2 = core_for("csv", 2) + extras["c2a"] + extras["r2"]
    text_1 = core_for("text", 1) + extras["d2"]
    text_2 = core_for("text", 2) + extras["d3"] + extras["c2b"] + extras["r1"]

    write_json(json_dir / "records_batch_1.json", json_1, wrapped=False, alias=False)
    write_json(json_dir / "records_batch_2.json", json_2, wrapped=True, alias=True)
    write_csv(csv_dir / "records_batch_1.csv", csv_1, alias=False)
    write_csv(csv_dir / "records_batch_2.csv", csv_2, alias=True)
    write_text(text_dir / "notes_batch_1.txt", text_1)
    write_text(text_dir / "notes_batch_2.txt", text_2)

    return {
        "json": len(json_1) + len(json_2),
        "csv": len(csv_1) + len(csv_2),
        "text": len(text_1) + len(text_2),
        "total": len(json_1) + len(json_2) + len(csv_1) + len(csv_2) + len(text_1) + len(text_2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "synthetic",
        help="directory to write the synthetic dataset into (default: data/synthetic)",
    )
    args = parser.parse_args()
    counts = generate(args.output_dir)
    for fmt in ("json", "csv", "text"):
        print(f"{fmt}: {counts[fmt]} raw records")
    print(f"total: {counts['total']} raw records written to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
