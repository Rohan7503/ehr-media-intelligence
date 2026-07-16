"""Conservative patient identity resolution.

Policy (documented in ``docs/architecture.md``):

- Identity is keyed **only** on the exact normalized MRN. Names are never
  used to associate records; similar or identical names alone never merge
  patients.
- A source patient ID observed with two different normalized MRNs is a
  conflict; the later record is quarantined.
- A normalized MRN observed with clearly incompatible demographics — a
  different date of birth or a different family name — is a conflict; the
  later record is quarantined.
- Compatible later records may backfill demographics the patient was first
  seen without (``None`` → value only). Every backfill is audited. Differing
  given names and genders are tolerated and never merged over; the first
  observed value is kept, with an audit entry for ignored gender variants.

Processing order is deterministic, so "first" and "later" are stable across
runs.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.domain.audit import AuditEntry
from app.domain.patient import Gender, Patient
from app.ingestion.errors import IngestionError
from app.ingestion.normalizers import collapse_whitespace


class IdentityConflict(BaseModel):
    """A structured report of one quarantined identity conflict."""

    conflict_type: Literal["source_patient_id_mrn_mismatch", "mrn_demographics_mismatch"]
    source_file: str
    source_record_id: str | None = None
    source_patient_id: str | None = None
    mrn: str
    existing_mrn: str | None = None
    reason: str


class IdentityConflictError(IngestionError):
    """Raised when a record's identity contradicts the established registry."""

    def __init__(self, conflict: IdentityConflict) -> None:
        super().__init__(conflict.reason)
        self.conflict = conflict


@dataclass
class PatientCandidate:
    """Normalized patient identity extracted from one raw record."""

    mrn: str
    source_patient_id: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    birth_date: date | None = None
    gender: Gender = Gender.UNKNOWN
    audit: list[AuditEntry] = field(default_factory=list)


