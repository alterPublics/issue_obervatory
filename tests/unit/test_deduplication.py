"""Unit tests for DeduplicationService and normalise_url.

Tests cover:
- normalise_url() lowercases the URL
- normalise_url() strips the www. prefix from the host
- normalise_url() removes UTM tracking parameters
- normalise_url() removes fbclid, gclid, ref, source, _ga parameters
- normalise_url() keeps non-tracking query parameters
- normalise_url() sorts remaining query parameters for stable comparison
- normalise_url() strips trailing slashes from the path
- normalise_url() preserves root paths ("/")
- normalise_url() returns lowercased input for malformed URLs (no netloc)
- find_url_duplicates() returns groups with ≥2 records sharing the same normalised URL
- find_url_duplicates() returns nothing for records with distinct URLs
- find_url_duplicates() ignores records with no URL
- find_hash_duplicates() returns groups where the same content_hash appears on different platforms
- find_hash_duplicates() does NOT return same-platform duplicates (those are DB-constraint violations)
- find_hash_duplicates() ignores records with NULL content_hash
- mark_duplicates() calls db.execute() with the expected UPDATE statement
- mark_duplicates() returns 0 and performs no DB call when duplicate_ids is empty
- run_dedup_pass() runs URL pass then hash pass and commits
- run_dedup_pass() returns the correct summary dict
- get_deduplication_service() returns a DeduplicationService instance
- Empty input to find_url_duplicates() / find_hash_duplicates() returns []

All tests mock the SQLAlchemy AsyncSession.  No live database is required.
"""

from __future__ import annotations

import uuid
from collections import namedtuple
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from issue_observatory.core.deduplication import (
    DeduplicationService,
    compute_simhash,
    get_deduplication_service,
    hamming_distance,
    normalise_url,
)


# ---------------------------------------------------------------------------
# normalise_url — pure function tests (no mocking needed)
# ---------------------------------------------------------------------------


class TestNormaliseUrl:
    def test_normalise_url_lowercases_the_url(self) -> None:
        """The entire URL is lowercased during normalisation."""
        result = normalise_url("HTTPS://DR.DK/ARTICLE")

        assert result == result.lower()

    def test_normalise_url_strips_www_prefix(self) -> None:
        """The www. subdomain is removed from the host."""
        result = normalise_url("https://www.dr.dk/nyheder/artikel")

        assert "www." not in result
        assert "dr.dk" in result

    def test_normalise_url_without_www_is_unchanged_in_host(self) -> None:
        """A URL without www. retains its host exactly."""
        result = normalise_url("https://berlingske.dk/article")

        assert "berlingske.dk" in result

    def test_normalise_url_removes_utm_source(self) -> None:
        """utm_source is stripped from the query string."""
        result = normalise_url("https://dr.dk/article?utm_source=twitter&id=123")

        assert "utm_source" not in result
        assert "id=123" in result

    def test_normalise_url_removes_utm_medium(self) -> None:
        """utm_medium is stripped from the query string."""
        result = normalise_url("https://dr.dk/article?utm_medium=social")

        assert "utm_medium" not in result

    def test_normalise_url_removes_utm_campaign(self) -> None:
        """utm_campaign is stripped from the query string."""
        result = normalise_url("https://dr.dk/article?utm_campaign=summer")

        assert "utm_campaign" not in result

    def test_normalise_url_removes_fbclid(self) -> None:
        """fbclid tracking parameter is stripped."""
        result = normalise_url("https://dr.dk/article?fbclid=IwAR0abc123")

        assert "fbclid" not in result

    def test_normalise_url_removes_gclid(self) -> None:
        """gclid tracking parameter is stripped."""
        result = normalise_url("https://dr.dk/article?gclid=abc")

        assert "gclid" not in result

    def test_normalise_url_removes_ga_parameter(self) -> None:
        """_ga tracking parameter is stripped."""
        result = normalise_url("https://dr.dk/article?_ga=2.123456.789")

        assert "_ga" not in result

    def test_normalise_url_removes_ref_parameter(self) -> None:
        """ref parameter is treated as a tracking parameter and stripped."""
        result = normalise_url("https://dr.dk/article?ref=newsletter")

        assert "ref=" not in result

    def test_normalise_url_preserves_non_tracking_params(self) -> None:
        """Non-tracking query parameters are retained in the output."""
        result = normalise_url("https://dr.dk/search?q=klimaforandringer&page=2")

        assert "q=klimaforandringer" in result
        assert "page=2" in result

    def test_normalise_url_sorts_query_params_for_stable_comparison(self) -> None:
        """Two URLs with the same params in different order produce the same normalised form."""
        url_a = "https://dr.dk/article?id=123&lang=da"
        url_b = "https://dr.dk/article?lang=da&id=123"

        assert normalise_url(url_a) == normalise_url(url_b)

    def test_normalise_url_strips_trailing_slash_from_path(self) -> None:
        """A trailing slash on a non-root path is removed."""
        result = normalise_url("https://dr.dk/nyheder/")

        assert not result.rstrip("?").endswith("/")

    def test_normalise_url_preserves_root_path(self) -> None:
        """The bare root path '/' is kept for bare domain URLs."""
        # A bare domain without a path does not get an extra slash
        result = normalise_url("https://dr.dk/")

        # The root slash is kept; the URL must not have it stripped to an empty path
        assert result.startswith("https://dr.dk")

    def test_normalise_url_returns_lowercased_for_malformed_url(self) -> None:
        """A URL without a netloc is returned lowercased only (no crash)."""
        result = normalise_url("not-a-url-AT-ALL")

        assert result == "not-a-url-at-all"

    def test_normalise_url_same_url_different_tracking_params_equal(self) -> None:
        """Two URLs identical except for tracking params normalise to the same string."""
        url_a = "https://information.dk/artikel/klimakrise?utm_source=newsletter"
        url_b = "https://information.dk/artikel/klimakrise?fbclid=xyz"

        assert normalise_url(url_a) == normalise_url(url_b)

    def test_normalise_url_different_paths_remain_distinct(self) -> None:
        """Two URLs with different paths do not collide after normalisation."""
        url_a = "https://dr.dk/nyheder/artikel-1"
        url_b = "https://dr.dk/nyheder/artikel-2"

        assert normalise_url(url_a) != normalise_url(url_b)


