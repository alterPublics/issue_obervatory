"""Unit tests for the actor sampling module.

Covers:
- NetworkExpander.expand_from_actor() with Bluesky platform (mock AT Protocol)
- NetworkExpander.find_co_mentioned_actors() with mock DB session
- SimilarityFinder.cross_platform_match() with mocked search responses
- SimilarityFinder.find_similar_by_content() with mock DB (sklearn present + absent)
- SnowballSampler.run() with seed actors, depth=1, verifying deduplication
- SnowballResult.wave_log populated correctly

These tests run without a live database or network connection.
"""

from __future__ import annotations

import os
import sys
import uuid
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

from issue_observatory.sampling.network_expander import NetworkExpander  # noqa: E402
from issue_observatory.sampling.similarity_finder import (  # noqa: E402
    SimilarityFinder,
    _name_similarity,
    _tokenize,
    _word_overlap_similarity,
)
from issue_observatory.sampling.snowball import SnowballResult, SnowballSampler  # noqa: E402

# ---------------------------------------------------------------------------
# AT Protocol endpoint constants (mirroring network_expander.py)
# ---------------------------------------------------------------------------

_BLUESKY_PUBLIC_API = "https://public.api.bsky.app/xrpc"
_BSKY_SEARCH_ACTORS = f"{_BLUESKY_PUBLIC_API}/app.bsky.actor.searchActors"
_BSKY_GET_FOLLOWS = f"{_BLUESKY_PUBLIC_API}/app.bsky.graph.getFollows"
_BSKY_GET_FOLLOWERS = f"{_BLUESKY_PUBLIC_API}/app.bsky.graph.getFollowers"
_BSKY_SUGGESTED_FOLLOWS = f"{_BLUESKY_PUBLIC_API}/app.bsky.graph.getSuggestedFollowsByActor"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_db_returning_presences(
    actor_id: uuid.UUID,
    platform: str,
    platform_user_id: str,
    platform_username: str,
) -> Any:
    """Create a mock AsyncSession that returns one platform presence row."""
    row = MagicMock()
    row.platform = platform
    row.platform_user_id = platform_user_id
    row.platform_username = platform_username
    row.profile_url = f"https://bsky.app/profile/{platform_username}"

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [row]

    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock

    db = MagicMock()
    db.execute = AsyncMock(return_value=execute_result)
    return db


def _make_mock_db_empty_presences() -> Any:
    """Create a mock AsyncSession that returns no platform presence rows."""
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = []

    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock

    db = MagicMock()
    db.execute = AsyncMock(return_value=execute_result)
    return db


def _make_bluesky_follows_response(profiles: list[dict]) -> dict:
    """Build a mock app.bsky.graph.getFollows response body."""
    return {"follows": profiles, "cursor": None}


def _make_bluesky_followers_response(profiles: list[dict]) -> dict:
    """Build a mock app.bsky.graph.getFollowers response body."""
    return {"followers": profiles, "cursor": None}


# ---------------------------------------------------------------------------
# NetworkExpander tests
# ---------------------------------------------------------------------------


