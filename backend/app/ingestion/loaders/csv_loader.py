"""Loader for CSV source files.

Uses the standard-library CSV parser. Alternate column names are resolved
through the explicit alias table in :mod:`app.ingestion.loaders.base`; files
whose header contains no recognized column raise a file-level error. Rows
whose recognized cells are all empty are skipped.
"""

import csv
from pathlib import Path

from app.domain.record import SourceFormat
from app.ingestion.errors import MalformedFileError
from app.ingestion.loaders.base import RawRecord, canonical_key


def load_csv_records(path: Path, source_file: str) -> list[RawRecord]:
    """Parse a CSV source file into raw records."""
    records: list[RawRecord] = []
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise MalformedFileError(source_file, "missing CSV header row")
            header_map: dict[str, str] = {}
            for name in reader.fieldnames:
                canonical = canonical_key(name)
                if canonical is not None:
                    header_map[name] = canonical
            if not header_map:
                raise MalformedFileError(source_file, "no recognized columns in CSV header")
            for index, row in enumerate(reader):
                fields: dict[str, str] = {}
                for name, canonical in header_map.items():
                    value = row.get(name)
                    if isinstance(value, str) and value.strip():
                        fields[canonical] = value
                if not fields:
                    continue
                records.append(
                    RawRecord(
                        source_file=source_file,
                        source_format=SourceFormat.CSV,
                        index=index,
                        fields=fields,
                    )
                )
    except csv.Error as exc:
        raise MalformedFileError(source_file, f"CSV parse error: {exc}") from exc
    except OSError as exc:
        raise MalformedFileError(source_file, f"unreadable file: {exc}") from exc
    return records
