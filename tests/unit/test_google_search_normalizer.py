"""Unit tests for GoogleSearchCollector.normalize().

Tests verify that raw Serper.dev and SerpAPI organic results are correctly
mapped to the universal content_records schema.

These are pure unit tests — no HTTP calls, no database, no Celery.
The GoogleSearchCollector.normalize() method is synchronous and depends only
on the injected Normalizer, so it can be exercised without any infrastructure.
"""

from __future__ import annotations

import pytest

from issue_observatory.arenas.google_search.collector import GoogleSearchCollector
from issue_observatory.arenas.base import Tier
from issue_observatory.core.normalizer import Normalizer
from tests.factories.content import GoogleSearchResultFactory

TEST_SALT = "test-pseudonymization-salt-for-unit-tests"


@pytest.fixture
def collector() -> GoogleSearchCollector:
    """GoogleSearchCollector with a test-salt Normalizer.

    No credential_pool or rate_limiter — normalize() is synchronous and
    does not touch external services.
    """
    # GoogleSearchCollector constructs its own Normalizer from settings.
    # We patch it with a known salt so pseudonymized IDs are deterministic.
    c = GoogleSearchCollector()
    c._normalizer = Normalizer(pseudonymization_salt=TEST_SALT)
    return c


# ---------------------------------------------------------------------------
# Happy path: Serper.dev organic result
# ---------------------------------------------------------------------------


class TestGoogleSearchNormalize:
    def test_normalize_serper_result_platform_is_google(
        self, collector: GoogleSearchCollector
    ) -> None:
        """Normalized record has platform='google'."""
        raw = GoogleSearchResultFactory.build()
        result = collector.normalize(raw)

        assert result["platform"] == "google_search"

    def test_normalize_serper_result_arena_is_google_search(
        self, collector: GoogleSearchCollector
    ) -> None:
        """Normalized record has arena='google_search'."""
        raw = GoogleSearchResultFactory.build()
        result = collector.normalize(raw)

        assert result["arena"] == "google_search"

    def test_normalize_serper_result_content_type_is_search_result(
        self, collector: GoogleSearchCollector
    ) -> None:
        """content_type is forced to 'search_result' regardless of raw input."""
        raw = GoogleSearchResultFactory.build()
        result = collector.normalize(raw)

        assert result["content_type"] == "search_result"

    def test_normalize_serper_result_url_from_link(
        self, collector: GoogleSearchCollector
    ) -> None:
        """The 'link' field from Serper.dev is mapped to 'url'."""
        raw = {
            "title": "Test Result",
            "link": "https://example.dk/article",
            "snippet": "Test snippet",
            "position": 1,
        }
        result = collector.normalize(raw)

        assert result["url"] == "https://example.dk/article"

    def test_normalize_serper_result_snippet_becomes_text_content(
        self, collector: GoogleSearchCollector
    ) -> None:
        """The 'snippet' field from Serper.dev maps to 'text_content'."""
        raw = {
            "title": "DR Artikel",
            "link": "https://dr.dk/artikel",
            "snippet": "Klimaforandringer er en udfordring",
        }
        result = collector.normalize(raw)

        assert result["text_content"] == "Klimaforandringer er en udfordring"

    def test_normalize_serper_result_title_is_mapped(
        self, collector: GoogleSearchCollector
    ) -> None:
        """The 'title' field is mapped correctly."""
        raw = {
            "title": "Grøn omstilling i Danmark",
            "link": "https://politiken.dk/groen",
        }
        result = collector.normalize(raw)

        assert result["title"] == "Grøn omstilling i Danmark"

    def test_normalize_preserves_raw_metadata(
        self, collector: GoogleSearchCollector
    ) -> None:
        """The original raw dict is preserved in raw_metadata."""
        raw = {
            "title": "Test",
            "link": "https://example.dk",
            "snippet": "snippet",
            "position": 3,
            "displayLink": "example.dk",
        }
        result = collector.normalize(raw)

        # raw_metadata should contain all original fields (plus the injected content_type)
        assert result["raw_metadata"]["position"] == 3
        assert result["raw_metadata"]["displayLink"] == "example.dk"

    def test_normalize_computes_content_hash(
        self, collector: GoogleSearchCollector
    ) -> None:
        """content_hash is computed from the snippet text."""
        raw = {
            "snippet": "Velfærdsstatens fremtid debatteres i Aarhus",
            "link": "https://jyllands-posten.dk/velfaerd",
        }
        result = collector.normalize(raw)

        assert result["content_hash"] is not None
        assert len(result["content_hash"]) == 64

    def test_normalize_with_no_snippet_falls_back_to_url_hash(
        self, collector: GoogleSearchCollector
    ) -> None:
        """When snippet is absent, content_hash is derived from the URL."""
        raw = {
            "title": "No snippet article",
            "link": "https://berlingske.dk/article-no-snippet",
        }
        result = collector.normalize(raw)

        assert result["content_hash"] is not None
        # The hash should match what we'd get from the URL
        from issue_observatory.core.normalizer import Normalizer  # noqa: PLC0415
        expected_norm = Normalizer(pseudonymization_salt=TEST_SALT)
        assert result["content_hash"] == expected_norm.compute_content_hash(
            "https://berlingske.dk/article-no-snippet"
        )

    def test_normalize_no_author_fields_for_search_results(
        self, collector: GoogleSearchCollector
    ) -> None:
        """Google Search results have no author — author fields must be None.

        Search results are website pages, not social media posts.  Attempting
        to pseudonymize a missing author would silently create a pseudonym
        for 'None', which would be incorrect.
        """
        raw = GoogleSearchResultFactory.build()
        result = collector.normalize(raw)

        assert result["author_platform_id"] is None
        assert result["author_display_name"] is None
        assert result["pseudonymized_author_id"] is None

    def test_normalize_required_fields_always_present(
        self, collector: GoogleSearchCollector
    ) -> None:
        """All five required fields are present in every normalized record."""
        raw = GoogleSearchResultFactory.build()
        result = collector.normalize(raw)

        assert result["platform"] == "google_search"
        assert result["arena"] == "google_search"
        assert result["content_type"] == "search_result"
        assert result["collected_at"] is not None
        assert result["collection_tier"] is not None