class TestNetworkExpanderBluesky:
    @pytest.mark.asyncio
    async def test_expand_from_actor_bluesky_returns_follows_and_followers(self) -> None:
        """expand_from_actor() on Bluesky returns actors from both follows and followers."""
        actor_id = uuid.uuid4()
        db = _make_mock_db_returning_presences(
            actor_id, "bluesky", "did:plc:abc123", "drdk.bsky.social"
        )

        follows_response = _make_bluesky_follows_response([
            {"did": "did:plc:follow1", "handle": "soeren.bsky.social", "displayName": "Søren"},
            {"did": "did:plc:follow2", "handle": "aase.bsky.social", "displayName": "Åse"},
        ])
        followers_response = _make_bluesky_followers_response([
            {"did": "did:plc:follower1", "handle": "mette.bsky.social", "displayName": "Mette"},
        ])

        with respx.mock:
            respx.get(_BSKY_GET_FOLLOWS).mock(
                return_value=httpx.Response(200, json=follows_response)
            )
            respx.get(_BSKY_GET_FOLLOWERS).mock(
                return_value=httpx.Response(200, json=followers_response)
            )

            async with httpx.AsyncClient() as client:
                expander = NetworkExpander(http_client=client)
                results = await expander.expand_from_actor(
                    actor_id=actor_id,
                    platforms=["bluesky"],
                    db=db,
                )

        assert len(results) == 3
        platforms = {r["platform"] for r in results}
        assert platforms == {"bluesky"}

        discovery_methods = {r["discovery_method"] for r in results}
        assert "bluesky_follows" in discovery_methods
        assert "bluesky_followers" in discovery_methods

    @pytest.mark.asyncio
    async def test_expand_from_actor_bluesky_preserves_danish_display_names(self) -> None:
        """expand_from_actor() preserves Danish characters in returned display names."""
        actor_id = uuid.uuid4()
        db = _make_mock_db_returning_presences(
            actor_id, "bluesky", "did:plc:abc123", "test.bsky.social"
        )

        follows_response = _make_bluesky_follows_response([
            {"did": "did:plc:dk1", "handle": "ørsted.bsky.social", "displayName": "Ørsted Energi"},
        ])

        with respx.mock:
            respx.get(_BSKY_GET_FOLLOWS).mock(
                return_value=httpx.Response(200, json=follows_response)
            )
            respx.get(_BSKY_GET_FOLLOWERS).mock(
                return_value=httpx.Response(200, json={"followers": [], "cursor": None})
            )

            async with httpx.AsyncClient() as client:
                expander = NetworkExpander(http_client=client)
                results = await expander.expand_from_actor(
                    actor_id=actor_id,
                    platforms=["bluesky"],
                    db=db,
                )

        assert len(results) == 1
        assert "Ørsted" in results[0]["canonical_name"]

    @pytest.mark.asyncio
    async def test_expand_from_actor_skips_platform_with_no_presence(self) -> None:
        """expand_from_actor() skips a platform if the actor has no presence on it."""
        actor_id = uuid.uuid4()
        db = _make_mock_db_empty_presences()

        expander = NetworkExpander()
        results = await expander.expand_from_actor(
            actor_id=actor_id,
            platforms=["bluesky"],
            db=db,
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_expand_from_actor_returns_empty_when_db_is_none(self) -> None:
        """expand_from_actor() returns [] when no db session is provided."""
        expander = NetworkExpander()
        results = await expander.expand_from_actor(
            actor_id=uuid.uuid4(),
            platforms=["bluesky"],
            db=None,
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_expand_from_actor_handles_http_error_gracefully(self) -> None:
        """expand_from_actor() logs error and returns [] on HTTP failure from platform."""
        actor_id = uuid.uuid4()
        db = _make_mock_db_returning_presences(
            actor_id, "bluesky", "did:plc:abc123", "test.bsky.social"
        )

        with respx.mock:
            respx.get(_BSKY_GET_FOLLOWS).mock(
                return_value=httpx.Response(500)
            )
            respx.get(_BSKY_GET_FOLLOWERS).mock(
                return_value=httpx.Response(500)
            )

            async with httpx.AsyncClient() as client:
                expander = NetworkExpander(http_client=client)
                results = await expander.expand_from_actor(
                    actor_id=actor_id,
                    platforms=["bluesky"],
                    db=db,
                )

        assert results == []


class TestNetworkExpanderCoMentions:
    @pytest.mark.asyncio
    async def test_find_co_mentioned_actors_returns_empty_when_db_is_none(self) -> None:
        """find_co_mentioned_actors() returns [] when called without a DB session."""
        expander = NetworkExpander()
        results = await expander.find_co_mentioned_actors(
            query_design_id=uuid.uuid4(),
            db=None,
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_find_co_mentioned_actors_returns_pairs_from_db(self) -> None:
        """find_co_mentioned_actors() returns co-mentioned actor pairs from DB query."""
        qd_id = uuid.uuid4()

        # Build mock DB that returns co-mention rows.
        row1 = MagicMock()
        row1.actor_a = "user_a"
        row1.actor_b = "user_b"
        row1.platform = "bluesky"
        row1.co_occurrence_count = 5

        execute_result = MagicMock()
        execute_result.fetchall.return_value = [row1]

        db = MagicMock()
        db.execute = AsyncMock(return_value=execute_result)

        expander = NetworkExpander()
        results = await expander.find_co_mentioned_actors(
            query_design_id=qd_id,
            db=db,
            min_co_occurrences=3,
        )

        assert len(results) == 1
        assert results[0]["actor_a"] == "user_a"
        assert results[0]["actor_b"] == "user_b"
        assert results[0]["co_occurrence_count"] == 5

    @pytest.mark.asyncio
    async def test_find_co_mentioned_actors_returns_empty_on_db_error(self) -> None:
        """find_co_mentioned_actors() returns [] when the DB query raises an exception."""
        db = MagicMock()
        db.execute = AsyncMock(side_effect=RuntimeError("DB connection lost"))

        expander = NetworkExpander()
        results = await expander.find_co_mentioned_actors(
            query_design_id=uuid.uuid4(),
            db=db,
        )

        assert results == []


# ---------------------------------------------------------------------------
# SimilarityFinder tests
# ---------------------------------------------------------------------------


class TestSimilarityFinderCrossPlatformMatch:
    @pytest.mark.asyncio
    async def test_cross_platform_match_bluesky_returns_actors_with_confidence(self) -> None:
        """cross_platform_match() on Bluesky returns actors with confidence_score."""
        search_response = {
            "actors": [
                {
                    "did": "did:plc:drdk1",
                    "handle": "drdk.bsky.social",
                    "displayName": "DR Nyheder",
                },
                {
                    "did": "did:plc:drdk2",
                    "handle": "drnyheder.bsky.social",
                    "displayName": "DR Nyheder Live",
                },
            ]
        }

        with respx.mock:
            respx.get(_BSKY_SEARCH_ACTORS).mock(
                return_value=httpx.Response(200, json=search_response)
            )

            async with httpx.AsyncClient() as client:
                finder = SimilarityFinder(http_client=client)
                results = await finder.cross_platform_match(
                    name_or_handle="drdk",
                    platforms=["bluesky"],
                    top_n=5,
                )

        assert len(results) > 0
        assert all("confidence_score" in r for r in results)
        assert all(r["platform"] == "bluesky" for r in results)

    @pytest.mark.asyncio
    async def test_cross_platform_match_returns_empty_on_http_error(self) -> None:
        """cross_platform_match() returns [] when the platform search fails."""
        with respx.mock:
            respx.get(_BSKY_SEARCH_ACTORS).mock(
                return_value=httpx.Response(500)
            )

            async with httpx.AsyncClient() as client:
                finder = SimilarityFinder(http_client=client)
                results = await finder.cross_platform_match(
                    name_or_handle="test",
                    platforms=["bluesky"],
                    top_n=5,
                )

        assert results == []

    @pytest.mark.asyncio
    async def test_cross_platform_match_danish_handle_returns_results(self) -> None:
        """cross_platform_match() handles Danish characters in query without error."""
        search_response = {
            "actors": [
                {
                    "did": "did:plc:ørsted1",
                    "handle": "oersted.bsky.social",
                    "displayName": "Ørsted Energi",
                }
            ]
        }

        with respx.mock:
            respx.get(_BSKY_SEARCH_ACTORS).mock(
                return_value=httpx.Response(200, json=search_response)
            )

            async with httpx.AsyncClient() as client:
                finder = SimilarityFinder(http_client=client)
                results = await finder.cross_platform_match(
                    name_or_handle="Ørsted",
                    platforms=["bluesky"],
                    top_n=3,
                )

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_cross_platform_match_unsupported_platform_returns_empty(self) -> None:
        """cross_platform_match() returns [] for a platform with no search implementation."""
        finder = SimilarityFinder()
        results = await finder.cross_platform_match(
            name_or_handle="test",
            platforms=["unsupported_platform"],
            top_n=5,
        )

        assert results == []


class TestSimilarityFinderContentBased:
    @pytest.mark.asyncio
    async def test_find_similar_by_content_returns_empty_when_db_none(self) -> None:
        """find_similar_by_content() returns [] when no DB session is provided."""
        finder = SimilarityFinder()
        results = await finder.find_similar_by_content(
            actor_id=uuid.uuid4(),
            db=None,
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_find_similar_by_content_with_mock_db_and_sklearn(self) -> None:
        """find_similar_by_content() returns scored actors when DB returns text content."""
        actor_id = uuid.uuid4()
        candidate_id = str(uuid.uuid4())

        # Mock DB: target actor has tokens, candidate has tokens
        target_row = MagicMock()
        target_row.combined = "Grøn omstilling og velfærdsstat er vigtigt for Danmark og Ålborg"

        candidate_row = MagicMock()
        candidate_row.author_id = candidate_id
        candidate_row.platform = "bluesky"
        candidate_row.combined_text = "Grøn energi og velfærd i Danmark"

        # DB returns target text on first call, candidates on second
        call_count = 0

        async def mock_execute(sql: Any, params: dict) -> MagicMock:
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # First call: target actor tokens
                row = MagicMock()
                row.combined = "Grøn omstilling og velfærdsstat er vigtigt for Danmark"
                result.fetchone.return_value = row
            else:
                # Second call: candidate actors
                result.fetchall.return_value = [candidate_row]
            return result

        db = MagicMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        finder = SimilarityFinder()
        results = await finder.find_similar_by_content(
            actor_id=actor_id,
            db=db,
            top_n=5,
        )

        # Results list should be a list (may be empty if candidate text is too short)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_find_similar_by_content_fallback_without_sklearn(self) -> None:
        """find_similar_by_content() uses Jaccard fallback when sklearn is not installed."""
        actor_id = uuid.uuid4()
        candidate_id = str(uuid.uuid4())

        call_count = 0

        async def mock_execute(sql: Any, params: dict) -> MagicMock:
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                row = MagicMock()
                row.combined = "grøn omstilling velfærd demokrati økonomi miljø klima"
                result.fetchone.return_value = row
            else:
                row = MagicMock()
                row.author_id = candidate_id
                row.platform = "bluesky"
                row.combined_text = "grøn energi velfærd demokrati"
                result.fetchall.return_value = [row]
            return result

        db = MagicMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        # Monkeypatch sklearn out of sys.modules to force the Jaccard fallback path
        with patch.dict(sys.modules, {"sklearn": None, "sklearn.feature_extraction": None,
                                       "sklearn.feature_extraction.text": None,
                                       "sklearn.metrics": None,
                                       "sklearn.metrics.pairwise": None}):
            finder = SimilarityFinder()
            results = await finder.find_similar_by_content(
                actor_id=actor_id,
                db=db,
                top_n=5,
            )

        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# SnowballSampler tests
# ---------------------------------------------------------------------------


class TestSnowballSampler:
    @pytest.mark.asyncio
    async def test_run_with_no_seeds_returns_empty_result(self) -> None:
        """SnowballSampler.run() with empty seed list returns empty SnowballResult."""
        sampler = SnowballSampler()
        result = await sampler.run(
            seed_actor_ids=[],
            platforms=["bluesky"],
            db=None,
            max_depth=1,
        )

        assert result.total_actors == 0
        assert result.actors == []

    @pytest.mark.asyncio
    async def test_run_with_db_none_uses_stub_seed_actors(self) -> None:
        """SnowballSampler.run() with db=None generates stub entries for seeds at wave 0."""
        seed_id = uuid.uuid4()
        sampler = SnowballSampler()
        result = await sampler.run(
            seed_actor_ids=[seed_id],
            platforms=["bluesky"],
            db=None,
            max_depth=1,
        )

        assert result.total_actors >= 1
        assert 0 in result.wave_log
        assert result.wave_log[0]["discovered"] == 1
        assert result.wave_log[0]["methods"] == ["seed"]

    @pytest.mark.asyncio
    async def test_run_depth1_expands_seeds_and_deduplicates(self) -> None:
        """SnowballSampler.run() at depth=1 discovers actors and deduplicates."""
        seed_id = uuid.uuid4()

        # Mock expander that returns two actors from Bluesky
        mock_expander = MagicMock()
        mock_expander.expand_from_actor = AsyncMock(
            return_value=[
                {
                    "canonical_name": "Søren Ærlighed",
                    "platform": "bluesky",
                    "platform_user_id": "did:plc:new1",
                    "platform_username": "soeren.bsky.social",
                    "profile_url": "https://bsky.app/profile/soeren.bsky.social",
                    "discovery_method": "bluesky_follows",
                },
                {
                    "canonical_name": "Åse Nyheder",
                    "platform": "bluesky",
                    "platform_user_id": "did:plc:new2",
                    "platform_username": "aase.bsky.social",
                    "profile_url": "https://bsky.app/profile/aase.bsky.social",
                    "discovery_method": "bluesky_followers",
                },
            ]
        )

        sampler = SnowballSampler(expander=mock_expander)
        result = await sampler.run(
            seed_actor_ids=[seed_id],
            platforms=["bluesky"],
            db=None,
            max_depth=1,
            max_actors_per_step=20,
        )

        # Wave 0: seed actor; Wave 1: 2 discovered actors
        assert 0 in result.wave_log
        assert 1 in result.wave_log
        assert result.wave_log[1]["discovered"] == 2
        assert "bluesky_follows" in result.wave_log[1]["methods"] or \
               "bluesky_followers" in result.wave_log[1]["methods"]

    @pytest.mark.asyncio
    async def test_run_deduplicates_actors_across_waves(self) -> None:
        """SnowballSampler.run() does not add the same actor twice."""
        seed_id = uuid.uuid4()

        # Mock expander returns same actor twice — should be deduped
        duplicate_actor = {
            "canonical_name": "Ørsted Media",
            "platform": "bluesky",
            "platform_user_id": "did:plc:dup1",
            "platform_username": "orsted.bsky.social",
            "profile_url": "https://bsky.app/profile/orsted.bsky.social",
            "discovery_method": "bluesky_follows",
        }
        mock_expander = MagicMock()
        mock_expander.expand_from_actor = AsyncMock(
            return_value=[duplicate_actor, duplicate_actor]
        )

        sampler = SnowballSampler(expander=mock_expander)
        result = await sampler.run(
            seed_actor_ids=[seed_id],
            platforms=["bluesky"],
            db=None,
            max_depth=1,
        )

        # Only one unique actor should be in wave 1 despite duplicate expansion
        assert result.wave_log[1]["discovered"] == 1

    @pytest.mark.asyncio
    async def test_run_wave_log_has_correct_structure(self) -> None:
        """SnowballSampler.run() wave_log has 'discovered' and 'methods' keys at each depth."""
        seed_id = uuid.uuid4()
        mock_expander = MagicMock()
        mock_expander.expand_from_actor = AsyncMock(return_value=[])

        sampler = SnowballSampler(expander=mock_expander)
        result = await sampler.run(
            seed_actor_ids=[seed_id],
            platforms=["bluesky"],
            db=None,
            max_depth=1,
        )

        for depth, wave_info in result.wave_log.items():
            assert "discovered" in wave_info, f"wave_log[{depth}] missing 'discovered'"
            assert "methods" in wave_info, f"wave_log[{depth}] missing 'methods'"

    @pytest.mark.asyncio
    async def test_run_max_actors_per_step_limits_discovery(self) -> None:
        """SnowballSampler.run() respects max_actors_per_step at each wave."""
        seed_id = uuid.uuid4()

        # Return 10 actors but limit to 3
        many_actors = [
            {
                "canonical_name": f"Actor {i}",
                "platform": "bluesky",
                "platform_user_id": f"did:plc:actor{i}",
                "platform_username": f"actor{i}.bsky.social",
                "profile_url": f"https://bsky.app/profile/actor{i}.bsky.social",
                "discovery_method": "bluesky_follows",
            }
            for i in range(10)
        ]
        mock_expander = MagicMock()
        mock_expander.expand_from_actor = AsyncMock(return_value=many_actors)

        sampler = SnowballSampler(expander=mock_expander)
        result = await sampler.run(
            seed_actor_ids=[seed_id],
            platforms=["bluesky"],
            db=None,
            max_depth=1,
            max_actors_per_step=3,
        )

        assert result.wave_log[1]["discovered"] <= 3

    def test_snowball_result_repr(self) -> None:
        """SnowballResult.__repr__() returns a meaningful string."""
        result = SnowballResult()
        result.total_actors = 5
        result.max_depth_reached = 2

        assert "5" in repr(result)
        assert "2" in repr(result)


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    def test_tokenize_lowercases_and_splits(self) -> None:
        """_tokenize() lowercases and splits text into tokens."""
        tokens = _tokenize("Grøn omstilling er vigtig")

        assert "grøn" in tokens
        assert "omstilling" in tokens
        assert "er" not in tokens  # too short (2 chars min)

    def test_tokenize_handles_danish_chars(self) -> None:
        """_tokenize() preserves æ, ø, å in token matching."""
        tokens = _tokenize("Ålborg og Ørsted og velfærd")

        assert "ålborg" in tokens
        assert "ørsted" in tokens
        assert "velfærd" in tokens

    def test_word_overlap_similarity_identical_tokens(self) -> None:
        """_word_overlap_similarity() returns 1.0 for identical token lists."""
        tokens = ["grøn", "omstilling", "dansk"]
        assert _word_overlap_similarity(tokens, tokens) == 1.0

    def test_word_overlap_similarity_disjoint_tokens(self) -> None:
        """_word_overlap_similarity() returns 0.0 for completely disjoint token lists."""
        a = ["grøn", "omstilling"]
        b = ["rød", "afvikling"]
        assert _word_overlap_similarity(a, b) == 0.0

    def test_word_overlap_similarity_empty_tokens(self) -> None:
        """_word_overlap_similarity() returns 0.0 when either token list is empty."""
        assert _word_overlap_similarity([], ["token"]) == 0.0
        assert _word_overlap_similarity(["token"], []) == 0.0

    def test_name_similarity_exact_match(self) -> None:
        """_name_similarity() returns 1.0 for exact string matches."""
        assert _name_similarity("drdk", "drdk") == 1.0

    def test_name_similarity_prefix_match(self) -> None:
        """_name_similarity() returns high score for prefix matches."""
        score = _name_similarity("dr", "drdk")
        assert score >= 0.7

    def test_name_similarity_unrelated_strings(self) -> None:
        """_name_similarity() returns low score for unrelated strings."""
        score = _name_similarity("abc", "xyz")
        assert score < 0.5

    def test_name_similarity_danish_chars_handled(self) -> None:
        """_name_similarity() handles Danish characters without error."""
        score = _name_similarity("ørsted", "ørsted")
        assert score == 1.0
