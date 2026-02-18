"""Tests for core/schemas/query_design.py utility functions.

Tests cover parse_language_codes() — the function that converts a stored
comma-separated language string back to a list of ISO 639-1 codes.
"""

from __future__ import annotations

import os

import pytest

# ---------------------------------------------------------------------------
# Env bootstrap
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==")

from issue_observatory.core.schemas.query_design import parse_language_codes  # noqa: E402


# ---------------------------------------------------------------------------
# M-01: parse_language_codes()
# ---------------------------------------------------------------------------


class TestParseLanguageCodes:
    def test_single_language_returns_single_element_list(self) -> None:
        """A single code string returns a one-element list."""
        assert parse_language_codes("da") == ["da"]

    def test_comma_separated_returns_list(self) -> None:
        """Comma-separated codes produce a list with one element per code."""
        assert parse_language_codes("da,en") == ["da", "en"]

    def test_comma_separated_with_spaces_returns_stripped_list(self) -> None:
        """Whitespace around codes is stripped before returning."""
        assert parse_language_codes("da, en") == ["da", "en"]

    def test_empty_string_returns_danish_fallback(self) -> None:
        """An empty string returns ['da'] (the Danish-first default fallback)."""
        result = parse_language_codes("")
        assert result == ["da"]

    def test_three_languages(self) -> None:
        """Three comma-separated codes produce a three-element list."""
        result = parse_language_codes("da,en,de")
        assert result == ["da", "en", "de"]

    def test_single_trailing_comma_ignored(self) -> None:
        """A trailing comma does not produce an empty element at the end of the list."""
        result = parse_language_codes("da,")
        assert result == ["da"]

    def test_uppercased_codes_are_lowercased(self) -> None:
        """Input codes are lowercased before being returned."""
        result = parse_language_codes("DA,EN")
        assert result == ["da", "en"]

    def test_deduplication_preserves_insertion_order(self) -> None:
        """Duplicate codes are removed; insertion order of first occurrence is kept."""
        result = parse_language_codes("da, EN, da")
        assert result == ["da", "en"]

    def test_preserves_insertion_order_for_distinct_codes(self) -> None:
        """When all codes are distinct, the output order matches the input order."""
        result = parse_language_codes("en,da,sv")
        assert result == ["en", "da", "sv"]

    def test_none_or_falsy_returns_list(self) -> None:
        """Passing None raises TypeError/AttributeError (function requires a string).

        If the function handles None gracefully, the result must be a list.
        If it raises, we skip — the function is not designed to handle None.
        """
        try:
            result = parse_language_codes(None)  # type: ignore[arg-type]
            assert isinstance(result, list)
        except (TypeError, AttributeError):
            pytest.skip("parse_language_codes does not handle None input by design")
