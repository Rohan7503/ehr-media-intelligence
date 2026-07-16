"""Loader for JSON source files.

Supported structures:

- a top-level array of record objects
- an object containing a ``records`` array

Anything else is a file-level :class:`MalformedFileError`. Unrecognized keys
are ignored; scalar values are read as strings; nested values are flagged as
record-level issues.
"""

import json
from pathlib import Path

from app.domain.record import SourceFormat
from app.ingestion.errors import MalformedFileError
from app.ingestion.loaders.base import RawRecord, canonical_key


def load_json_records(path: Path, source_file: str) -> list[RawRecord]:
    """Parse a JSON source file into raw records."""
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MalformedFileError(source_file, f"invalid JSON: {exc}") from exc
    except OSError as exc:
        raise MalformedFileError(source_file, f"unreadable file: {exc}") from exc

    entries = _extract_entries(parsed, source_file)

    records: list[RawRecord] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            records.append(
                RawRecord(
                    source_file=source_file,
                    source_format=SourceFormat.JSON,
                    index=index,
                    issues=[f"record entry {index} is not a JSON object"],
                )
            )
            continue
        fields: dict[str, str] = {}
        issues: list[str] = []
        for key, value in entry.items():
            canonical = canonical_key(str(key))
            if canonical is None or value is None:
                continue
            if isinstance(value, str):
                fields[canonical] = value
            elif isinstance(value, bool | int | float):
                fields[canonical] = str(value)
            else:
                issues.append(f"field '{canonical}' has an unsupported nested value")
        records.append(
            RawRecord(
                source_file=source_file,
                source_format=SourceFormat.JSON,
                index=index,
                fields=fields,
                issues=issues,
            )
        )
    return records


def _extract_entries(parsed: object, source_file: str) -> list[object]:
    if isinstance(parsed, list):
        return list(parsed)
    if isinstance(parsed, dict):
        records = parsed.get("records")
        if isinstance(records, list):
            return list(records)
    raise MalformedFileError(
        source_file,
        "expected a top-level array of records or an object with a 'records' array",
    )
