"""Unit tests for the cleaning and normalization rules."""

from datetime import date, datetime

import pytest

from app.domain.patient import Gender
from app.domain.record import RecordType
from app.ingestion.errors import InvalidDateError, InvalidIdentifierError
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


class TestParseFlexibleDate:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2024-03-05", date(2024, 3, 5)),
            ("03/05/2024", date(2024, 3, 5)),  # US MM/DD/YYYY
            ("05-03-2024", date(2024, 3, 5)),  # DD-MM-YYYY
            ("25/12/2020", None),  # invalid as MM/DD -> rejected, never guessed
        ],
    )
    def test_supported_date_formats(self, value: str, expected: date | None) -> None:
        if expected is None:
            with pytest.raises(InvalidDateError):
                parse_flexible_date(value, "record_date")
        else:
            assert parse_flexible_date(value, "record_date") == expected

    def test_iso_datetime(self) -> None:
        parsed = parse_flexible_date("2024-03-05T09:30:00", "record_date")
        assert parsed == datetime(2024, 3, 5, 9, 30)

    def test_iso_datetime_with_zulu_offset(self) -> None:
        parsed = parse_flexible_date("2024-03-05T09:30:00Z", "record_date")
        assert isinstance(parsed, datetime)
        assert parsed.tzinfo is not None

    @pytest.mark.parametrize(
        "value",
        [
            "1/2/03",  # two-digit year: genuinely ambiguous
            "2024-13-01",  # impossible month
            "2/30/2024",  # impossible day
            "not a date",
            "04-13-2024",  # looks day-first but month 13 is impossible
            "1850-01-01",  # outside supported year range
        ],
    )
    def test_invalid_or_ambiguous_dates_rejected(self, value: str) -> None:
        with pytest.raises(InvalidDateError):
            parse_flexible_date(value, "record_date")


class TestNormalizeGender:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("M", Gender.MALE),
            ("Male", Gender.MALE),
            ("male", Gender.MALE),
            ("F", Gender.FEMALE),
            ("Female", Gender.FEMALE),
            ("O", Gender.OTHER),
            ("X", Gender.OTHER),
            ("nonbinary", Gender.OTHER),
            ("Non-Binary", Gender.OTHER),
            ("U", Gender.UNKNOWN),
            ("unknown", Gender.UNKNOWN),
        ],
    )
    def test_variants(self, value: str, expected: Gender) -> None:
        assert normalize_gender(value) is expected

    def test_unrecognized_returns_none(self) -> None:
        assert normalize_gender("banana") is None


class TestNormalizeMrn:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("123", "MRN-000123"),
            ("mrn 00123", "MRN-000123"),
            ("ab-123", "MRN-AB123"),
            ("MRN-000123", "MRN-000123"),
            ("  22 05 ", "MRN-002205"),
            ("mrn_0789", "MRN-000789"),
            ("1234567", "MRN-1234567"),  # longer than six digits: preserved
        ],
    )
    def test_canonical_format(self, value: str, expected: str) -> None:
        assert normalize_mrn(value) == expected

    @pytest.mark.parametrize("value", ["", "   ", "mrn-", "MRN", "??!"])
    def test_unusable_mrns_rejected(self, value: str) -> None:
        with pytest.raises(InvalidIdentifierError):
            normalize_mrn(value)


class TestTextAndNames:
    def test_clean_value_null_markers(self) -> None:
        assert clean_value("  n/a ") is None
        assert clean_value("NULL") is None
        assert clean_value("-") is None
        assert clean_value(" value ") == "value"
        assert clean_value(None) is None

    def test_collapse_whitespace(self) -> None:
        assert collapse_whitespace("  a   b\t c ") == "a b c"

    def test_multiline_text_preserves_line_breaks(self) -> None:
        raw = "line one   \r\nline two\r\n\r\nline four\n"
        assert normalize_multiline_text(raw) == "line one\nline two\n\nline four"

    def test_split_full_name_space_form(self) -> None:
        assert split_full_name("Avery Quinn Kestrel") == ("Avery Quinn", "Kestrel")

    def test_split_full_name_comma_form(self) -> None:
        assert split_full_name("Kestrel, Avery") == ("Avery", "Kestrel")

    def test_split_full_name_single_token(self) -> None:
        assert split_full_name("Kestrel") == (None, "Kestrel")


class TestNormalizeRecordType:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("note", RecordType.DOCUMENT),
            ("Progress Note", RecordType.DOCUMENT),
            ("clinical-note", RecordType.DOCUMENT),
            ("lab", RecordType.DIAGNOSTIC_REPORT),
            ("Lab Report", RecordType.DIAGNOSTIC_REPORT),
            ("imaging", RecordType.DIAGNOSTIC_REPORT),
        ],
    )
    def test_variants(self, value: str, expected: RecordType) -> None:
        assert normalize_record_type(value) is expected

    def test_unrecognized_returns_none(self) -> None:
        assert normalize_record_type("billing-summary") is None
