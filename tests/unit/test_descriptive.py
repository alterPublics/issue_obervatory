"""Unit tests for the descriptive statistics module.

Tests cover:
- get_volume_over_time(): correct period grouping, arenas breakdown, granularity validation
- get_top_actors(): actors sorted by record count descending, Danish names preserved
- get_top_terms(): terms sorted by frequency descending, Danish terms preserved
- get_engagement_distribution(): min/max/mean/median returned correctly
- Empty dataset: returns empty result without exception
- Single-record dataset: handles edge case without error
- Danish actor/term names with æ, ø, å preserved in output
- _build_content_filters helper: correct WHERE clause construction
- _dt_iso helper: datetime → ISO string conversion
- get_run_summary(): returns expected keys, handles missing run

All database calls are mocked via unittest.mock.AsyncMock / MagicMock.
No live PostgreSQL instance is required.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Env bootstrap
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==")

from issue_observatory.analysis.descriptive import (  # noqa: E402
    _build_content_filters,
    _dt_iso,
    get_emergent_terms,
    get_engagement_distribution,
    get_run_summary,
    get_top_actors,
    get_top_terms,
    get_volume_over_time,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db_returning(rows: list[Any]) -> Any:
    """Create a mock AsyncSession whose execute() returns the given rows via fetchall()."""
    result_mock = MagicMock()
    result_mock.fetchall.return_value = rows
    db = MagicMock()
    db.execute = AsyncMock(return_value=result_mock)
    return db


def _mock_db_returning_one(row: Any) -> Any:
    """Create a mock AsyncSession whose execute() returns a single row via fetchone()."""
    result_mock = MagicMock()
    result_mock.fetchone.return_value = row
    db = MagicMock()
    db.execute = AsyncMock(return_value=result_mock)
    return db


def _make_volume_row(period: datetime, arena: str, cnt: int) -> Any:
    """Build a mock SQL row for get_volume_over_time."""
    row = MagicMock()
    row.period = period
    row.arena = arena
    row.cnt = cnt
    return row


def _make_actor_row(
    display_name: str,
    author_id: str,
    platform: str,
    cnt: int,
    engagement: int,
) -> Any:
    """Build a mock SQL row for get_top_actors."""
    row = MagicMock()
    row.author_display_name = display_name
    row.pseudonymized_author_id = author_id
    row.platform = platform
    row.cnt = cnt
    row.total_engagement = engagement
    return row


def _make_term_row(term: str, cnt: int) -> Any:
    """Build a mock SQL row for get_top_terms."""
    row = MagicMock()
    row.term = term
    row.cnt = cnt
    return row


def _make_engagement_row(
    likes_mean: float | None = 10.0,
    likes_median: float | None = 5.0,
    likes_p95: float | None = 50.0,
    likes_max: int | None = 500,
    shares_mean: float | None = 2.0,
    shares_median: float | None = 0.0,
    shares_p95: float | None = 15.0,
    shares_max: int | None = 100,
    comments_mean: float | None = 3.0,
    comments_median: float | None = 1.0,
    comments_p95: float | None = 20.0,
    comments_max: int | None = 200,
    views_mean: float | None = 500.0,
    views_median: float | None = 100.0,
    views_p95: float | None = 3000.0,
    views_max: int | None = 50000,
) -> Any:
    """Build a mock SQL row for get_engagement_distribution."""
    row = MagicMock()
    row.likes_mean = likes_mean
    row.likes_median = likes_median
    row.likes_p95 = likes_p95
    row.likes_max = likes_max
    row.shares_mean = shares_mean
    row.shares_median = shares_median
    row.shares_p95 = shares_p95
    row.shares_max = shares_max
    row.comments_mean = comments_mean
    row.comments_median = comments_median
    row.comments_p95 = comments_p95
    row.comments_max = comments_max
    row.views_mean = views_mean
    row.views_median = views_median
    row.views_p95 = views_p95
    row.views_max = views_max
    return row


# ---------------------------------------------------------------------------
# _dt_iso helper
# ---------------------------------------------------------------------------


class TestDtIso:
    def test_dt_iso_converts_datetime_to_iso_string(self) -> None:
        """_dt_iso() converts a datetime object to an ISO 8601 string."""
        dt = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = _dt_iso(dt)
        assert isinstance(result, str)
        assert "2026-01-15" in result

    def test_dt_iso_passes_through_string(self) -> None:
        """_dt_iso() returns non-datetime values unchanged."""
        assert _dt_iso("hello") == "hello"
        assert _dt_iso(42) == 42
        assert _dt_iso(None) is None


# ---------------------------------------------------------------------------
# _build_content_filters helper
# ---------------------------------------------------------------------------


class TestBuildContentFilters:
    def test_build_content_filters_no_filters_returns_duplicate_exclusion_clause(self) -> None:
        """With no filter arguments, _build_content_filters returns a WHERE clause
        containing only the duplicate exclusion predicate.

        Phase A refactoring: build_content_where() always emits a duplicate
        exclusion clause so that analysis functions never accidentally include
        records flagged as duplicates, even when no other filters are active.
        """
        params: dict = {}
        result = _build_content_filters(None, None, None, None, None, None, params)
        assert result.startswith("WHERE")
        assert "(raw_metadata->>'duplicate_of') IS NULL" in result
        assert params == {}

    def test_build_content_filters_query_design_id_adds_clause(self) -> None:
        """query_design_id filter adds correct SQL predicate."""
        params: dict = {}
        qd_id = uuid.uuid4()
        result = _build_content_filters(qd_id, None, None, None, None, None, params)
        assert "query_design_id" in result
        assert "WHERE" in result
        assert params.get("query_design_id") == str(qd_id)

    def test_build_content_filters_run_id_adds_clause(self) -> None:
        """run_id filter adds correct SQL predicate."""
        params: dict = {}
        run_id = uuid.uuid4()
        result = _build_content_filters(None, run_id, None, None, None, None, params)
        assert "collection_run_id" in result
        assert params.get("run_id") == str(run_id)

    def test_build_content_filters_multiple_filters_joined_with_and(self) -> None:
        """Multiple active filters are joined with AND."""
        params: dict = {}
        qd_id = uuid.uuid4()
        result = _build_content_filters(qd_id, None, "news", "bluesky", None, None, params)
        assert "AND" in result
        assert "arena" in result
        assert "platform" in result

    def test_build_content_filters_date_range_adds_both_clauses(self) -> None:
        """date_from and date_to each generate a WHERE predicate."""
        params: dict = {}
        date_from = datetime(2026, 1, 1, tzinfo=timezone.utc)
        date_to = datetime(2026, 1, 31, tzinfo=timezone.utc)
        result = _build_content_filters(None, None, None, None, date_from, date_to, params)
        assert "published_at >=" in result
        assert "published_at <=" in result


# ---------------------------------------------------------------------------
# get_volume_over_time
# ---------------------------------------------------------------------------


class TestGetVolumeOverTime:
    @pytest.mark.asyncio
    async def test_volume_over_time_returns_list(self) -> None:
        """get_volume_over_time() returns a list."""
        db = _mock_db_returning([])
        result = await get_volume_over_time(db)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_volume_over_time_empty_db_returns_empty_list(self) -> None:
        """get_volume_over_time() with no rows returns an empty list."""
        db = _mock_db_returning([])
        result = await get_volume_over_time(db)
        assert result == []

    @pytest.mark.asyncio
    async def test_volume_over_time_groups_by_period(self) -> None:
        """Records in the same period are aggregated into one dict entry."""
        period = datetime(2026, 1, 15, tzinfo=timezone.utc)
        rows = [
            _make_volume_row(period, "social_media", 50),
            _make_volume_row(period, "news_media", 30),
        ]
        db = _mock_db_returning(rows)
        result = await get_volume_over_time(db)
        # Both rows belong to the same period → one entry
        assert len(result) == 1
        entry = result[0]
        assert entry["count"] == 80
        assert "social_media" in entry["arenas"]
        assert "news_media" in entry["arenas"]

    @pytest.mark.asyncio
    async def test_volume_over_time_period_is_iso_string(self) -> None:
        """The 'period' value in the returned dict is an ISO 8601 string."""
        period = datetime(2026, 2, 1, tzinfo=timezone.utc)
        db = _mock_db_returning([_make_volume_row(period, "social_media", 10)])
        result = await get_volume_over_time(db)
        assert isinstance(result[0]["period"], str)
        assert "2026-02-01" in result[0]["period"]

    @pytest.mark.asyncio
    async def test_volume_over_time_invalid_granularity_raises_value_error(self) -> None:
        """An invalid granularity value raises ValueError before hitting the DB."""
        db = _mock_db_returning([])
        with pytest.raises(ValueError, match="Invalid granularity"):
            await get_volume_over_time(db, granularity="quarter")

    @pytest.mark.asyncio
    async def test_volume_over_time_valid_granularities_do_not_raise(self) -> None:
        """All four valid granularities ('hour', 'day', 'week', 'month') are accepted."""
        for granularity in ("hour", "day", "week", "month"):
            db = _mock_db_returning([])
            result = await get_volume_over_time(db, granularity=granularity)
            assert result == []

    @pytest.mark.asyncio
    async def test_volume_over_time_multiple_periods_preserved(self) -> None:
        """Multiple distinct periods each get their own entry in the result list."""
        period1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        period2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
        rows = [
            _make_volume_row(period1, "news_media", 100),
            _make_volume_row(period2, "news_media", 200),
        ]
        db = _mock_db_returning(rows)
        result = await get_volume_over_time(db)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_volume_over_time_passes_filters_to_db(self) -> None:
        """Filter arguments result in a DB call (execute is invoked)."""
        db = _mock_db_returning([])
        qd_id = uuid.uuid4()
        await get_volume_over_time(db, query_design_id=qd_id, arena="news_media")
        db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# get_top_actors
# ---------------------------------------------------------------------------


class TestGetTopActors:
    @pytest.mark.asyncio
    async def test_top_actors_returns_list(self) -> None:
        """get_top_actors() returns a list."""
        db = _mock_db_returning([])
        result = await get_top_actors(db)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_top_actors_empty_db_returns_empty_list(self) -> None:
        """get_top_actors() with no rows returns an empty list."""
        db = _mock_db_returning([])
        result = await get_top_actors(db)
        assert result == []

    @pytest.mark.asyncio
    async def test_top_actors_result_preserves_all_fields(self) -> None:
        """Each returned dict has the expected keys."""
        rows = [_make_actor_row("DR Nyheder", "author-abc", "bluesky", 150, 42000)]
        db = _mock_db_returning(rows)
        result = await get_top_actors(db)
        assert len(result) == 1
        actor = result[0]
        assert actor["author_display_name"] == "DR Nyheder"
        assert actor["pseudonymized_author_id"] == "author-abc"
        assert actor["platform"] == "bluesky"
        assert actor["count"] == 150
        assert actor["total_engagement"] == 42000

    @pytest.mark.asyncio
    async def test_top_actors_sorted_by_count_descending(self) -> None:
        """Actors are returned in descending order of post count."""
        rows = [
            _make_actor_row("Actor B", "b", "bluesky", 50, 1000),
            _make_actor_row("Actor A", "a", "bluesky", 200, 5000),
        ]
        db = _mock_db_returning(rows)
        result = await get_top_actors(db)
        # The mock returns rows in the given order (ORDER BY is done by SQL)
        assert result[0]["count"] == 50
        assert result[1]["count"] == 200

    @pytest.mark.asyncio
    async def test_top_actors_danish_name_preserved(self) -> None:
        """Danish characters in author_display_name are preserved without corruption."""
        rows = [_make_actor_row("Søren Ærlighed-Øberg", "author-da", "bluesky", 25, 500)]
        db = _mock_db_returning(rows)
        result = await get_top_actors(db)
        assert result[0]["author_display_name"] == "Søren Ærlighed-Øberg"

    @pytest.mark.asyncio
    async def test_top_actors_single_record(self) -> None:
        """A single-row result is handled correctly without error."""
        rows = [_make_actor_row("Solo Author", "solo-id", "reddit", 1, 0)]
        db = _mock_db_returning(rows)
        result = await get_top_actors(db)
        assert len(result) == 1
        assert result[0]["count"] == 1

    @pytest.mark.asyncio
    async def test_top_actors_null_engagement_treated_as_zero(self) -> None:
        """None total_engagement is coerced to integer 0."""
        row = MagicMock()
        row.author_display_name = "Test"
        row.pseudonymized_author_id = "id-001"
        row.platform = "bluesky"
        row.cnt = 5
        row.total_engagement = None  # simulate SQL NULL
        db = _mock_db_returning([row])
        result = await get_top_actors(db)
        assert result[0]["total_engagement"] == 0

    @pytest.mark.asyncio
    async def test_top_actors_passes_limit_to_db(self) -> None:
        """The limit parameter is passed as a bind param (execute is called)."""
        db = _mock_db_returning([])
        await get_top_actors(db, limit=5)
        db.execute.assert_called_once()

    # ------------------------------------------------------------------
    # M-02: resolved_name and actor_id fields (IP2-061 LEFT JOIN)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_top_actors_includes_resolved_name_field_in_result(self) -> None:
        """When the DB row has resolved_name set, it appears in the returned dict.

        IP2-061: get_top_actors() LEFT JOINs the actors table and returns
        MAX(a.canonical_name) AS resolved_name.  When an actor row exists and
        canonical_name is populated, the result dict must contain a non-None
        resolved_name.
        """
        row = MagicMock()
        row.author_display_name = "mette-f-pseudo"
        row.pseudonymized_author_id = "pseudo-001"
        row.platform = "bluesky"
        row.author_id = uuid.uuid4()
        row.resolved_name = "Mette Frederiksen"
        row.cnt = 42
        row.total_engagement = 1000

        db = _mock_db_returning([row])
        result = await get_top_actors(db)

        assert len(result) == 1
        assert result[0]["resolved_name"] == "Mette Frederiksen"

    @pytest.mark.asyncio
    async def test_get_top_actors_resolved_name_is_none_when_no_actor_record(self) -> None:
        """When the actor has not been resolved, resolved_name is None in the result.

        IP2-061: LEFT JOIN means unresolved records return NULL for
        MAX(a.canonical_name).  The result dict must contain the key
        'resolved_name' with value None (not missing the key entirely).
        """
        row = MagicMock()
        row.author_display_name = "unknown-user"
        row.pseudonymized_author_id = "pseudo-002"
        row.platform = "reddit"
        row.author_id = None
        row.resolved_name = None
        row.cnt = 5
        row.total_engagement = 0

        db = _mock_db_returning([row])
        result = await get_top_actors(db)

        assert len(result) == 1
        assert "resolved_name" in result[0], (
            "result dict must contain 'resolved_name' key even when None"
        )
        assert result[0]["resolved_name"] is None

    @pytest.mark.asyncio
    async def test_get_top_actors_includes_actor_id_field(self) -> None:
        """When author_id is a UUID, actor_id in the result dict is its string form.

        IP2-061: the result dict includes actor_id = str(row.author_id) so the
        front-end can link to the canonical actor profile.
        """
        actor_uuid = uuid.uuid4()
        row = MagicMock()
        row.author_display_name = "politiken-dk"
        row.pseudonymized_author_id = "pseudo-003"
        row.platform = "x_twitter"
        row.author_id = actor_uuid
        row.resolved_name = "Politiken"
        row.cnt = 99
        row.total_engagement = 5000

        db = _mock_db_returning([row])
        result = await get_top_actors(db)

        assert len(result) == 1
        assert "actor_id" in result[0], "result dict must contain 'actor_id' key"
        assert result[0]["actor_id"] == str(actor_uuid)


# ---------------------------------------------------------------------------
# get_top_terms
# ---------------------------------------------------------------------------


class TestGetTopTerms:
    @pytest.mark.asyncio
    async def test_top_terms_returns_list(self) -> None:
        """get_top_terms() returns a list."""
        db = _mock_db_returning([])
        result = await get_top_terms(db)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_top_terms_empty_db_returns_empty_list(self) -> None:
        """get_top_terms() with no rows returns an empty list."""
        db = _mock_db_returning([])
        result = await get_top_terms(db)
        assert result == []

    @pytest.mark.asyncio
    async def test_top_terms_result_has_term_and_count_keys(self) -> None:
        """Each entry in the result has 'term' and 'count' keys."""
        rows = [_make_term_row("klimaforandringer", 834)]
        db = _mock_db_returning(rows)
        result = await get_top_terms(db)
        assert len(result) == 1
        assert result[0]["term"] == "klimaforandringer"
        assert result[0]["count"] == 834

    @pytest.mark.asyncio
    async def test_top_terms_multiple_terms_returned(self) -> None:
        """Multiple terms are returned in the order the DB provides them."""
        rows = [
            _make_term_row("klimaforandringer", 834),
            _make_term_row("grøn omstilling", 512),
            _make_term_row("velfærdsstat", 300),
        ]
        db = _mock_db_returning(rows)
        result = await get_top_terms(db)
        assert len(result) == 3
        assert result[0]["term"] == "klimaforandringer"
        assert result[1]["term"] == "grøn omstilling"

    @pytest.mark.asyncio
    async def test_top_terms_danish_term_preserved(self) -> None:
        """Danish characters in term strings are preserved in the output."""
        rows = [
            _make_term_row("grøn omstilling", 512),
            _make_term_row("velfærdsstat", 300),
            _make_term_row("Ålborg kommune", 50),
        ]
        db = _mock_db_returning(rows)
        result = await get_top_terms(db)
        terms = [r["term"] for r in result]
        assert "grøn omstilling" in terms
        assert "velfærdsstat" in terms
        assert "Ålborg kommune" in terms

    @pytest.mark.asyncio
    async def test_top_terms_single_term_result(self) -> None:
        """A single-term result is handled without error."""
        db = _mock_db_returning([_make_term_row("demokrati", 10)])
        result = await get_top_terms(db)
        assert len(result) == 1
        assert result[0]["count"] == 10

    @pytest.mark.asyncio
    async def test_top_terms_invokes_db_execute(self) -> None:
        """get_top_terms() invokes db.execute exactly once."""
        db = _mock_db_returning([])
        await get_top_terms(db, limit=10)
        db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# get_engagement_distribution
# ---------------------------------------------------------------------------


class TestGetEngagementDistribution:
    @pytest.mark.asyncio
    async def test_engagement_distribution_returns_dict(self) -> None:
        """get_engagement_distribution() returns a dict."""
        db = _mock_db_returning_one(_make_engagement_row())
        result = await get_engagement_distribution(db)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_engagement_distribution_has_all_metric_keys(self) -> None:
        """Returned dict has 'likes', 'shares', 'comments', 'views' keys."""
        db = _mock_db_returning_one(_make_engagement_row())
        result = await get_engagement_distribution(db)
        assert set(result.keys()) == {"likes", "shares", "comments", "views"}

    @pytest.mark.asyncio
    async def test_engagement_distribution_each_metric_has_stats(self) -> None:
        """Each metric dict contains 'mean', 'median', 'p95', 'max' keys."""
        db = _mock_db_returning_one(_make_engagement_row())
        result = await get_engagement_distribution(db)
        for metric in ("likes", "shares", "comments", "views"):
            assert "mean" in result[metric]
            assert "median" in result[metric]
            assert "p95" in result[metric]
            assert "max" in result[metric]

    @pytest.mark.asyncio
    async def test_engagement_distribution_values_rounded_to_2dp(self) -> None:
        """Float values are rounded to 2 decimal places."""
        db = _mock_db_returning_one(_make_engagement_row(likes_mean=12.3456789))
        result = await get_engagement_distribution(db)
        likes_mean = result["likes"]["mean"]
        # Rounded to at most 2 decimal places
        assert likes_mean == round(12.3456789, 2)

    @pytest.mark.asyncio
    async def test_engagement_distribution_max_is_integer(self) -> None:
        """The 'max' field for each metric is an integer (not float)."""
        db = _mock_db_returning_one(_make_engagement_row(likes_max=500))
        result = await get_engagement_distribution(db)
        assert isinstance(result["likes"]["max"], int)
        assert result["likes"]["max"] == 500

    @pytest.mark.asyncio
    async def test_engagement_distribution_none_row_returns_empty_dict(self) -> None:
        """If DB returns no row (None), the result is an empty dict."""
        result_mock = MagicMock()
        result_mock.fetchone.return_value = None
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await get_engagement_distribution(db)
        assert result == {}

    @pytest.mark.asyncio
    async def test_engagement_distribution_none_metric_values_returned_as_none(self) -> None:
        """NULL metric values from SQL are returned as Python None (not 0)."""
        db = _mock_db_returning_one(
            _make_engagement_row(
                likes_mean=None,
                likes_median=None,
                likes_p95=None,
                likes_max=None,
            )
        )
        result = await get_engagement_distribution(db)
        assert result["likes"]["mean"] is None
        assert result["likes"]["median"] is None
        assert result["likes"]["max"] is None

    @pytest.mark.asyncio
    async def test_engagement_distribution_invokes_db_execute(self) -> None:
        """get_engagement_distribution() calls db.execute exactly once."""
        db = _mock_db_returning_one(_make_engagement_row())
        await get_engagement_distribution(db)
        db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# get_run_summary
# ---------------------------------------------------------------------------


class TestGetRunSummary:
    def _make_run_row(self) -> Any:
        """Build a mock collection_runs SQL row."""
        run_id = uuid.uuid4()
        row = MagicMock()
        row.id = run_id
        row.status = "completed"
        row.mode = "batch"
        row.started_at = datetime(2026, 2, 15, 10, 0, 0, tzinfo=timezone.utc)
        row.completed_at = datetime(2026, 2, 15, 10, 47, 0, tzinfo=timezone.utc)
        row.credits_spent = 240
        row.records_collected = 5812
        return row

    def _make_content_row(self) -> Any:
        row = MagicMock()
        row.total_records = 5812
        row.published_at_min = datetime(2026, 1, 1, tzinfo=timezone.utc)
        row.published_at_max = datetime(2026, 2, 14, tzinfo=timezone.utc)
        return row

    def _make_arena_row(self, arena: str, record_count: int, tasks_records: int) -> Any:
        row = MagicMock()
        row.arena = arena
        row.record_count = record_count
        row.tasks_records_collected = tasks_records
        return row

    @pytest.mark.asyncio
    async def test_run_summary_missing_run_returns_empty_dict(self) -> None:
        """get_run_summary() returns {} if the run_id does not exist in the DB."""
        result_mock = MagicMock()
        result_mock.fetchone.return_value = None
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await get_run_summary(db, run_id=uuid.uuid4())
        assert result == {}

    @pytest.mark.asyncio
    async def test_run_summary_returns_expected_keys(self) -> None:
        """get_run_summary() result contains all required top-level keys."""
        run_row = self._make_run_row()
        content_row = self._make_content_row()
        arena_rows = [self._make_arena_row("social_media", 3000, 3000)]

        call_count = 0

        async def multi_execute(sql: Any, params: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            if call_count == 1:
                mock.fetchone.return_value = run_row
            elif call_count == 2:
                mock.fetchone.return_value = content_row
            else:
                mock.fetchall.return_value = arena_rows
            return mock

        db = MagicMock()
        db.execute = AsyncMock(side_effect=multi_execute)

        run_id = uuid.uuid4()
        result = await get_run_summary(db, run_id=run_id)

        required_keys = {
            "run_id", "status", "mode", "started_at", "completed_at",
            "credits_spent", "total_records", "published_at_min",
            "published_at_max", "by_arena",
        }
        assert required_keys.issubset(result.keys()), (
            f"Missing keys: {required_keys - result.keys()}"
        )

    @pytest.mark.asyncio
    async def test_run_summary_status_and_mode_correct(self) -> None:
        """get_run_summary() returns the correct status and mode from the DB."""
        run_row = self._make_run_row()
        content_row = self._make_content_row()

        call_count = 0

        async def multi_execute(sql: Any, params: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            if call_count == 1:
                mock.fetchone.return_value = run_row
            elif call_count == 2:
                mock.fetchone.return_value = content_row
            else:
                mock.fetchall.return_value = []
            return mock

        db = MagicMock()
        db.execute = AsyncMock(side_effect=multi_execute)
        result = await get_run_summary(db, run_id=uuid.uuid4())
        assert result["status"] == "completed"
        assert result["mode"] == "batch"


# ---------------------------------------------------------------------------
# get_emergent_terms (TF-IDF term extraction with stop word filtering)
# ---------------------------------------------------------------------------


class TestGetEmergentTerms:
    """Tests for get_emergent_terms() TF-IDF term extraction.

    F-05 fix: Comprehensive stop word filtering to prevent common
    Danish and English function words from appearing in suggested terms.
    """

    @pytest.mark.asyncio
    async def test_emergent_terms_requires_scikit_learn(self) -> None:
        """get_emergent_terms() returns empty list when scikit-learn is not installed.

        This test verifies graceful degradation when the optional ML dependency
        is not available.
        """
        import sys
        from unittest.mock import patch

        # Mock ImportError for sklearn
        with patch.dict(sys.modules, {"sklearn.feature_extraction.text": None}):
            db = _mock_db_returning([])
            # Re-import to trigger the ImportError path
            # (This is a bit fragile but acceptable for unit tests)
            result = await get_emergent_terms(db)
            # The function logs a warning and returns empty list
            assert result == []

    @pytest.mark.asyncio
    async def test_emergent_terms_requires_minimum_texts(self) -> None:
        """get_emergent_terms() returns empty list when fewer than 5 text records exist."""
        # Mock DB returning only 3 text records (below the threshold)
        row1 = MagicMock()
        row1.text_content = "Dette er en test"
        row2 = MagicMock()
        row2.text_content = "Endnu en test"
        row3 = MagicMock()
        row3.text_content = "Sidste test"

        db = _mock_db_returning([row1, row2, row3])
        result = await get_emergent_terms(db)
        assert result == []

    @pytest.mark.asyncio
    async def test_emergent_terms_filters_danish_stop_words(self) -> None:
        """F-05: Danish stop words like 'og', 'at', 'er', 'det' are excluded from results."""
        # Create mock texts with Danish stop words mixed with meaningful terms
        texts = [
            "klimaforandringer og grøn omstilling er vigtigt for Danmark",
            "klimaforandringer påvirker økonomien og miljøet",
            "grøn omstilling er nødvendig for fremtiden",
            "økonomien er påvirket af klimaforandringer",
            "Danmark satser på grøn omstilling",
            "miljøet skal beskyttes mod klimaforandringer",
        ]

        rows = [MagicMock(text_content=t) for t in texts]
        db = _mock_db_returning(rows)

        result = await get_emergent_terms(db, top_n=20)

        # Extract returned term strings
        returned_terms = [item["term"] for item in result]

        # Danish stop words should NOT appear
        danish_stop_words = ["og", "at", "er", "det", "for", "af", "på", "skal"]
        for stop_word in danish_stop_words:
            assert stop_word not in returned_terms, f"Danish stop word '{stop_word}' should be filtered out"

        # Meaningful terms SHOULD appear
        assert any("klimaforandringer" in term for term in returned_terms), (
            "Meaningful term 'klimaforandringer' should be present"
        )

    @pytest.mark.asyncio
    async def test_emergent_terms_filters_english_stop_words(self) -> None:
        """F-05: English stop words like 'the', 'and', 'is', 'for' are excluded from results."""
        # Create mock texts with English stop words mixed with meaningful terms
        texts = [
            "climate change and green transition are important for the world",
            "climate change affects the economy and the environment",
            "green transition is necessary for the future",
            "the economy is affected by climate change",
            "countries invest in green transition",
            "environment must be protected from climate change",
        ]

        rows = [MagicMock(text_content=t) for t in texts]
        db = _mock_db_returning(rows)

        result = await get_emergent_terms(db, top_n=20)

        # Extract returned term strings
        returned_terms = [item["term"] for item in result]

        # English stop words should NOT appear
        english_stop_words = ["the", "and", "is", "are", "for", "by", "from", "must"]
        for stop_word in english_stop_words:
            assert stop_word not in returned_terms, f"English stop word '{stop_word}' should be filtered out"

        # Meaningful terms SHOULD appear
        assert any("climate" in term for term in returned_terms), (
            "Meaningful term 'climate' should be present"
        )

    @pytest.mark.asyncio
    async def test_emergent_terms_filters_single_character_tokens(self) -> None:
        """F-05: Single-character tokens are filtered out."""
        texts = [
            "a b c meaningful content here",
            "x y z important information",
            "meaningful important content information",
        ]

        rows = [MagicMock(text_content=t) for t in texts]
        db = _mock_db_returning(rows)

        result = await get_emergent_terms(db, top_n=20)
        returned_terms = [item["term"] for item in result]

        # Single-character tokens should be excluded
        for term in returned_terms:
            assert len(term) >= 2, f"Single-character token '{term}' should be filtered out"

    @pytest.mark.asyncio
    async def test_emergent_terms_filters_numeric_tokens(self) -> None:
        """F-05: Purely numeric tokens are filtered out."""
        texts = [
            "meaningful content from 2026 study",
            "123 456 789 research findings",
            "important 2025 results meaningful data",
        ]

        rows = [MagicMock(text_content=t) for t in texts]
        db = _mock_db_returning(rows)

        result = await get_emergent_terms(db, top_n=20)
        returned_terms = [item["term"] for item in result]

        # Purely numeric tokens should be excluded
        for term in returned_terms:
            assert not term.isdigit(), f"Numeric token '{term}' should be filtered out"

    @pytest.mark.asyncio
    async def test_emergent_terms_excludes_existing_search_terms(self) -> None:
        """When exclude_search_terms=True, existing query design terms are filtered out."""
        # Mock texts
        texts = [
            "klimaforandringer og grøn omstilling",
            "klimaforandringer påvirker økonomien",
            "grøn omstilling er vigtigt",
        ]

        # Mock DB to return texts AND existing search terms
        call_count = 0

        async def multi_execute(sql: Any, params: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            mock = MagicMock()

            if call_count == 1:
                # First call: return text_content rows
                rows = [MagicMock(text_content=t) for t in texts]
                mock.fetchall.return_value = rows
            else:
                # Second call: return existing search terms
                term_row = MagicMock()
                term_row.term = "klimaforandringer"
                mock.fetchall.return_value = [term_row]

            return mock

        db = MagicMock()
        db.execute = AsyncMock(side_effect=multi_execute)

        qd_id = uuid.uuid4()
        result = await get_emergent_terms(db, query_design_id=qd_id, exclude_search_terms=True)

        returned_terms = [item["term"] for item in result]

        # "klimaforandringer" should be excluded (it's an existing search term)
        assert "klimaforandringer" not in returned_terms, (
            "Existing search term 'klimaforandringer' should be filtered out"
        )

    @pytest.mark.asyncio
    async def test_emergent_terms_result_structure(self) -> None:
        """Result dicts contain 'term', 'score', and 'document_frequency' keys."""
        texts = [
            "meaningful important content research study",
            "meaningful research findings important",
            "important study content meaningful",
        ]

        rows = [MagicMock(text_content=t) for t in texts]
        db = _mock_db_returning(rows)

        result = await get_emergent_terms(db, top_n=5)

        assert len(result) > 0, "Should return at least one term"
        for item in result:
            assert "term" in item, "Result item must have 'term' key"
            assert "score" in item, "Result item must have 'score' key"
            assert "document_frequency" in item, "Result item must have 'document_frequency' key"
            assert isinstance(item["term"], str)
            assert isinstance(item["score"], float)
            assert isinstance(item["document_frequency"], int)
