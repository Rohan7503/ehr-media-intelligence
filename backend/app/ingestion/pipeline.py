"""Ingestion pipeline: discover files, normalize records, resolve identity.

The pipeline is deterministic: input files are processed in sorted order and
no timestamps or randomness enter the output, so identical inputs always
produce byte-identical canonical output.

A record is rejected (never silently dropped) when it has loader-detected
structural issues, lacks an MRN (insufficient patient identity), has no
meaningful clinical text, or carries an unrecognized record type. Invalid
optional values (dates, gender) are flagged in the audit trail and set to
``None`` instead of causing rejection.
"""

from collections.abc import Callable, Sequence
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from app.domain.audit import AuditEntry
from app.domain.patient import Gender, Patient
from app.domain.record import ClinicalRecord, RecordType, SourceFormat
from app.ingestion.deduplication import DuplicateIndex, DuplicateRecord, record_fingerprint
from app.ingestion.errors import (
    IngestionError,
    InvalidDateError,
    InvalidIdentifierError,
    MalformedFileError,
    UnsupportedFormatError,
)
from app.ingestion.identity import (
    IdentityConflict,
    IdentityConflictError,
    IdentityRegistry,
    PatientCandidate,
)
from app.ingestion.loaders.base import RawRecord
from app.ingestion.loaders.csv_loader import load_csv_records
from app.ingestion.loaders.json_loader import load_json_records
from app.ingestion.loaders.text_loader import load_text_records
from app.ingestion.normalizers import (
    clean_value,
    collapse_whitespace,
    normalize_gender,
    normalize_mrn,
    normalize_multiline_text,
    normalize_record_type,
    parse_flexible_date,
    split_full_name,
)

LoaderFn = Callable[[Path, str], list[RawRecord]]

_LOADERS: dict[str, tuple[SourceFormat, LoaderFn]] = {
    ".json": (SourceFormat.JSON, load_json_records),
    ".csv": (SourceFormat.CSV, load_csv_records),
    ".txt": (SourceFormat.TEXT, load_text_records),
}

_DERIVED_TITLE_MAX = 80


class SkippedFile(BaseModel):
    """A discovered file that was ignored because its format is unsupported."""

    source_file: str
    reason: str


class FileError(BaseModel):
    """A supported file that failed to parse entirely."""

    source_file: str
    error: str


class RejectedRecord(BaseModel):
    """A structured report of one record that could not be accepted."""

    source_file: str
    index: int
    source_record_id: str | None = None
    reasons: list[str]
    raw_fields: dict[str, str] = Field(default_factory=dict)


class PipelineCounts(BaseModel):
    """Aggregate counts for one pipeline run."""

    files_processed: int
    files_skipped: int
    files_failed: int
    raw_records: int
    accepted_patients: int
    accepted_records: int
    duplicate_records: int
    rejected_records: int
    identity_conflicts: int


class PipelineResult(BaseModel):
    """Everything produced by one ingestion run."""

    patients: list[Patient]
    records: list[ClinicalRecord]
    duplicates: list[DuplicateRecord]
    rejected: list[RejectedRecord]
    conflicts: list[IdentityConflict]
    skipped_files: list[SkippedFile]
    file_errors: list[FileError]
    counts: PipelineCounts


