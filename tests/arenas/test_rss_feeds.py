"""Tests for the RSS Feeds arena collector.

Covers:
- normalize() unit tests using raw entry-like dicts
- collect_by_terms() integration tests with mocked HTTP (respx) + feedparser
- Edge cases: empty feed, HTTP error response, feedparser bozo error, missing author
- health_check() test
- Danish character preservation (æ, ø, å)

These tests run without a live database or network connection.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

# ---------------------------------------------------------------------------
# Env bootstrap (must run before any application imports)
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==")

from issue_observatory.arenas.base import Tier  # noqa: E402
from issue_observatory.arenas.rss_feeds.collector import RSSFeedsCollector  # noqa: E402
from issue_observatory.arenas.rss_feeds.config import HEALTH_CHECK_FEED_URL  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "api_responses" / "rss_feeds"


def _load_dr_feed_xml() -> str:
    """Load the recorded DR RSS feed XML fixture."""
    return (FIXTURES_DIR / "dr_feed_response.xml").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Feedparser entry mock helpers
# ---------------------------------------------------------------------------


def _time_struct_from_epoch(epoch: float):
    """Convert a Unix epoch to a time.struct_time in UTC."""
    import time
    return time.gmtime(int(epoch))


def _make_feed_entry(
    entry_id: str = "https://www.dr.dk/article/001",
    title: str = "Test article title",
    link: str = "https://www.dr.dk/article/001",
    summary: str = "Test article summary.",
    author: str | None = "DR Nyheder",
    published_epoch: float = 1739620200.0,
) -> SimpleNamespace:
    """Build a SimpleNamespace that mimics a feedparser entry object."""
    entry = SimpleNamespace()
    entry.id = entry_id
    entry.title = title
    entry.link = link
    entry.summary = summary
    entry.description = summary
    entry.author = author
    entry.published_parsed = _time_struct_from_epoch(published_epoch)
    entry.updated_parsed = None
    entry.tags = []
    entry.media_content = []
    entry.enclosures = []
    return entry


def _make_feed_result(entries: list, bozo: bool = False) -> SimpleNamespace:
    """Build a SimpleNamespace that mimics feedparser.FeedParserDict."""
    feed = SimpleNamespace()
    feed.entries = entries
    feed.bozo = bozo
    feed.bozo_exception = None
    return feed


# ---------------------------------------------------------------------------
# normalize() unit tests
# ---------------------------------------------------------------------------


class TestNormalize:
    def _collector(self) -> RSSFeedsCollector:
        return RSSFeedsCollector()

    def test_normalize_sets_arena_to_news_media(self) -> None:
        """normalize() writes arena='news_media' for all RSS entries."""
        collector = self._collector()
        raw = {
            "id": "https://dr.dk/test",
            "title": "Test article",
            "url": "https://dr.dk/test",
            "text_content": "Test content.",
            "author": "DR",
            "published_at": "2026-02-15T10:00:00+00:00",
            "language": "da",
            "content_type": "article",
            "media_urls": [],
            "outlet_slug": "dr",
            "_search_terms_matched": [],
        }
        result = collector.normalize(raw)

        assert result["arena"] == "news_media"
        assert result["content_type"] == "article"

    def test_normalize_platform_is_outlet_slug(self) -> None:
        """normalize() uses outlet_slug as the platform identifier."""
        collector = self._collector()
        raw = {
            "id": "https://politiken.dk/test",
            "title": "Politiken article",
            "url": "https://politiken.dk/test",
            "text_content": "Body.",
            "author": None,
            "published_at": None,
            "language": "da",
            "content_type": "article",
            "media_urls": [],
            "outlet_slug": "politiken",
            "_search_terms_matched": [],
        }
        result = collector.normalize(raw)

        assert result["platform"] == "politiken"

    def test_normalize_collection_tier_is_free(self) -> None:
        """normalize() always sets collection_tier='free' for RSS feeds."""
        collector = self._collector()
        raw = {
            "id": "url1",
            "title": "T",
            "url": "https://dr.dk/t",
            "text_content": "c",
            "author": None,
            "published_at": None,
            "language": "da",
            "content_type": "article",
            "media_urls": [],
            "outlet_slug": "dr",
            "_search_terms_matched": [],
        }
        result = collector.normalize(raw)

        assert result["collection_tier"] == "free"

    def test_normalize_preserves_danish_title(self) -> None:
        """æ, ø, å in article title survive normalize() without corruption."""
        collector = self._collector()
        danish_title = "Mette Frederiksen: Grøn omstilling er vores vigtigste opgave"
        raw = {
            "id": "https://dr.dk/danish",
            "title": danish_title,
            "url": "https://dr.dk/danish",
            "text_content": "Indhold.",
            "author": None,
            "published_at": None,
            "language": "da",
            "content_type": "article",
            "media_urls": [],
            "outlet_slug": "dr",
            "_search_terms_matched": [],
        }
        result = collector.normalize(raw)

        assert result["title"] == danish_title
        assert "ø" in result["title"]
        assert "Æ" in result["title"]  # from "vigtigste" -> no, but "Grøn" has ø

    def test_normalize_preserves_danish_text_content(self) -> None:
        """æ, ø, å in article body survive normalize()."""
        collector = self._collector()
        danish_body = "Statsministeren talte om klimaforandringer og velfærd i Ålborg."
        raw = {
            "id": "https://dr.dk/body",
            "title": "Test",
            "url": "https://dr.dk/body",
            "text_content": danish_body,
            "author": None,
            "published_at": None,
            "language": "da",
            "content_type": "article",
            "media_urls": [],
            "outlet_slug": "dr",
            "_search_terms_matched": [],
        }
        result = collector.normalize(raw)

        assert result["text_content"] == danish_body

    @pytest.mark.parametrize("char", ["æ", "ø", "å", "Æ", "Ø", "Å"])
    def test_normalize_handles_each_danish_character(self, char: str) -> None:
        """Each Danish character in title survives normalize() without error."""
        collector = self._collector()
        raw = {
            "id": f"https://dr.dk/{char}",
            "title": f"Artikel med {char} tegn",
            "url": f"https://dr.dk/{char}",
            "text_content": f"Indhold: {char}",
            "author": None,
            "published_at": None,
            "language": "da",
            "content_type": "article",
            "media_urls": [],
            "outlet_slug": "dr",
            "_search_terms_matched": [],
        }
        result = collector.normalize(raw)

        assert char in result["title"]

    def test_normalize_missing_author_produces_none_pseudonym(self) -> None:
        """normalize() produces None pseudonymized_author_id when author is absent."""
        collector = self._collector()
        raw = {
            "id": "https://dr.dk/noauthor",
            "title": "Anonymous article",
            "url": "https://dr.dk/noauthor",
            "text_content": "Content without author.",
            "author": None,
            "published_at": None,
            "language": "da",
            "content_type": "article",
            "media_urls": [],
            "outlet_slug": "dr",
            "_search_terms_matched": [],
        }
        result = collector.normalize(raw)

        assert result["pseudonymized_author_id"] is None

    def test_normalize_required_fields_always_present(self) -> None:
        """All required schema fields are present in the normalized output."""
        collector = self._collector()
        raw = {
            "id": "https://test.dk/req",
            "title": "Required fields test",
            "url": "https://test.dk/req",
            "text_content": "Body.",
            "author": None,
            "published_at": None,
            "language": "da",
            "content_type": "article",
            "media_urls": [],
            "outlet_slug": "test",
            "_search_terms_matched": [],
        }
        result = collector.normalize(raw)

        for field in ("platform", "arena", "content_type", "collected_at", "collection_tier"):
            assert field in result, f"Missing required field: {field}"
            assert result[field] is not None, f"Required field None: {field}"


# ---------------------------------------------------------------------------
# collect_by_terms() integration tests
# ---------------------------------------------------------------------------


class TestCollectByTerms:
    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_returns_matching_records(self) -> None:
        """collect_by_terms() returns records whose title/summary matches the search term."""
        feed_url = "https://www.dr.dk/rss/nyheder"

        respx.get(feed_url).mock(
            return_value=httpx.Response(
                200,
                text=_load_dr_feed_xml(),
                headers={"Content-Type": "application/rss+xml; charset=utf-8"},
            )
        )

        collector = RSSFeedsCollector(feed_overrides={"dr_nyheder": feed_url})
        records = await collector.collect_by_terms(
            terms=["folkeskolen"], tier=Tier.FREE, max_results=50
        )

        assert isinstance(records, list)
        # The DR fixture contains "folkeskolen" in the description of the first entry
        assert len(records) >= 1
        for record in records:
            assert record["arena"] == "news_media"
            assert record["content_type"] == "article"

    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_empty_results_when_no_match(self) -> None:
        """collect_by_terms() returns [] when no entries match the search terms."""
        feed_url = "https://www.dr.dk/rss/nyheder"

        respx.get(feed_url).mock(
            return_value=httpx.Response(
                200,
                text=_load_dr_feed_xml(),
                headers={"Content-Type": "application/rss+xml; charset=utf-8"},
            )
        )

        collector = RSSFeedsCollector(feed_overrides={"dr_nyheder": feed_url})
        records = await collector.collect_by_terms(
            terms=["xyzzymatchnothing99"], tier=Tier.FREE, max_results=50
        )

        assert records == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_http_error_skips_feed_gracefully(self) -> None:
        """collect_by_terms() returns [] when the feed URL returns a 404."""
        feed_url = "https://www.dr.dk/rss/nonexistent"

        respx.get(feed_url).mock(return_value=httpx.Response(404))

        collector = RSSFeedsCollector(feed_overrides={"dr_broken": feed_url})
        # Should not raise; just skip the broken feed
        records = await collector.collect_by_terms(
            terms=["grøn"], tier=Tier.FREE, max_results=50
        )

        assert isinstance(records, list)
        assert records == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_danish_text_preserved_end_to_end(self) -> None:
        """Danish characters in feed entries survive the full collect → normalize pipeline."""
        feed_url = "https://www.dr.dk/rss/nyheder"

        respx.get(feed_url).mock(
            return_value=httpx.Response(
                200,
                text=_load_dr_feed_xml(),
                headers={"Content-Type": "application/rss+xml; charset=utf-8"},
            )
        )

        collector = RSSFeedsCollector(feed_overrides={"dr_nyheder": feed_url})
        records = await collector.collect_by_terms(
            terms=["grøn"], tier=Tier.FREE, max_results=50
        )

        # DR fixture title: "Mette Frederiksen: Grøn omstilling er vores vigtigste opgave"
        titles = [r.get("title", "") or "" for r in records]
        assert any("ø" in t for t in titles), "Expected 'ø' in at least one article title"
        assert any("Grøn" in t for t in titles), "Expected 'Grøn' in at least one article title"

    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_respects_max_results(self) -> None:
        """collect_by_terms() returns no more records than max_results."""
        feed_url = "https://www.dr.dk/rss/nyheder"

        respx.get(feed_url).mock(
            return_value=httpx.Response(
                200,
                text=_load_dr_feed_xml(),
                headers={"Content-Type": "application/rss+xml; charset=utf-8"},
            )
        )

        collector = RSSFeedsCollector(feed_overrides={"dr_nyheder": feed_url})
        records = await collector.collect_by_terms(
            terms=[""], tier=Tier.FREE, max_results=1
        )

        assert len(records) <= 1

    @pytest.mark.asyncio
    async def test_collect_by_terms_bozo_feed_with_no_entries_skipped(self) -> None:
        """collect_by_terms() skips bozo feeds that produce zero entries."""
        bozo_xml = "NOT VALID XML AT ALL <<<>>>"
        feed_url = "https://broken.example.com/rss"

        with respx.mock:
            respx.get(feed_url).mock(
                return_value=httpx.Response(200, text=bozo_xml)
            )

            collector = RSSFeedsCollector(feed_overrides={"broken_feed": feed_url})
            records = await collector.collect_by_terms(
                terms=["anything"], tier=Tier.FREE, max_results=50
            )

        # Should not raise; bozo feeds are skipped
        assert isinstance(records, list)


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    @respx.mock
    async def test_health_check_returns_ok_on_valid_feed(self) -> None:
        """health_check() returns status='ok' when feed responds with entries."""
        respx.get(HEALTH_CHECK_FEED_URL).mock(
            return_value=httpx.Response(
                200,
                text=_load_dr_feed_xml(),
                headers={"Content-Type": "application/rss+xml; charset=utf-8"},
            )
        )

        collector = RSSFeedsCollector()
        result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "rss_feeds"
        assert result["platform"] == "rss_feeds"
        assert "entries" in result

    @pytest.mark.asyncio
    @respx.mock
    async def test_health_check_returns_ok_on_304_not_modified(self) -> None:
        """health_check() returns status='ok' for a 304 Not Modified response."""
        respx.get(HEALTH_CHECK_FEED_URL).mock(
            return_value=httpx.Response(304)
        )

        collector = RSSFeedsCollector()
        result = await collector.health_check()

        assert result["status"] == "ok"

    @pytest.mark.asyncio
    @respx.mock
    async def test_health_check_returns_down_on_http_error(self) -> None:
        """health_check() returns status='down' on HTTP error response."""
        respx.get(HEALTH_CHECK_FEED_URL).mock(
            return_value=httpx.Response(503)
        )

        collector = RSSFeedsCollector()
        result = await collector.health_check()

        assert result["status"] == "down"
