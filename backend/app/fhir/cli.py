"""End-to-end CLI: ingestion followed by FHIR mapping and persistence.

Usage (from ``backend/``)::

    python -m app.fhir.cli ../data/synthetic --output-dir ../data/generated/fhir --database-url sqlite:///../data/generated/ehr_media.db

Runs the existing ingestion pipeline, maps one Bundle per accepted patient,
validates and persists each Bundle to SQLite, and writes readable Bundle JSON
plus an aggregate validation report. No network calls and no API key required.

Exit codes:
  0  all Bundles valid
  1  one or more Bundles invalid (reports are still written)
  2  unrecoverable configuration, input, or storage failure
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.fhir.pipeline import canonical_json, pretty_json, run_fhir_pipeline
from app.fhir.report import FHIRPipelineReport
from app.ingestion.errors import IngestionError
from app.ingestion.pipeline import run_pipeline
from app.persistence.database import StorageError, create_db_engine, init_db

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_FATAL = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.fhir.cli",
        description=(
            "Ingest synthetic EHR files, map accepted records to FHIR Bundles, "
            "validate them, and persist Bundles and reports to SQLite."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="input files or directories to ingest",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="directory for exported Bundle JSON and the aggregate report",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="SQLAlchemy database URL (defaults to the configured DATABASE_URL)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database_url = args.database_url or get_settings().database_url

    try:
        ingestion = run_pipeline(args.paths)
    except IngestionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FATAL

    output_dir: Path = args.output_dir
    try:
        engine = create_db_engine(database_url)
        init_db(engine)
    except Exception as exc:  # noqa: BLE001 - configuration/storage failure is fatal
        print(f"error: could not initialize database '{database_url}': {exc}", file=sys.stderr)
        return EXIT_FATAL

    try:
        with Session(engine) as session:
            report = run_fhir_pipeline(ingestion, session=session, export_dir=output_dir)
    except StorageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FATAL
    finally:
        engine.dispose()

    _write_report(output_dir, report)
    _print_summary(report, ingestion.counts.accepted_records, database_url)

    return EXIT_INVALID if report.invalid_bundle_count > 0 else EXIT_OK


def _write_report(output_dir: Path, report: FHIRPipelineReport) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "fhir_report.json").write_text(
        pretty_json(report.model_dump(mode="json")), encoding="utf-8", newline="\n"
    )


def _print_summary(report: FHIRPipelineReport, accepted_records: int, database_url: str) -> None:
    target = f"{report.model_library} / {report.model_namespace}"
    print(f"target:       FHIR {report.fhir_version} ({target})")
    print(f"patients:     {report.patient_count}")
    valid_summary = f"{report.valid_bundle_count} valid, {report.invalid_bundle_count} invalid"
    print(f"bundles:      {report.bundle_count} ({valid_summary})")
    print(f"resources:    {canonical_json(dict(report.resource_totals))}")
    print(f"accepted records ingested: {accepted_records}")
    stored = {"inserted": 0, "updated": 0, "unchanged": 0}
    for result in report.storage_results:
        stored[result.outcome] += 1
    print(
        f"storage:      {stored['inserted']} inserted, "
        f"{stored['updated']} updated, {stored['unchanged']} unchanged  ->  {database_url}"
    )
    if report.invalid_bundle_count:
        print(
            f"WARNING: {report.invalid_bundle_count} invalid Bundle(s); see fhir_report.json",
            file=sys.stderr,
        )


if __name__ == "__main__":
    raise SystemExit(main())
