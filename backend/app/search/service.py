"""Semantic search service: scoring, filtering, and the top-five results.

Scoring rule (simple, deterministic, documented):

- A clinical resource's base relevance is ``1 - cosine_distance / 2``, mapping
  Chroma's cosine distance (``0`` identical … ``2`` opposite) to ``[0, 1]``
  where higher is better.
- Each patient gets a summary relevance equal to the best base score among
  that patient's summary documents (``0`` if none). The final resource score is
  ``base + SUMMARY_BOOST * summary_relevance`` — a small patient-level boost
  that never replaces the clinical resource as the returned result.

Results are clinical resources only, ordered by descending score then ascending
resource ID as a stable tie-breaker, limited to five.
"""

import time
from datetime import date
from typing import Protocol

from pydantic import BaseModel

from app.search.documents import KIND_RESOURCE, KIND_SUMMARY, snippet
from app.search.embeddings import Embedder
from app.search.errors import IndexUnavailableError, SearchValidationError
from app.search.index_store import ChromaIndex, QueryHit

TOP_K = 5
SUMMARY_BOOST = 0.1
_CANDIDATE_CAP = 500
ALLOWED_RESOURCE_TYPES = ("DocumentReference", "DiagnosticReport")


class SearchQuery(BaseModel):
    """A validated search request."""

    query: str
    resource_type: str | None = None
    date_from: date | None = None
    date_to: date | None = None


class SearchResultItem(BaseModel):
    """One clinical-resource search result."""

    patient_id: str
    patient_name: str
    mrn: str
    resource_id: str
    resource_type: str
    record_date: str | None = None
    title: str
    relevance_score: float
    resource_text_snippet: str
    clinical_summary_snippet: str | None = None


class SearchResponse(BaseModel):
    """The typed search response."""

    query: str
    result_count: int
    elapsed_ms: float
    results: list[SearchResultItem]


class SearchEngine(Protocol):
    """Runs a validated search and returns a response."""

    def search(self, request: SearchQuery) -> SearchResponse: ...


def _score_from_distance(distance: float) -> float:
    """Map cosine distance in ``[0, 2]`` to a relevance score in ``[0, 1]``."""
    return max(0.0, min(1.0, 1.0 - distance / 2.0))


def _parse_date(value: object) -> date | None:
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


class SearchService:
    """Cosine semantic search over the clinical-resource and summary index."""

    def __init__(self, *, index: ChromaIndex, embedder: Embedder) -> None:
        self._index = index
        self._embedder = embedder

    def search(self, request: SearchQuery) -> SearchResponse:
        started = time.perf_counter()
        self._validate(request)

        total = self._index.count()
        if total <= 0:
            raise IndexUnavailableError("the search index is empty; build it with the indexing CLI")

        embedding = self._embedder.embed([request.query])[0]
        n_results = min(total, _CANDIDATE_CAP)

        summary_relevance, summary_snippets = self._summary_signals(embedding, n_results)
        resource_hits = self._index.query(
            embedding, n_results=n_results, where=self._resource_where(request.resource_type)
        )

        scored: list[tuple[float, str, SearchResultItem]] = []
        for hit in resource_hits:
            if not self._passes_date_filter(hit, request):
                continue
            patient_id = str(hit.metadata.get("patient_id", ""))
            base = _score_from_distance(hit.distance)
            score = base + SUMMARY_BOOST * summary_relevance.get(patient_id, 0.0)
            item = SearchResultItem(
                patient_id=patient_id,
                patient_name=str(hit.metadata.get("patient_name", "")),
                mrn=str(hit.metadata.get("mrn", "")),
                resource_id=str(hit.metadata.get("resource_id", "")),
                resource_type=str(hit.metadata.get("resource_type", "")),
                record_date=hit.metadata.get("record_date"),
                title=str(hit.metadata.get("title", "")),
                relevance_score=round(score, 6),
                resource_text_snippet=snippet(hit.document),
                clinical_summary_snippet=summary_snippets.get(patient_id),
            )
            scored.append((score, item.resource_id, item))

        scored.sort(key=lambda entry: (-entry[0], entry[1]))
        results = [item for _, _, item in scored[:TOP_K]]
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        return SearchResponse(
            query=request.query,
            result_count=len(results),
            elapsed_ms=elapsed_ms,
            results=results,
        )

    def _validate(self, request: SearchQuery) -> None:
        if not request.query.strip():
            raise SearchValidationError("query must not be empty")
        if (
            request.resource_type is not None
            and request.resource_type not in ALLOWED_RESOURCE_TYPES
        ):
            allowed = ", ".join(ALLOWED_RESOURCE_TYPES)
            raise SearchValidationError(
                f"unsupported resource_type '{request.resource_type}'; allowed: {allowed}"
            )
        if (
            request.date_from is not None
            and request.date_to is not None
            and request.date_from > request.date_to
        ):
            raise SearchValidationError("date_from must be on or before date_to")

    def _resource_where(self, resource_type: str | None) -> dict[str, object]:
        conditions: list[dict[str, object]] = [{"document_kind": {"$eq": KIND_RESOURCE}}]
        if resource_type is not None:
            conditions.append({"resource_type": {"$eq": resource_type}})
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    def _summary_signals(
        self, embedding: list[float], n_results: int
    ) -> tuple[dict[str, float], dict[str, str]]:
        hits = self._index.query(
            embedding, n_results=n_results, where={"document_kind": {"$eq": KIND_SUMMARY}}
        )
        relevance: dict[str, float] = {}
        snippets: dict[str, str] = {}
        for hit in hits:
            patient_id = str(hit.metadata.get("patient_id", ""))
            score = _score_from_distance(hit.distance)
            if score > relevance.get(patient_id, -1.0):
                relevance[patient_id] = score
                snippets[patient_id] = snippet(hit.document)
        return relevance, snippets

    def _passes_date_filter(self, hit: QueryHit, request: SearchQuery) -> bool:
        if request.date_from is None and request.date_to is None:
            return True
        record_date = _parse_date(hit.metadata.get("record_date"))
        if record_date is None:
            return False
        if request.date_from is not None and record_date < request.date_from:
            return False
        return not (request.date_to is not None and record_date > request.date_to)
