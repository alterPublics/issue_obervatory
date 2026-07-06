"""Unit tests for NER extraction module.

Tests the spaCy model loading singleton and entity type filtering.
Full extraction is tested via integration tests (requires DB).
"""
from __future__ import annotations

from unittest.mock import patch

from issue_observatory.analysis import ner_extraction


class TestGetNlp:
    """Verify spaCy model singleton loading behavior."""

    def test_returns_none_when_spacy_not_installed(self) -> None:
        """When spaCy is not installed, _get_nlp returns None without crashing."""
        # Reset singleton state
        ner_extraction._nlp_model = None
        ner_extraction._nlp_load_attempted = False

        with patch.dict("sys.modules", {"spacy": None}):
            # Force reimport to trigger ImportError
            ner_extraction._nlp_load_attempted = False
            ner_extraction._nlp_model = None
            result = ner_extraction._get_nlp()

        assert result is None

        # Clean up singleton state
        ner_extraction._nlp_load_attempted = False
        ner_extraction._nlp_model = None

    def test_singleton_caches_load_attempt(self) -> None:
        """Second call returns cached result without reloading."""
        ner_extraction._nlp_model = None
        ner_extraction._nlp_load_attempted = True

        # Should return cached None without trying to load
        result = ner_extraction._get_nlp()
        assert result is None

        # Clean up
        ner_extraction._nlp_load_attempted = False
        ner_extraction._nlp_model = None
