"""Audit trail entries recorded during ingestion and normalization.

Audit entries are intentionally free of timestamps so that canonical output
stays byte-identical across repeated runs over the same input.
"""

from pydantic import BaseModel, ConfigDict


class AuditEntry(BaseModel):
    """A single normalization or validation decision applied to a field."""

    model_config = ConfigDict(frozen=True)

    field: str
    rule: str
    original: str | None = None
    normalized: str | None = None
    reason: str