def run_pipeline(paths: Sequence[Path]) -> PipelineResult:
    """Ingest all supported files under the given paths.

    Raises :class:`IngestionError` for unrecoverable input problems (a path
    that does not exist, or no supported files at all). Individual malformed
    files and invalid records are reported in the result, never fatal.
    """
    files, skipped = discover_files(paths)
    if not files:
        raise UnsupportedFormatError(
            "no supported input files found (supported extensions: .json, .csv, .txt)"
        )

    registry = IdentityRegistry()
    duplicate_index = DuplicateIndex()
    accepted: list[ClinicalRecord] = []
    duplicates: list[DuplicateRecord] = []
    rejected: list[RejectedRecord] = []
    conflicts: list[IdentityConflict] = []
    file_errors: list[FileError] = []
    used_record_ids: set[str] = set()
    raw_count = 0
    files_processed = 0

    for path, display, _fmt, loader in files:
        try:
            raw_records = loader(path, display)
        except MalformedFileError as exc:
            file_errors.append(FileError(source_file=display, error=str(exc)))
            continue
        files_processed += 1
        for raw in raw_records:
            raw_count += 1
            _process_record(
                raw,
                registry=registry,
                duplicate_index=duplicate_index,
                accepted=accepted,
                duplicates=duplicates,
                rejected=rejected,
                conflicts=conflicts,
                used_record_ids=used_record_ids,
            )

    patients = registry.patients()
    accepted.sort(key=lambda record: record.record_id)
    counts = PipelineCounts(
        files_processed=files_processed,
        files_skipped=len(skipped),
        files_failed=len(file_errors),
        raw_records=raw_count,
        accepted_patients=len(patients),
        accepted_records=len(accepted),
        duplicate_records=len(duplicates),
        rejected_records=len(rejected),
        identity_conflicts=len(conflicts),
    )
    return PipelineResult(
        patients=patients,
        records=accepted,
        duplicates=duplicates,
        rejected=rejected,
        conflicts=conflicts,
        skipped_files=skipped,
        file_errors=file_errors,
        counts=counts,
    )


def discover_files(
    paths: Sequence[Path],
) -> tuple[list[tuple[Path, str, SourceFormat, LoaderFn]], list[SkippedFile]]:
    """Find supported files under the given files or directories.

    Directory contents are walked recursively and sorted by relative path so
    processing order is deterministic.
    """
    files: list[tuple[Path, str, SourceFormat, LoaderFn]] = []
    skipped: list[SkippedFile] = []

    def add(candidate: Path, display: str) -> None:
        entry = _LOADERS.get(candidate.suffix.lower())
        if entry is None:
            skipped.append(
                SkippedFile(
                    source_file=display,
                    reason=f"unsupported file type '{candidate.suffix or '(none)'}'",
                )
            )
            return
        files.append((candidate, display, entry[0], entry[1]))

    for path in paths:
        if not path.exists():
            raise IngestionError(f"input path does not exist: {path}")
        if path.is_file():
            add(path, path.name)
            continue
        children = sorted(
            (child for child in path.rglob("*") if child.is_file()),
            key=lambda child: child.relative_to(path).as_posix(),
        )
        for child in children:
            add(child, child.relative_to(path).as_posix())
    return files, skipped


