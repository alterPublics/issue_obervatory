"""Tests for the Wikipedia arena collector.

Covers:
- Config validation: WIKIPEDIA_TIERS, DEFAULT_WIKI_PROJECTS, DEFAULT_USER_AGENT
- Collector construction: arena_name, platform_name, supported_tiers
- normalize() for wiki_revision records: platform_id format, content_type, language
  detection, talk-page flag, bot-edit filtering, Danish character preservation
- normalize() for wiki_pageview records: platform_id format, content_type, views_count,
  null author fields
- collect_by_terms() with mocked httpx: search -> revisions -> pageviews pipeline,
  deduplication, date filtering, max_results cap, empty results, rate-limit handling
- collect_by_actors() with mocked httpx: usercontribs pipeline, date filtering
- health_check(): ok on siteinfo response, down on HTTP error and connection error
- get_tier_config(): correct TierConfig for FREE, ValueError for unsupported tier
- _make_headers(): User-Agent key present and contains "IssueObservatory"
- Module-level helpers: _is_bot_edit(), _to_mediawiki_timestamp(),
  _resolve_pageview_date_range()

These tests run without a live database or network connection.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# Env bootstrap — must run before any application imports so that modules
# that read env vars at import time see the test values.
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault(
    "CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA=="
)

from issue_observatory.arenas.base import Tier  # noqa: E402
from issue_observatory.arenas.wikipedia.collector import (  # noqa: E402
    WikipediaCollector,
    _is_bot_edit,
    _resolve_pageview_date_range,
    _to_mediawiki_timestamp,
)
from issue_observatory.arenas.wikipedia.config import (  # noqa: E402
    DEFAULT_USER_AGENT,
    DEFAULT_WIKI_PROJECTS,
    WIKIPEDIA_TIERS,
)
from issue_observatory.core.exceptions import (  # noqa: E402
    ArenaCollectionError,
    ArenaRateLimitError,
)


# ---------------------------------------------------------------------------
# Shared raw-record builder helpers
# ---------------------------------------------------------------------------


def _make_raw_revision(
    wiki_project: str = "da.wikipedia",
    rev_id: int = 98765,
    page_title: str = "CO2-afgift",
    page_id: int = 12345,
    namespace: int = 0,
    user: str = "TestEditor",
    timestamp: str = "2026-02-17T12:00:00Z",
    comment: str | None = "Updated statistics",
    size: int = 5432,
    parent_size: int = 5400,
    tags: list[str] | None = None,
    is_minor: bool = False,
) -> dict[str, Any]:
    """Build an intermediate wiki_revision dict as produced by _get_revisions()."""
    language = "da" if wiki_project.startswith("da") else "en"
    platform_id = f"{wiki_project}:rev:{rev_id}"
    rev_url = f"https://{wiki_project}.org/w/index.php?oldid={rev_id}"
    return {
        "_record_type": "wiki_revision",
        "_wiki_project": wiki_project,
        "platform_id": platform_id,
        "platform": "wikipedia",
        "arena": "reference",
        "content_type": "wiki_revision",
        "title": page_title,
        "url": rev_url,
        "language": language,
        "published_at": timestamp,
        "text_content": comment,
        "author_platform_id": user,
        "author_display_name": user,
        "views_count": None,
        "likes_count": None,
        "shares_count": None,
        "comments_count": None,
        "delta": size - parent_size,
        "minor": is_minor,
        "tags": tags if tags is not None else [],
        "parentid": rev_id - 1,
        "namespace": namespace,
        "is_talk_page": namespace == 1,
        "wiki_project": wiki_project,
        "page_id": page_id,
    }


def _make_raw_pageview(
    wiki_project: str = "da.wikipedia",
    article: str = "CO2-afgift",
    date_str: str = "2026-02-17",
    views: int = 1234,
) -> dict[str, Any]:
    """Build an intermediate wiki_pageview dict as produced by _get_pageviews()."""
    language = "da" if wiki_project.startswith("da") else "en"
    platform_id = f"{wiki_project}:pv:{article}:{date_str}"
    article_url = f"https://{wiki_project}.org/wiki/{article.replace(' ', '_')}"
    return {
        "_record_type": "wiki_pageview",
        "_wiki_project": wiki_project,
        "platform_id": platform_id,
        "platform": "wikipedia",
        "arena": "reference",
        "content_type": "wiki_pageview",
        "title": article,
        "url": article_url,
        "language": language,
        "published_at": date_str,
        "text_content": None,
        "author_platform_id": None,
        "author_display_name": None,
        "views_count": views,
        "likes_count": None,
        "shares_count": None,
        "comments_count": None,
        "access": "all-access",
        "agent": "user",
        "wiki_project": wiki_project,
    }


# ---------------------------------------------------------------------------
# MediaWiki API response fixtures
# ---------------------------------------------------------------------------

SEARCH_RESPONSE: dict[str, Any] = {
    "query": {
        "search": [
            {"title": "CO2-afgift", "pageid": 12345},
        ]
    }
}

SEARCH_EMPTY_RESPONSE: dict[str, Any] = {
    "query": {
        "search": []
    }
}

REVISIONS_RESPONSE: dict[str, Any] = {
    "query": {
        "pages": {
            "12345": {
                "title": "CO2-afgift",
                "pageid": 12345,
                "ns": 0,
                "revisions": [
                    {
                        "revid": 98765,
                        "parentid": 98764,
                        "user": "TestEditor",
                        "timestamp": "2026-02-17T12:00:00Z",
                        "comment": "Updated statistics",
                        "size": 5432,
                        "tags": [],
                        "minor": False,
                    }
                ],
            }
        }
    }
}

PAGEVIEWS_RESPONSE: dict[str, Any] = {
    "items": [
        {
            "article": "CO2-afgift",
            "timestamp": "2026021700",
            "access": "all-access",
            "agent": "user",
            "views": 1234,
        }
    ]
}

USERCONTRIBS_RESPONSE: dict[str, Any] = {
    "query": {
        "usercontribs": [
            {
                "revid": 11111,
                "parentid": 11110,
                "user": "JohnEditor",
                "ns": 0,
                "title": "Klimaaftale",
                "timestamp": "2026-02-15T10:00:00Z",
                "comment": "Fixed typo",
                "size": 3210,
                "tags": [],
                "minor": False,
            }
        ]
    },
    "continue": None,
}

SITEINFO_RESPONSE: dict[str, Any] = {
    "query": {
        "general": {
            "sitename": "Wikipedia",
            "lang": "da",
        }
    }
}


# ---------------------------------------------------------------------------
# Async HTTP client mock helpers
#
# WikipediaCollector._api_get() calls asyncio.sleep() after each request as
# a courtesy rate-limit delay.  We patch asyncio.sleep throughout to keep
# the test suite fast without altering any other behaviour.
# ---------------------------------------------------------------------------


def _make_mock_client(responses: list[dict[str, Any]]) -> MagicMock:
    """Return an async context-manager mock whose GET calls return *responses* in order.

    Each entry in *responses* is served as a JSON payload with status 200.
    The mock supports use as ``async with collector._build_http_client() as client``.
    """
    response_iter = iter(responses)

    async def _fake_get(url, params=None, **kwargs):
        payload = next(response_iter)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = payload
        mock_response.raise_for_status = MagicMock()
        return mock_response

    mock_client = MagicMock()
    mock_client.get = _fake_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


def _make_error_client(status_code: int, headers: dict[str, str] | None = None) -> MagicMock:
    """Return a mock client whose single GET call raises an HTTPStatusError."""

    async def _fake_get(url, params=None, **kwargs):
        mock_request = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.headers = headers or {}
        raise httpx.HTTPStatusError(
            f"HTTP {status_code}",
            request=mock_request,
            response=mock_response,
        )

    mock_client = MagicMock()
    mock_client.get = _fake_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


def _make_connection_error_client() -> MagicMock:
    """Return a mock client whose single GET call raises an httpx.RequestError."""

    async def _fake_get(url, params=None, **kwargs):
        raise httpx.ConnectError("Connection refused")

    mock_client = MagicMock()
    mock_client.get = _fake_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


# ---------------------------------------------------------------------------
# Config validation tests
# ---------------------------------------------------------------------------


class TestConfig:
    def test_wikipedia_tiers_free_requires_no_credential(self) -> None:
        """WIKIPEDIA_TIERS[FREE] must not require a credential — Wikipedia is unauthenticated."""
        tier_config = WIKIPEDIA_TIERS[Tier.FREE]
        assert tier_config.requires_credential is False

    def test_wikipedia_tiers_free_estimated_credits_is_zero(self) -> None:
        """WIKIPEDIA_TIERS[FREE].estimated_credits_per_1k must be 0 (no API cost)."""
        tier_config = WIKIPEDIA_TIERS[Tier.FREE]
        assert tier_config.estimated_credits_per_1k == 0

    def test_wikipedia_tiers_free_tier_field_matches_tier_enum(self) -> None:
        """WIKIPEDIA_TIERS[FREE].tier must equal Tier.FREE."""
        tier_config = WIKIPEDIA_TIERS[Tier.FREE]
        assert tier_config.tier == Tier.FREE

    def test_default_wiki_projects_contains_danish_wikipedia(self) -> None:
        """DEFAULT_WIKI_PROJECTS must include 'da.wikipedia' as the primary project."""
        assert "da.wikipedia" in DEFAULT_WIKI_PROJECTS

    def test_default_wiki_projects_contains_english_wikipedia(self) -> None:
        """DEFAULT_WIKI_PROJECTS must include 'en.wikipedia' for international coverage."""
        assert "en.wikipedia" in DEFAULT_WIKI_PROJECTS

    def test_default_user_agent_contains_issue_observatory(self) -> None:
        """DEFAULT_USER_AGENT must contain 'IssueObservatory' per Wikimedia etiquette policy."""
        assert "IssueObservatory" in DEFAULT_USER_AGENT

    def test_default_user_agent_is_non_empty_string(self) -> None:
        """DEFAULT_USER_AGENT must be a non-empty string."""
        assert isinstance(DEFAULT_USER_AGENT, str)
        assert len(DEFAULT_USER_AGENT) > 0


# ---------------------------------------------------------------------------
# Collector construction tests
# ---------------------------------------------------------------------------


class TestCollectorConstruction:
    def test_instantiates_without_arguments(self) -> None:
        """WikipediaCollector() must instantiate with no arguments (Wikipedia is unauthenticated)."""
        collector = WikipediaCollector()
        assert collector is not None

    def test_arena_name_is_reference(self) -> None:
        """arena_name must equal 'reference' — Wikipedia is an editorial reference source."""
        collector = WikipediaCollector()
        assert collector.arena_name == "reference"

    def test_platform_name_is_wikipedia(self) -> None:
        """platform_name must equal 'wikipedia'."""
        collector = WikipediaCollector()
        assert collector.platform_name == "wikipedia"

    def test_supported_tiers_is_free_only(self) -> None:
        """supported_tiers must be exactly [Tier.FREE] — no paid Wikipedia tier exists."""
        collector = WikipediaCollector()
        assert collector.supported_tiers == [Tier.FREE]

    def test_accepts_injected_http_client(self) -> None:
        """WikipediaCollector accepts an http_client kwarg for test injection."""
        mock_client = MagicMock(spec=httpx.AsyncClient)
        collector = WikipediaCollector(http_client=mock_client)
        assert collector._http_client is mock_client


# ---------------------------------------------------------------------------
# normalize() tests — wiki_revision records
# ---------------------------------------------------------------------------


class TestNormalizeRevision:
    def _collector(self) -> WikipediaCollector:
        return WikipediaCollector()

    def test_normalize_platform_id_format_for_da_revision(self) -> None:
        """normalize() sets platform_id to '{wiki_project}:rev:{revision_id}' for da.wikipedia."""
        collector = self._collector()
        raw = _make_raw_revision(wiki_project="da.wikipedia", rev_id=98765)
        result = collector.normalize(raw)

        assert result["platform_id"] == "da.wikipedia:rev:98765"

    def test_normalize_platform_id_format_for_en_revision(self) -> None:
        """normalize() sets platform_id to 'en.wikipedia:rev:{revision_id}' for en.wikipedia."""
        collector = self._collector()
        raw = _make_raw_revision(wiki_project="en.wikipedia", rev_id=42000)
        result = collector.normalize(raw)

        assert result["platform_id"] == "en.wikipedia:rev:42000"

    def test_normalize_content_type_is_wiki_revision(self) -> None:
        """normalize() sets content_type='wiki_revision' for revision records."""
        collector = self._collector()
        raw = _make_raw_revision()
        result = collector.normalize(raw)

        assert result["content_type"] == "wiki_revision"

    def test_normalize_platform_is_wikipedia(self) -> None:
        """normalize() sets platform='wikipedia' for all revision records."""
        collector = self._collector()
        raw = _make_raw_revision()
        result = collector.normalize(raw)

        assert result["platform"] == "wikipedia"

    def test_normalize_arena_is_reference(self) -> None:
        """normalize() sets arena='reference' for all revision records."""
        collector = self._collector()
        raw = _make_raw_revision()
        result = collector.normalize(raw)

        assert result["arena"] == "reference"

    def test_normalize_language_is_da_for_danish_wikipedia(self) -> None:
        """normalize() sets language='da' when wiki_project is 'da.wikipedia'."""
        collector = self._collector()
        raw = _make_raw_revision(wiki_project="da.wikipedia")
        result = collector.normalize(raw)

        assert result["language"] == "da"

    def test_normalize_language_is_en_for_english_wikipedia(self) -> None:
        """normalize() sets language='en' when wiki_project is 'en.wikipedia'."""
        collector = self._collector()
        raw = _make_raw_revision(wiki_project="en.wikipedia")
        result = collector.normalize(raw)

        assert result["language"] == "en"

    def test_normalize_url_contains_oldid_revision_id(self) -> None:
        """normalize() sets url containing '?oldid={revision_id}' for direct revision linking."""
        collector = self._collector()
        raw = _make_raw_revision(rev_id=98765)
        result = collector.normalize(raw)

        assert "oldid=98765" in result["url"]

    def test_normalize_text_content_maps_to_edit_comment(self) -> None:
        """normalize() maps text_content to the editor's edit summary."""
        collector = self._collector()
        raw = _make_raw_revision(comment="Updated statistics")
        result = collector.normalize(raw)

        assert result["text_content"] == "Updated statistics"

    def test_normalize_empty_comment_produces_none_text_content(self) -> None:
        """normalize() maps an empty/absent edit summary to None for text_content."""
        collector = self._collector()
        raw = _make_raw_revision(comment=None)
        result = collector.normalize(raw)

        assert result["text_content"] is None

    def test_normalize_author_platform_id_is_revision_user(self) -> None:
        """normalize() maps author_platform_id to the revision's user field."""
        collector = self._collector()
        raw = _make_raw_revision(user="TestEditor")
        result = collector.normalize(raw)

        assert result["author_platform_id"] == "TestEditor"

    def test_normalize_raw_metadata_is_talk_page_false_for_ns_zero(self) -> None:
        """normalize() sets raw_metadata.is_talk_page=False for article-namespace (ns=0) edits."""
        collector = self._collector()
        raw = _make_raw_revision(namespace=0)
        result = collector.normalize(raw)

        assert result["raw_metadata"]["is_talk_page"] is False

    def test_normalize_raw_metadata_is_talk_page_true_for_ns_one(self) -> None:
        """normalize() sets raw_metadata.is_talk_page=True for talk-namespace (ns=1) edits."""
        collector = self._collector()
        raw = _make_raw_revision(namespace=1)
        result = collector.normalize(raw)

        assert result["raw_metadata"]["is_talk_page"] is True

    def test_normalize_raw_metadata_wiki_project_preserved(self) -> None:
        """normalize() stores wiki_project in raw_metadata for provenance tracking."""
        collector = self._collector()
        raw = _make_raw_revision(wiki_project="da.wikipedia")
        result = collector.normalize(raw)

        assert result["raw_metadata"]["wiki_project"] == "da.wikipedia"

    def test_normalize_raw_metadata_namespace_preserved(self) -> None:
        """normalize() stores the MediaWiki namespace integer in raw_metadata."""
        collector = self._collector()
        raw = _make_raw_revision(namespace=4)
        result = collector.normalize(raw)

        assert result["raw_metadata"]["namespace"] == 4

    def test_normalize_collection_tier_is_free(self) -> None:
        """normalize() always sets collection_tier='free' — Wikipedia is unauthenticated."""
        collector = self._collector()
        raw = _make_raw_revision()
        result = collector.normalize(raw)

        assert result["collection_tier"] == "free"

    def test_normalize_required_fields_always_present(self) -> None:
        """normalize() output contains all mandatory schema fields with non-None values."""
        collector = self._collector()
        raw = _make_raw_revision()
        result = collector.normalize(raw)

        for field in ("platform", "arena", "content_type", "collected_at", "collection_tier"):
            assert field in result, f"Missing required field: {field}"
            assert result[field] is not None, f"Required field is None: {field}"

    def test_normalize_preserves_danish_title(self) -> None:
        """normalize() preserves Danish characters (æ, ø, å) in the article title."""
        collector = self._collector()
        danish_title = "Grøn omstilling og velfærd i Ålborg"
        raw = _make_raw_revision(page_title=danish_title)
        result = collector.normalize(raw)

        assert result["title"] == danish_title
        assert "ø" in result["title"]
        assert "æ" in result["title"]
        assert "Å" in result["title"]

    def test_normalize_preserves_danish_characters_in_comment(self) -> None:
        """normalize() preserves Danish characters (æ, ø, å) in the edit summary."""
        collector = self._collector()
        danish_comment = "Tilføjet afsnit om CO2-afgifter og grøn omstilling"
        raw = _make_raw_revision(comment=danish_comment)
        result = collector.normalize(raw)

        assert result["text_content"] == danish_comment
        assert "ø" in result["text_content"]

    @pytest.mark.parametrize("char", ["æ", "ø", "å", "Æ", "Ø", "Å"])
    def test_normalize_handles_each_danish_character_in_title(self, char: str) -> None:
        """Each Danish character in article title survives normalize() without error or corruption."""
        collector = self._collector()
        raw = _make_raw_revision(page_title=f"Artikel med {char} tegn")
        result = collector.normalize(raw)

        assert char in result["title"]

    def test_normalize_unknown_record_type_raises_arena_collection_error(self) -> None:
        """normalize() raises ArenaCollectionError for unrecognised _record_type values."""
        collector = self._collector()
        raw = {"_record_type": "wiki_unknown", "_wiki_project": "da.wikipedia"}

        with pytest.raises(ArenaCollectionError):
            collector.normalize(raw)


