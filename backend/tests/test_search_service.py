"""Tests for search scoring, filtering, and result shaping."""

from collections.abc import Callable
from datetime import date

import pytest

from app.search.documents import IndexDocument
from app.search.errors import IndexUnavailableError, SearchValidationError
from app.search.index_store import ChromaIndex
from app.search.service import SearchQuery, SearchService

IndexFactory = Callable[..., ChromaIndex]


def _resource(
    doc_id: str,
    patient_id: str,
    text: str,
    *,
    resource_type: str = "DocumentReference",
    record_date: str | None = None,
    patient_name: str = "Avery Kestrel",
) -> IndexDocument:
    metadata = {
        "document_kind": "resource",
        "patient_id": patient_id,
        "patient_name": patient_name,
        "mrn": "MRN-1",
        "resource_id": doc_id.split(":", 1)[1],
        "resource_type": resource_type,
        "title": text,
        "bundle_hash": "hash-1",
    }
    if record_date is not None:
        metadata["record_date"] = record_date
    return IndexDocument(doc_id=doc_id, text=text, metadata=metadata)


def _summary(doc_id: str, patient_id: str, text: str) -> IndexDocument:
    return IndexDocument(
        doc_id=doc_id,
        text=text,
        metadata={
            "document_kind": "summary",
            "patient_id": patient_id,
            "bundle_hash": "hash-1",
            "model_name": "m",
            "prompt_version": "clinical-summary-v1",
        },
    )


def _service(index: ChromaIndex, embedder: object) -> SearchService:
    return SearchService(index=index, embedder=embedder)  # type: ignore[arg-type]


def test_semantic_ranking_orders_by_similarity(embedder: object, make_index: IndexFactory) -> None:
    index = make_index(embedder)
    index.reconcile_patient(
        "PAT-1",
        [
            _resource("resource:a", "PAT-1", "chest imaging radiograph findings"),
            _resource("resource:b", "PAT-1", "routine medication refill note"),
        ],
    )
    response = _service(index, embedder).search(SearchQuery(query="chest imaging"))
    assert response.results[0].resource_id == "a"
    assert response.results[0].relevance_score >= response.results[-1].relevance_score


def test_resource_type_filter(embedder: object, make_index: IndexFactory) -> None:
    index = make_index(embedder)
    index.reconcile_patient(
        "PAT-1",
        [
            _resource("resource:a", "PAT-1", "chest imaging", resource_type="DocumentReference"),
            _resource("resource:b", "PAT-1", "chest imaging", resource_type="DiagnosticReport"),
        ],
    )
    response = _service(index, embedder).search(
        SearchQuery(query="chest imaging", resource_type="DiagnosticReport")
    )
    assert [r.resource_type for r in response.results] == ["DiagnosticReport"]


def test_date_filter_excludes_out_of_range_and_undated(
    embedder: object, make_index: IndexFactory
) -> None:
    index = make_index(embedder)
    index.reconcile_patient(
        "PAT-1",
        [
            _resource("resource:in", "PAT-1", "chest imaging", record_date="2024-05-01"),
            _resource("resource:out", "PAT-1", "chest imaging", record_date="2023-01-01"),
            _resource("resource:undated", "PAT-1", "chest imaging"),
        ],
    )
    response = _service(index, embedder).search(
        SearchQuery(
            query="chest imaging",
            date_from=date(2024, 1, 1),
            date_to=date(2024, 12, 31),
        )
    )
    ids = {r.resource_id for r in response.results}
    assert ids == {"in"}


def test_summary_boost_lifts_matching_patient(embedder: object, make_index: IndexFactory) -> None:
    index = make_index(embedder)
    # Two identical resources for different patients; only PAT-2 has a summary
    # that matches the query, so PAT-2's resource should rank first.
    index.reconcile_patient("PAT-1", [_resource("resource:a", "PAT-1", "generic note text")])
    index.reconcile_patient(
        "PAT-2",
        [
            _resource("resource:b", "PAT-2", "generic note text"),
            _summary("summary:s2", "PAT-2", "chest imaging abnormal opacity"),
        ],
    )
    response = _service(index, embedder).search(SearchQuery(query="chest imaging"))
    assert response.results[0].patient_id == "PAT-2"
    assert response.results[0].clinical_summary_snippet is not None


def test_top_five_limit_and_stable_tie_order(embedder: object, make_index: IndexFactory) -> None:
    index = make_index(embedder)
    # Seven identical-text resources -> identical scores -> tie broken by
    # ascending resource_id; only five returned.
    docs = [_resource(f"resource:{i}", "PAT-1", "same text") for i in range(7)]
    index.reconcile_patient("PAT-1", docs)
    response = _service(index, embedder).search(SearchQuery(query="same text"))
    assert response.result_count == 5
    assert [r.resource_id for r in response.results] == ["0", "1", "2", "3", "4"]


def test_empty_query_rejected(embedder: object, make_index: IndexFactory) -> None:
    index = make_index(embedder)
    index.reconcile_patient("PAT-1", [_resource("resource:a", "PAT-1", "text")])
    with pytest.raises(SearchValidationError):
        _service(index, embedder).search(SearchQuery(query="   "))


def test_bad_date_range_rejected(embedder: object, make_index: IndexFactory) -> None:
    index = make_index(embedder)
    index.reconcile_patient("PAT-1", [_resource("resource:a", "PAT-1", "text")])
    with pytest.raises(SearchValidationError):
        _service(index, embedder).search(
            SearchQuery(
                query="text",
                date_from=date(2024, 12, 31),
                date_to=date(2024, 1, 1),
            )
        )


def test_unsupported_resource_type_rejected(embedder: object, make_index: IndexFactory) -> None:
    index = make_index(embedder)
    index.reconcile_patient("PAT-1", [_resource("resource:a", "PAT-1", "text")])
    with pytest.raises(SearchValidationError):
        _service(index, embedder).search(SearchQuery(query="text", resource_type="Observation"))


def test_empty_index_raises_unavailable(embedder: object, make_index: IndexFactory) -> None:
    index = make_index(embedder)
    with pytest.raises(IndexUnavailableError):
        _service(index, embedder).search(SearchQuery(query="anything"))
