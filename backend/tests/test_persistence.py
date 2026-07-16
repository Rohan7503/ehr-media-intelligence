"""Tests for SQLite persistence and idempotent upsert behavior."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.fhir.report import StorageOutcome
from app.persistence.database import StorageError, create_db_engine, init_db
from app.persistence.repositories.bundles import BundleRepository


def _upsert(
    repo: BundleRepository,
    *,
    patient_id: str = "PAT-000123",
    bundle_id: str = "bundle-1",
    bundle_hash: str = "hash-1",
    bundle_json: str = '{"resourceType":"Bundle"}',
    valid: bool = True,
    report_json: str = '{"valid":true}',
) -> StorageOutcome:
    return repo.upsert_bundle_and_report(
        patient_id=patient_id,
        bundle_id=bundle_id,
        bundle_hash=bundle_hash,
        bundle_json=bundle_json,
        fhir_version="4.0.1",
        model_namespace="R4B",
        valid=valid,
        report_json=report_json,
    )


def test_init_db_creates_tables(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'schema.db'}")
    init_db(engine)
    tables = set(inspect(engine).get_table_names())
    assert {"fhir_bundle", "validation_report"} <= tables
    engine.dispose()


def test_bundle_insertion(session: Session) -> None:
    repo = BundleRepository(session)
    outcome = _upsert(repo)
    assert outcome == "inserted"
    assert repo.count_bundles() == 1
    assert repo.count_reports() == 1


def test_idempotent_upsert_is_unchanged(session: Session) -> None:
    repo = BundleRepository(session)
    _upsert(repo)
    outcome = _upsert(repo)
    assert outcome == "unchanged"
    assert repo.count_bundles() == 1


def test_changed_hash_replaces_bundle(session: Session) -> None:
    repo = BundleRepository(session)
    _upsert(repo)
    outcome = _upsert(
        repo,
        bundle_hash="hash-2",
        bundle_json='{"resourceType":"Bundle","id":"changed"}',
        valid=False,
    )
    assert outcome == "updated"
    assert repo.count_bundles() == 1
    row = repo.get_bundle_by_patient_id("PAT-000123")
    assert row is not None
    assert row.bundle_hash == "hash-2"
    assert row.valid is False


def test_get_bundle_by_patient_id(session: Session) -> None:
    repo = BundleRepository(session)
    assert repo.get_bundle_by_patient_id("PAT-000123") is None
    _upsert(repo)
    row = repo.get_bundle_by_patient_id("PAT-000123")
    assert row is not None
    assert row.bundle_id == "bundle-1"


def test_list_bundle_metadata(session: Session) -> None:
    repo = BundleRepository(session)
    _upsert(repo)
    _upsert(repo, patient_id="PAT-000456", bundle_id="bundle-2")
    metadata = repo.list_bundle_metadata()
    assert [m.patient_id for m in metadata] == ["PAT-000123", "PAT-000456"]


def test_transaction_rollback_on_failure(session: Session) -> None:
    repo = BundleRepository(session)
    _upsert(repo)
    # A second patient reusing the same bundle_id violates the unique
    # constraint; the failed write must roll back and leave one row.
    with pytest.raises(StorageError):
        _upsert(repo, patient_id="PAT-000999")
    assert repo.count_bundles() == 1
    assert repo.get_bundle_by_patient_id("PAT-000999") is None


def test_create_db_engine_uses_url(tmp_path: Path) -> None:
    db_path = tmp_path / "explicit.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    init_db(engine)
    with Session(engine) as active:
        _upsert(BundleRepository(active))
    engine.dispose()
    assert db_path.exists()