# ---------------------------------------------------------------------------
# normalize() tests — wiki_pageview records
# ---------------------------------------------------------------------------


class TestNormalizePageview:
    def _collector(self) -> WikipediaCollector:
        return WikipediaCollector()

    def test_normalize_platform_id_format_for_da_pageview(self) -> None:
        """normalize() sets platform_id to '{wiki_project}:pv:{article}:{date}' for pageviews."""
        collector = self._collector()
        raw = _make_raw_pageview(
            wiki_project="da.wikipedia", article="CO2-afgift", date_str="2026-02-17"
        )
        result = collector.normalize(raw)

        assert result["platform_id"] == "da.wikipedia:pv:CO2-afgift:2026-02-17"

    def test_normalize_content_type_is_wiki_pageview(self) -> None:
        """normalize() sets content_type='wiki_pageview' for pageview records."""
        collector = self._collector()
        raw = _make_raw_pageview()
        result = collector.normalize(raw)

        assert result["content_type"] == "wiki_pageview"

    def test_normalize_pageview_text_content_is_none(self) -> None:
        """normalize() sets text_content=None for pageview records — no textual content."""
        collector = self._collector()
        raw = _make_raw_pageview()
        result = collector.normalize(raw)

        assert result["text_content"] is None

    def test_normalize_pageview_author_platform_id_is_none(self) -> None:
        """normalize() sets author_platform_id=None for pageview records — no single author."""
        collector = self._collector()
        raw = _make_raw_pageview()
        result = collector.normalize(raw)

        assert result["author_platform_id"] is None

    def test_normalize_pageview_views_count_set_to_pageview_count(self) -> None:
        """normalize() maps views_count to the daily pageview integer from the API."""
        collector = self._collector()
        raw = _make_raw_pageview(views=1234)
        result = collector.normalize(raw)

        assert result["views_count"] == 1234

    def test_normalize_pageview_language_da_for_danish_project(self) -> None:
        """normalize() sets language='da' for da.wikipedia pageview records."""
        collector = self._collector()
        raw = _make_raw_pageview(wiki_project="da.wikipedia")
        result = collector.normalize(raw)

        assert result["language"] == "da"

    def test_normalize_pageview_language_en_for_english_project(self) -> None:
        """normalize() sets language='en' for en.wikipedia pageview records."""
        collector = self._collector()
        raw = _make_raw_pageview(wiki_project="en.wikipedia")
        result = collector.normalize(raw)

        assert result["language"] == "en"

    def test_normalize_pageview_raw_metadata_contains_access_and_agent(self) -> None:
        """normalize() stores Wikimedia API access/agent parameters in raw_metadata."""
        collector = self._collector()
        raw = _make_raw_pageview()
        result = collector.normalize(raw)

        assert result["raw_metadata"]["access"] == "all-access"
        assert result["raw_metadata"]["agent"] == "user"

    def test_normalize_pageview_preserves_danish_article_title(self) -> None:
        """normalize() preserves Danish characters in pageview article titles."""
        collector = self._collector()
        danish_article = "Grøn omstilling"
        raw = _make_raw_pageview(article=danish_article)
        result = collector.normalize(raw)

        assert result["title"] == danish_article
        assert "ø" in result["title"]

    def test_normalize_pageview_collection_tier_is_free(self) -> None:
        """normalize() sets collection_tier='free' for pageview records."""
        collector = self._collector()
        raw = _make_raw_pageview()
        result = collector.normalize(raw)

        assert result["collection_tier"] == "free"