# ---------------------------------------------------------------------------
# Helper: build a mock AsyncSession returning prescribed rows
# ---------------------------------------------------------------------------

# Named tuple that mirrors the fields selected in find_url_duplicates
_UrlRow = namedtuple("_UrlRow", ["id", "url", "platform", "arena", "published_at"])
# Named tuple for find_hash_duplicates
_HashRow = namedtuple("_HashRow", ["id", "content_hash", "platform", "arena"])


def _mock_db_for_url_rows(rows: list[_UrlRow]) -> MagicMock:
    """Return a mock AsyncSession whose execute() returns the given URL rows."""
    db = MagicMock()
    mock_result = MagicMock()
    mock_result.all.return_value = rows
    db.execute = AsyncMock(return_value=mock_result)
    db.commit = AsyncMock()
    return db


def _mock_db_for_hash_rows(rows: list[_HashRow]) -> MagicMock:
    """Return a mock AsyncSession whose execute() returns the given hash rows."""
    return _mock_db_for_url_rows(rows)  # same shape


# ---------------------------------------------------------------------------
# find_url_duplicates()
# ---------------------------------------------------------------------------


class TestFindUrlDuplicates:
    async def test_find_url_duplicates_returns_empty_for_no_records(self) -> None:
        """Empty input returns an empty list with no exception."""
        db = _mock_db_for_url_rows([])
        svc = DeduplicationService()

        result = await svc.find_url_duplicates(db)

        assert result == []

    async def test_find_url_duplicates_returns_empty_for_unique_urls(self) -> None:
        """Records with distinct URLs produce no duplicate groups."""
        rows = [
            _UrlRow(
                id=uuid.uuid4(),
                url="https://dr.dk/article-1",
                platform="dr",
                arena="news_media",
                published_at=None,
            ),
            _UrlRow(
                id=uuid.uuid4(),
                url="https://berlingske.dk/article-2",
                platform="berlingske",
                arena="news_media",
                published_at=None,
            ),
        ]
        db = _mock_db_for_url_rows(rows)
        svc = DeduplicationService()

        result = await svc.find_url_duplicates(db)

        assert result == []

    async def test_find_url_duplicates_detects_same_url_on_two_platforms(self) -> None:
        """Two records sharing the same normalised URL are grouped as duplicates."""
        shared_url = "https://dr.dk/nyheder/klimaforandringer"
        rows = [
            _UrlRow(
                id=uuid.uuid4(),
                url=shared_url,
                platform="bluesky",
                arena="social_media",
                published_at=None,
            ),
            _UrlRow(
                id=uuid.uuid4(),
                url=shared_url + "?utm_source=twitter",
                platform="reddit",
                arena="social_media",
                published_at=None,
            ),
        ]
        db = _mock_db_for_url_rows(rows)
        svc = DeduplicationService()

        result = await svc.find_url_duplicates(db)

        assert len(result) == 1
        assert result[0]["normalised_url"] == normalise_url(shared_url)
        assert len(result[0]["records"]) == 2

    async def test_find_url_duplicates_ignores_records_with_null_url(self) -> None:
        """Records with url=None do not participate in URL dedup."""
        rows = [
            _UrlRow(
                id=uuid.uuid4(),
                url=None,
                platform="bluesky",
                arena="social_media",
                published_at=None,
            ),
            _UrlRow(
                id=uuid.uuid4(),
                url=None,
                platform="reddit",
                arena="social_media",
                published_at=None,
            ),
        ]
        db = _mock_db_for_url_rows(rows)
        svc = DeduplicationService()

        result = await svc.find_url_duplicates(db)

        assert result == []

    async def test_find_url_duplicates_group_contains_platform_and_arena(self) -> None:
        """Each record in a group dict has 'id', 'platform', 'arena' keys."""
        shared_url = "https://information.dk/artikel/groen-omstilling"
        rows = [
            _UrlRow(
                id=uuid.uuid4(),
                url=shared_url,
                platform="twitter",
                arena="social_media",
                published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            ),
            _UrlRow(
                id=uuid.uuid4(),
                url=shared_url,
                platform="bluesky",
                arena="social_media",
                published_at=None,
            ),
        ]
        db = _mock_db_for_url_rows(rows)
        svc = DeduplicationService()

        result = await svc.find_url_duplicates(db)

        assert len(result) == 1
        first_record = result[0]["records"][0]
        assert "id" in first_record
        assert "platform" in first_record
        assert "arena" in first_record


