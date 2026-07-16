"""SQLAlchemy 2 typed declarative models.

These are storage models only, kept separate from the Pydantic/domain and
FHIR models. Bundle and report bodies are stored as canonical JSON strings,
not Python reprs. ``patient_id`` is the primary key of each table, so there is
exactly one current Bundle and one current validation report per patient.
"""

from sqlalchemy import Boolean, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.database import Base


class FhirBundleRow(Base):
    """The current FHIR Bundle stored for one canonical patient."""

    __tablename__ = "fhir_bundle"
    __table_args__ = (UniqueConstraint("bundle_id", name="uq_fhir_bundle_bundle_id"),)

    patient_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    bundle_id: Mapped[str] = mapped_column(String(64), nullable=False)
    bundle_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    bundle_json: Mapped[str] = mapped_column(Text, nullable=False)
    fhir_version: Mapped[str] = mapped_column(String(16), nullable=False)
    model_namespace: Mapped[str] = mapped_column(String(16), nullable=False)
    valid: Mapped[bool] = mapped_column(Boolean, nullable=False)


class ValidationReportRow(Base):
    """The current validation report stored for one canonical patient."""

    __tablename__ = "validation_report"

    patient_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    bundle_id: Mapped[str] = mapped_column(String(64), nullable=False)
    report_json: Mapped[str] = mapped_column(Text, nullable=False)
