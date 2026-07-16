"""Repository for the clinical-summary cache.

The effective cache key is ``(patient_id, record_hash, model_name,
prompt_version)``. Reads never touch the provider, so a cached summary is
usable without an API key. Writes run in a transaction and roll back cleanly
on failure; storing a new key never overwrites unrelated historical rows.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.persistence.database import StorageError
from app.summarization.cache_models import SummaryCacheRow


@dataclass(frozen=True)
class SummaryCacheKey:
    """The four fields that identify a cached summary."""

    patient_id: str
    record_hash: str
    model_name: str
    prompt_version: str


class SummaryRepository:
    """Data-access methods for the summary cache."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_current(self, key: SummaryCacheKey) -> SummaryCacheRow | None:
        """Return the cached summary for a key, or ``None`` on a cache miss."""
        return self._session.scalar(
            select(SummaryCacheRow).where(
                SummaryCacheRow.patient_id == key.patient_id,
                SummaryCacheRow.record_hash == key.record_hash,
                SummaryCacheRow.model_name == key.model_name,
                SummaryCacheRow.prompt_version == key.prompt_version,
            )
        )

    def store(
        self,
        key: SummaryCacheKey,
        *,
        summary_json: str,
        rendered_text: str,
        word_count: int,
    ) -> None:
        """Insert or refresh the row for a key, leaving other rows untouched."""
        session = self._session
        try:
            existing = self.get_current(key)
            if existing is None:
                session.add(
                    SummaryCacheRow(
                        patient_id=key.patient_id,
                        record_hash=key.record_hash,
                        model_name=key.model_name,
                        prompt_version=key.prompt_version,
                        summary_json=summary_json,
                        rendered_text=rendered_text,
                        word_count=word_count,
                    )
                )
            else:
                existing.summary_json = summary_json
                existing.rendered_text = rendered_text
                existing.word_count = word_count
            session.commit()
        except Exception as exc:  # noqa: BLE001 - re-raised as StorageError
            session.rollback()
            raise StorageError(f"failed to store summary for {key.patient_id}: {exc}") from exc

    def list_for_bundle(self, patient_id: str, record_hash: str) -> list[SummaryCacheRow]:
        """Return all cached summaries for a patient's current Bundle hash.

        Used by the search indexer to include whatever summaries exist for the
        current Bundle, across models and prompt versions.
        """
        return list(
            self._session.scalars(
                select(SummaryCacheRow)
                .where(
                    SummaryCacheRow.patient_id == patient_id,
                    SummaryCacheRow.record_hash == record_hash,
                )
                .order_by(SummaryCacheRow.model_name, SummaryCacheRow.prompt_version)
            ).all()
        )

    def count(self) -> int:
        """Return the number of cached summaries."""
        result = self._session.scalar(select(func.count()).select_from(SummaryCacheRow))
        return result or 0
