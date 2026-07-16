"""CLI for generating cached clinical summaries from stored FHIR Bundles.

Usage (from ``backend/``)::

    python -m app.summarization.cli \\
        --database-url sqlite:///../data/generated/ehr_media.db \\
        --output-dir ../data/generated/summaries

Reads valid Bundles already stored by the FHIR pipeline (it never re-runs
ingestion or FHIR normalization), summarizes all patients or one ``--patient-id``,
reuses cached summaries where possible, and writes deterministic summary and
quality JSON. Cached summaries are usable without an API key; generating a new
summary requires ``ANTHROPIC_API_KEY`` and a model (``ANTHROPIC_MODEL``).

Exit codes:
  0  all requested summaries available (generated, cached, or nothing to do)
  1  one or more summaries failed
  2  unrecoverable configuration, database, or storage failure
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.persistence.database import StorageError, create_db_engine, init_db
from app.persistence.repositories.bundles import BundleRepository
from app.summarization.provider import AnthropicSummaryProvider
from app.summarization.render import render_report_json, render_summaries_json
from app.summarization.service import SummarizationReport, SummarizationService

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_FATAL = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.summarization.cli",
        description="Generate cached clinical summaries from stored FHIR Bundles.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="directory for summaries.json and summary_quality_report.json",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="SQLAlchemy database URL (defaults to the configured DATABASE_URL)",
    )
    parser.add_argument(
        "--patient-id",
        default=None,
        help="summarize only this patient (default: all stored patients)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Anthropic model (defaults to the configured ANTHROPIC_MODEL)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    database_url = args.database_url or settings.database_url
    model_name = args.model or settings.anthropic_model

    try:
        engine = create_db_engine(database_url)
        init_db(engine)
    except Exception as exc:  # noqa: BLE001 - configuration/db failure is fatal
        print(f"error: could not open database '{database_url}': {exc}", file=sys.stderr)
        return EXIT_FATAL

    provider = AnthropicSummaryProvider(api_key=settings.anthropic_api_key, model=model_name)
    output_dir: Path = args.output_dir

    try:
        with Session(engine) as session:
            patient_ids = _select_patients(session, args.patient_id)
            if not patient_ids:
                print("no stored patients to summarize", file=sys.stderr)
            service = SummarizationService(
                session=session, provider=provider, model_name=model_name
            )
            report = service.summarize(patient_ids)
    except StorageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FATAL
    finally:
        engine.dispose()

    _write_outputs(output_dir, report)
    _print_summary(report)
    return EXIT_FAILED if report.failed > 0 else EXIT_OK


def _select_patients(session: Session, patient_id: str | None) -> list[str]:
    if patient_id is not None:
        return [patient_id]
    metadata = BundleRepository(session).list_bundle_metadata()
    return sorted(row.patient_id for row in metadata if row.valid)


def _write_outputs(output_dir: Path, report: SummarizationReport) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summaries.json").write_text(
        render_summaries_json(report), encoding="utf-8", newline="\n"
    )
    (output_dir / "summary_quality_report.json").write_text(
        render_report_json(report), encoding="utf-8", newline="\n"
    )


def _print_summary(report: SummarizationReport) -> None:
    print(f"model:        {report.model_name}")
    print(f"prompt:       {report.prompt_version}")
    print(
        f"summaries:    {report.generated} generated, {report.cached} cached, "
        f"{report.skipped} skipped, {report.failed} failed"
    )
    if report.failed:
        needs_key = any(
            result.error and "ANTHROPIC_API_KEY" in result.error for result in report.results
        )
        for result in report.results:
            if result.status == "failed":
                print(f"  FAILED {result.patient_id}: {result.error}", file=sys.stderr)
        if needs_key:
            print(
                "hint: set ANTHROPIC_API_KEY (and ANTHROPIC_MODEL) to generate new "
                "summaries; cached summaries need no key",
                file=sys.stderr,
            )


if __name__ == "__main__":
    raise SystemExit(main())