# ---------------------------------------------------------------------------
# Danish character preservation
# ---------------------------------------------------------------------------


class TestGoogleSearchNormalizeDanish:
    @pytest.mark.parametrize(
        "danish_text",
        [
            "Klimaforandringer påvirker de grønne danske søer",
            "Velfærdsstatens fremtid i Ålborg og Aarhus",
            "Færøerne og Grønland i den arktiske strategi",
            "Søren Kierkegaard og Aabenraa",
        ],
    )
    def test_normalize_preserves_danish_in_snippet(
        self,
        collector: GoogleSearchCollector,
        danish_text: str,
    ) -> None:
        """æ, ø, å in the snippet (text_content) survive normalization."""
        raw = {"snippet": danish_text, "link": "https://example.dk"}
        result = collector.normalize(raw)

        assert result["text_content"] == danish_text

    @pytest.mark.parametrize(
        "danish_title",
        [
            "Grøn omstilling og velfærd",
            "Ålborg kommunes budgetplan",
            "Søer og ådale i Danmark",
        ],
    )
    def test_normalize_preserves_danish_in_title(
        self,
        collector: GoogleSearchCollector,
        danish_title: str,
    ) -> None:
        """æ, ø, å in the title survive normalization."""
        raw = {"title": danish_title, "link": "https://example.dk"}
        result = collector.normalize(raw)

        assert result["title"] == danish_title


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestGoogleSearchNormalizeEdgeCases:
    def test_normalize_completely_empty_raw_does_not_raise(
        self, collector: GoogleSearchCollector
    ) -> None:
        """An empty dict does not crash normalize() — all fields default gracefully."""
        result = collector.normalize({})

        assert result["platform"] == "google_search"
        assert result["arena"] == "google_search"
        assert result["content_type"] == "search_result"
        assert result["url"] is None
        assert result["text_content"] is None
        assert result["content_hash"] is None

    def test_normalize_missing_link_url_is_none(
        self, collector: GoogleSearchCollector
    ) -> None:
        """Missing 'link' field results in url=None without KeyError."""
        raw = {"title": "Some Title", "snippet": "Some snippet"}
        result = collector.normalize(raw)

        assert result["url"] is None

    def test_normalize_missing_title_is_none(
        self, collector: GoogleSearchCollector
    ) -> None:
        """Missing 'title' produces title=None without error."""
        raw = {"link": "https://example.dk", "snippet": "test"}
        result = collector.normalize(raw)

        assert result["title"] is None

    def test_normalize_extra_fields_in_raw_are_preserved_in_metadata(
        self, collector: GoogleSearchCollector
    ) -> None:
        """Platform-specific fields not in the universal schema are in raw_metadata."""
        raw = {
            "link": "https://example.dk",
            "position": 5,
            "sitelinks": [{"title": "Sub", "link": "https://example.dk/sub"}],
        }
        result = collector.normalize(raw)

        assert result["raw_metadata"]["position"] == 5
        assert result["raw_metadata"]["sitelinks"] is not None


# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------


class TestGoogleSearchTierConfig:
    def test_get_tier_config_free_returns_none(
        self, collector: GoogleSearchCollector
    ) -> None:
        """FREE tier config returns None — signalling the tier is unavailable."""
        result = collector.get_tier_config(Tier.FREE)
        assert result is None

    def test_get_tier_config_medium_has_expected_fields(
        self, collector: GoogleSearchCollector
    ) -> None:
        """MEDIUM tier config has all required TierConfig fields."""
        config = collector.get_tier_config(Tier.MEDIUM)

        assert config is not None
        assert config.max_results_per_run > 0
        assert config.rate_limit_per_minute > 0
        assert config.requires_credential is True
        assert config.estimated_credits_per_1k >= 1

    def test_get_tier_config_premium_has_higher_limits_than_medium(
        self, collector: GoogleSearchCollector
    ) -> None:
        """PREMIUM tier allows more results per run than MEDIUM."""
        medium = collector.get_tier_config(Tier.MEDIUM)
        premium = collector.get_tier_config(Tier.PREMIUM)

        assert premium is not None
        assert medium is not None
        assert premium.max_results_per_run > medium.max_results_per_run

    async def test_estimate_credits_free_tier_is_zero(
        self, collector: GoogleSearchCollector
    ) -> None:
        """estimate_credits() returns 0 for FREE tier (unavailable)."""
        result = await collector.estimate_credits(terms=["test"], tier=Tier.FREE)
        assert result == 0

    async def test_estimate_credits_medium_tier_counts_queries(
        self, collector: GoogleSearchCollector
    ) -> None:
        """estimate_credits() counts one query per page of 10 results for MEDIUM tier."""
        # 3 terms, 100 results each, 10 results/page → 10 pages per term → 30 queries
        result = await collector.estimate_credits(
            terms=["term1", "term2", "term3"],
            tier=Tier.MEDIUM,
            max_results=100,
        )
        assert result == 30  # 3 terms * ceil(100/10) pages = 3 * 10 = 30