def _process_record(
    raw: RawRecord,
    *,
    registry: IdentityRegistry,
    duplicate_index: DuplicateIndex,
    accepted: list[ClinicalRecord],
    duplicates: list[DuplicateRecord],
    rejected: list[RejectedRecord],
    conflicts: list[IdentityConflict],
    used_record_ids: set[str],
) -> None:
    audits: list[AuditEntry] = []
    cleaned: dict[str, str] = {}
    for key, value in raw.fields.items():
        cleaned_value = clean_value(value)
        if cleaned_value is not None:
            cleaned[key] = cleaned_value

    reasons = list(raw.issues)

    text = None
    raw_text = cleaned.get("text")
    if raw_text is not None:
        text = normalize_multiline_text(raw_text)
        if text != raw_text:
            audits.append(
                AuditEntry(
                    field="text",
                    rule="text.whitespace_normalized",
                    reason="line endings and trailing whitespace normalized",
                )
            )
    if not text:
        reasons.append("no meaningful clinical text")

    mrn = None
    raw_mrn = cleaned.get("mrn")
    if raw_mrn is None:
        reasons.append("missing MRN: insufficient patient identity to associate safely")
    else:
        try:
            mrn = normalize_mrn(raw_mrn)
        except InvalidIdentifierError as exc:
            reasons.append(f"invalid MRN '{raw_mrn}': {exc.reason}")
        else:
            if mrn != raw_mrn:
                audits.append(
                    AuditEntry(
                        field="mrn",
                        rule="mrn.normalized",
                        original=raw_mrn,
                        normalized=mrn,
                        reason="MRN converted to canonical format",
                    )
                )

    record_type: RecordType | None = None
    raw_type = cleaned.get("record_type")
    if raw_type is None:
        record_type = RecordType.DOCUMENT
        audits.append(
            AuditEntry(
                field="record_type",
                rule="record_type.defaulted",
                normalized=record_type.value,
                reason="record type missing; defaulted to document",
            )
        )
    else:
        record_type = normalize_record_type(raw_type)
        if record_type is None:
            reasons.append(f"unknown record type '{raw_type}'")
        elif record_type.value != raw_type:
            audits.append(
                AuditEntry(
                    field="record_type",
                    rule="record_type.normalized",
                    original=raw_type,
                    normalized=record_type.value,
                    reason="record type mapped to canonical value",
                )
            )

    if reasons:
        rejected.append(
            RejectedRecord(
                source_file=raw.source_file,
                index=raw.index,
                source_record_id=cleaned.get("record_id"),
                reasons=reasons,
                raw_fields=raw.fields,
            )
        )
        return
    assert text is not None and mrn is not None and record_type is not None

    given_name, family_name = _normalize_names(cleaned, audits)
    birth_date = _normalize_date_field(cleaned.get("dob"), "birth_date", audits)
    if isinstance(birth_date, datetime):
        birth_date = birth_date.date()
    gender = _normalize_gender_field(cleaned.get("gender"), audits)
    record_date = _normalize_date_field(cleaned.get("record_date"), "record_date", audits)

    raw_title = cleaned.get("title")
    if raw_title is not None:
        title = collapse_whitespace(raw_title)
        if title != raw_title:
            audits.append(
                AuditEntry(
                    field="title",
                    rule="title.whitespace_collapsed",
                    original=raw_title,
                    normalized=title,
                    reason="surrounding and repeated whitespace collapsed",
                )
            )
    else:
        first_line = next(line for line in text.split("\n") if line.strip())
        title = collapse_whitespace(first_line)[:_DERIVED_TITLE_MAX]
        audits.append(
            AuditEntry(
                field="title",
                rule="title.derived",
                normalized=title,
                reason="title missing; derived from the first line of the record text",
            )
        )

    encounter_id = cleaned.get("encounter_id")
    diagnostic_code = cleaned.get("diagnostic_code")
    source_patient_id = cleaned.get("patient_id")

    fingerprint = record_fingerprint(
        mrn=mrn,
        record_type=record_type,
        record_date=record_date,
        title=title,
        text=text,
        encounter_id=encounter_id,
        diagnostic_code=diagnostic_code,
    )

    existing = duplicate_index.lookup(fingerprint)
    if existing is not None:
        canonical_id, canonical_file = existing
        duplicates.append(
            DuplicateRecord(
                fingerprint=fingerprint,
                source_file=raw.source_file,
                source_record_id=cleaned.get("record_id"),
                duplicate_of_record_id=canonical_id,
                duplicate_of_source_file=canonical_file,
                reason=("exact content fingerprint match; first occurrence kept as canonical"),
            )
        )
        return

    candidate = PatientCandidate(
        mrn=mrn,
        source_patient_id=source_patient_id,
        given_name=given_name,
        family_name=family_name,
        birth_date=birth_date,
        gender=gender,
        audit=[entry for entry in audits if entry.field in _PATIENT_FIELDS],
    )
    try:
        patient = registry.resolve(
            candidate,
            source_file=raw.source_file,
            source_record_id=cleaned.get("record_id"),
        )
    except IdentityConflictError as exc:
        conflicts.append(exc.conflict)
        return

    record_id = _canonical_record_id(cleaned.get("record_id"), fingerprint, audits)
    if record_id in used_record_ids:
        suffixed = f"{record_id}-{fingerprint[:6].upper()}"
        audits.append(
            AuditEntry(
                field="record_id",
                rule="record_id.collision_suffix",
                original=record_id,
                normalized=suffixed,
                reason="canonical record ID already in use; fingerprint suffix added",
            )
        )
        record_id = suffixed
    used_record_ids.add(record_id)

    accepted.append(
        ClinicalRecord(
            record_id=record_id,
            source_record_id=cleaned.get("record_id"),
            source_file=raw.source_file,
            source_format=raw.source_format,
            patient_id=patient.patient_id,
            encounter_id=encounter_id,
            record_type=record_type,
            title=title,
            text=text,
            record_date=record_date,
            diagnostic_code=diagnostic_code,
            fingerprint=fingerprint,
            audit=audits,
        )
    )
    duplicate_index.register(fingerprint, record_id, raw.source_file)


