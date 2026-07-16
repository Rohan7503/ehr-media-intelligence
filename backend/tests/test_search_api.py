"""API tests for POST /search using an injected fake/real engine."""

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.search import get_search_engine
from app.main import create_app
from app.search.documents import IndexDocument
from app.search.errors import IndexUnavailableError
from app.search.index_store import ChromaIndex
from app.search.service import SearchQuery, SearchResponse, SearchService

IndexFactory = Callable[..., ChromaIndex]


def _resource(doc_id: str, text: str) -> IndexDocument:
    return IndexDocument(
        doc_id=doc_id,
        text=text,
        metadata={
            "document_kind": "resource",
            "patient_id": "PAT-1",
            "patient_name": "Avery Kestrel",
            "mrn": "MRN-1",
            "resource_id": doc_id.split(":", 1)[1],
            "resource_type": "DocumentReference",
            "title": text,
            "bundle_hash": "hash-1",
        },
    )


@pytest.fixture
def client(embedder: object, make_index: IndexFactory) -> Iterator[TestClient]:
    index = make_index(embedder)
    index.reconcile_patient(
        "PAT-1",
        [
            _resource("resource:a", "chest imaging radiograph"),
            _resource("resource:b", "medication refill"),
        ],
    )
    service = SearchService(index=index, embedder=embedder)  # type: ignore[arg-type]
    app = create_app()
    app.dependency_overrides[get_search_engine] = lambda: service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_search_success(client: TestClient) -> None:
    response = client.post("/search", json={"query": "chest imaging"})
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "chest imaging"
    assert body["result_count"] >= 1
    assert body["results"][0]["resource_id"] == "a"
    assert "relevance_score" in body["results"][0]
    assert "elapsed_ms" in body


def test_search_with_resource_type_filter(client: TestClient) -> None:
    response = client.post(
        "/search", json={"query": "chest imaging"}, params={"resource_type": "DocumentReference"}
    )
    assert response.status_code == 200


def test_empty_query_is_422(client: TestClient) -> None:
    response = client.post("/search", json={"query": "   "})
    assert response.status_code == 422


def test_unsupported_resource_type_is_422(client: TestClient) -> None:
    response = client.post("/search", json={"query": "x"}, params={"resource_type": "Observation"})
    assert response.status_code == 422


def test_bad_date_range_is_422(client: TestClient) -> None:
    response = client.post(
        "/search",
        json={"query": "x"},
        params={"date_from": "2024-12-31", "date_to": "2024-01-01"},
    )
    assert response.status_code == 422


def test_malformed_date_is_422(client: TestClient) -> None:
    response = client.post("/search", json={"query": "x"}, params={"date_from": "not-a-date"})
    assert response.status_code == 422


def test_unavailable_index_returns_service_error() -> None:
    class Unavailable:
        def search(self, request: SearchQuery) -> SearchResponse:
            raise IndexUnavailableError("the search index is empty")

    app = create_app()
    app.dependency_overrides[get_search_engine] = lambda: Unavailable()
    with TestClient(app) as client:
        response = client.post("/search", json={"query": "chest imaging"})
    app.dependency_overrides.clear()
    assert response.status_code == 503
    assert "stack" not in response.text.lower()
