"""Persistent ChromaDB index wrapper.

Wraps a cosine-distance Chroma collection with a per-patient reconcile that is
idempotent (unchanged documents are neither re-embedded nor rewritten) and
that removes stale entries when a patient's Bundle changes. Nothing here opens
Chroma at import time; a client is created only when the store is constructed.
"""

from dataclasses import dataclass
from typing import Any

from app.search.documents import IndexDocument
from app.search.embeddings import Embedder


@dataclass(frozen=True)
class ReconcileCounts:
    """Per-reconcile tallies."""

    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0


@dataclass
class QueryHit:
    """One raw hit from a vector query."""

    doc_id: str
    document: str
    metadata: dict[str, Any]
    distance: float


def open_persistent_index(*, path: str, collection: str, embedder: Embedder) -> "ChromaIndex":
    """Open (or create) a persistent Chroma collection and wrap it.

    ``chromadb`` is imported here so importing this module never opens Chroma.
    """
    import chromadb

    client = chromadb.PersistentClient(path=path)
    chroma_collection = client.get_or_create_collection(
        name=collection, metadata={"hnsw:space": "cosine"}
    )
    return ChromaIndex(chroma_collection, embedder)


class ChromaIndex:
    """A cosine-similarity vector collection for clinical documents."""

    def __init__(self, collection: Any, embedder: Embedder) -> None:
        self._collection = collection
        self._embedder = embedder

    def count(self) -> int:
        return int(self._collection.count())

    def reconcile_patient(self, patient_id: str, documents: list[IndexDocument]) -> ReconcileCounts:
        """Insert/update/remove a patient's documents to match ``documents``.

        Only inserted and updated documents are embedded, so re-running with
        unchanged data performs no embedding and no writes.
        """
        desired = {doc.doc_id: doc for doc in documents}
        desired_meta = {doc_id: doc.with_content_hash() for doc_id, doc in desired.items()}

        existing = self._collection.get(where={"patient_id": patient_id}, include=["metadatas"])
        existing_ids: list[str] = list(existing.get("ids") or [])
        existing_metas: list[dict[str, Any]] = list(existing.get("metadatas") or [])
        existing_hash = {
            doc_id: (meta or {}).get("content_hash")
            for doc_id, meta in zip(existing_ids, existing_metas, strict=False)
        }

        to_write: list[str] = []
        inserted = updated = unchanged = 0
        for doc_id, meta in desired_meta.items():
            if doc_id not in existing_hash:
                inserted += 1
                to_write.append(doc_id)
            elif existing_hash[doc_id] != meta["content_hash"]:
                updated += 1
                to_write.append(doc_id)
            else:
                unchanged += 1

        stale = [doc_id for doc_id in existing_ids if doc_id not in desired]
        if stale:
            self._collection.delete(ids=stale)

        if to_write:
            texts = [desired[doc_id].text for doc_id in to_write]
            embeddings = self._embedder.embed(texts)
            self._collection.upsert(
                ids=to_write,
                embeddings=embeddings,
                documents=texts,
                metadatas=[desired_meta[doc_id] for doc_id in to_write],
            )

        return ReconcileCounts(
            inserted=inserted, updated=updated, unchanged=unchanged, removed=len(stale)
        )

    def query(
        self,
        embedding: list[float],
        *,
        n_results: int,
        where: dict[str, Any] | None = None,
    ) -> list[QueryHit]:
        """Return raw query hits (may be empty)."""
        if n_results <= 0:
            return []
        result = self._collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        hits: list[QueryHit] = []
        for doc_id, document, metadata, distance in zip(
            ids, documents, metadatas, distances, strict=False
        ):
            hits.append(
                QueryHit(
                    doc_id=doc_id,
                    document=document or "",
                    metadata=dict(metadata or {}),
                    distance=float(distance),
                )
            )
        return hits
