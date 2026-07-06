"""Unit tests for RAKE keyword extraction.

Tests the window extraction helper and RAKE processing logic without
requiring a database connection. The full async extract_rake_keywords()
function is tested via integration tests since it requires DB access.
"""
from __future__ import annotations

from issue_observatory.analysis.keyword_extraction import _extract_window


class TestExtractWindow:
    """Verify text windowing around search term occurrences."""

    def test_window_returns_words_around_term(self) -> None:
        """Extracts N words before and after each search term occurrence."""
        content = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        result = _extract_window(content, ["epsilon"], window_size=2)
        # The search term and surrounding words should appear
        assert "epsilon" in result
        # Verify we get a subset, not the full content
        result_words = result.split()
        assert len(result_words) < len(content.split())

    def test_window_with_no_match_returns_full_content(self) -> None:
        """If no search term is found, returns the original content."""
        content = "dette er noget helt andet tekst"
        result = _extract_window(content, ["xyz_missing"], window_size=3)
        assert result == content

    def test_window_with_empty_terms_returns_content(self) -> None:
        """Empty search term list returns full content."""
        content = "test tekst her"
        result = _extract_window(content, [], window_size=3)
        assert result == content

    def test_window_with_empty_content_returns_content(self) -> None:
        """Empty content returns empty string."""
        result = _extract_window("", ["test"], window_size=3)
        assert result == ""

    def test_window_case_insensitive(self) -> None:
        """Search term matching is case-insensitive."""
        content = "Den danske Folkeskole har mange elever"
        result = _extract_window(content, ["folkeskole"], window_size=1)
        assert "Folkeskole" in result

    def test_window_multiple_terms(self) -> None:
        """Multiple search terms produce combined windows."""
        content = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        result = _extract_window(content, ["alpha", "kappa"], window_size=1)
        assert "alpha" in result
        assert "kappa" in result

    def test_window_term_at_start(self) -> None:
        """Window handles search term at the very start of content."""
        content = "klimaforandringer er en global udfordring"
        result = _extract_window(content, ["klimaforandringer"], window_size=2)
        assert "klimaforandringer" in result
        assert "er" in result
        assert "en" in result

    def test_window_term_at_end(self) -> None:
        """Window handles search term at the very end of content."""
        content = "vi taler om klimaforandringer"
        result = _extract_window(content, ["klimaforandringer"], window_size=2)
        assert "klimaforandringer" in result
        assert "om" in result

    def test_window_danish_characters(self) -> None:
        """Window extraction preserves Danish special characters."""
        content = "grøn omstilling kræver ændringer i samfundet"
        result = _extract_window(content, ["kræver"], window_size=1)
        assert "kræver" in result
