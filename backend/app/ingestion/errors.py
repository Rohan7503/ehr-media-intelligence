"""Application exceptions raised by the ingestion pipeline."""


class IngestionError(Exception):
    """Base class for all ingestion errors."""


class UnsupportedFormatError(IngestionError):
    """No input file has a supported format."""


class MalformedFileError(IngestionError):
    """A source file could not be parsed at all (file-level failure)."""

    def __init__(self, source_file: str, detail: str) -> None:
        super().__init__(f"malformed source file '{source_file}': {detail}")
        self.source_file = source_file
        self.detail = detail


class RecordValidationError(IngestionError):
    """A single record field failed validation (record-level failure)."""

    def __init__(self, field: str, value: str | None, reason: str) -> None:
        super().__init__(f"invalid value for '{field}': {reason}")
        self.field = field
        self.value = value
        self.reason = reason


class InvalidDateError(RecordValidationError):
    """A date value could not be parsed deterministically."""


class InvalidIdentifierError(RecordValidationError):
    """An identifier (such as an MRN) is empty or unusable after cleanup."""
