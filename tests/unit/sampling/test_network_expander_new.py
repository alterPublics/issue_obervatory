"""Unit tests for new network expander functionality.

Covers the following additions to sampling/network_expander.py:

- _expand_tiktok(): OAuth token retrieval, follower/following pagination,
  empty credentials, OAuth failure.
- _expand_gab(): Mastodon-compatible account lookup, follower/following
  pagination with max_id, lookup failure.
- _expand_x_twitter(): TwitterAPI.io cursor pagination, empty credentials.
- _expand_via_comention() URL co-mention: URL-based actor discovery via
  link_miner integration, platform mapping, seed-actor self-exclusion.
- expand_from_actor() dispatch: tiktok, gab, x_twitter route to correct
  private methods.
- _post_json() helper: success, HTTP error, general exception.

All tests use mocked HTTP and DB sessions -- no live infrastructure required.
"""

from __future__ import annotations

import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# Env bootstrap (must run before any application imports)
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault(
    "CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA=="
)

from issue_observatory.sampling.network_expander import (  # noqa: E402
    NetworkExpander,
    _COMENTION_MIN_RECORDS,
    _GAB_API_BASE,
    _TIKTOK_FOLLOWERS_URL,
    _TIKTOK_FOLLOWING_URL,
    _TIKTOK_OAUTH_URL,
    _TWITTERAPIIO_FOLLOWERS_URL,
    _TWITTERAPIIO_FOLLOWING_URL,
    _URL_PLATFORM_MAP,
    _make_actor_dict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_with_fetchall(rows: list[MagicMock]) -> MagicMock:
    """Return a mock AsyncSession whose execute() returns rows via fetchall()."""
    execute_result = MagicMock()
    execute_result.fetchall.return_value = rows
    db = MagicMock()
    db.execute = AsyncMock(return_value=execute_result)
    return db


def _make_comention_row(record_id: str, text_content: str) -> MagicMock:
    """Return a mock row as returned by the co-mention seed-records SQL query."""
    row = MagicMock()
    row.id = record_id
    row.text_content = text_content
    return row


def _platform_presence(
    platform_user_id: str = "12345",
    platform_username: str = "testuser",
    profile_url: str = "",
) -> dict[str, str]:
    """Return a minimal platform presence dict."""
    return {
        "platform_user_id": platform_user_id,
        "platform_username": platform_username,
        "profile_url": profile_url,
    }


def _mock_presence_db(platform: str, presence: dict[str, str]) -> MagicMock:
    """Build a mock DB that returns a single ActorPlatformPresence row.

    The first db.execute() call (from _load_platform_presences) returns
    a presence row. Subsequent calls return empty fetchall() results.
    """
    presence_row = MagicMock()
    presence_row.platform = platform
    presence_row.platform_user_id = presence.get("platform_user_id", "")
    presence_row.platform_username = presence.get("platform_username", "")
    presence_row.profile_url = presence.get("profile_url", "")

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [presence_row]
    presence_result = MagicMock()
    presence_result.scalars.return_value = scalars_mock

    empty_result = MagicMock()
    empty_result.fetchall.return_value = []

    call_count = 0

    async def mock_execute(sql: Any, params: Any = None) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return presence_result
        return empty_result

    db = MagicMock()
    db.execute = AsyncMock(side_effect=mock_execute)
    return db


# ---------------------------------------------------------------------------
# _post_json() helper
# ---------------------------------------------------------------------------


class TestPostJson:
    @pytest.mark.asyncio
    async def test_success_returns_parsed_json(self) -> None:
        """_post_json returns the parsed JSON dict on a successful POST."""
        expected = {"access_token": "tok123", "token_type": "bearer"}

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=expected)

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        expander = NetworkExpander(http_client=client)

        result = await expander._post_json(
            "https://example.com/token", json_body={"grant_type": "client_credentials"}
        )
        assert result == expected

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self) -> None:
        """_post_json returns None when the server responds with an HTTP error."""

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "unauthorized"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        expander = NetworkExpander(http_client=client)

        result = await expander._post_json(
            "https://example.com/token", json_body={"grant_type": "client_credentials"}
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_general_exception_returns_none(self) -> None:
        """_post_json returns None when an unexpected exception occurs (e.g. network)."""

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        expander = NetworkExpander(http_client=client)

        result = await expander._post_json("https://example.com/token")
        assert result is None


# ---------------------------------------------------------------------------
# _expand_tiktok()
# ---------------------------------------------------------------------------


class TestExpandTiktok:
    @pytest.mark.asyncio
    async def test_empty_credentials_returns_empty_list(self) -> None:
        """_expand_tiktok returns [] when credentials are None."""
        expander = NetworkExpander()
        result = await expander._expand_tiktok("someuser", credentials=None)
        assert result == []

    @pytest.mark.asyncio
    async def test_missing_client_key_returns_empty_list(self) -> None:
        """_expand_tiktok returns [] when credentials lack client_key."""
        expander = NetworkExpander()
        result = await expander._expand_tiktok("someuser", credentials={"client_secret": "s"})
        assert result == []

    @pytest.mark.asyncio
    async def test_oauth_failure_returns_empty_list(self) -> None:
        """_expand_tiktok returns [] when OAuth token retrieval fails."""

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            # OAuth endpoint returns 401
            return httpx.Response(401, json={"error": "invalid_client"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        expander = NetworkExpander(http_client=client)

        result = await expander._expand_tiktok(
            "someuser",
            credentials={"client_key": "ck", "client_secret": "cs"},
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_successful_expansion_returns_actors(self) -> None:
        """_expand_tiktok returns correctly shaped ActorDicts on success."""
        call_log: list[str] = []

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            call_log.append(url)

            if _TIKTOK_OAUTH_URL in url:
                return httpx.Response(
                    200,
                    json={"access_token": "test_token", "token_type": "bearer"},
                )

            # Follower/following endpoint: return 2 users, no more pages
            return httpx.Response(
                200,
                json={
                    "data": {
                        "users": [
                            {"username": "alice", "display_name": "Alice"},
                            {"username": "bob", "display_name": "Bob"},
                        ],
                        "cursor": 0,
                        "has_more": False,
                    }
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        expander = NetworkExpander(http_client=client)

        result = await expander._expand_tiktok(
            "someuser",
            credentials={"client_key": "ck", "client_secret": "cs"},
        )

        # 2 users x 2 directions (followers + following)
        assert len(result) == 4
        for actor in result:
            assert actor["platform"] == "tiktok"
            assert actor["profile_url"].startswith("https://www.tiktok.com/@")
            assert actor["discovery_method"] in ("tiktok_followers", "tiktok_following")

    @pytest.mark.asyncio
    async def test_discovery_methods_are_tiktok_followers_and_following(self) -> None:
        """_expand_tiktok sets correct discovery_method per direction."""

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if _TIKTOK_OAUTH_URL in url:
                return httpx.Response(200, json={"access_token": "tok"})
            return httpx.Response(
                200,
                json={
                    "data": {
                        "users": [{"username": "u1", "display_name": "U1"}],
                        "cursor": 0,
                        "has_more": False,
                    }
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        expander = NetworkExpander(http_client=client)

        result = await expander._expand_tiktok(
            "seed", credentials={"client_key": "ck", "client_secret": "cs"}
        )

        methods = {a["discovery_method"] for a in result}
        assert "tiktok_followers" in methods
        assert "tiktok_following" in methods

    @pytest.mark.asyncio
    async def test_pagination_with_cursor_and_has_more(self) -> None:
        """_expand_tiktok paginates when has_more is True and cursor advances."""
        page = 0

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal page
            url = str(request.url)

            if _TIKTOK_OAUTH_URL in url:
                return httpx.Response(200, json={"access_token": "tok"})

            page += 1
            if page <= 2:
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "users": [{"username": f"user_p{page}", "display_name": f"P{page}"}],
                            "cursor": page * 100,
                            "has_more": True,
                        }
                    },
                )
            # Third page: no more
            return httpx.Response(
                200,
                json={
                    "data": {
                        "users": [{"username": f"user_p{page}", "display_name": f"P{page}"}],
                        "cursor": 0,
                        "has_more": False,
                    }
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        expander = NetworkExpander(http_client=client)

        result = await expander._expand_tiktok(
            "seed", credentials={"client_key": "ck", "client_secret": "cs"}
        )

        # 3 pages for followers direction, then page counter resets for following
        # (mock handler increments page globally so the second direction also paginates)
        assert len(result) >= 3
        usernames = [a["platform_username"] for a in result]
        assert "user_p1" in usernames
        assert "user_p2" in usernames

    @pytest.mark.asyncio
    async def test_username_without_display_name_falls_back(self) -> None:
        """When display_name is missing, canonical_name falls back to username."""

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if _TIKTOK_OAUTH_URL in url:
                return httpx.Response(200, json={"access_token": "tok"})
            return httpx.Response(
                200,
                json={
                    "data": {
                        "users": [{"username": "nodisplay"}],
                        "cursor": 0,
                        "has_more": False,
                    }
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        expander = NetworkExpander(http_client=client)

        result = await expander._expand_tiktok(
            "seed", credentials={"client_key": "ck", "client_secret": "cs"}
        )

        # Check that fallback to username works (display_name absent)
        nodisplay_actors = [a for a in result if a["platform_username"] == "nodisplay"]
        assert len(nodisplay_actors) >= 1
        assert nodisplay_actors[0]["canonical_name"] == "nodisplay"


# ---------------------------------------------------------------------------
# _expand_gab()
# ---------------------------------------------------------------------------


class TestExpandGab:
    @pytest.mark.asyncio
    async def test_lookup_failure_returns_empty_list(self) -> None:
        """_expand_gab returns [] when account lookup fails (HTTP error)."""

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "not found"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        expander = NetworkExpander(http_client=client)

        result = await expander._expand_gab("nonexistent", credentials=None)
        assert result == []

    @pytest.mark.asyncio
    async def test_lookup_returns_no_id_returns_empty_list(self) -> None:
        """_expand_gab returns [] when lookup JSON lacks an id field."""

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"username": "test"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        expander = NetworkExpander(http_client=client)

        result = await expander._expand_gab("test", credentials=None)
        assert result == []

    @pytest.mark.asyncio
    async def test_successful_expansion_returns_actors(self) -> None:
        """_expand_gab returns correctly shaped ActorDicts on success."""

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/accounts/lookup" in url:
                return httpx.Response(
                    200, json={"id": "99001", "username": "gabuser", "acct": "gabuser"}
                )
            # Followers or following endpoint
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "100",
                        "acct": "follower1",
                        "display_name": "Follower One",
                        "url": "https://gab.com/follower1",
                    },
                    {
                        "id": "101",
                        "acct": "follower2",
                        "display_name": "Follower Two",
                        "url": "https://gab.com/follower2",
                    },
                ],
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        expander = NetworkExpander(http_client=client)

        result = await expander._expand_gab("gabuser", credentials=None)

        # 2 accounts x 2 directions
        assert len(result) == 4
        for actor in result:
            assert actor["platform"] == "gab"
            assert actor["discovery_method"] in ("gab_followers", "gab_following")

    @pytest.mark.asyncio
    async def test_discovery_methods_are_gab_followers_and_following(self) -> None:
        """_expand_gab sets correct discovery_method per direction."""

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/accounts/lookup" in url:
                return httpx.Response(200, json={"id": "500"})
            return httpx.Response(
                200,
                json=[{"id": "600", "acct": "peer1", "display_name": "Peer"}],
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        expander = NetworkExpander(http_client=client)

        result = await expander._expand_gab("seed", credentials=None)
        methods = {a["discovery_method"] for a in result}
        assert "gab_followers" in methods
        assert "gab_following" in methods

    @pytest.mark.asyncio
    async def test_mastodon_style_max_id_pagination(self) -> None:
        """_expand_gab paginates using max_id from the last item in each page."""
        page_count = 0

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal page_count
            url = str(request.url)

            if "/accounts/lookup" in url:
                return httpx.Response(200, json={"id": "1"})

            page_count += 1
            if page_count == 1:
                # Full page of 40 items signals more pages available
                accounts = [
                    {"id": str(i), "acct": f"user_{i}", "display_name": f"User {i}"}
                    for i in range(40)
                ]
                return httpx.Response(200, json=accounts)
            # Second page: fewer than 40 items signals end of pagination
            return httpx.Response(
                200,
                json=[{"id": "999", "acct": "last_user", "display_name": "Last"}],
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        expander = NetworkExpander(http_client=client)

        result = await expander._expand_gab("seed", credentials=None)

        # At least 41 from followers direction (40 + 1), plus following direction
        assert len(result) >= 41

    @pytest.mark.asyncio
    async def test_bearer_token_sent_when_credentials_provided(self) -> None:
        """_expand_gab includes Authorization header when access_token is present."""
        captured_headers: list[dict[str, str]] = []

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            captured_headers.append(dict(request.headers))
            url = str(request.url)
            if "/accounts/lookup" in url:
                return httpx.Response(200, json={"id": "1"})
            return httpx.Response(200, json=[])

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        expander = NetworkExpander(http_client=client)

        await expander._expand_gab(
            "user", credentials={"access_token": "test_gab_token"}
        )

        # The lookup request should have the Bearer token
        assert any("bearer test_gab_token" in h.get("authorization", "").lower()
                    for h in captured_headers)

    @pytest.mark.asyncio
    async def test_acct_fallback_to_username_field(self) -> None:
        """When acct is missing, _expand_gab falls back to the username field."""

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/accounts/lookup" in url:
                return httpx.Response(200, json={"id": "1"})
            return httpx.Response(
                200,
                json=[{"id": "200", "username": "fallback_user"}],
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        expander = NetworkExpander(http_client=client)

        result = await expander._expand_gab("seed", credentials=None)
        fallback_actors = [a for a in result if a["platform_username"] == "fallback_user"]
        assert len(fallback_actors) >= 1


# ---------------------------------------------------------------------------
# _expand_x_twitter()
# ---------------------------------------------------------------------------


class TestExpandXTwitter:
    @pytest.mark.asyncio
    async def test_empty_credentials_returns_empty_list(self) -> None:
        """_expand_x_twitter returns [] when credentials are None."""
        expander = NetworkExpander()
        result = await expander._expand_x_twitter("someuser", credentials=None)
        assert result == []

    @pytest.mark.asyncio
    async def test_missing_api_key_returns_empty_list(self) -> None:
        """_expand_x_twitter returns [] when credentials lack api_key."""
        expander = NetworkExpander()
        result = await expander._expand_x_twitter("someuser", credentials={"other": "val"})
        assert result == []

    @pytest.mark.asyncio
    async def test_successful_expansion_returns_actors(self) -> None:
        """_expand_x_twitter returns correctly shaped ActorDicts on success."""

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "users": [
                        {"userName": "alice", "id": "111", "name": "Alice"},
                        {"userName": "bob", "id": "222", "name": "Bob"},
                    ],
                    "next_cursor": None,
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        expander = NetworkExpander(http_client=client)

        result = await expander._expand_x_twitter(
            "seeduser", credentials={"api_key": "test_key"}
        )

        # 2 users x 2 directions
        assert len(result) == 4
        for actor in result:
            assert actor["platform"] == "x_twitter"
            assert actor["profile_url"].startswith("https://x.com/")
            assert actor["discovery_method"] in ("x_twitter_followers", "x_twitter_following")

    @pytest.mark.asyncio
    async def test_discovery_methods_are_x_twitter_followers_and_following(self) -> None:
        """_expand_x_twitter sets correct discovery_method per direction."""

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "users": [{"userName": "peer", "id": "333", "name": "Peer"}],
                    "next_cursor": None,
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        expander = NetworkExpander(http_client=client)

        result = await expander._expand_x_twitter(
            "seed", credentials={"api_key": "k"}
        )
        methods = {a["discovery_method"] for a in result}
        assert "x_twitter_followers" in methods
        assert "x_twitter_following" in methods

    @pytest.mark.asyncio
    async def test_cursor_pagination(self) -> None:
        """_expand_x_twitter follows next_cursor for multiple pages."""
        page = 0

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal page
            page += 1
            if page <= 2:
                return httpx.Response(
                    200,
                    json={
                        "users": [{"userName": f"u{page}", "id": str(page), "name": f"U{page}"}],
                        "next_cursor": f"cursor_{page}",
                    },
                )
            return httpx.Response(
                200,
                json={
                    "users": [{"userName": f"u{page}", "id": str(page), "name": f"U{page}"}],
                    "next_cursor": None,
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        expander = NetworkExpander(http_client=client)

        result = await expander._expand_x_twitter(
            "seed", credentials={"api_key": "k"}
        )
        usernames = [a["platform_username"] for a in result]
        assert "u1" in usernames
        assert "u2" in usernames

    @pytest.mark.asyncio
    async def test_api_key_sent_in_header(self) -> None:
        """_expand_x_twitter sends the API key in the X-API-Key header."""
        captured_headers: list[dict[str, str]] = []

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            captured_headers.append(dict(request.headers))
            return httpx.Response(200, json={"users": [], "next_cursor": None})

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        expander = NetworkExpander(http_client=client)

        await expander._expand_x_twitter("user", credentials={"api_key": "my_secret_key"})

        assert any(h.get("x-api-key") == "my_secret_key" for h in captured_headers)

    @pytest.mark.asyncio
    async def test_screen_name_fallback(self) -> None:
        """_expand_x_twitter falls back to screen_name when userName is missing."""

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "users": [{"screen_name": "legacy_name", "userId": "444", "name": "Legacy"}],
                    "next_cursor": None,
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        expander = NetworkExpander(http_client=client)

        result = await expander._expand_x_twitter(
            "seed", credentials={"api_key": "k"}
        )
        legacy_actors = [a for a in result if a["platform_username"] == "legacy_name"]
        assert len(legacy_actors) >= 1


# ---------------------------------------------------------------------------
# _expand_via_comention() -- URL co-mention detection
# ---------------------------------------------------------------------------


class TestExpandViaComentionUrlDiscovery:
    @pytest.mark.asyncio
    async def test_url_comention_discovers_twitter_actor(self) -> None:
        """URL co-mention extracts x.com links and maps them to x_twitter platform."""
        expander = NetworkExpander()

        text = (
            "Check @seeduser and https://x.com/tweetperson for more "
            "also https://x.com/tweetperson again"
        )
        rows = [
            _make_comention_row("rec-1", text),
            _make_comention_row("rec-2", text),
        ]
        db = _make_db_with_fetchall(rows)

        result = await expander._expand_via_comention(
            actor_id=uuid.uuid4(),
            platform="x_twitter",
            presence=_platform_presence(platform_username="seeduser"),
            db=db,
            min_records=2,
        )

        url_actors = [a for a in result if a["discovery_method"] == "url_comention"]
        twitter_actors = [a for a in url_actors if a["platform"] == "x_twitter"]
        assert len(twitter_actors) >= 1
        assert any(a["platform_username"] == "tweetperson" for a in twitter_actors)

    @pytest.mark.asyncio
    async def test_url_comention_discovers_bluesky_actor(self) -> None:
        """URL co-mention extracts bsky.app links and maps to bluesky platform."""
        expander = NetworkExpander()

        text = (
            "Follow @seeduser and also check "
            "https://bsky.app/profile/someone.bsky.social"
        )
        rows = [
            _make_comention_row("rec-1", text),
            _make_comention_row("rec-2", text),
        ]
        db = _make_db_with_fetchall(rows)

        result = await expander._expand_via_comention(
            actor_id=uuid.uuid4(),
            platform="bluesky",
            presence=_platform_presence(platform_username="seeduser"),
            db=db,
            min_records=2,
        )

        url_actors = [a for a in result if a["discovery_method"] == "url_comention"]
        bsky_actors = [a for a in url_actors if a["platform"] == "bluesky"]
        assert len(bsky_actors) >= 1
        assert any("someone.bsky.social" in a["platform_username"] for a in bsky_actors)

    @pytest.mark.asyncio
    async def test_url_comention_excludes_seed_actor_url(self) -> None:
        """URL co-mention does not include the seed actor's own URL in results."""
        expander = NetworkExpander()

        text = (
            "Post by @seeduser mentions https://x.com/seeduser "
            "and https://x.com/otheruser"
        )
        rows = [
            _make_comention_row("rec-1", text),
            _make_comention_row("rec-2", text),
        ]
        db = _make_db_with_fetchall(rows)

        result = await expander._expand_via_comention(
            actor_id=uuid.uuid4(),
            platform="x_twitter",
            presence=_platform_presence(platform_username="seeduser"),
            db=db,
            min_records=2,
        )

        url_actors = [a for a in result if a["discovery_method"] == "url_comention"]
        # seeduser should NOT appear via URL co-mention (it's the seed actor)
        assert all(a["platform_username"] != "seeduser" for a in url_actors)

    @pytest.mark.asyncio
    async def test_url_comention_discovery_method_is_url_comention(self) -> None:
        """URL-discovered actors have discovery_method set to 'url_comention'.

        Uses a Gab URL (no @ prefix in path) so the target is discovered
        exclusively via URL classification, not as an @mention first.  This
        avoids the deduplication path that would classify the target as
        'comention_fallback' when TikTok's @-prefixed URLs are used.
        """
        expander = NetworkExpander()

        text = (
            "Check @seeduser and also https://gab.com/gabperson for more"
        )
        rows = [
            _make_comention_row("rec-1", text),
            _make_comention_row("rec-2", text),
        ]
        db = _make_db_with_fetchall(rows)

        result = await expander._expand_via_comention(
            actor_id=uuid.uuid4(),
            platform="x_twitter",
            presence=_platform_presence(platform_username="seeduser"),
            db=db,
            min_records=2,
        )

        url_actors = [a for a in result if a["discovery_method"] == "url_comention"]
        assert len(url_actors) >= 1
        for actor in url_actors:
            assert actor["discovery_method"] == "url_comention"
            assert actor["platform"] == "gab"

    @pytest.mark.asyncio
    async def test_url_comention_maps_platforms_correctly(self) -> None:
        """Verify the _URL_PLATFORM_MAP mapping is consistent with expected values."""
        assert _URL_PLATFORM_MAP["twitter"] == "x_twitter"
        assert _URL_PLATFORM_MAP["bluesky"] == "bluesky"
        assert _URL_PLATFORM_MAP["youtube"] == "youtube"
        assert _URL_PLATFORM_MAP["tiktok"] == "tiktok"
        assert _URL_PLATFORM_MAP["gab"] == "gab"
        assert _URL_PLATFORM_MAP["instagram"] == "instagram"
        assert _URL_PLATFORM_MAP["telegram"] == "telegram"
        assert _URL_PLATFORM_MAP["reddit_user"] == "reddit"

    @pytest.mark.asyncio
    async def test_url_comention_below_min_records_not_included(self) -> None:
        """URL co-mention actors appearing in fewer than min_records are excluded."""
        expander = NetworkExpander()

        # Only one record mentions the URL -- below min_records=2
        text = "Check @seeduser and https://x.com/rareuser"
        rows = [
            _make_comention_row("rec-1", text),
        ]
        db = _make_db_with_fetchall(rows)

        result = await expander._expand_via_comention(
            actor_id=uuid.uuid4(),
            platform="x_twitter",
            presence=_platform_presence(platform_username="seeduser"),
            db=db,
            min_records=2,
        )

        url_actors = [a for a in result if a["discovery_method"] == "url_comention"]
        rare_actors = [a for a in url_actors if a["platform_username"] == "rareuser"]
        assert len(rare_actors) == 0


# ---------------------------------------------------------------------------
# expand_from_actor() -- dispatch routing
# ---------------------------------------------------------------------------


class TestExpandFromActorDispatch:
    @pytest.mark.asyncio
    async def test_tiktok_dispatches_to_expand_tiktok(self) -> None:
        """expand_from_actor routes 'tiktok' platform to _expand_tiktok."""
        expander = NetworkExpander()
        actor_id = uuid.uuid4()
        presence = _platform_presence(platform_username="tiktokuser")
        db = _mock_presence_db("tiktok", presence)

        mock_cred_pool = MagicMock()
        mock_cred_pool.acquire = AsyncMock(
            return_value={"client_key": "ck", "client_secret": "cs"}
        )

        with patch.object(
            expander, "_expand_tiktok", new_callable=AsyncMock, return_value=[]
        ) as mock_expand:
            await expander.expand_from_actor(
                actor_id=actor_id,
                platforms=["tiktok"],
                db=db,
                credential_pool=mock_cred_pool,
            )
            mock_expand.assert_called_once_with(
                "tiktokuser",
                {"client_key": "ck", "client_secret": "cs"},
            )

    @pytest.mark.asyncio
    async def test_gab_dispatches_to_expand_gab(self) -> None:
        """expand_from_actor routes 'gab' platform to _expand_gab."""
        expander = NetworkExpander()
        actor_id = uuid.uuid4()
        presence = _platform_presence(platform_username="gabuser")
        db = _mock_presence_db("gab", presence)

        mock_cred_pool = MagicMock()
        mock_cred_pool.acquire = AsyncMock(
            return_value={"access_token": "gab_tok"}
        )

        with patch.object(
            expander, "_expand_gab", new_callable=AsyncMock, return_value=[]
        ) as mock_expand:
            await expander.expand_from_actor(
                actor_id=actor_id,
                platforms=["gab"],
                db=db,
                credential_pool=mock_cred_pool,
            )
            mock_expand.assert_called_once_with(
                "gabuser",
                {"access_token": "gab_tok"},
            )

    @pytest.mark.asyncio
    async def test_x_twitter_dispatches_to_expand_x_twitter(self) -> None:
        """expand_from_actor routes 'x_twitter' platform to _expand_x_twitter."""
        expander = NetworkExpander()
        actor_id = uuid.uuid4()
        presence = _platform_presence(platform_username="xuser")
        db = _mock_presence_db("x_twitter", presence)

        mock_cred_pool = MagicMock()
        mock_cred_pool.acquire = AsyncMock(
            return_value={"api_key": "twitterapiio_key"}
        )

        with patch.object(
            expander, "_expand_x_twitter", new_callable=AsyncMock, return_value=[]
        ) as mock_expand:
            await expander.expand_from_actor(
                actor_id=actor_id,
                platforms=["x_twitter"],
                db=db,
                credential_pool=mock_cred_pool,
            )
            mock_expand.assert_called_once_with(
                "xuser",
                {"api_key": "twitterapiio_key"},
            )

    @pytest.mark.asyncio
    async def test_tiktok_uses_free_tier_credentials(self) -> None:
        """expand_from_actor acquires tiktok credentials with tier='free'."""
        expander = NetworkExpander()
        actor_id = uuid.uuid4()
        presence = _platform_presence(platform_username="tiktokuser")
        db = _mock_presence_db("tiktok", presence)

        mock_cred_pool = MagicMock()
        mock_cred_pool.acquire = AsyncMock(return_value=None)

        with patch.object(
            expander, "_expand_tiktok", new_callable=AsyncMock, return_value=[]
        ):
            await expander.expand_from_actor(
                actor_id=actor_id,
                platforms=["tiktok"],
                db=db,
                credential_pool=mock_cred_pool,
            )
            mock_cred_pool.acquire.assert_called_once_with(
                platform="tiktok", tier="free"
            )

    @pytest.mark.asyncio
    async def test_gab_uses_free_tier_credentials(self) -> None:
        """expand_from_actor acquires gab credentials with tier='free'."""
        expander = NetworkExpander()
        actor_id = uuid.uuid4()
        presence = _platform_presence(platform_username="gabuser")
        db = _mock_presence_db("gab", presence)

        mock_cred_pool = MagicMock()
        mock_cred_pool.acquire = AsyncMock(return_value=None)

        with patch.object(
            expander, "_expand_gab", new_callable=AsyncMock, return_value=[]
        ):
            await expander.expand_from_actor(
                actor_id=actor_id,
                platforms=["gab"],
                db=db,
                credential_pool=mock_cred_pool,
            )
            mock_cred_pool.acquire.assert_called_once_with(
                platform="gab", tier="free"
            )

    @pytest.mark.asyncio
    async def test_x_twitter_uses_medium_tier_credentials(self) -> None:
        """expand_from_actor acquires twitterapi_io credentials with tier='medium'."""
        expander = NetworkExpander()
        actor_id = uuid.uuid4()
        presence = _platform_presence(platform_username="xuser")
        db = _mock_presence_db("x_twitter", presence)

        mock_cred_pool = MagicMock()
        mock_cred_pool.acquire = AsyncMock(return_value=None)

        with patch.object(
            expander, "_expand_x_twitter", new_callable=AsyncMock, return_value=[]
        ):
            await expander.expand_from_actor(
                actor_id=actor_id,
                platforms=["x_twitter"],
                db=db,
                credential_pool=mock_cred_pool,
            )
            mock_cred_pool.acquire.assert_called_once_with(
                platform="twitterapi_io", tier="medium"
            )

    @pytest.mark.asyncio
    async def test_unknown_platform_falls_back_to_comention(self) -> None:
        """expand_from_actor falls back to _expand_via_comention for unknown platforms."""
        expander = NetworkExpander()
        actor_id = uuid.uuid4()
        presence = _platform_presence(platform_username="myuser")
        db = _mock_presence_db("threads", presence)

        with patch.object(
            expander, "_expand_via_comention", new_callable=AsyncMock, return_value=[]
        ) as mock_comention:
            await expander.expand_from_actor(
                actor_id=actor_id,
                platforms=["threads"],
                db=db,
            )
            mock_comention.assert_called_once()

    @pytest.mark.asyncio
    async def test_platform_with_no_presence_is_skipped(self) -> None:
        """expand_from_actor skips platforms where the actor has no presence."""
        expander = NetworkExpander()
        actor_id = uuid.uuid4()

        # DB returns a presence for bluesky but NOT for tiktok
        presence_row = MagicMock()
        presence_row.platform = "bluesky"
        presence_row.platform_user_id = "did:plc:abc"
        presence_row.platform_username = "user.bsky.social"
        presence_row.profile_url = ""

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [presence_row]
        presence_result = MagicMock()
        presence_result.scalars.return_value = scalars_mock

        db = MagicMock()
        db.execute = AsyncMock(return_value=presence_result)

        with patch.object(
            expander, "_expand_tiktok", new_callable=AsyncMock, return_value=[]
        ) as mock_tiktok:
            await expander.expand_from_actor(
                actor_id=actor_id,
                platforms=["tiktok"],
                db=db,
            )
            # _expand_tiktok should NOT be called because actor has no tiktok presence
            mock_tiktok.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_in_expander_does_not_propagate(self) -> None:
        """expand_from_actor catches exceptions from individual platform expanders."""
        expander = NetworkExpander()
        actor_id = uuid.uuid4()
        presence = _platform_presence(platform_username="crashuser")
        db = _mock_presence_db("gab", presence)

        with patch.object(
            expander, "_expand_gab",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            # Must not raise, even though _expand_gab throws
            result = await expander.expand_from_actor(
                actor_id=actor_id,
                platforms=["gab"],
                db=db,
            )
            assert isinstance(result, list)


# ---------------------------------------------------------------------------
# _make_actor_dict() helper
# ---------------------------------------------------------------------------


class TestMakeActorDict:
    def test_returns_all_required_fields(self) -> None:
        """_make_actor_dict returns a dict with all required ActorDict fields."""
        result = _make_actor_dict(
            canonical_name="Test User",
            platform="bluesky",
            platform_user_id="did:plc:123",
            platform_username="test.bsky.social",
            profile_url="https://bsky.app/profile/test.bsky.social",
            discovery_method="bluesky_follows",
        )
        assert result["canonical_name"] == "Test User"
        assert result["platform"] == "bluesky"
        assert result["platform_user_id"] == "did:plc:123"
        assert result["platform_username"] == "test.bsky.social"
        assert result["profile_url"] == "https://bsky.app/profile/test.bsky.social"
        assert result["discovery_method"] == "bluesky_follows"

    def test_preserves_danish_characters(self) -> None:
        """_make_actor_dict preserves Danish characters in canonical_name."""
        result = _make_actor_dict(
            canonical_name="Jens Ransen",
            platform="bluesky",
            platform_user_id="did:plc:dk",
            platform_username="jens.bsky.social",
            profile_url="",
            discovery_method="bluesky_followers",
        )
        assert result["canonical_name"] == "Jens Ransen"

    def test_handles_empty_strings(self) -> None:
        """_make_actor_dict accepts empty strings without error."""
        result = _make_actor_dict(
            canonical_name="",
            platform="",
            platform_user_id="",
            platform_username="",
            profile_url="",
            discovery_method="",
        )
        assert result["canonical_name"] == ""
        assert len(result) == 6


# ---------------------------------------------------------------------------
# _COMENTION_MIN_RECORDS constant
# ---------------------------------------------------------------------------


class TestComentionConstants:
    def test_comention_min_records_default(self) -> None:
        """_COMENTION_MIN_RECORDS is 2 by default."""
        assert _COMENTION_MIN_RECORDS == 2
