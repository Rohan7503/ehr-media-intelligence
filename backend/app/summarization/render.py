"""Deterministic JSON rendering of summarization run outputs."""

import json

from app.summarization.service import SummarizationReport
from app.summarization.summary import render_summary


def _pretty(payload: dict[str, object]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render_summaries_json(report: SummarizationReport) -> str:
    """Render available summaries (generated or cached) as deterministic JSON."""
    summaries = [
        {
            "patient_id": result.patient_id,
            "status": result.status,
            "summary": result.summary.model_dump(mode="json"),
            "rendered": render_summary(result.summary),
        }
        for result in sorted(report.results, key=lambda r: r.patient_id)
        if result.summary is not None and result.status in ("generated", "cached")
    ]
    return _pretty(
        {
            "model": report.model_name,
            "prompt_version": report.prompt_version,
            "summaries": summaries,
        }
    )


def render_report_json(report: SummarizationReport) -> str:
    """Render the aggregate quality report as deterministic JSON."""
    patients = [
        {
            "patient_id": result.patient_id,
            "status": result.status,
            "quality": result.quality.model_dump(mode="json") if result.quality else None,
            "error": result.error,
        }
        for result in sorted(report.results, key=lambda r: r.patient_id)
    ]
    return _pretty(
        {
            "model": report.model_name,
            "prompt_version": report.prompt_version,
            "counts": {
                "generated": report.generated,
                "cached": report.cached,
                "skipped": report.skipped,
                "failed": report.failed,
            },
            "patients": patients,
        }
    )
