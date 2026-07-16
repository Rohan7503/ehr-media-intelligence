"""Shared fixtures and canonical-model factories for the test suite."""

import hashlib
import math
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.domain.patient import Gender, Patient
from app.domain.record import ClinicalRecord, RecordType, SourceFormat
from app.persistence.database import create_db_engine, init_db
from app.search.index_store import ChromaIndex

PatientFactory = Callable[..., Patient]
RecordFactory = Callable[..., ClinicalRecord]
IndexFactory = Callable[..., ChromaIndex]


def _make_patient(**overrides: object) -> Patient:
    defaults: dict[str, object] = {
        "patient_id": "PAT-000123",
        "source_patient_ids": ["SRC-1"],
        "mrn": "MRN-000123",
        "given_name": "Avery",
        "family_name": "Kestrel",
        "birth_date": date(1984, 3, 2),
        "gender": Gender.FEMALE,
    }
    defaults.update(overrides)
    return Patient(**defaults)


def _make_record(**overrides: object) -> ClinicalRecord:
    defaults: dict[str, object] = {
        "record_id": "R-1",
        "source_record_id": "R-1",
        "source_file": "a.json",
        "source_format": SourceFormat.JSON,
        "patient_id": "PAT-000123",
        "encounter_id": None,
        "record_type": RecordType.DOCUMENT,
        "title": "Visit note",
        "text": "Body of the note.",
        "record_date": date(2024, 5, 1),
        "diagnostic_code": None,
        "fingerprint": "f" * 64,
    }
    defaults.update(overrides)
    return ClinicalRecord(**defaults)


@pytest.fixture
def make_patient() -> PatientFactory:
    return _make_patient


@pytest.fixture
def make_record() -> RecordFactory:
    return _make_record


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    """A Session bound to a temporary file-backed SQLite database."""
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    with Session(engine) as active:
        yield active
    engine.dispose()


_EMBED_DIM = 64


class DeterministicEmbedder:
    """A deterministic, network-free bag-of-tokens embedder for tests.

    Shared tokens produce higher cosine similarity, so semantic ranking is
    predictable without downloading a model. Vectors are L2-normalized.
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * _EMBED_DIM
            for token in text.lower().split():
                cleaned = "".join(ch for ch in token if ch.isalnum())
                if not cleaned:
                    continue
                digest = hashlib.sha1(cleaned.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "big") % _EMBED_DIM
                vector[index] += 1.0
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors


@pytest.fixture
def embedder() -> DeterministicEmbedder:
    return DeterministicEmbedder()


@pytest.fixture
def make_index(tmp_path: Path) -> IndexFactory:
    """Factory building a ChromaIndex over a temporary persistent collection."""

    def _make(embedder: object, name: str = "test") -> ChromaIndex:
        import chromadb

        client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
        collection = client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})
        return ChromaIndex(collection, embedder)  # type: ignore[arg-type]

    return _make