# ---------------------------------------------------------------------------
# find_hash_duplicates()
# ---------------------------------------------------------------------------


class TestFindHashDuplicates:
    async def test_find_hash_duplicates_returns_empty_for_no_records(self) -> None:
        """Empty input returns an empty list."""
        db = _mock_db_for_hash_rows([])
        svc = DeduplicationService()

        result = await svc.find_hash_duplicates(db)

        assert result == []

    async def test_find_hash_duplicates_detects_same_hash_on_different_platforms(self) -> None:
        """Two records with the same content_hash on different platforms are grouped."""
        shared_hash = "a" * 64
        rows = [
            _HashRow(
                id=uuid.uuid4(),
                content_hash=shared_hash,
                platform="bluesky",
                arena="social_media",
            ),
            _HashRow(
                id=uuid.uuid4(),
                content_hash=shared_hash,
                platform="reddit",
                arena="social_media",
            ),
        ]
        db = _mock_db_for_hash_rows(rows)
        svc = DeduplicationService()

        result = await svc.find_hash_duplicates(db)

        assert len(result) == 1
        assert result[0]["content_hash"] == shared_hash
        assert result[0]["count"] == 2

    async def test_find_hash_duplicates_same_platform_same_arena_not_surfaced(self) -> None:
        """Records with the same hash, platform, AND arena are not surfaced.

        Same-platform duplicates are blocked by the DB unique constraint and
        should not appear here (the DB would reject them first).  But if they
        do appear (e.g. via a test fixture that bypasses constraints), the
        dedup service must NOT surface them as cross-platform duplicates.
        """
        shared_hash = "b" * 64
        rows = [
            _HashRow(
                id=uuid.uuid4(),
                content_hash=shared_hash,
                platform="bluesky",
                arena="social_media",
            ),
            _HashRow(
                id=uuid.uuid4(),
                content_hash=shared_hash,
                platform="bluesky",
                arena="social_media",
            ),
        ]
        db = _mock_db_for_hash_rows(rows)
        svc = DeduplicationService()

        result = await svc.find_hash_duplicates(db)

        assert result == []

    async def test_find_hash_duplicates_different_hashes_are_not_grouped(self) -> None:
        """Records with distinct content_hashes produce no duplicate groups."""
        rows = [
            _HashRow(
                id=uuid.uuid4(),
                content_hash="a" * 64,
                platform="bluesky",
                arena="social_media",
            ),
            _HashRow(
                id=uuid.uuid4(),
                content_hash="b" * 64,
                platform="reddit",
                arena="social_media",
            ),
        ]
        db = _mock_db_for_hash_rows(rows)
        svc = DeduplicationService()

        result = await svc.find_hash_duplicates(db)

        assert result == []

    async def test_find_hash_duplicates_group_has_count_field(self) -> None:
        """The 'count' key in a duplicate group equals the number of matching records."""
        shared_hash = "c" * 64
        rows = [
            _HashRow(
                id=uuid.uuid4(),
                content_hash=shared_hash,
                platform="bluesky",
                arena="social_media",
            ),
            _HashRow(
                id=uuid.uuid4(),
                content_hash=shared_hash,
                platform="reddit",
                arena="social_media",
            ),
            _HashRow(
                id=uuid.uuid4(),
                content_hash=shared_hash,
                platform="gdelt",
                arena="news_media",
            ),
        ]
        db = _mock_db_for_hash_rows(rows)
        svc = DeduplicationService()

        result = await svc.find_hash_duplicates(db)

        assert len(result) == 1
        assert result[0]["count"] == 3