# ---------------------------------------------------------------------------
# Bot-edit filtering tests (_is_bot_edit helper)
# ---------------------------------------------------------------------------


class TestIsBotEdit:
    def test_is_bot_edit_returns_false_for_human_edit_with_empty_tags(self) -> None:
        """_is_bot_edit() returns False when the revision has an empty tags list."""
        rev = {"tags": [], "user": "HumanEditor"}
        assert _is_bot_edit(rev) is False

    def test_is_bot_edit_returns_true_for_mw_bot_tag(self) -> None:
        """_is_bot_edit() returns True when tags contains a 'mw-bot' tag."""
        rev = {"tags": ["mw-bot"], "user": "SomeBot"}
        assert _is_bot_edit(rev) is True

    def test_is_bot_edit_returns_true_for_case_insensitive_bot_tag(self) -> None:
        """_is_bot_edit() is case-insensitive — 'Bot', 'BOT', 'bot' all trigger True."""
        for tag in ["Bot", "BOT", "bot-edit"]:
            rev = {"tags": [tag]}
            assert _is_bot_edit(rev) is True, f"Expected True for tag '{tag}'"

    def test_is_bot_edit_returns_true_for_oauth_cid_tag(self) -> None:
        """_is_bot_edit() returns True when tags contains an 'OAuth CID:...' prefix tag."""
        rev = {"tags": ["OAuth CID:12345"], "user": "SomeApp"}
        assert _is_bot_edit(rev) is True

    def test_is_bot_edit_returns_false_when_tags_key_absent(self) -> None:
        """_is_bot_edit() returns False gracefully when 'tags' key is absent from dict."""
        rev = {"user": "HumanEditor"}
        assert _is_bot_edit(rev) is False

    def test_is_bot_edit_returns_false_for_unrelated_tags(self) -> None:
        """_is_bot_edit() returns False for revision tags that contain no bot markers."""
        rev = {"tags": ["mobile edit", "mobile web edit"], "user": "MobileEditor"}
        assert _is_bot_edit(rev) is False