_PATIENT_FIELDS = frozenset(
    {"mrn", "gender", "birth_date", "given_name", "family_name", "full_name"}
)


def _normalize_names(
    cleaned: dict[str, str], audits: list[AuditEntry]
) -> tuple[str | None, str | None]:
    given = cleaned.get("given_name")
    family = cleaned.get("family_name")
    full = cleaned.get("full_name")
    if full is not None and given is None and family is None:
        given, family = split_full_name(full)
        audits.append(
            AuditEntry(
                field="full_name",
                rule="name.split",
                original=full,
                normalized=f"given={given or ''} family={family or ''}",
                reason="full name split into given and family components",
            )
        )
    result: list[str | None] = []
    for field_name, value in (("given_name", given), ("family_name", family)):
        if value is None:
            result.append(None)
            continue
        collapsed = collapse_whitespace(value)
        if collapsed != value:
            audits.append(
                AuditEntry(
                    field=field_name,
                    rule="name.whitespace_collapsed",
                    original=value,
                    normalized=collapsed,
                    reason="surrounding and repeated whitespace collapsed",
                )
            )
        result.append(collapsed or None)
    return result[0], result[1]


def _normalize_date_field(
    raw_value: str | None,
    field_name: str,
    audits: list[AuditEntry],
) -> date | datetime | None:
    if raw_value is None:
        audits.append(
            AuditEntry(
                field=field_name,
                rule="field.missing",
                reason=f"{field_name} not provided",
            )
        )
        return None
    try:
        parsed = parse_flexible_date(raw_value, field_name)
    except InvalidDateError as exc:
        audits.append(
            AuditEntry(
                field=field_name,
                rule="date.invalid",
                original=raw_value,
                reason=f"flagged: {exc.reason}; value discarded rather than guessed",
            )
        )
        return None
    normalized_repr = parsed.isoformat()
    if normalized_repr != raw_value:
        audits.append(
            AuditEntry(
                field=field_name,
                rule="date.parsed",
                original=raw_value,
                normalized=normalized_repr,
                reason="date converted to canonical ISO format",
            )
        )
    return parsed


def _normalize_gender_field(raw_value: str | None, audits: list[AuditEntry]) -> Gender:
    if raw_value is None:
        audits.append(
            AuditEntry(
                field="gender",
                rule="field.missing",
                normalized=Gender.UNKNOWN.value,
                reason="gender not provided; recorded as unknown",
            )
        )
        return Gender.UNKNOWN
    gender = normalize_gender(raw_value)
    if gender is None:
        audits.append(
            AuditEntry(
                field="gender",
                rule="gender.unrecognized",
                original=raw_value,
                normalized=Gender.UNKNOWN.value,
                reason="unrecognized gender value; recorded as unknown, never inferred",
            )
        )
        return Gender.UNKNOWN
    if gender.value != raw_value:
        audits.append(
            AuditEntry(
                field="gender",
                rule="gender.normalized",
                original=raw_value,
                normalized=gender.value,
                reason="gender variant mapped to canonical value",
            )
        )
    return gender


def _canonical_record_id(raw_id: str | None, fingerprint: str, audits: list[AuditEntry]) -> str:
    if raw_id is None:
        derived = f"REC-{fingerprint[:12].upper()}"
        audits.append(
            AuditEntry(
                field="record_id",
                rule="record_id.derived",
                normalized=derived,
                reason="source record ID missing; deterministic ID derived from fingerprint",
            )
        )
        return derived
    normalized = collapse_whitespace(raw_id).upper()
    if normalized != raw_id:
        audits.append(
            AuditEntry(
                field="record_id",
                rule="record_id.normalized",
                original=raw_id,
                normalized=normalized,
                reason="record ID trimmed and uppercased",
            )
        )
    return normalized
