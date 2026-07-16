"""POST /search endpoint for semantic search.

The search engine (embedding model + Chroma client) is provided by dependency
injection and built lazily on first request, never at import time. API tests
override the dependency with a fake engine.
"""

from datetime import date
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.config import get_settings
from app.search.embeddings import SentenceTransformerEmbedder
from app.search.errors import IndexUnavailableError, SearchValidationError
from app.search.index_store import open_persistent_index
from app.search.service import SearchEngine, SearchQuery, SearchResponse, SearchService

router = APIRouter()


class SearchRequestBody(BaseModel):
    """Request body for POST /search."""

    query: str


@lru_cache
def _build_engine() -> SearchService:
    settings = get_settings()
    embedder = SentenceTransformerEmbedder(settings.embedding_model)
    index = open_persistent_index(
        path=settings.chroma_path,
        collection=settings.chroma_collection,
        embedder=embedder,
    )
    return SearchService(index=index, embedder=embedder)


def get_search_engine() -> SearchEngine:
    """Provide the shared search engine, or a 503 if it cannot be opened."""
    try:
        return _build_engine()
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean service error
        raise HTTPException(status_code=503, detail="search index is unavailable") from exc


@router.post("/search", response_model=SearchResponse)
def post_search(
    body: SearchRequestBody,
    engine: Annotated[SearchEngine, Depends(get_search_engine)],
    resource_type: Annotated[str | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> SearchResponse:
    """Run semantic search over indexed clinical resources."""
    request = SearchQuery(
        query=body.query,
        resource_type=resource_type,
        date_from=date_from,
        date_to=date_to,
    )
    try:
        return engine.search(request)
    except SearchValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IndexUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
