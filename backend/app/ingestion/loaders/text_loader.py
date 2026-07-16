"""Loader for plain-text source files (scanned-note exports).

Format
------

A text file contains one or more records separated by one or more blank
lines. Each record is a sequence of ``KEY: value`` metadata headers followed
by an optional ``TEXT:`` header whose value continues over subsequent lines:

.. code-block:: text

    PATIENT_ID: SRC-007
    MRN: 3310
    NAME: Priya Ramanathan
    DOB: 1988-09-15
    GENDER: F
    RECORD_ID: TX-0700
    RECORD_TYPE: document
    RECORD_DATE: 2024-06-03
    TITLE: Follow-up note
    TEXT: Patient reports improvement.
    Vitals stable at today's visit.
    Plan reviewed and continued.

Recognized keys: ``PATIENT_ID``, ``MRN``, ``NAME``, ``GIVEN_NAME``,
``FAMILY_NAME``, ``DOB``, ``GENDER``, ``RECORD_ID``, ``ENCOUNTER_ID``,
``RECORD_TYPE``, ``RECORD_DATE``, ``TITLE``, ``TEXT``, ``DIAGNOSTIC_CODE``.

Limitations (by design, for determinism):

- A blank line always ends the record, so TEXT cannot contain blank lines.
- Everything after ``TEXT:`` is taken verbatim as note content, including
  lines that resemble headers (for example ``BP: 132/84``).
- Unknown metadata keys and unparseable header lines are recorded as issues
  and cause the record to be rejected with a structured reason.
"""

import re
from pathlib import Path

from app.domain.record import SourceFormat
from app.ingestion.errors import MalformedFileError
from app.ingestion.loaders.base import RawRecord

_HEADER_RE = re.compile(r"^([A-Z_]+):\s?(.*)$")

_KEY_MAP: dict[str, str] = {
    "PATIENT_ID": "patient_id",
    "MRN": "mrn",
    "NAME": "full_name",
    "GIVEN_NAME": "given_name",
    "FAMILY_NAME": "family_name",
    "DOB": "dob",
    "GENDER": "gender",
    "RECORD_ID": "record_id",
    "ENCOUNTER_ID": "encounter_id",
    "RECORD_TYPE": "record_type",
    "RECORD_DATE": "record_date",
    "TITLE": "title",
    "TEXT": "text",
    "DIAGNOSTIC_CODE": "diagnostic_code",
}


def load_text_records(path: Path, source_file: str) -> list[RawRecord]:
    """Parse a plain-text source file into raw records."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MalformedFileError(source_file, f"unreadable file: {exc}") from exc

    records: list[RawRecord] = []
    for index, block in enumerate(_split_blocks(content)):
        fields: dict[str, str] = {}
        issues: list[str] = []
        text_lines: list[str] | None = None
        for line in block:
            if text_lines is not None:
                text_lines.append(line)
                continue
            match = _HEADER_RE.match(line)
            if match is None:
                issues.append(f"unparseable line before TEXT: '{line[:60]}'")
                continue
            key, value = match.group(1), match.group(2)
            canonical = _KEY_MAP.get(key)
            if canonical is None:
                issues.append(f"unknown metadata key '{key}'")
                continue
            if canonical == "text":
                text_lines = [value]
                continue
            if value.strip():
                fields[canonical] = value
        if text_lines is not None:
            text = "\n".join(text_lines)
            if text.strip():
                fields["text"] = text
        records.append(
            RawRecord(
                source_file=source_file,
                source_format=SourceFormat.TEXT,
                index=index,
                fields=fields,
                issues=issues,
            )
        )
    return records


def _split_blocks(content: str) -> list[list[str]]:
    """Split file content into blank-line-separated blocks of lines."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip():
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks
