"""Database engine and schema initialization.

The engine is created explicitly from a configured ``DATABASE_URL`` and tables
are created by calling :func:`init_db`. Nothing here runs at import time, so
importing the module never touches the filesystem or a database.
"""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all persistence models."""


class StorageError(Exception):
    """Raised when a storage operation fails and is rolled back."""


def create_db_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine for the given database URL."""
    return create_engine(database_url)


def init_db(engine: Engine) -> None:
    """Create all tables. Safe to call repeatedly (create-if-not-exists)."""
    # Import models so they are registered on Base.metadata before create_all.
    from app.persistence import models  # noqa: F401

    Base.metadata.create_all(engine)