# ---------------------------------------------------------------------------
# mark_duplicates()
# ---------------------------------------------------------------------------


class TestMarkDuplicates:
    async def test_mark_duplicates_returns_zero_for_empty_list(self) -> None:
        """mark_duplicates() returns 0 immediately when duplicate_ids is empty."""
        db = MagicMock()
        db.execute = AsyncMock()
        svc = DeduplicationService()

        count = await svc.mark_duplicates(db, canonical_id=uuid.uuid4(), duplicate_ids=[])

        assert count == 0
        db.execute.assert_not_called()

    async def test_mark_duplicates_calls_db_execute_with_update(self) -> None:
        """mark_duplicates() calls db.execute() with an UPDATE statement."""
        db = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 2
        db.execute = AsyncMock(return_value=mock_result)
        svc = DeduplicationService()

        canonical_id = uuid.uuid4()
        duplicate_ids = [uuid.uuid4(), uuid.uuid4()]

        count = await svc.mark_duplicates(db, canonical_id=canonical_id, duplicate_ids=duplicate_ids)

        assert count == 2
        db.execute.assert_called_once()

    async def test_mark_duplicates_returns_rowcount_from_db(self) -> None:
        """mark_duplicates() returns the rowcount reported by the DB execute result."""
        db = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 3
        db.execute = AsyncMock(return_value=mock_result)
        svc = DeduplicationService()

        count = await svc.mark_duplicates(
            db,
            canonical_id=uuid.uuid4(),
            duplicate_ids=[uuid.uuid4(), uuid.uuid4(), uuid.uuid4()],
        )

        assert count == 3


# ---------------------------------------------------------------------------
# run_dedup_pass()
# ---------------------------------------------------------------------------


