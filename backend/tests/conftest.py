"""Shared fixtures and canonical-model factories for the test suite."""

from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.domain.patient import Gender, Patient
from app.domain.record import ClinicalRecord, RecordType, SourceFormat
from app.persistence.database import create_db_engine, init_db

PatientFactory = Callable[..., Patient]
RecordFactory = Callable[..., ClinicalRecord]


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