# ---------------------------------------------------------------------------
# _to_mediawiki_timestamp helper tests
# ---------------------------------------------------------------------------


class TestToMediawikiTimestamp:
    def test_returns_none_for_none_input(self) -> None:
        """_to_mediawiki_timestamp(None) returns None."""
        assert _to_mediawiki_timestamp(None) is None

    def test_converts_datetime_with_utc_timezone(self) -> None:
        """_to_mediawiki_timestamp() formats timezone-aware datetime to ISO 8601 with Z suffix."""
        dt = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)
        result = _to_mediawiki_timestamp(dt)
        assert result == "2026-02-17T12:00:00Z"

    def test_converts_naive_datetime_treating_as_utc(self) -> None:
        """_to_mediawiki_timestamp() treats naive datetime as UTC and appends Z suffix."""
        dt = datetime(2026, 2, 17, 12, 0, 0)  # naive
        result = _to_mediawiki_timestamp(dt)
        assert result == "2026-02-17T12:00:00Z"

    def test_converts_date_only_string_to_full_timestamp(self) -> None:
        """_to_mediawiki_timestamp() pads 'YYYY-MM-DD' strings to 'YYYY-MM-DDT00:00:00Z'."""
        result = _to_mediawiki_timestamp("2026-02-17")
        assert result == "2026-02-17T00:00:00Z"

    def test_passes_through_full_iso_string_ending_with_z(self) -> None:
        """_to_mediawiki_timestamp() returns full ISO 8601 strings ending with Z unchanged."""
        ts = "2026-02-17T12:00:00Z"
        result = _to_mediawiki_timestamp(ts)
        assert result == ts

    def test_returns_none_for_empty_string(self) -> None:
        """_to_mediawiki_timestamp('') returns None."""
        assert _to_mediawiki_timestamp("") is None


# ---------------------------------------------------------------------------
# _resolve_pageview_date_range helper tests
# ---------------------------------------------------------------------------


class TestResolvePageviewDateRange:
    def test_uses_provided_dates_when_both_supplied(self) -> None:
        """_resolve_pageview_date_range() uses caller-provided start and end dates."""
        start, end = _resolve_pageview_date_range("2026-01-01", "2026-01-31")
        assert start == "20260101"
        assert end == "20260131"

    def test_defaults_when_both_dates_are_none(self) -> None:
        """_resolve_pageview_date_range() returns YYYYMMDD strings when both dates are None."""
        start, end = _resolve_pageview_date_range(None, None)
        assert len(start) == 8
        assert len(end) == 8
        assert start.isdigit()
        assert end.isdigit()

    def test_start_date_is_30_days_before_end_when_only_end_supplied(self) -> None:
        """_resolve_pageview_date_range() defaults start to 30 days before supplied end."""
        start, end = _resolve_pageview_date_range(None, "2026-02-17")
        assert end == "20260217"
        assert start == "20260118"  # 30 days before 2026-02-17

    def test_accepts_datetime_objects(self) -> None:
        """_resolve_pageview_date_range() accepts datetime objects in addition to strings."""
        from datetime import timedelta

        dt_from = datetime(2026, 1, 15, tzinfo=timezone.utc)
        dt_to = datetime(2026, 1, 31, tzinfo=timezone.utc)
        start, end = _resolve_pageview_date_range(dt_from, dt_to)
        assert start == "20260115"
        assert end == "20260131"


