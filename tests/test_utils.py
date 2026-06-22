"""Thorough unit tests for docverify.utils — the foundation every module relies on."""

import logging

import pytest
from docverify.utils import content_hash, normalize_identifier, parse_number, parse_int, get_logger


# ── content_hash ──────────────────────────────────────────────────────────────

class TestContentHash:
    def test_basic_hash(self):
        h = content_hash("hello world")
        assert isinstance(h, str)
        assert len(h) == 64  # sha256 hex digest

    def test_normalizes_whitespace(self):
        h1 = content_hash("hello   world")
        h2 = content_hash("hello world")
        assert h1 == h2

    def test_normalizes_case(self):
        h1 = content_hash("Hello World")
        h2 = content_hash("hello world")
        assert h1 == h2

    def test_normalizes_newlines_and_tabs(self):
        h1 = content_hash("hello\n\tworld")
        h2 = content_hash("hello world")
        assert h1 == h2

    def test_different_content_different_hash(self):
        h1 = content_hash("hello world")
        h2 = content_hash("goodbye world")
        assert h1 != h2

    def test_empty_string(self):
        h = content_hash("")
        assert len(h) == 64

    def test_stable_across_calls(self):
        assert content_hash("test") == content_hash("test")


# ── normalize_identifier ─────────────────────────────────────────────────────

class TestNormalizeIdentifier:
    def test_uppercase(self):
        assert normalize_identifier("abc") == "ABC"

    def test_strip_hyphens(self):
        assert normalize_identifier("ord-2026-77566") == "ORD202677566"

    def test_strip_slashes(self):
        assert normalize_identifier("ABC/123/DEF") == "ABC123DEF"

    def test_strip_dots(self):
        assert normalize_identifier("A.B.C") == "ABC"

    def test_strip_spaces(self):
        assert normalize_identifier("ABC 123 DEF") == "ABC123DEF"

    def test_mixed_separators(self):
        assert normalize_identifier("ord-2026/77566.1") == "ORD2026775661"

    def test_none_returns_none(self):
        assert normalize_identifier(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_identifier("") is None

    def test_only_separators_returns_none(self):
        assert normalize_identifier("- /.") is None

    def test_preserves_digits(self):
        assert normalize_identifier("SLNM5154974") == "SLNM5154974"

    def test_real_world_container(self):
        assert normalize_identifier("BRUX-359-1184") == "BRUX3591184"


# ── parse_number ─────────────────────────────────────────────────────────────

class TestParseNumber:
    def test_plain_integer(self):
        assert parse_number("42") == 42.0

    def test_plain_float(self):
        assert parse_number("3.14") == pytest.approx(3.14)

    def test_us_thousands_with_decimal(self):
        assert parse_number("6,402.00") == pytest.approx(6402.00)

    def test_us_thousands_no_decimal(self):
        assert parse_number("4,967") == pytest.approx(4967)

    def test_eu_format_with_comma_decimal(self):
        assert parse_number("6.402,00") == pytest.approx(6402.00)

    def test_eu_format_large(self):
        assert parse_number("1.234.567,89") == pytest.approx(1234567.89)

    def test_space_separated_thousands(self):
        assert parse_number("4 967") == pytest.approx(4967)

    def test_currency_symbol_euro(self):
        assert parse_number("€6,402.00") == pytest.approx(6402.00)

    def test_currency_symbol_dollar(self):
        assert parse_number("$12,345") == pytest.approx(12345)

    def test_currency_prefix_usd(self):
        assert parse_number("USD 12,345") == pytest.approx(12345)

    def test_currency_prefix_eur(self):
        assert parse_number("EUR 1.234,56") == pytest.approx(1234.56)

    def test_none_returns_none(self):
        assert parse_number(None) is None

    def test_empty_string_returns_none(self):
        assert parse_number("") is None

    def test_whitespace_only_returns_none(self):
        assert parse_number("   ") is None

    def test_non_numeric_returns_none(self):
        assert parse_number("abc") is None

    def test_single_comma_as_decimal(self):
        # "6,42" — 2 decimal digits, should be EU decimal
        assert parse_number("6,42") == pytest.approx(6.42)

    def test_negative_number(self):
        assert parse_number("-42.5") == pytest.approx(-42.5)

    def test_zero(self):
        assert parse_number("0") == 0.0

    def test_integer_input(self):
        assert parse_number(42) == 42.0

    def test_float_input(self):
        assert parse_number(3.14) == pytest.approx(3.14)

    def test_euro_with_spaces(self):
        assert parse_number("€ 6 402") == pytest.approx(6402)

    def test_pound_symbol(self):
        assert parse_number("£1,234.56") == pytest.approx(1234.56)


# ── parse_int ────────────────────────────────────────────────────────────────

class TestParseInt:
    def test_plain_int(self):
        assert parse_int("42") == 42

    def test_with_separators(self):
        assert parse_int("4,967") == 4967

    def test_float_string_truncated(self):
        assert parse_int("42.9") == 42

    def test_none_returns_none(self):
        assert parse_int(None) is None

    def test_non_numeric_returns_none(self):
        assert parse_int("abc") is None

    def test_int_passthrough(self):
        assert parse_int(42) == 42

    def test_float_passthrough(self):
        assert parse_int(42.7) == 42

    def test_eu_format(self):
        assert parse_int("1.234") == 1234


# ── get_logger ───────────────────────────────────────────────────────────────

class TestGetLogger:
    def test_returns_logger(self):
        import logging
        logger = get_logger("test.module")
        assert isinstance(logger, logging.Logger)

    def test_logger_name(self):
        logger = get_logger("my_module")
        assert logger.name == "my_module"

    def test_warning_level(self):
        logger = get_logger("test_warn")
        assert logger.level == logging.WARNING

    def test_has_handler(self):
        logger = get_logger("test_handler")
        assert len(logger.handlers) >= 1
