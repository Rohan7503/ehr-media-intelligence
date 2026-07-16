"""Indexer: build or update the vector index from stored data.

Reads valid stored Bundles and their available cached summaries (summaries are
optional — resources are always indexed) and reconciles each patient's
documents into the Chroma index. Reconciling is idempotent and removes stale
entries when a patient's Bundle changes. No ingestion, FHIR mapping, or
summarization is run here, and no Anthropic API is called.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.persistence.repositories.bundles import BundleRepository
from app.search.documents import build_resource_documents, build_summary_documents
from app.search.index_store import ChromaIndex
from app.summarization.cache import SummaryRepository


@dataclass
class IndexReport:
    """Aggregate outcome of an indexing run."""

    patients: int = 0
    resource_documents: int = 0
    summary_documents: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0


class Indexer:
    """Builds and maintains the semantic search index from stored data."""

    def __init__(self, *, session: Session, index: ChromaIndex) -> None:
        self._bundles = BundleRepository(session)
        self._summaries = SummaryRepository(session)
        self._index = index

    def reindex_all(self) -> IndexReport:
        """Reconcile every valid stored Bundle into the index."""
        report = IndexReport()
        for meta in self._bundles.list_bundle_metadata():
            if not meta.valid:
                continue
            bundle = self._bundles.get_bundle_by_patient_id(meta.patient_id)
            if bundle is None:
                continue

            resource_docs = build_resource_documents(
                meta.patient_id, bundle.bundle_hash, bundle.bundle_json
            )
            summary_rows = self._summaries.list_for_bundle(meta.patient_id, bundle.bundle_hash)
            summary_docs = build_summary_documents(summary_rows)

            counts = self._index.reconcile_patient(meta.patient_id, resource_docs + summary_docs)

            report.patients += 1
            report.resource_documents += len(resource_docs)
            report.summary_documents += len(summary_docs)
            report.inserted += counts.inserted
            report.updated += counts.updated
            report.unchanged += counts.unchanged
            report.removed += counts.removed
        return report
