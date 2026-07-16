"""Deterministic cleaning and normalization rules.

Every function here is pure and deterministic: the same input always produces
the same output. Rules never invent demographic or medical values and never
alter clinical meaning — they only reshape formatting into one canonical form
or reject values that cannot be interpreted safely.
"""

import re
from datetime import date, datetime

from app.domain.patient import Gender
from app.domain.record import RecordType
from app.ingestion.errors import InvalidDateError, InvalidIdentifierError

#: Raw values treated as "not provided" in any field.
NULL_MARKERS = frozenset({"", "n/a", "na", "none", "null", "-"})

#: Dates outside this range are rejected as implausible for EHR content.
MIN_YEAR = 1900
MAX_YEAR = 2100

_DATE_FORMATS = (
    "%Y-%m-%d",  # ISO date
    "%m/%d/%Y",  # US slash convention (documented; not guessed per value)
    "%d-%m-%Y",  # day-first dash convention (documented; not guessed per value)
)

_ISO_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")

_MRN_SEPARATORS_RE = re.compile(r"[\s\-_./]")
_MRN_ALLOWED_RE = re.compile(r"^[A-Z0-9]+$")

_GENDER_ALIASES: dict[str, Gender] = {
    "m": Gender.MALE,
    "male": Gender.MALE,
    "f": Gender.FEMALE,
    "female": Gender.FEMALE,
    "o": Gender.OTHER,
    "other": Gender.OTHER,
    "x": Gender.OTHER,
    "nb": Gender.OTHER,
    "nonbinary": Gender.OTHER,
    "non-binary": Gender.OTHER,
    "u": Gender.UNKNOWN,
    "unk": Gender.UNKNOWN,
    "unknown": Gender.UNKNOWN,
}

_RECORD_TYPE_ALIASES: dict[str, RecordType] = {
    "document": RecordType.DOCUMENT,
    "documentreference": RecordType.DOCUMENT,
    "doc": RecordType.DOCUMENT,
    "note": RecordType.DOCUMENT,
    "clinical_note": RecordType.DOCUMENT,
    "progress_note": RecordType.DOCUMENT,
    "consult_note": RecordType.DOCUMENT,
    "consultation": RecordType.DOCUMENT,
    "diagnostic": RecordType.DIAGNOSTIC_REPORT,
    "diagnostic_report": RecordType.DIAGNOSTIC_REPORT,
    "diagnosticreport": RecordType.DIAGNOSTIC_REPORT,
    "lab": RecordType.DIAGNOSTIC_REPORT,
    "lab_report": RecordType.DIAGNOSTIC_REPORT,
    "laboratory": RecordType.DIAGNOSTIC_REPORT,
    "imaging": RecordType.DIAGNOSTIC_REPORT,
    "radiology": RecordType.DIAGNOSTIC_REPORT,
    "pathology": RecordType.DIAGNOSTIC_REPORT,
}


def clean_value(value: str | None) -> str | None:
    """Trim a raw value and map common null markers to ``None``."""
    if value is None:
        return None
    stripped = value.strip()
    if stripped.lower() in NULL_MARKERS:
        return None
    return stripped


def collapse_whitespace(value: str) -> str:
    """Collapse all whitespace runs to single spaces and trim the ends."""
    return " ".join(value.split())


def normalize_multiline_text(value: str) -> str:
    """Normalize clinical text while preserving meaningful line breaks.

    Line endings become ``\\n``, trailing whitespace is stripped per line,
    and leading/trailing blank lines are removed. Internal spacing and line
    structure are otherwise left untouched.
    """
    unified = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in unified.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def split_full_name(value: str) -> tuple[str | None, str | None]:
    """Split a full name into ``(given, family)``.

    ``"Family, Given"`` splits on the comma; otherwise the final
    whitespace-separated token is treated as the family name. A single token
    is treated as a family name.
    """
    if "," in value:
        family, _, given = value.partition(",")
        return collapse_whitespace(given) or None, collapse_whitespace(family) or None
    parts = value.split()
    if not parts:
        return None, None
    if len(parts) == 1:
        return None, parts[0]
    return " ".join(parts[:-1]), parts[-1]


def parse_flexible_date(value: str, field: str) -> date | datetime:
    """Parse a date or ISO 8601 date-time string deterministically.

    Supported formats: ``YYYY-MM-DD``, ``MM/DD/YYYY`` (slash values follow
    the US convention), ``DD-MM-YYYY`` (dash values with a trailing year are
    day-first), and ISO 8601 date-times. Anything else — including two-digit
    years — is rejected rather than guessed.
    """
    candidate = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue
        _check_year(parsed.year, field, value)
        return parsed
    if _ISO_DATETIME_RE.match(candidate):
        try:
            parsed_dt = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError as exc:
            raise InvalidDateError(field, value, f"invalid ISO 8601 date-time: {exc}") from exc
        _check_year(parsed_dt.year, field, value)
        return parsed_dt
    raise InvalidDateError(field, value, "unrecognized or ambiguous date format")


def _check_year(year: int, field: str, value: str) -> None:
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise InvalidDateError(
            field, value, f"year {year} outside supported range {MIN_YEAR}-{MAX_YEAR}"
        )


def normalize_gender(value: str) -> Gender | None:
    """Map a source gender variant to the canonical enum.

    Returns ``None`` for unrecognized values so the caller can flag them;
    gender is never inferred from other information.
    """
    return _GENDER_ALIASES.get(value.strip().lower())


def normalize_mrn(value: str) -> str:
    """Normalize an MRN to the canonical ``MRN-`` format.

    Steps: trim, uppercase, remove spaces and common separators, drop an
    existing ``MRN`` prefix, zero-pad purely numeric identifiers to six
    digits, preserve alphanumeric identifiers, and add the ``MRN-`` prefix.
    """
    core = _MRN_SEPARATORS_RE.sub("", value.strip().upper())
    core = core.removeprefix("MRN")
    if not core:
        raise InvalidIdentifierError("mrn", value, "MRN is empty after normalization")
    if not _MRN_ALLOWED_RE.match(core):
        raise InvalidIdentifierError("mrn", value, "MRN contains unsupported characters")
    if core.isdigit():
        core = (core.lstrip("0") or "0").zfill(6)
    return f"MRN-{core}"


def normalize_record_type(value: str) -> RecordType | None:
    """Map a source record-type variant to the canonical enum.

    Returns ``None`` for unrecognized values so the caller can reject the
    record rather than misclassify it.
    """
    key = re.sub(r"[\s\-]+", "_", value.strip().lower())
    return _RECORD_TYPE_ALIASES.get(key)