# ---------------------------------------------------------------------------
# get_tier_config() tests
# ---------------------------------------------------------------------------


class TestGetTierConfig:
    def test_returns_tier_config_for_free_tier(self) -> None:
        """get_tier_config(Tier.FREE) returns the FREE TierConfig without error."""
        from issue_observatory.config.tiers import TierConfig

        collector = WikipediaCollector()
        config = collector.get_tier_config(Tier.FREE)

        assert isinstance(config, TierConfig)
        assert config.tier == Tier.FREE

    def test_raises_value_error_for_medium_tier(self) -> None:
        """get_tier_config(Tier.MEDIUM) raises ValueError — Wikipedia has no MEDIUM tier."""
        collector = WikipediaCollector()
        with pytest.raises(ValueError, match="Unknown tier"):
            collector.get_tier_config(Tier.MEDIUM)

    def test_raises_value_error_for_premium_tier(self) -> None:
        """get_tier_config(Tier.PREMIUM) raises ValueError — Wikipedia has no PREMIUM tier."""
        collector = WikipediaCollector()
        with pytest.raises(ValueError, match="Unknown tier"):
            collector.get_tier_config(Tier.PREMIUM)


# ---------------------------------------------------------------------------
# _make_headers() tests
# ---------------------------------------------------------------------------


class TestMakeHeaders:
    def test_make_headers_returns_dict_with_user_agent_key(self) -> None:
        """_make_headers() returns a dict containing a 'User-Agent' key."""
        collector = WikipediaCollector()
        headers = collector._make_headers()

        assert isinstance(headers, dict)
        assert "User-Agent" in headers

    def test_make_headers_user_agent_contains_issue_observatory(self) -> None:
        """_make_headers() User-Agent value contains 'IssueObservatory'."""
        collector = WikipediaCollector()
        headers = collector._make_headers()

        assert "IssueObservatory" in headers["User-Agent"]

    def test_make_headers_user_agent_is_non_empty_string(self) -> None:
        """_make_headers() User-Agent value is a non-empty string."""
        collector = WikipediaCollector()
        headers = collector._make_headers()

        assert isinstance(headers["User-Agent"], str)
        assert len(headers["User-Agent"]) > 0


# ---------------------------------------------------------------------------
# _resolve_wiki_projects() tests
# ---------------------------------------------------------------------------


class TestResolveWikiProjects:
    def test_returns_both_projects_when_language_filter_is_none(self) -> None:
        """_resolve_wiki_projects(None) returns all DEFAULT_WIKI_PROJECTS."""
        collector = WikipediaCollector()
        projects = collector._resolve_wiki_projects(None)

        assert "da.wikipedia" in projects
        assert "en.wikipedia" in projects

    def test_returns_only_da_when_language_filter_is_da(self) -> None:
        """_resolve_wiki_projects(['da']) returns only 'da.wikipedia'."""
        collector = WikipediaCollector()
        projects = collector._resolve_wiki_projects(["da"])

        assert projects == ["da.wikipedia"]

    def test_returns_only_en_when_language_filter_is_en(self) -> None:
        """_resolve_wiki_projects(['en']) returns only 'en.wikipedia'."""
        collector = WikipediaCollector()
        projects = collector._resolve_wiki_projects(["en"])

        assert projects == ["en.wikipedia"]

    def test_returns_both_when_language_filter_contains_da_and_en(self) -> None:
        """_resolve_wiki_projects(['da', 'en']) returns both projects."""
        collector = WikipediaCollector()
        projects = collector._resolve_wiki_projects(["da", "en"])

        assert "da.wikipedia" in projects
        assert "en.wikipedia" in projects

    def test_falls_back_to_defaults_for_unknown_language_filter(self) -> None:
        """_resolve_wiki_projects(['fr']) falls back to DEFAULT_WIKI_PROJECTS when no match."""
        collector = WikipediaCollector()
        projects = collector._resolve_wiki_projects(["fr"])

        # Filter produced no matches — should fall back to defaults
        assert len(projects) > 0
        assert projects == list(DEFAULT_WIKI_PROJECTS)


# ---------------------------------------------------------------------------
# collect_by_terms() integration tests with mocked HTTP
# ---------------------------------------------------------------------------