class TestRunDedupPass:
    async def test_run_dedup_pass_returns_summary_dict_with_correct_keys(self) -> None:
        """run_dedup_pass() always returns a dict with url_groups, hash_groups, total_marked."""
        svc = DeduplicationService()
        db = MagicMock()
        db.commit = AsyncMock()

        with (
            patch.object(svc, "find_url_duplicates", new=AsyncMock(return_value=[])),
            patch.object(svc, "find_hash_duplicates", new=AsyncMock(return_value=[])),
        ):
            result = await svc.run_dedup_pass(db, run_id=uuid.uuid4())

        assert "url_groups" in result
        assert "hash_groups" in result
        assert "total_marked" in result

    async def test_run_dedup_pass_returns_zero_counts_for_no_duplicates(self) -> None:
        """When no duplicates are found, all counts in the summary are 0."""
        svc = DeduplicationService()
        db = MagicMock()
        db.commit = AsyncMock()

        with (
            patch.object(svc, "find_url_duplicates", new=AsyncMock(return_value=[])),
            patch.object(svc, "find_hash_duplicates", new=AsyncMock(return_value=[])),
        ):
            result = await svc.run_dedup_pass(db, run_id=uuid.uuid4())

        assert result["url_groups"] == 0
        assert result["hash_groups"] == 0
        assert result["total_marked"] == 0

    async def test_run_dedup_pass_calls_commit(self) -> None:
        """run_dedup_pass() calls db.commit() at the end of the pass."""
        svc = DeduplicationService()
        db = MagicMock()
        db.commit = AsyncMock()

        with (
            patch.object(svc, "find_url_duplicates", new=AsyncMock(return_value=[])),
            patch.object(svc, "find_hash_duplicates", new=AsyncMock(return_value=[])),
        ):
            await svc.run_dedup_pass(db, run_id=uuid.uuid4())

        db.commit.assert_called_once()

    async def test_run_dedup_pass_marks_url_duplicates_correctly(self) -> None:
        """run_dedup_pass() calls mark_duplicates for each URL duplicate group."""
        svc = DeduplicationService()
        db = MagicMock()
        db.commit = AsyncMock()

        id_a = uuid.uuid4()
        id_b = uuid.uuid4()
        canonical_id = min(id_a, id_b)

        url_group = {
            "normalised_url": "https://dr.dk/artikel",
            "records": [
                {"id": str(id_a), "platform": "bluesky", "arena": "social_media"},
                {"id": str(id_b), "platform": "reddit", "arena": "social_media"},
            ],
        }

        marked_calls: list[tuple] = []

        async def _fake_mark(db, canonical_id, duplicate_ids):
            marked_calls.append((canonical_id, duplicate_ids))
            return len(duplicate_ids)

        with (
            patch.object(svc, "find_url_duplicates", new=AsyncMock(return_value=[url_group])),
            patch.object(svc, "find_hash_duplicates", new=AsyncMock(return_value=[])),
            patch.object(svc, "mark_duplicates", side_effect=_fake_mark),
        ):
            result = await svc.run_dedup_pass(db, run_id=uuid.uuid4())

        assert len(marked_calls) == 1
        elected_canonical, dup_ids = marked_calls[0]
        assert elected_canonical == canonical_id
        assert result["total_marked"] == 1

    async def test_run_dedup_pass_url_groups_count_reflects_groups_found(self) -> None:
        """run_dedup_pass() sets url_groups to the number of URL duplicate groups."""
        svc = DeduplicationService()
        db = MagicMock()
        db.commit = AsyncMock()

        id1, id2, id3, id4 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        url_groups = [
            {
                "normalised_url": "https://dr.dk/article-a",
                "records": [
                    {"id": str(id1), "platform": "bluesky", "arena": "social_media"},
                    {"id": str(id2), "platform": "reddit", "arena": "social_media"},
                ],
            },
            {
                "normalised_url": "https://berlingske.dk/article-b",
                "records": [
                    {"id": str(id3), "platform": "x_twitter", "arena": "social_media"},
                    {"id": str(id4), "platform": "bluesky", "arena": "social_media"},
                ],
            },
        ]

        with (
            patch.object(svc, "find_url_duplicates", new=AsyncMock(return_value=url_groups)),
            patch.object(svc, "find_hash_duplicates", new=AsyncMock(return_value=[])),
            patch.object(svc, "mark_duplicates", new=AsyncMock(return_value=1)),
        ):
            result = await svc.run_dedup_pass(db, run_id=uuid.uuid4())

        assert result["url_groups"] == 2


# ---------------------------------------------------------------------------
# get_deduplication_service()
# ---------------------------------------------------------------------------


