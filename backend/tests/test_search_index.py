"""Tests for idempotent reconcile and stale-entry replacement."""

from collections.abc import Callable

from app.search.documents import IndexDocument
from app.search.index_store import ChromaIndex

IndexFactory = Callable[..., ChromaIndex]


def _resource_doc(doc_id: str, patient_id: str, text: str) -> IndexDocument:
    return IndexDocument(
        doc_id=doc_id,
        text=text,
        metadata={
            "document_kind": "resource",
            "patient_id": patient_id,
            "resource_id": doc_id.split(":", 1)[1],
            "resource_type": "DocumentReference",
            "title": text,
            "bundle_hash": "hash-1",
        },
    )


def test_first_reconcile_inserts(embedder: object, make_index: IndexFactory) -> None:
    index = make_index(embedder)
    docs = [
        _resource_doc("resource:a", "PAT-1", "chest x-ray"),
        _resource_doc("resource:b", "PAT-1", "lipid panel"),
    ]
    counts = index.reconcile_patient("PAT-1", docs)
    assert counts.inserted == 2
    assert counts.updated == 0
    assert counts.unchanged == 0
    assert counts.removed == 0
    assert index.count() == 2


def test_reindexing_unchanged_is_idempotent(embedder: object, make_index: IndexFactory) -> None:
    index = make_index(embedder)
    docs = [_resource_doc("resource:a", "PAT-1", "chest x-ray")]
    index.reconcile_patient("PAT-1", docs)
    counts = index.reconcile_patient("PAT-1", docs)
    assert counts == counts.__class__(unchanged=1)
    assert index.count() == 1


def test_changed_document_is_updated(embedder: object, make_index: IndexFactory) -> None:
    index = make_index(embedder)
    index.reconcile_patient("PAT-1", [_resource_doc("resource:a", "PAT-1", "old text")])
    counts = index.reconcile_patient("PAT-1", [_resource_doc("resource:a", "PAT-1", "new text")])
    assert counts.updated == 1
    assert counts.inserted == 0
    assert index.count() == 1


def test_stale_patient_entries_removed(embedder: object, make_index: IndexFactory) -> None:
    index = make_index(embedder)
    index.reconcile_patient(
        "PAT-1",
        [
            _resource_doc("resource:a", "PAT-1", "note a"),
            _resource_doc("resource:b", "PAT-1", "note b"),
        ],
    )
    # New Bundle for the same patient drops resource b and adds c.
    counts = index.reconcile_patient(
        "PAT-1",
        [
            _resource_doc("resource:a", "PAT-1", "note a"),
            _resource_doc("resource:c", "PAT-1", "note c"),
        ],
    )
    assert counts.removed == 1
    assert counts.inserted == 1
    assert counts.unchanged == 1
    assert index.count() == 2


def test_reconcile_does_not_touch_other_patients(
    embedder: object, make_index: IndexFactory
) -> None:
    index = make_index(embedder)
    index.reconcile_patient("PAT-1", [_resource_doc("resource:a", "PAT-1", "note a")])
    index.reconcile_patient("PAT-2", [_resource_doc("resource:b", "PAT-2", "note b")])
    # Re-reconciling PAT-1 with an empty set removes only PAT-1's entries.
    counts = index.reconcile_patient("PAT-1", [])
    assert counts.removed == 1
    assert index.count() == 1
