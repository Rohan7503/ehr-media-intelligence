"""Summarization service: cache-aware orchestration over stored Bundles.

For each patient the service loads the current valid Bundle, checks the cache
(no provider call or API key needed on a hit), and on a miss extracts
evidence, calls the provider, validates and assembles the summary, enforces
the word limit, runs quality checks, and caches valid results. One patient's
failure never stops the others.
"""

from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.persistence.database import StorageError
from app.persistence.repositories.bundles import BundleRepository
from app.summarization.cache import SummaryCacheKey, SummaryRepository
from app.summarization.errors import (
    MalformedResponseError,
    SummarizationError,
    WordLimitError,
)
from app.summarization.evidence import extract_patient_evidence
from app.summarization.prompt import PROMPT_VERSION, SYSTEM_PROMPT, build_user_message
from app.summarization.provider import SummaryProvider
from app.summarization.quality import QualityResult, check_summary
from app.summarization.summary import (
    WORD_LIMIT,
    ClinicalSummary,
    SummaryDraft,
    build_clinical_summary,
    render_summary,
)

SummaryStatus = Literal["generated", "cached", "failed", "skipped"]


class PatientSummaryResult(BaseModel):
    """Per-patient outcome of a summarization run."""

    patient_id: str
    status: SummaryStatus
    summary: ClinicalSummary | None = None
    quality: QualityResult | None = None
    error: str | None = None


class SummarizationReport(BaseModel):
    """Aggregate outcome of a summarization run."""

    model_name: str
    prompt_version: str
    generated: int = 0
    cached: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[PatientSummaryResult] = Field(default_factory=list)


class SummarizationService:
    """Generates and caches clinical summaries for stored patients."""

    def __init__(
        self,
        *,
        session: Session,
        provider: SummaryProvider,
        model_name: str,
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        self._session = session
        self._bundles = BundleRepository(session)
        self._summaries = SummaryRepository(session)
        self._provider = provider
        self._model_name = model_name
        self._prompt_version = prompt_version

    def summarize_patient(self, patient_id: str) -> PatientSummaryResult:
        """Summarize one patient, converting expected failures into a result."""
        bundle = self._bundles.get_bundle_by_patient_id(patient_id)
        if bundle is None or not bundle.valid:
            return PatientSummaryResult(
                patient_id=patient_id,
                status="skipped",
                error="no valid stored Bundle to summarize",
            )

        key = SummaryCacheKey(
            patient_id=patient_id,
            record_hash=bundle.bundle_hash,
            model_name=self._model_name,
            prompt_version=self._prompt_version,
        )
        resource_ids = set(extract_patient_evidence(patient_id, bundle.bundle_json).resource_ids)

        cached = self._summaries.get_current(key)
        if cached is not None:
            summary = ClinicalSummary.model_validate_json(cached.summary_json)
            return PatientSummaryResult(
                patient_id=patient_id,
                status="cached",
                summary=summary,
                quality=check_summary(summary, resource_ids),
            )

        try:
            summary, quality = self._generate(patient_id, bundle.bundle_json, resource_ids)
        except (SummarizationError, StorageError) as exc:
            return PatientSummaryResult(patient_id=patient_id, status="failed", error=str(exc))

        if not quality.valid:
            # Do not cache a summary that fails deterministic quality checks.
            return PatientSummaryResult(
                patient_id=patient_id,
                status="failed",
                summary=summary,
                quality=quality,
                error="; ".join(quality.errors),
            )

        self._summaries.store(
            key,
            summary_json=summary.model_dump_json(),
            rendered_text=render_summary(summary),
            word_count=summary.word_count,
        )
        return PatientSummaryResult(
            patient_id=patient_id, status="generated", summary=summary, quality=quality
        )

    def _generate(
        self, patient_id: str, bundle_json: str, resource_ids: set[str]
    ) -> tuple[ClinicalSummary, QualityResult]:
        evidence = extract_patient_evidence(patient_id, bundle_json)
        raw = self._provider.generate(system=SYSTEM_PROMPT, user=build_user_message(evidence))
        try:
            draft = SummaryDraft.model_validate(raw)
        except ValidationError as exc:
            raise MalformedResponseError(
                f"provider response did not match the summary schema: {exc.error_count()} error(s)"
            ) from exc
        summary = build_clinical_summary(patient_id, draft)
        if summary.word_count >= WORD_LIMIT:
            raise WordLimitError(
                f"rendered summary has {summary.word_count} words (limit {WORD_LIMIT})"
            )
        return summary, check_summary(summary, resource_ids)

    def summarize(self, patient_ids: list[str]) -> SummarizationReport:
        """Summarize the given patients, tallying outcomes."""
        report = SummarizationReport(
            model_name=self._model_name, prompt_version=self._prompt_version
        )
        for patient_id in patient_ids:
            result = self.summarize_patient(patient_id)
            report.results.append(result)
            if result.status == "generated":
                report.generated += 1
            elif result.status == "cached":
                report.cached += 1
            elif result.status == "skipped":
                report.skipped += 1
            else:
                report.failed += 1
        return report