class TestGetDeduplicationService:
    def test_get_deduplication_service_returns_deduplication_service_instance(self) -> None:
        """get_deduplication_service() returns a DeduplicationService object."""
        svc = get_deduplication_service()

        assert isinstance(svc, DeduplicationService)

    def test_get_deduplication_service_returns_new_instance_each_call(self) -> None:
        """get_deduplication_service() is a factory, not a singleton."""
        svc_a = get_deduplication_service()
        svc_b = get_deduplication_service()

        assert svc_a is not svc_b


# ---------------------------------------------------------------------------
# H-01: compute_simhash() — pure function tests
# ---------------------------------------------------------------------------


class TestComputeSimhash:
    def test_compute_simhash_returns_integer(self) -> None:
        """compute_simhash() returns a Python int for any text input."""
        result = compute_simhash("hello world")

        assert isinstance(result, int)

    def test_compute_simhash_returns_64_bit_value(self) -> None:
        """The fingerprint is an unsigned 64-bit integer: 0 <= result < 2**64."""
        result = compute_simhash("klimaforandringer i Danmark")

        assert 0 <= result < (1 << 64)

    def test_compute_simhash_returns_zero_for_empty_string(self) -> None:
        """compute_simhash('') returns 0 (documented behaviour for empty input)."""
        result = compute_simhash("")

        assert result == 0

    def test_compute_simhash_returns_zero_for_whitespace_only(self) -> None:
        """compute_simhash() normalises whitespace; only-whitespace input returns 0."""
        result = compute_simhash("   ")

        assert result == 0

    def test_compute_simhash_is_deterministic(self) -> None:
        """The same input always produces the same fingerprint."""
        text = "Grøn omstilling er vigtig for velfærdsstaten"

        assert compute_simhash(text) == compute_simhash(text)

    def test_compute_simhash_similar_texts_have_low_hamming_distance(self) -> None:
        """Two nearly identical Danish texts have a Hamming distance <= 10."""
        a = compute_simhash("klimaforandringer og vejret i Danmark")
        b = compute_simhash("klimaforandringer og vejret i Danmark idag")

        assert hamming_distance(a, b) <= 10

    def test_compute_simhash_very_different_texts_have_higher_hamming_distance_than_similar(
        self,
    ) -> None:
        """A dissimilar pair has a larger Hamming distance than the similar pair above.

        We do not assert an absolute threshold for the different pair because
        SimHash distributes bits probabilistically.  Instead we assert that the
        ordering of distances is preserved: similar pair < different pair.
        """
        similar_a = compute_simhash("klimaforandringer og vejret i Danmark")
        similar_b = compute_simhash("klimaforandringer og vejret i Danmark idag")
        similar_dist = hamming_distance(similar_a, similar_b)

        different_a = compute_simhash("klimaforandringer og vejret")
        different_b = compute_simhash("den store mur i Kina")
        different_dist = hamming_distance(different_a, different_b)

        assert different_dist >= similar_dist, (
            f"Expected different pair (dist={different_dist}) to have distance "
            f">= similar pair (dist={similar_dist})"
        )

    def test_compute_simhash_preserves_danish_characters(self) -> None:
        """compute_simhash() handles æ, ø, å without raising an exception."""
        result = compute_simhash("Grøn omstilling: æøå er vigtige bogstaver")

        assert isinstance(result, int)
        assert 0 <= result < (1 << 64)


# ---------------------------------------------------------------------------
# H-01: hamming_distance() — pure function tests
# ---------------------------------------------------------------------------


class TestHammingDistance:
    def test_hamming_distance_identical_values_is_zero(self) -> None:
        """hamming_distance(x, x) == 0 for any x."""
        h = compute_simhash("test text for hamming distance")

        assert hamming_distance(h, h) == 0

    def test_hamming_distance_uses_xor(self) -> None:
        """hamming_distance(0b1010, 0b0101) == 4 (all 4 bits differ)."""
        assert hamming_distance(0b1010, 0b0101) == 4

    def test_hamming_distance_single_bit_difference(self) -> None:
        """hamming_distance(0b1000, 0b0000) == 1 (exactly one bit flipped)."""
        assert hamming_distance(0b1000, 0b0000) == 1

    def test_hamming_distance_all_64_bits_different(self) -> None:
        """hamming_distance(0, 2**64 - 1) == 64 (all 64 bits differ)."""
        assert hamming_distance(0, (1 << 64) - 1) == 64
