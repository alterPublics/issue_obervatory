"""Unit tests for arena category standardization.

Verifies the canonical platform-to-category mapping, category labels, and the
get_arena_category() lookup function — the single source of truth for the
four-category scheme (news, search, web, social_media).
"""
from __future__ import annotations

import pytest

from issue_observatory.arenas.categories import (
    ARENA_CATEGORIES,
    ARENA_CATEGORY_LABELS,
    VALID_CATEGORIES,
    get_arena_category,
)


class TestArenaCategories:
    """Verify the canonical mapping dict."""

    def test_all_platforms_have_category(self) -> None:
        """Every platform in the mapping resolves to a valid category."""
        for platform, category in ARENA_CATEGORIES.items():
            assert category in VALID_CATEGORIES, (
                f"Platform {platform!r} maps to unknown category {category!r}"
            )

    def test_exactly_four_categories(self) -> None:
        """The system defines exactly 4 arena categories."""
        assert VALID_CATEGORIES == frozenset({"news", "search", "web", "social_media"})

    def test_news_platforms(self) -> None:
        """News category includes GDELT, RSS, Ritzau, Event Registry, Domain Crawler."""
        news_platforms = {p for p, c in ARENA_CATEGORIES.items() if c == "news"}
        expected = {"gdelt", "rss_feeds", "ritzau_via", "event_registry", "domain_crawler"}
        assert expected.issubset(news_platforms)

    def test_search_platforms(self) -> None:
        """Search category includes Google Search, Autocomplete, Wikipedia, OpenRouter."""
        search_platforms = {p for p, c in ARENA_CATEGORIES.items() if c == "search"}
        expected = {"google_search", "google_autocomplete", "wikipedia", "openrouter"}
        assert expected.issubset(search_platforms)

    def test_web_platforms(self) -> None:
        """Web category includes URL scraper, Majestic, Common Crawl, Wayback."""
        web_platforms = {p for p, c in ARENA_CATEGORIES.items() if c == "web"}
        expected = {"url_scraper", "majestic", "common_crawl", "wayback"}
        assert expected.issubset(web_platforms)

    def test_social_media_platforms(self) -> None:
        """Social media category includes Reddit, Bluesky, YouTube, and others."""
        social_platforms = {p for p, c in ARENA_CATEGORIES.items() if c == "social_media"}
        expected = {"reddit", "bluesky", "youtube", "telegram"}
        assert expected.issubset(social_platforms)

    def test_domain_crawler_is_news_not_web(self) -> None:
        """domain_crawler was reclassified from 'web' to 'news' in the standardization."""
        assert ARENA_CATEGORIES["domain_crawler"] == "news"


class TestArenaCategoryLabels:
    """Verify human-readable labels for each category."""

    def test_all_categories_have_labels(self) -> None:
        """Every valid category has a human-readable label."""
        for cat in VALID_CATEGORIES:
            assert cat in ARENA_CATEGORY_LABELS, f"Missing label for category {cat!r}"

    def test_labels_are_non_empty_strings(self) -> None:
        """Labels are non-empty strings."""
        for _cat, label in ARENA_CATEGORY_LABELS.items():
            assert isinstance(label, str)
            assert len(label) > 0


class TestGetArenaCategory:
    """Verify the lookup function."""

    @pytest.mark.parametrize(
        "platform,expected",
        [
            ("gdelt", "news"),
            ("rss_feeds", "news"),
            ("google_search", "search"),
            ("wikipedia", "search"),
            ("url_scraper", "web"),
            ("reddit", "social_media"),
            ("bluesky", "social_media"),
            ("domain_crawler", "news"),
        ],
    )
    def test_known_platform_returns_correct_category(
        self, platform: str, expected: str
    ) -> None:
        """Known platforms return their canonical category."""
        assert get_arena_category(platform) == expected

    def test_unknown_platform_raises_key_error(self) -> None:
        """Unknown platforms raise KeyError (strict mapping, no fallback)."""
        with pytest.raises(KeyError):
            get_arena_category("nonexistent_platform")
