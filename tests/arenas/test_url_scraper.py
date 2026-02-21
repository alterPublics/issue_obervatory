"""Tests for the URL Scraper arena collector.

Covers:
- normalize() unit tests: platform/arena/content_type, platform_id computed
  as SHA-256 of final URL, content_hash, pseudonymized_author_id from domain,
  raw_metadata with fetch diagnostics, published_at resolution
- collect_by_terms() with mocked HTTP fetch: happy path, term matching,
  empty extra_urls returns [], boolean term_groups, max_results cap
- collect_by_actors() with mocked HTTP fetch: domain matching, empty actor_ids
- get_tier_config() for FREE and MEDIUM tiers
- Tier validation: PREMIUM raises ValueError
- health_check() with mocked fetch pipeline
- Danish character preservation through fetch and normalize
- Error isolation: failed URLs do not block remaining fetches

These tests run without a live database or network connection.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Env bootstrap (must run before any application imports)
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==")

from issue_observatory.arenas.base import Tier  # noqa: E402
from issue_observatory.arenas.web.url_scraper._helpers import (  # noqa: E402
    build_searchable_text,
    deduplicate_urls,
    extract_domain,
)
from issue_observatory.arenas.web.url_scraper._normalizer import (  # noqa: E402
    normalize_raw_record,
)
from issue_observatory.arenas.web.url_scraper.collector import (  # noqa: E402
    UrlScraperCollector,
    _make_failure_record,
)
from issue_observatory.core.normalizer import Normalizer  # noqa: E402
from issue_observatory.scraper.content_extractor import ExtractedContent  # noqa: E402
from issue_observatory.scraper.http_fetcher import FetchResult  # noqa: E402


# ---------------------------------------------------------------------------
# Sample data builders
# ---------------------------------------------------------------------------


def _make_raw_record(
    source_url: str = "https://www.dr.dk/nyheder/test-article",
    final_url: str | None = None,
    title: str = "Test Artikel om Dansk Politik",
    text_content: str = "Folkeskolen i Danmark er under forandring.",
    language: str | None = "da",
    http_status: int = 200,
    fetch_failed: bool = False,
) -> dict[str, Any]:
    """Build a raw fetch record dict suitable for normalize()."""
    if final_url is None:
        final_url = source_url

    extracted = ExtractedContent(
        text=text_content,
        title=title,
        language=language,
    )

    return {
        "source_url": source_url,
        "final_url": final_url,
        "html": f"<html><body>{text_content}</body></html>",
        "extracted": extracted,
        "http_status": http_status,
        "fetch_error": None,
        "robots_txt_allowed": True,
        "needs_playwright": False,
        "fetch_duration_ms": 450,
        "last_modified_header": None,
        "_fetch_failed": fetch_failed,
        "_search_terms_matched": [],
    }


def _make_fetch_result(
    html: str = "<html><body>Test content</body></html>",
    status_code: int = 200,
    final_url: str = "https://www.dr.dk/nyheder/test-article",
    error: str | None = None,
    needs_playwright: bool = False,
) -> FetchResult:
    """Build a FetchResult for mocking fetch_url()."""
    return FetchResult(
        html=html,
        status_code=status_code,
        final_url=final_url,
        error=error,
        needs_playwright=needs_playwright,
    )


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------


class TestExtractDomain:
    def test_extract_domain_strips_www(self) -> None:
        """extract_domain() strips www. prefix."""
        assert extract_domain("https://www.dr.dk/nyheder/article") == "dr.dk"

    def test_extract_domain_lowercase(self) -> None:
        """extract_domain() lowercases the hostname."""
        assert extract_domain("https://WWW.DR.DK/Nyheder") == "dr.dk"

    def test_extract_domain_no_www(self) -> None:
        """extract_domain() works without www. prefix."""
        assert extract_domain("https://politiken.dk/article") == "politiken.dk"

    def test_extract_domain_with_port(self) -> None:
        """extract_domain() handles URLs with port numbers."""
        assert extract_domain("https://example.dk:8080/page") == "example.dk:8080"


class TestDeduplicateUrls:
    def test_deduplicates_identical_urls(self) -> None:
        """deduplicate_urls() removes exact duplicate URLs."""
        urls = [
            "https://dr.dk/article1",
            "https://dr.dk/article1",
            "https://dr.dk/article2",
        ]
        result = deduplicate_urls(urls)
        assert len(result) == 2

    def test_deduplicates_tracking_param_variants(self) -> None:
        """deduplicate_urls() deduplicates URLs differing only in UTM params."""
        urls = [
            "https://dr.dk/article?utm_source=twitter",
            "https://dr.dk/article?utm_source=facebook",
        ]
        result = deduplicate_urls(urls)
        assert len(result) == 1

    def test_preserves_order(self) -> None:
        """deduplicate_urls() preserves first-occurrence order."""
        urls = ["https://b.dk/page", "https://a.dk/page", "https://b.dk/page"]
        result = deduplicate_urls(urls)
        assert result == ["https://b.dk/page", "https://a.dk/page"]


class TestBuildSearchableText:
    def test_combines_title_and_text(self) -> None:
        """build_searchable_text() concatenates title and text, lowercased."""
        raw = _make_raw_record(
            title="Dansk Klimapolitik",
            text_content="Ny rapport om CO2-udledning",
        )
        result = build_searchable_text(raw)
        assert "dansk klimapolitik" in result
        assert "co2-udledning" in result

    def test_empty_extracted_returns_empty_string(self) -> None:
        """build_searchable_text() returns '' when extracted is None."""
        raw = _make_raw_record()
        raw["extracted"] = None
        result = build_searchable_text(raw)
        assert result == ""


# ---------------------------------------------------------------------------
# normalize() / normalize_raw_record() unit tests
# ---------------------------------------------------------------------------


class TestNormalize:
    def _normalizer(self) -> Normalizer:
        return Normalizer(pseudonymization_salt="test-pseudonymization-salt-for-unit-tests")

    def _collector(self) -> UrlScraperCollector:
        return UrlScraperCollector()

    def test_normalize_sets_platform_arena_content_type(self) -> None:
        """normalize() sets platform='url_scraper', arena='web', content_type='web_page'."""
        collector = self._collector()
        raw = _make_raw_record()
        result = collector.normalize(raw)

        assert result["platform"] == "url_scraper"
        assert result["arena"] == "web"
        assert result["content_type"] == "web_page"

    def test_normalize_platform_id_is_sha256_of_final_url(self) -> None:
        """normalize() computes platform_id as SHA-256 hex of the final URL."""
        collector = self._collector()
        url = "https://www.dr.dk/nyheder/test-article"
        raw = _make_raw_record(source_url=url, final_url=url)
        result = collector.normalize(raw)

        expected_id = hashlib.sha256(url.encode()).hexdigest()
        assert result["platform_id"] == expected_id

    def test_normalize_url_is_final_url(self) -> None:
        """normalize() uses the final_url (after redirects) as the URL."""
        collector = self._collector()
        raw = _make_raw_record(
            source_url="https://short.dk/abc",
            final_url="https://www.dr.dk/nyheder/full-article",
        )
        result = collector.normalize(raw)

        assert result["url"] == "https://www.dr.dk/nyheder/full-article"

    def test_normalize_text_content_from_extracted(self) -> None:
        """normalize() maps extracted text to text_content."""
        collector = self._collector()
        raw = _make_raw_record(text_content="Denne tekst er fra artiklen.")
        result = collector.normalize(raw)

        assert result["text_content"] == "Denne tekst er fra artiklen."

    def test_normalize_title_from_extracted(self) -> None:
        """normalize() maps extracted title to title."""
        collector = self._collector()
        raw = _make_raw_record(title="Overskrift om Velfaerd")
        result = collector.normalize(raw)

        assert result["title"] == "Overskrift om Velfaerd"

    def test_normalize_language_from_extracted(self) -> None:
        """normalize() maps extracted language to language."""
        collector = self._collector()
        raw = _make_raw_record(language="da")
        result = collector.normalize(raw)

        assert result["language"] == "da"

    def test_normalize_content_hash_is_64_char_hex(self) -> None:
        """normalize() computes a 64-character hex content_hash."""
        collector = self._collector()
        raw = _make_raw_record()
        result = collector.normalize(raw)

        assert result["content_hash"] is not None
        assert len(result["content_hash"]) == 64
        assert all(c in "0123456789abcdef" for c in result["content_hash"])

    def test_normalize_pseudonymized_author_id_from_domain(self) -> None:
        """normalize() uses the domain as the author, pseudonymized."""
        collector = self._collector()
        raw = _make_raw_record(source_url="https://www.politiken.dk/article")
        result = collector.normalize(raw)

        assert result["pseudonymized_author_id"] is not None
        assert len(result["pseudonymized_author_id"]) == 64

    def test_normalize_author_display_name_is_domain(self) -> None:
        """normalize() sets author_display_name to the extracted domain."""
        normalizer = self._normalizer()
        raw = _make_raw_record(source_url="https://www.politiken.dk/article")
        result = normalize_raw_record(
            normalizer, raw, "url_scraper", "web", Tier.FREE, []
        )

        assert result["author_display_name"] == "politiken.dk"

    def test_normalize_raw_metadata_has_fetch_diagnostics(self) -> None:
        """normalize() embeds fetch diagnostics in raw_metadata."""
        collector = self._collector()
        raw = _make_raw_record(http_status=200)
        result = collector.normalize(raw)

        meta = result["raw_metadata"]
        assert meta["http_status_code"] == 200
        assert meta["extraction_method"] == "trafilatura"
        assert meta["robots_txt_allowed"] is True
        assert meta["needs_playwright"] is False
        assert meta["fetch_duration_ms"] == 450

    def test_normalize_raw_metadata_source_and_final_url(self) -> None:
        """normalize() stores both source and final URL in raw_metadata."""
        collector = self._collector()
        raw = _make_raw_record(
            source_url="https://short.dk/abc",
            final_url="https://www.dr.dk/nyheder/full-article",
        )
        result = collector.normalize(raw)

        meta = result["raw_metadata"]
        assert meta["source_url"] == "https://short.dk/abc"
        assert meta["final_url"] == "https://www.dr.dk/nyheder/full-article"

    def test_normalize_collection_tier_free(self) -> None:
        """normalize() sets collection_tier='free' for FREE tier."""
        collector = self._collector()
        raw = _make_raw_record()
        result = collector.normalize(raw, tier=Tier.FREE)

        assert result["collection_tier"] == "free"

    def test_normalize_collection_tier_medium(self) -> None:
        """normalize() sets collection_tier='medium' for MEDIUM tier."""
        collector = self._collector()
        raw = _make_raw_record()
        result = collector.normalize(raw, tier=Tier.MEDIUM)

        assert result["collection_tier"] == "medium"

    def test_normalize_required_fields_always_present(self) -> None:
        """All required schema fields are present in normalized output."""
        collector = self._collector()
        raw = _make_raw_record()
        result = collector.normalize(raw)

        for field in ("platform", "arena", "content_type", "collected_at", "collection_tier"):
            assert field in result, f"Missing required field: {field}"
            assert result[field] is not None, f"Required field is None: {field}"

    def test_normalize_no_extracted_content_produces_none_text(self) -> None:
        """normalize() returns None text_content when extraction yields nothing."""
        collector = self._collector()
        raw = _make_raw_record()
        raw["extracted"] = None
        result = collector.normalize(raw)

        assert result["text_content"] is None

    def test_normalize_media_urls_always_empty(self) -> None:
        """normalize() always sets media_urls to empty list for web pages."""
        collector = self._collector()
        raw = _make_raw_record()
        result = collector.normalize(raw)

        assert result["media_urls"] == []

    @pytest.mark.parametrize("char", ["ae", "oe", "aa", "AE", "OE", "AA"])
    def test_normalize_preserves_danish_transliterated_chars_in_text(self, char: str) -> None:
        """Danish transliterated character sequences survive normalize()."""
        collector = self._collector()
        raw = _make_raw_record(text_content=f"Artikel med {char} tegn i teksten.")
        result = collector.normalize(raw)

        assert char in result["text_content"]

    def test_normalize_preserves_danish_title(self) -> None:
        """Danish characters in the title survive normalize()."""
        collector = self._collector()
        raw = _make_raw_record(title="Koebenhavn og Aalborg diskuterer velfaerd")
        result = collector.normalize(raw)

        assert result["title"] == "Koebenhavn og Aalborg diskuterer velfaerd"


# ---------------------------------------------------------------------------
# _make_failure_record() unit tests
# ---------------------------------------------------------------------------


class TestMakeFailureRecord:
    def test_failure_record_has_fetch_failed_flag(self) -> None:
        """_make_failure_record() sets _fetch_failed=True."""
        record = _make_failure_record(
            source_url="https://example.dk/broken",
            final_url="https://example.dk/broken",
            http_status=500,
            fetch_error="Internal Server Error",
            robots_txt_allowed=True,
            needs_playwright=False,
            fetch_duration_ms=100,
        )

        assert record["_fetch_failed"] is True
        assert record["html"] is None
        assert record["extracted"] is None
        assert record["http_status"] == 500
        assert record["fetch_error"] == "Internal Server Error"

    def test_failure_record_robots_blocked(self) -> None:
        """_make_failure_record() records robots.txt block."""
        record = _make_failure_record(
            source_url="https://example.dk/secret",
            final_url="https://example.dk/secret",
            http_status=None,
            fetch_error="robots.txt disallowed",
            robots_txt_allowed=False,
            needs_playwright=False,
            fetch_duration_ms=50,
        )

        assert record["robots_txt_allowed"] is False


# ---------------------------------------------------------------------------
# collect_by_terms() integration tests
# ---------------------------------------------------------------------------


class TestCollectByTerms:
    @pytest.mark.asyncio
    async def test_collect_by_terms_returns_matching_records(self) -> None:
        """collect_by_terms() returns records for URLs where terms match."""
        collector = UrlScraperCollector()

        fetch_result = _make_fetch_result(
            html="<html><body>Dansk klimapolitik diskuteres i Folketinget</body></html>",
            final_url="https://www.dr.dk/nyheder/klima-artikel",
        )

        extracted = ExtractedContent(
            text="Dansk klimapolitik diskuteres i Folketinget",
            title="Klimapolitik i Danmark",
            language="da",
        )

        with patch(
            "issue_observatory.arenas.web.url_scraper.collector.fetch_url",
            new=AsyncMock(return_value=fetch_result),
        ), patch(
            "issue_observatory.arenas.web.url_scraper.collector.extract_from_html",
            return_value=extracted,
        ):
            records = await collector.collect_by_terms(
                terms=["klimapolitik"],
                tier=Tier.FREE,
                max_results=10,
                extra_urls=["https://www.dr.dk/nyheder/klima-artikel"],
            )

        assert isinstance(records, list)
        assert len(records) == 1
        assert records[0]["platform"] == "url_scraper"
        assert records[0]["arena"] == "web"
        assert records[0]["content_type"] == "web_page"

    @pytest.mark.asyncio
    async def test_collect_by_terms_no_urls_returns_empty(self) -> None:
        """collect_by_terms() returns [] when extra_urls is None."""
        collector = UrlScraperCollector()
        records = await collector.collect_by_terms(
            terms=["test"],
            tier=Tier.FREE,
            max_results=10,
            extra_urls=None,
        )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_empty_urls_returns_empty(self) -> None:
        """collect_by_terms() returns [] when extra_urls is empty list."""
        collector = UrlScraperCollector()
        records = await collector.collect_by_terms(
            terms=["test"],
            tier=Tier.FREE,
            max_results=10,
            extra_urls=[],
        )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_no_matching_terms_returns_empty(self) -> None:
        """collect_by_terms() returns [] when extracted text does not match terms."""
        collector = UrlScraperCollector()

        fetch_result = _make_fetch_result(
            html="<html><body>An article about sports</body></html>",
            final_url="https://www.dr.dk/sport/article",
        )

        extracted = ExtractedContent(
            text="An article about sports and football",
            title="Sports News",
            language="en",
        )

        with patch(
            "issue_observatory.arenas.web.url_scraper.collector.fetch_url",
            new=AsyncMock(return_value=fetch_result),
        ), patch(
            "issue_observatory.arenas.web.url_scraper.collector.extract_from_html",
            return_value=extracted,
        ):
            records = await collector.collect_by_terms(
                terms=["klimapolitik"],
                tier=Tier.FREE,
                max_results=10,
                extra_urls=["https://www.dr.dk/sport/article"],
            )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_boolean_term_groups(self) -> None:
        """collect_by_terms() supports boolean AND/OR term groups."""
        collector = UrlScraperCollector()

        fetch_result = _make_fetch_result(
            html="<html><body>Dansk klimapolitik og energi</body></html>",
            final_url="https://www.dr.dk/nyheder/klima",
        )

        extracted = ExtractedContent(
            text="Dansk klimapolitik og energi er vigtige emner",
            title="Klimapolitik",
            language="da",
        )

        with patch(
            "issue_observatory.arenas.web.url_scraper.collector.fetch_url",
            new=AsyncMock(return_value=fetch_result),
        ), patch(
            "issue_observatory.arenas.web.url_scraper.collector.extract_from_html",
            return_value=extracted,
        ):
            # AND group: both "klimapolitik" AND "energi" must be present
            records = await collector.collect_by_terms(
                terms=[],
                tier=Tier.FREE,
                max_results=10,
                extra_urls=["https://www.dr.dk/nyheder/klima"],
                term_groups=[["klimapolitik", "energi"]],
            )

        assert len(records) == 1

    @pytest.mark.asyncio
    async def test_collect_by_terms_failed_fetch_skipped(self) -> None:
        """collect_by_terms() skips URLs that fail to fetch."""
        collector = UrlScraperCollector()

        fetch_result = _make_fetch_result(
            html=None,
            status_code=500,
            final_url="https://broken.dk/page",
            error="Internal Server Error",
        )

        with patch(
            "issue_observatory.arenas.web.url_scraper.collector.fetch_url",
            new=AsyncMock(return_value=fetch_result),
        ):
            records = await collector.collect_by_terms(
                terms=["test"],
                tier=Tier.FREE,
                max_results=10,
                extra_urls=["https://broken.dk/page"],
            )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_max_results_caps_output(self) -> None:
        """collect_by_terms() respects max_results cap."""
        collector = UrlScraperCollector()

        async def mock_fetch(url, **kwargs):
            return _make_fetch_result(
                html=f"<html><body>Content about klimapolitik from {url}</body></html>",
                final_url=url,
            )

        extracted = ExtractedContent(
            text="Content about klimapolitik",
            title="Article",
            language="da",
        )

        with patch(
            "issue_observatory.arenas.web.url_scraper.collector.fetch_url",
            new=AsyncMock(side_effect=mock_fetch),
        ), patch(
            "issue_observatory.arenas.web.url_scraper.collector.extract_from_html",
            return_value=extracted,
        ):
            records = await collector.collect_by_terms(
                terms=["klimapolitik"],
                tier=Tier.FREE,
                max_results=1,
                extra_urls=[
                    "https://dr.dk/article1",
                    "https://politiken.dk/article2",
                ],
            )

        assert len(records) <= 1

    @pytest.mark.asyncio
    async def test_collect_by_terms_danish_text_preserved(self) -> None:
        """Danish text in fetched pages survives the full collect pipeline."""
        collector = UrlScraperCollector()
        danish_text = "Koebenhavn og Aalborg diskuterer velfaerd og uddannelse"

        fetch_result = _make_fetch_result(
            html=f"<html><body>{danish_text}</body></html>",
            final_url="https://www.dr.dk/nyheder/article",
        )

        extracted = ExtractedContent(
            text=danish_text,
            title="Velfaerd i Danmark",
            language="da",
        )

        with patch(
            "issue_observatory.arenas.web.url_scraper.collector.fetch_url",
            new=AsyncMock(return_value=fetch_result),
        ), patch(
            "issue_observatory.arenas.web.url_scraper.collector.extract_from_html",
            return_value=extracted,
        ):
            records = await collector.collect_by_terms(
                terms=["velfaerd"],
                tier=Tier.FREE,
                max_results=10,
                extra_urls=["https://www.dr.dk/nyheder/article"],
            )

        assert len(records) == 1
        assert "velfaerd" in records[0]["text_content"]


# ---------------------------------------------------------------------------
# collect_by_actors() tests
# ---------------------------------------------------------------------------


class TestCollectByActors:
    @pytest.mark.asyncio
    async def test_collect_by_actors_empty_actor_ids_returns_empty(self) -> None:
        """collect_by_actors() returns [] when actor_ids is empty."""
        collector = UrlScraperCollector()
        records = await collector.collect_by_actors(
            actor_ids=[],
            tier=Tier.FREE,
            max_results=10,
        )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_actors_fetches_actor_base_url(self) -> None:
        """collect_by_actors() fetches the actor's base URL when no extra_urls match."""
        collector = UrlScraperCollector()
        actor_url = "https://www.dr.dk"

        fetch_result = _make_fetch_result(
            html="<html><body>DR Nyheder forside</body></html>",
            final_url="https://www.dr.dk",
        )

        extracted = ExtractedContent(
            text="DR Nyheder forside med seneste nyheder",
            title="DR Nyheder",
            language="da",
        )

        with patch(
            "issue_observatory.arenas.web.url_scraper.collector.fetch_url",
            new=AsyncMock(return_value=fetch_result),
        ), patch(
            "issue_observatory.arenas.web.url_scraper.collector.extract_from_html",
            return_value=extracted,
        ):
            records = await collector.collect_by_actors(
                actor_ids=[actor_url],
                tier=Tier.FREE,
                max_results=10,
            )

        assert len(records) == 1
        assert records[0]["platform"] == "url_scraper"

    @pytest.mark.asyncio
    async def test_collect_by_actors_filters_extra_urls_by_domain(self) -> None:
        """collect_by_actors() filters extra_urls by actor domain match."""
        collector = UrlScraperCollector()

        async def mock_fetch(url, **kwargs):
            return _make_fetch_result(
                html=f"<html><body>Content from {url}</body></html>",
                final_url=url,
            )

        extracted = ExtractedContent(
            text="Content from the page",
            title="Page Title",
            language="da",
        )

        with patch(
            "issue_observatory.arenas.web.url_scraper.collector.fetch_url",
            new=AsyncMock(side_effect=mock_fetch),
        ), patch(
            "issue_observatory.arenas.web.url_scraper.collector.extract_from_html",
            return_value=extracted,
        ):
            records = await collector.collect_by_actors(
                actor_ids=["https://www.dr.dk"],
                tier=Tier.FREE,
                max_results=10,
                extra_urls=[
                    "https://www.dr.dk/nyheder/article1",
                    "https://www.dr.dk/nyheder/article2",
                    "https://www.politiken.dk/article3",  # Different domain -- excluded
                ],
            )

        # Only dr.dk URLs should be fetched (2 matches)
        assert len(records) == 2

    @pytest.mark.asyncio
    async def test_collect_by_actors_failed_fetch_skipped(self) -> None:
        """collect_by_actors() skips URLs that fail to fetch."""
        collector = UrlScraperCollector()

        fetch_result = _make_fetch_result(
            html=None,
            status_code=404,
            final_url="https://example.dk/gone",
            error="Not Found",
        )

        with patch(
            "issue_observatory.arenas.web.url_scraper.collector.fetch_url",
            new=AsyncMock(return_value=fetch_result),
        ):
            records = await collector.collect_by_actors(
                actor_ids=["https://example.dk"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert records == []


# ---------------------------------------------------------------------------
# Tier validation tests
# ---------------------------------------------------------------------------


class TestTierValidation:
    def test_supported_tiers_contains_free_and_medium(self) -> None:
        """UrlScraperCollector.supported_tiers contains [Tier.FREE, Tier.MEDIUM]."""
        collector = UrlScraperCollector()
        assert Tier.FREE in collector.supported_tiers
        assert Tier.MEDIUM in collector.supported_tiers

    def test_get_tier_config_free_returns_config(self) -> None:
        """get_tier_config(Tier.FREE) returns a TierConfig with 100 max results."""
        collector = UrlScraperCollector()
        config = collector.get_tier_config(Tier.FREE)

        assert config is not None
        assert config.max_results_per_run == 100
        assert config.requires_credential is False

    def test_get_tier_config_medium_returns_config(self) -> None:
        """get_tier_config(Tier.MEDIUM) returns a TierConfig with 500 max results."""
        collector = UrlScraperCollector()
        config = collector.get_tier_config(Tier.MEDIUM)

        assert config is not None
        assert config.max_results_per_run == 500

    def test_get_tier_config_premium_raises_value_error(self) -> None:
        """get_tier_config(Tier.PREMIUM) raises ValueError."""
        collector = UrlScraperCollector()
        with pytest.raises(ValueError, match="Unknown tier"):
            collector.get_tier_config(Tier.PREMIUM)

    @pytest.mark.asyncio
    async def test_collect_by_terms_unsupported_tier_raises_value_error(self) -> None:
        """collect_by_terms() raises ValueError when PREMIUM tier is passed."""
        collector = UrlScraperCollector()
        with pytest.raises(ValueError, match="not supported"):
            await collector.collect_by_terms(
                terms=["test"],
                tier=Tier.PREMIUM,
                max_results=5,
                extra_urls=["https://example.dk/page"],
            )


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_ok_on_successful_fetch(self) -> None:
        """health_check() returns status='ok' when fetch and extraction succeed."""
        collector = UrlScraperCollector()

        fetch_result = _make_fetch_result(
            html="<html><body>DR Nyheder indhold</body></html>",
            final_url="https://www.dr.dk/",
        )

        extracted = ExtractedContent(
            text="DR Nyheder indhold fra forsiden",
            title="DR Nyheder",
            language="da",
        )

        with patch(
            "issue_observatory.arenas.web.url_scraper.collector.fetch_url",
            new=AsyncMock(return_value=fetch_result),
        ), patch(
            "issue_observatory.arenas.web.url_scraper.collector.extract_from_html",
            return_value=extracted,
        ):
            result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "web"
        assert result["platform"] == "url_scraper"
        assert "checked_at" in result
        assert result["scraper_module"] == "available"
        assert result["extracted_chars"] > 0

    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_on_fetch_error(self) -> None:
        """health_check() returns status='degraded' when fetch returns an error."""
        collector = UrlScraperCollector()

        fetch_result = _make_fetch_result(
            html=None,
            status_code=503,
            final_url="https://www.dr.dk/",
            error="Service Unavailable",
        )

        with patch(
            "issue_observatory.arenas.web.url_scraper.collector.fetch_url",
            new=AsyncMock(return_value=fetch_result),
        ):
            result = await collector.health_check()

        assert result["status"] == "degraded"
        assert result["scraper_module"] == "available"

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_exception(self) -> None:
        """health_check() returns status='down' when fetch raises an exception."""
        collector = UrlScraperCollector()

        with patch(
            "issue_observatory.arenas.web.url_scraper.collector.fetch_url",
            new=AsyncMock(side_effect=Exception("Connection refused")),
        ):
            result = await collector.health_check()

        assert result["status"] == "down"
        assert "Connection refused" in result["detail"]

    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_on_empty_extraction(self) -> None:
        """health_check() returns status='degraded' when extraction yields no text."""
        collector = UrlScraperCollector()

        fetch_result = _make_fetch_result(
            html="<html><body></body></html>",
            final_url="https://www.dr.dk/",
        )

        extracted = ExtractedContent(text=None, title=None, language=None)

        with patch(
            "issue_observatory.arenas.web.url_scraper.collector.fetch_url",
            new=AsyncMock(return_value=fetch_result),
        ), patch(
            "issue_observatory.arenas.web.url_scraper.collector.extract_from_html",
            return_value=extracted,
        ):
            result = await collector.health_check()

        assert result["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_health_check_always_has_arena_platform_checked_at(self) -> None:
        """health_check() always includes arena, platform, and checked_at."""
        collector = UrlScraperCollector()

        with patch(
            "issue_observatory.arenas.web.url_scraper.collector.fetch_url",
            new=AsyncMock(side_effect=Exception("test")),
        ):
            result = await collector.health_check()

        assert result["arena"] == "web"
        assert result["platform"] == "url_scraper"
        assert "checked_at" in result