class TestCollectByTerms:
    @pytest.mark.asyncio
    async def test_collect_by_terms_returns_normalized_records(self) -> None:
        """collect_by_terms() returns normalized wiki_revision records for a search term."""
        # Sequence: search (da), revisions (da), pageviews (da),
        #           search (en), revisions (en), pageviews (en)
        mock_client = _make_mock_client([
            SEARCH_RESPONSE,        # da search
            REVISIONS_RESPONSE,     # da revisions
            PAGEVIEWS_RESPONSE,     # da pageviews
            SEARCH_EMPTY_RESPONSE,  # en search (no results)
        ])

        collector = WikipediaCollector(http_client=mock_client)

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            records = await collector.collect_by_terms(
                terms=["CO2-afgift"], tier=Tier.FREE, max_results=50
            )

        assert isinstance(records, list)
        assert len(records) >= 1
        revision_records = [r for r in records if r["content_type"] == "wiki_revision"]
        assert len(revision_records) >= 1
        assert revision_records[0]["platform"] == "wikipedia"
        assert revision_records[0]["arena"] == "reference"

    @pytest.mark.asyncio
    async def test_collect_by_terms_empty_search_returns_empty_list(self) -> None:
        """collect_by_terms() returns [] when the search API returns no articles."""
        mock_client = _make_mock_client([
            SEARCH_EMPTY_RESPONSE,  # da search: no results
            SEARCH_EMPTY_RESPONSE,  # en search: no results
        ])

        collector = WikipediaCollector(http_client=mock_client)

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            records = await collector.collect_by_terms(
                terms=["xyzzy_nomatch_99"], tier=Tier.FREE, max_results=50
            )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_deduplicates_by_platform_id(self) -> None:
        """collect_by_terms() deduplicates records with the same platform_id across queries."""
        # Both da and en return the same revision ID (simulating cross-project overlap).
        same_revision_response = {
            "query": {
                "pages": {
                    "12345": {
                        "title": "CO2-afgift",
                        "pageid": 12345,
                        "ns": 0,
                        "revisions": [
                            {
                                "revid": 98765,
                                "parentid": 98764,
                                "user": "TestEditor",
                                "timestamp": "2026-02-17T12:00:00Z",
                                "comment": "Updated statistics",
                                "size": 5432,
                                "tags": [],
                                "minor": False,
                            }
                        ],
                    }
                }
            }
        }

        mock_client = _make_mock_client([
            SEARCH_RESPONSE,          # da search
            same_revision_response,   # da revisions
            PAGEVIEWS_RESPONSE,       # da pageviews
            SEARCH_RESPONSE,          # en search (same article title)
            same_revision_response,   # en revisions (same rev id)
            PAGEVIEWS_RESPONSE,       # en pageviews
        ])

        collector = WikipediaCollector(http_client=mock_client)

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            records = await collector.collect_by_terms(
                terms=["CO2-afgift"], tier=Tier.FREE, max_results=100
            )

        platform_ids = [r["platform_id"] for r in records]
        assert len(platform_ids) == len(set(platform_ids)), (
            "platform_ids must be unique — deduplication failed"
        )

    @pytest.mark.asyncio
    async def test_collect_by_terms_respects_max_results_cap(self) -> None:
        """collect_by_terms() returns no more than max_results records."""
        # Build a revisions response with 5 revisions to ensure we exceed the cap.
        many_revisions_response: dict[str, Any] = {
            "query": {
                "pages": {
                    "12345": {
                        "title": "CO2-afgift",
                        "pageid": 12345,
                        "ns": 0,
                        "revisions": [
                            {
                                "revid": 98760 + i,
                                "parentid": 98759 + i,
                                "user": f"Editor{i}",
                                "timestamp": "2026-02-17T12:00:00Z",
                                "comment": f"Edit {i}",
                                "size": 5000 + i,
                                "tags": [],
                                "minor": False,
                            }
                            for i in range(5)
                        ],
                    }
                }
            }
        }

        mock_client = _make_mock_client([
            SEARCH_RESPONSE,           # da search
            many_revisions_response,   # da revisions (5 results)
            # pageviews and en are not reached due to max_results=2
        ])

        collector = WikipediaCollector(http_client=mock_client)

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            records = await collector.collect_by_terms(
                terms=["CO2-afgift"],
                tier=Tier.FREE,
                max_results=2,
                language_filter=["da"],  # restrict to da only for predictability
            )

        assert len(records) <= 2

    @pytest.mark.asyncio
    async def test_collect_by_terms_language_filter_da_only_skips_english(self) -> None:
        """collect_by_terms() with language_filter=['da'] queries only da.wikipedia."""
        call_log: list[str] = []

        async def _tracked_get(url: str, params=None, **kwargs):
            call_log.append(url)
            mock_response = MagicMock()
            mock_response.status_code = 200
            if "da.wikipedia" in url:
                mock_response.json.return_value = SEARCH_EMPTY_RESPONSE
            else:
                mock_response.json.return_value = SEARCH_EMPTY_RESPONSE
            mock_response.raise_for_status = MagicMock()
            return mock_response

        mock_client = MagicMock()
        mock_client.get = _tracked_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        collector = WikipediaCollector(http_client=mock_client)

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            await collector.collect_by_terms(
                terms=["CO2-afgift"],
                tier=Tier.FREE,
                max_results=10,
                language_filter=["da"],
            )

        # No en.wikipedia URLs should appear in the call log.
        en_calls = [url for url in call_log if "en.wikipedia" in url]
        assert en_calls == [], f"Expected no en.wikipedia API calls, got: {en_calls}"

    @pytest.mark.asyncio
    async def test_collect_by_terms_empty_terms_returns_empty_list(self) -> None:
        """collect_by_terms() with an empty terms list returns [] without making API calls."""
        mock_client = _make_mock_client([])  # no responses needed
        collector = WikipediaCollector(http_client=mock_client)

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            records = await collector.collect_by_terms(
                terms=[], tier=Tier.FREE, max_results=50
            )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_http_429_raises_arena_rate_limit_error(self) -> None:
        """collect_by_terms() raises ArenaRateLimitError on HTTP 429 from Wikimedia."""
        mock_client = _make_error_client(
            status_code=429, headers={"Retry-After": "60"}
        )
        collector = WikipediaCollector(http_client=mock_client)

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            with pytest.raises(ArenaRateLimitError):
                await collector.collect_by_terms(
                    terms=["CO2-afgift"], tier=Tier.FREE, max_results=10
                )

    @pytest.mark.asyncio
    async def test_collect_by_terms_http_500_raises_arena_collection_error(self) -> None:
        """collect_by_terms() raises ArenaCollectionError on HTTP 500 from Wikimedia."""
        mock_client = _make_error_client(status_code=500)
        collector = WikipediaCollector(http_client=mock_client)

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            with pytest.raises(ArenaCollectionError):
                await collector.collect_by_terms(
                    terms=["CO2-afgift"], tier=Tier.FREE, max_results=10
                )

    @pytest.mark.asyncio
    async def test_collect_by_terms_connection_error_raises_arena_collection_error(self) -> None:
        """collect_by_terms() raises ArenaCollectionError when the HTTP connection fails."""
        mock_client = _make_connection_error_client()
        collector = WikipediaCollector(http_client=mock_client)

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            with pytest.raises(ArenaCollectionError):
                await collector.collect_by_terms(
                    terms=["CO2-afgift"], tier=Tier.FREE, max_results=10
                )

    @pytest.mark.asyncio
    async def test_collect_by_terms_term_groups_joined_as_search_queries(self) -> None:
        """collect_by_terms() joins each term_group inner list into a single search string."""
        call_params: list[Any] = []

        async def _capturing_get(url: str, params=None, **kwargs):
            call_params.append(params or {})
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = SEARCH_EMPTY_RESPONSE
            mock_response.raise_for_status = MagicMock()
            return mock_response

        mock_client = MagicMock()
        mock_client.get = _capturing_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        collector = WikipediaCollector(http_client=mock_client)

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            await collector.collect_by_terms(
                terms=[],
                tier=Tier.FREE,
                max_results=10,
                language_filter=["da"],
                term_groups=[["CO2", "afgift"], ["grøn", "omstilling"]],
            )

        search_queries = [p.get("srsearch") for p in call_params if "srsearch" in p]
        assert "CO2 afgift" in search_queries
        assert "grøn omstilling" in search_queries

    @pytest.mark.asyncio
    async def test_collect_by_terms_bot_edits_filtered_by_default(self) -> None:
        """collect_by_terms() excludes bot-tagged revisions when INCLUDE_BOT_EDITS=False."""
        bot_revision_response: dict[str, Any] = {
            "query": {
                "pages": {
                    "12345": {
                        "title": "CO2-afgift",
                        "pageid": 12345,
                        "ns": 0,
                        "revisions": [
                            {
                                "revid": 99000,
                                "parentid": 98999,
                                "user": "CleanupBot",
                                "timestamp": "2026-02-17T12:00:00Z",
                                "comment": "Automated cleanup",
                                "size": 5000,
                                "tags": ["mw-bot"],
                                "minor": False,
                            },
                            {
                                "revid": 99001,
                                "parentid": 99000,
                                "user": "HumanEditor",
                                "timestamp": "2026-02-17T13:00:00Z",
                                "comment": "Manual correction",
                                "size": 5010,
                                "tags": [],
                                "minor": False,
                            },
                        ],
                    }
                }
            }
        }

        mock_client = _make_mock_client([
            SEARCH_RESPONSE,         # da search
            bot_revision_response,   # da revisions (one bot, one human)
            PAGEVIEWS_RESPONSE,      # da pageviews
            SEARCH_EMPTY_RESPONSE,   # en search
        ])

        collector = WikipediaCollector(http_client=mock_client)

        with (
            patch("asyncio.sleep", new=AsyncMock(return_value=None)),
            patch(
                "issue_observatory.arenas.wikipedia.collector.INCLUDE_BOT_EDITS",
                False,
            ),
        ):
            records = await collector.collect_by_terms(
                terms=["CO2-afgift"],
                tier=Tier.FREE,
                max_results=50,
            )

        revision_records = [r for r in records if r["content_type"] == "wiki_revision"]
        platform_ids = [r["platform_id"] for r in revision_records]
        assert "da.wikipedia:rev:99000" not in platform_ids, (
            "Bot revision (revid=99000) should be filtered out"
        )
        assert "da.wikipedia:rev:99001" in platform_ids, (
            "Human revision (revid=99001) should be included"
        )

    @pytest.mark.asyncio
    async def test_collect_by_terms_includes_pageview_records_when_enabled(self) -> None:
        """collect_by_terms() includes wiki_pageview records alongside wiki_revision records."""
        mock_client = _make_mock_client([
            SEARCH_RESPONSE,        # da search
            REVISIONS_RESPONSE,     # da revisions
            PAGEVIEWS_RESPONSE,     # da pageviews
            SEARCH_EMPTY_RESPONSE,  # en search
        ])

        collector = WikipediaCollector(http_client=mock_client)

        with (
            patch("asyncio.sleep", new=AsyncMock(return_value=None)),
            patch(
                "issue_observatory.arenas.wikipedia.collector.INCLUDE_PAGEVIEWS",
                True,
            ),
        ):
            records = await collector.collect_by_terms(
                terms=["CO2-afgift"],
                tier=Tier.FREE,
                max_results=50,
                language_filter=["da"],
            )

        content_types = {r["content_type"] for r in records}
        assert "wiki_pageview" in content_types, (
            "Expected at least one wiki_pageview record when INCLUDE_PAGEVIEWS=True"
        )

    @pytest.mark.asyncio
    async def test_collect_by_terms_danish_text_preserved_end_to_end(self) -> None:
        """Danish characters in article titles survive the full collect -> normalize pipeline."""
        danish_revision_response: dict[str, Any] = {
            "query": {
                "pages": {
                    "99999": {
                        "title": "Grøn omstilling og velfærd i Ålborg",
                        "pageid": 99999,
                        "ns": 0,
                        "revisions": [
                            {
                                "revid": 55555,
                                "parentid": 55554,
                                "user": "DanishEditor",
                                "timestamp": "2026-02-17T10:00:00Z",
                                "comment": "Tilføjet afsnit om velfærd",
                                "size": 3000,
                                "tags": [],
                                "minor": False,
                            }
                        ],
                    }
                }
            }
        }
        danish_search_response: dict[str, Any] = {
            "query": {
                "search": [
                    {"title": "Grøn omstilling og velfærd i Ålborg", "pageid": 99999},
                ]
            }
        }

        mock_client = _make_mock_client([
            danish_search_response,      # da search
            danish_revision_response,    # da revisions
            PAGEVIEWS_RESPONSE,          # da pageviews
            SEARCH_EMPTY_RESPONSE,       # en search
        ])

        collector = WikipediaCollector(http_client=mock_client)

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            records = await collector.collect_by_terms(
                terms=["grøn omstilling"],
                tier=Tier.FREE,
                max_results=50,
            )

        revision_records = [r for r in records if r["content_type"] == "wiki_revision"]
        assert len(revision_records) >= 1
        titles = [r.get("title", "") or "" for r in revision_records]
        assert any("ø" in t for t in titles), "Expected 'ø' in at least one article title"
        assert any("Å" in t for t in titles), "Expected 'Å' in at least one article title"

    @pytest.mark.asyncio
    async def test_collect_by_terms_invalid_tier_raises_value_error(self) -> None:
        """collect_by_terms() raises ValueError when called with an unsupported tier."""
        collector = WikipediaCollector()
        with pytest.raises((ValueError, ArenaCollectionError)):
            await collector.collect_by_terms(
                terms=["test"], tier=Tier.MEDIUM, max_results=5
            )


