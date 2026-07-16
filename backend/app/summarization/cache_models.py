"""SQLAlchemy model for the clinical-summary cache.

Kept separate from the Pydantic/domain models. One row is the current cached
summary for a distinct ``(patient_id, record_hash, model_name, prompt_version)``
key; a surrogate primary key plus a unique constraint on that tuple lets
historical entries (older Bundle hashes, models, or prompt versions) coexist
without being overwritten.

Importing this module registers the table on the shared declarative ``Base``,
so ``init_db`` creates it alongside the FHIR tables.
"""

from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.database import Base


class SummaryCacheRow(Base):
    """A cached clinical summary keyed on Bundle hash, model, and prompt."""

    __tablename__ = "summary_cache"
    __table_args__ = (
        UniqueConstraint(
            "patient_id",
            "record_hash",
            "model_name",
            "prompt_version",
            name="uq_summary_cache_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    record_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    rendered_text: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
