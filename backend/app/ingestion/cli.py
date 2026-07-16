"""Command-line entry point for the ingestion pipeline.

Usage (from ``backend/``)::

    python -m app.ingestion.cli ../data/synthetic --output-dir ../data/generated

Writes three deterministic JSON files to the output directory:

- ``patients.json`` — canonical patients with their audit trails
- ``records.json`` — accepted canonical records with their audit trails
- ``ingestion_report.json`` — counts, skipped files, file errors, duplicates,
  rejections, identity conflicts, and per-record outcomes

Exit codes: 0 on success (individual invalid records never fail the run),
1 for unrecoverable input or configuration errors.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from app.ingestion.errors import IngestionError
from app.ingestion.pipeline import PipelineResult, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.ingestion.cli",
        description=(
            "Ingest synthetic EHR source files (JSON, CSV, TXT) into canonical "
            "patients and records with a full audit trail."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="input files or directories to ingest (directories are walked recursively)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="directory to write patients.json, records.json, and ingestion_report.json",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_pipeline(args.paths)
    except IngestionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    dumped = result.model_dump(mode="json")
    _write_json(output_dir / "patients.json", {"patients": dumped["patients"]})
    _write_json(output_dir / "records.json", {"records": dumped["records"]})
    _write_json(output_dir / "ingestion_report.json", _build_report(result))

    counts = result.counts
    print(
        f"files: {counts.files_processed} processed, "
        f"{counts.files_skipped} skipped, {counts.files_failed} failed"
    )
    print(f"raw records:  {counts.raw_records}")
    print(f"accepted:     {counts.accepted_records} records / {counts.accepted_patients} patients")
    print(f"duplicates:   {counts.duplicate_records}")
    print(f"rejected:     {counts.rejected_records}")
    print(f"conflicts:    {counts.identity_conflicts}")
    print(f"output written to {output_dir}")
    return 0


def _build_report(result: PipelineResult) -> dict[str, object]:
    """Assemble the ingestion report, including per-record outcomes."""
    dumped = result.model_dump(mode="json")
    accepted_outcomes = [
        {
            "record_id": record["record_id"],
            "patient_id": record["patient_id"],
            "source_file": record["source_file"],
            "source_record_id": record["source_record_id"],
            "audit": record["audit"],
        }
        for record in dumped["records"]
    ]
    return {
        "counts": dumped["counts"],
        "skipped_files": dumped["skipped_files"],
        "file_errors": dumped["file_errors"],
        "accepted_records": accepted_outcomes,
        "duplicates": dumped["duplicates"],
        "rejected": dumped["rejected"],
        "conflicts": dumped["conflicts"],
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    """Write JSON deterministically (sorted keys, LF line endings)."""
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
        handle.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