# ---------------------------------------------------------------------------
# collect_by_actors() integration tests with mocked HTTP
# ---------------------------------------------------------------------------


class TestCollectByActors:
    @pytest.mark.asyncio
    async def test_collect_by_actors_returns_revision_records_for_user(self) -> None:
        """collect_by_actors() returns wiki_revision records for the given Wikipedia username."""
        # One response per project (da + en)
        mock_client = _make_mock_client([
            USERCONTRIBS_RESPONSE,  # da usercontribs for JohnEditor
            USERCONTRIBS_RESPONSE,  # en usercontribs for JohnEditor
        ])

        collector = WikipediaCollector(http_client=mock_client)

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            records = await collector.collect_by_actors(
                actor_ids=["JohnEditor"], tier=Tier.FREE, max_results=50
            )

        assert isinstance(records, list)
        assert len(records) >= 1
        assert all(r["content_type"] == "wiki_revision" for r in records)
        assert all(r["platform"] == "wikipedia" for r in records)

    @pytest.mark.asyncio
    async def test_collect_by_actors_platform_id_format_is_project_rev_revid(self) -> None:
        """collect_by_actors() produces platform_id in '{wiki_project}:rev:{revid}' format."""
        mock_client = _make_mock_client([
            USERCONTRIBS_RESPONSE,  # da
            {"query": {"usercontribs": []}},  # en: no results
        ])

        collector = WikipediaCollector(http_client=mock_client)

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            records = await collector.collect_by_actors(
                actor_ids=["JohnEditor"],
                tier=Tier.FREE,
                max_results=50,
            )

        da_records = [r for r in records if r.get("language") == "da"]
        assert len(da_records) >= 1
        assert da_records[0]["platform_id"] == "da.wikipedia:rev:11111"

    @pytest.mark.asyncio
    async def test_collect_by_actors_author_platform_id_is_username(self) -> None:
        """collect_by_actors() sets author_platform_id to the supplied username."""
        mock_client = _make_mock_client([
            USERCONTRIBS_RESPONSE,
            {"query": {"usercontribs": []}},
        ])

        collector = WikipediaCollector(http_client=mock_client)

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            records = await collector.collect_by_actors(
                actor_ids=["JohnEditor"], tier=Tier.FREE, max_results=50
            )

        da_records = [r for r in records if r.get("language") == "da"]
        assert da_records[0]["author_platform_id"] == "JohnEditor"

    @pytest.mark.asyncio
    async def test_collect_by_actors_deduplicates_across_projects(self) -> None:
        """collect_by_actors() deduplicates revision records with the same platform_id."""
        # Both da and en return the same revid — in practice this shouldn't happen
        # but the deduplication guard should handle it.
        mock_client = _make_mock_client([
            USERCONTRIBS_RESPONSE,  # da: revid=11111
            USERCONTRIBS_RESPONSE,  # en: same revid=11111 (edge case)
        ])

        collector = WikipediaCollector(http_client=mock_client)

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            records = await collector.collect_by_actors(
                actor_ids=["JohnEditor"], tier=Tier.FREE, max_results=50
            )

        platform_ids = [r["platform_id"] for r in records]
        assert len(platform_ids) == len(set(platform_ids)), (
            "platform_ids must be unique — deduplication failed in collect_by_actors"
        )

    @pytest.mark.asyncio
    async def test_collect_by_actors_empty_usercontribs_returns_empty_list(self) -> None:
        """collect_by_actors() returns [] when the API returns zero contributions."""
        mock_client = _make_mock_client([
            {"query": {"usercontribs": []}},  # da: empty
            {"query": {"usercontribs": []}},  # en: empty
        ])

        collector = WikipediaCollector(http_client=mock_client)

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            records = await collector.collect_by_actors(
                actor_ids=["InactiveUser"], tier=Tier.FREE, max_results=50
            )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_actors_respects_max_results(self) -> None:
        """collect_by_actors() returns no more than max_results records."""
        many_contribs: dict[str, Any] = {
            "query": {
                "usercontribs": [
                    {
                        "revid": 20000 + i,
                        "parentid": 19999 + i,
                        "user": "ProEditor",
                        "ns": 0,
                        "title": f"Article{i}",
                        "timestamp": "2026-02-15T10:00:00Z",
                        "comment": f"Edit {i}",
                        "size": 100 * i,
                        "tags": [],
                        "minor": False,
                    }
                    for i in range(10)
                ]
            },
            "continue": None,
        }

        mock_client = _make_mock_client([many_contribs, many_contribs])

        collector = WikipediaCollector(http_client=mock_client)

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            records = await collector.collect_by_actors(
                actor_ids=["ProEditor"], tier=Tier.FREE, max_results=3
            )

        assert len(records) <= 3

    @pytest.mark.asyncio
    async def test_collect_by_actors_http_429_raises_arena_rate_limit_error(self) -> None:
        """collect_by_actors() raises ArenaRateLimitError on HTTP 429 from Wikimedia."""
        mock_client = _make_error_client(status_code=429, headers={"Retry-After": "30"})
        collector = WikipediaCollector(http_client=mock_client)

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            with pytest.raises(ArenaRateLimitError):
                await collector.collect_by_actors(
                    actor_ids=["SomeEditor"], tier=Tier.FREE, max_results=10
                )

    @pytest.mark.asyncio
    async def test_collect_by_actors_danish_username_preserved(self) -> None:
        """collect_by_actors() preserves Danish characters in usernames as author_platform_id."""
        danish_contrib_response: dict[str, Any] = {
            "query": {
                "usercontribs": [
                    {
                        "revid": 33333,
                        "parentid": 33332,
                        "user": "SørenØberg",
                        "ns": 0,
                        "title": "Klimaaftale",
                        "timestamp": "2026-02-15T10:00:00Z",
                        "comment": "Rettet stavefejl",
                        "size": 2000,
                        "tags": [],
                        "minor": False,
                    }
                ]
            },
            "continue": None,
        }

        mock_client = _make_mock_client([
            danish_contrib_response,
            {"query": {"usercontribs": []}},
        ])

        collector = WikipediaCollector(http_client=mock_client)

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            records = await collector.collect_by_actors(
                actor_ids=["SørenØberg"], tier=Tier.FREE, max_results=10
            )

        assert len(records) >= 1
        assert records[0]["author_platform_id"] == "SørenØberg"
        assert "ø" in records[0]["author_platform_id"]


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_ok_on_successful_siteinfo_response(self) -> None:
        """health_check() returns status='ok' when da.wikipedia siteinfo API responds."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = SITEINFO_RESPONSE

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        collector = WikipediaCollector()

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "reference"
        assert result["platform"] == "wikipedia"
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_ok_with_sitename_from_response(self) -> None:
        """health_check() includes the sitename from the siteinfo response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = SITEINFO_RESPONSE

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        collector = WikipediaCollector()

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await collector.health_check()

        assert result.get("site") == "Wikipedia"

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_http_503(self) -> None:
        """health_check() returns status='down' when da.wikipedia API returns HTTP 503."""
        mock_request = MagicMock()
        mock_response_obj = MagicMock()
        mock_response_obj.status_code = 503
        http_error = httpx.HTTPStatusError(
            "HTTP 503", request=mock_request, response=mock_response_obj
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(side_effect=http_error)

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        collector = WikipediaCollector()

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await collector.health_check()

        assert result["status"] == "down"
        assert result["arena"] == "reference"
        assert result["platform"] == "wikipedia"

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_connection_error(self) -> None:
        """health_check() returns status='down' when a network connection error occurs."""
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        collector = WikipediaCollector()

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await collector.health_check()

        assert result["status"] == "down"
        assert "detail" in result

    @pytest.mark.asyncio
    async def test_health_check_contains_checked_at_iso_timestamp(self) -> None:
        """health_check() always includes a 'checked_at' ISO 8601 timestamp in the result."""
        mock_request = MagicMock()
        mock_response_obj = MagicMock()
        mock_response_obj.status_code = 500
        http_error = httpx.HTTPStatusError(
            "HTTP 500", request=mock_request, response=mock_response_obj
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(side_effect=http_error)

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        collector = WikipediaCollector()

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await collector.health_check()

        assert "checked_at" in result
        # Verify it parses as an ISO 8601 datetime
        checked_at = result["checked_at"]
        dt = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
        assert dt.tzinfo is not None