class IdentityRegistry:
    """Deterministic MRN-keyed patient registry."""

    def __init__(self) -> None:
        self._by_mrn: dict[str, Patient] = {}
        self._source_to_mrn: dict[str, str] = {}

    def resolve(
        self,
        candidate: PatientCandidate,
        *,
        source_file: str,
        source_record_id: str | None,
    ) -> Patient:
        """Return the canonical patient for a candidate identity.

        Raises :class:`IdentityConflictError` when the candidate contradicts
        an established identity; the registry is left unchanged in that case.
        """
        source_id = candidate.source_patient_id
        if source_id is not None:
            known_mrn = self._source_to_mrn.get(source_id)
            if known_mrn is not None and known_mrn != candidate.mrn:
                raise IdentityConflictError(
                    IdentityConflict(
                        conflict_type="source_patient_id_mrn_mismatch",
                        source_file=source_file,
                        source_record_id=source_record_id,
                        source_patient_id=source_id,
                        mrn=candidate.mrn,
                        existing_mrn=known_mrn,
                        reason=(
                            f"source patient ID '{source_id}' is already associated with "
                            f"{known_mrn} but this record presents {candidate.mrn}"
                        ),
                    )
                )

        existing = self._by_mrn.get(candidate.mrn)
        if existing is None:
            patient = self._create(candidate)
        else:
            self._check_demographics(existing, candidate, source_file, source_record_id)
            self._enrich(existing, candidate, source_record_id)
            patient = existing

        if source_id is not None:
            self._source_to_mrn.setdefault(source_id, candidate.mrn)
        return patient

    def patients(self) -> list[Patient]:
        """All canonical patients, sorted by canonical ID."""
        return sorted(self._by_mrn.values(), key=lambda p: p.patient_id)

    def _create(self, candidate: PatientCandidate) -> Patient:
        patient_id = "PAT-" + candidate.mrn.removeprefix("MRN-")
        audit = list(candidate.audit)
        for name, value in (
            ("birth_date", candidate.birth_date),
            ("given_name", candidate.given_name),
            ("family_name", candidate.family_name),
        ):
            if value is None:
                audit.append(
                    AuditEntry(
                        field=name,
                        rule="field.missing",
                        reason=f"{name} not provided by any source record yet",
                    )
                )
        patient = Patient(
            patient_id=patient_id,
            source_patient_ids=(
                [candidate.source_patient_id] if candidate.source_patient_id else []
            ),
            mrn=candidate.mrn,
            given_name=candidate.given_name,
            family_name=candidate.family_name,
            birth_date=candidate.birth_date,
            gender=candidate.gender,
            audit=audit,
        )
        self._by_mrn[candidate.mrn] = patient
        return patient

    def _check_demographics(
        self,
        existing: Patient,
        candidate: PatientCandidate,
        source_file: str,
        source_record_id: str | None,
    ) -> None:
        if (
            candidate.birth_date is not None
            and existing.birth_date is not None
            and candidate.birth_date != existing.birth_date
        ):
            raise IdentityConflictError(
                IdentityConflict(
                    conflict_type="mrn_demographics_mismatch",
                    source_file=source_file,
                    source_record_id=source_record_id,
                    source_patient_id=candidate.source_patient_id,
                    mrn=candidate.mrn,
                    reason=(
                        f"MRN {candidate.mrn} already has date of birth "
                        f"{existing.birth_date.isoformat()} but this record presents "
                        f"{candidate.birth_date.isoformat()}"
                    ),
                )
            )
        if (
            candidate.family_name is not None
            and existing.family_name is not None
            and _name_key(candidate.family_name) != _name_key(existing.family_name)
        ):
            raise IdentityConflictError(
                IdentityConflict(
                    conflict_type="mrn_demographics_mismatch",
                    source_file=source_file,
                    source_record_id=source_record_id,
                    source_patient_id=candidate.source_patient_id,
                    mrn=candidate.mrn,
                    reason=(
                        f"MRN {candidate.mrn} already has family name "
                        f"'{existing.family_name}' but this record presents "
                        f"'{candidate.family_name}'"
                    ),
                )
            )

    def _enrich(
        self,
        existing: Patient,
        candidate: PatientCandidate,
        source_record_id: str | None,
    ) -> None:
        origin = source_record_id or "a later record"
        if existing.birth_date is None and candidate.birth_date is not None:
            existing.birth_date = candidate.birth_date
            existing.audit.append(
                AuditEntry(
                    field="birth_date",
                    rule="patient.field_backfilled",
                    normalized=candidate.birth_date.isoformat(),
                    reason=f"backfilled from record {origin}",
                )
            )
        for name in ("given_name", "family_name"):
            if getattr(existing, name) is None and getattr(candidate, name) is not None:
                value: str = getattr(candidate, name)
                setattr(existing, name, value)
                existing.audit.append(
                    AuditEntry(
                        field=name,
                        rule="patient.field_backfilled",
                        normalized=value,
                        reason=f"backfilled from record {origin}",
                    )
                )
        if existing.gender is Gender.UNKNOWN and candidate.gender is not Gender.UNKNOWN:
            existing.gender = candidate.gender
            existing.audit.append(
                AuditEntry(
                    field="gender",
                    rule="patient.field_backfilled",
                    normalized=candidate.gender.value,
                    reason=f"backfilled from record {origin}",
                )
            )
        elif candidate.gender is not Gender.UNKNOWN and candidate.gender is not existing.gender:
            existing.audit.append(
                AuditEntry(
                    field="gender",
                    rule="gender.mismatch_ignored",
                    original=candidate.gender.value,
                    normalized=existing.gender.value,
                    reason=(
                        f"record {origin} presents a different gender; first observed "
                        "value retained"
                    ),
                )
            )
        source_id = candidate.source_patient_id
        if source_id is not None and source_id not in existing.source_patient_ids:
            existing.source_patient_ids.append(source_id)
            existing.source_patient_ids.sort()
            existing.audit.append(
                AuditEntry(
                    field="source_patient_ids",
                    rule="patient.source_id_added",
                    normalized=source_id,
                    reason=f"additional source patient ID observed in record {origin}",
                )
            )


def _name_key(value: str) -> str:
    return collapse_whitespace(value).casefold()
