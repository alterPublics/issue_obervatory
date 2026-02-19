"""Unit tests for analysis/alerting.py and the VolumeSpike data model (GR-09).

Covers:
- detect_volume_spikes() returns empty list when fewer than 7 prior runs exist
  (grace period guard — prevents false positives on new query designs)
- VolumeSpike.to_dict() serializes all fields correctly and rounds floats
- threshold_multiplier=2.0 correctly flags spikes where current > 2x rolling average
- Absolute minimum count guard (_MIN_ABSOLUTE_COUNT=10) suppresses low-volume false positives

These tests use mock AsyncSession objects — no live database required.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Env bootstrap (must run before any application imports)
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault(
    "CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA=="
)

from issue_observatory.analysis.alerting import VolumeSpike, detect_volume_spikes  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_current_counts_row(arena: str, platform: str, cnt: int) -> MagicMock:
    """Return a mock row as returned by the current-run counts query."""
    row = MagicMock()
    row.arena = arena
    row.platform = platform
    row.cnt = cnt
    return row


def _make_prior_run_row(run_id: str) -> MagicMock:
    """Return a mock row as returned by the prior runs query."""
    row = MagicMock()
    row.id = run_id
    return row


def _make_rolling_avg_row(arena: str, platform: str, avg_count: float) -> MagicMock:
    """Return a mock row as returned by the rolling average query."""
    row = MagicMock()
    row.arena = arena
    row.platform = platform
    row.avg_count = avg_count
    return row


def _make_top_terms_row(term: str) -> MagicMock:
    """Return a mock row as returned by the top-terms query."""
    row = MagicMock()
    row.term = term
    return row


def _build_mock_session(
    current_rows: list[MagicMock],
    prior_run_rows: list[MagicMock],
    rolling_avg_rows: list[MagicMock],
    top_terms_rows: list[MagicMock] | None = None,
) -> MagicMock:
    """Build a mock AsyncSession that returns canned data for each SQL query.

    detect_volume_spikes() makes these queries in order:
    1. current counts  (fetchall)
    2. prior run IDs   (fetchall)
    3. rolling avg     (fetchall, only when >= _ROLLING_WINDOW prior runs)
    4. top terms       (fetchall, once per spike — only when spikes found)
    """
    call_count = 0
    top_terms = top_terms_rows or []

    async def mock_execute(sql: object, params: dict | None = None) -> MagicMock:
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.fetchall.return_value = current_rows
        elif call_count == 2:
            result.fetchall.return_value = prior_run_rows
        elif call_count == 3:
            result.fetchall.return_value = rolling_avg_rows
        else:
            # Subsequent calls are top-terms queries, one per spike
            result.fetchall.return_value = top_terms
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=mock_execute)
    return session


# ---------------------------------------------------------------------------
# VolumeSpike.to_dict()
# ---------------------------------------------------------------------------


class TestVolumeSpikeToDict:
    def test_to_dict_contains_all_fields(self) -> None:
        """VolumeSpike.to_dict() returns a dict with all documented keys."""
        spike = VolumeSpike(
            arena_name="social",
            platform="bluesky",
            current_count=42,
            rolling_7d_average=15.0,
            ratio=2.8,
            top_terms=["grønland", "selvstændighed"],
        )
        result = spike.to_dict()

        assert result["arena_name"] == "social"
        assert result["platform"] == "bluesky"
        assert result["current_count"] == 42
        assert result["rolling_7d_average"] == 15.0
        assert result["ratio"] == 2.8
        assert result["top_terms"] == ["grønland", "selvstændighed"]

    def test_to_dict_rounds_floats_to_two_decimal_places(self) -> None:
        """VolumeSpike.to_dict() rounds rolling_7d_average and ratio to 2 d.p."""
        spike = VolumeSpike(
            arena_name="news",
            platform="reddit",
            current_count=100,
            rolling_7d_average=33.333333333,
            ratio=3.0000001,
            top_terms=[],
        )
        result = spike.to_dict()

        assert result["rolling_7d_average"] == round(33.333333333, 2)
        assert result["ratio"] == round(3.0000001, 2)

    def test_to_dict_empty_top_terms(self) -> None:
        """VolumeSpike.to_dict() serializes an empty top_terms list correctly."""
        spike = VolumeSpike(
            arena_name="web",
            platform="wayback",
            current_count=20,
            rolling_7d_average=8.0,
            ratio=2.5,
        )
        result = spike.to_dict()
        assert result["top_terms"] == []

    def test_to_dict_preserves_danish_terms(self) -> None:
        """VolumeSpike.to_dict() preserves æ, ø, å in top_terms strings."""
        spike = VolumeSpike(
            arena_name="social",
            platform="telegram",
            current_count=50,
            rolling_7d_average=10.0,
            ratio=5.0,
            top_terms=["grønland", "økonomi", "åbenhed"],
        )
        result = spike.to_dict()
        assert "grønland" in result["top_terms"]
        assert "økonomi" in result["top_terms"]
        assert "åbenhed" in result["top_terms"]


# ---------------------------------------------------------------------------
# detect_volume_spikes() — grace period (insufficient history)
# ---------------------------------------------------------------------------


class TestDetectVolumeSpikesGracePeriod:
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_zero_prior_runs(self) -> None:
        """detect_volume_spikes() returns [] when the query design has no prior runs.

        This is the brand-new query design case: the rolling window has no data,
        so no threshold comparison can be made.
        """
        session = _build_mock_session(
            current_rows=[_make_current_counts_row("social", "bluesky", 50)],
            prior_run_rows=[],  # No prior runs at all
            rolling_avg_rows=[],
        )

        result = await detect_volume_spikes(
            session=session,
            query_design_id=uuid.uuid4(),
            collection_run_id=uuid.uuid4(),
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_fewer_than_seven_prior_runs(self) -> None:
        """detect_volume_spikes() returns [] with 6 prior runs (below 7-run minimum).

        The rolling window requires exactly 7 completed prior runs.  With fewer,
        the grace period applies and no spike is declared.
        """
        prior_runs = [_make_prior_run_row(str(uuid.uuid4())) for _ in range(6)]

        session = _build_mock_session(
            current_rows=[_make_current_counts_row("social", "bluesky", 100)],
            prior_run_rows=prior_runs,  # 6 runs — one short of the required 7
            rolling_avg_rows=[],
        )

        result = await detect_volume_spikes(
            session=session,
            query_design_id=uuid.uuid4(),
            collection_run_id=uuid.uuid4(),
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_records_in_current_run(self) -> None:
        """detect_volume_spikes() returns [] when the current run collected nothing."""
        session = _build_mock_session(
            current_rows=[],  # Empty current run
            prior_run_rows=[_make_prior_run_row(str(uuid.uuid4())) for _ in range(7)],
            rolling_avg_rows=[],
        )

        result = await detect_volume_spikes(
            session=session,
            query_design_id=uuid.uuid4(),
            collection_run_id=uuid.uuid4(),
        )

        assert result == []


# ---------------------------------------------------------------------------
# detect_volume_spikes() — threshold logic
# ---------------------------------------------------------------------------


class TestDetectVolumeSpikesThreshold:
    @pytest.mark.asyncio
    async def test_flags_spike_when_current_exceeds_two_times_rolling_average(self) -> None:
        """detect_volume_spikes() returns a VolumeSpike when current > 2x rolling average.

        Setup:
        - Rolling average for social/bluesky: 10.0 records per run
        - Current run: 25 records
        - Threshold multiplier: 2.0 (default)
        - 25 > 2 * 10 = 20, AND 25 >= _MIN_ABSOLUTE_COUNT (10)
        - Expected: one spike returned
        """
        prior_runs = [_make_prior_run_row(str(uuid.uuid4())) for _ in range(7)]

        session = _build_mock_session(
            current_rows=[_make_current_counts_row("social", "bluesky", 25)],
            prior_run_rows=prior_runs,
            rolling_avg_rows=[_make_rolling_avg_row("social", "bluesky", 10.0)],
            top_terms_rows=[_make_top_terms_row("grønland"), _make_top_terms_row("selvstændighed")],
        )

        result = await detect_volume_spikes(
            session=session,
            query_design_id=uuid.uuid4(),
            collection_run_id=uuid.uuid4(),
            threshold_multiplier=2.0,
        )

        assert len(result) == 1
        spike = result[0]
        assert isinstance(spike, VolumeSpike)
        assert spike.arena_name == "social"
        assert spike.platform == "bluesky"
        assert spike.current_count == 25
        assert spike.rolling_7d_average == 10.0
        assert spike.ratio > 2.0

    @pytest.mark.asyncio
    async def test_does_not_flag_when_current_equals_exactly_two_times_average(self) -> None:
        """detect_volume_spikes() does not flag when current == exactly 2x average.

        The condition is strict greater-than: current > threshold * average.
        current == threshold * average must NOT trigger a spike.
        """
        prior_runs = [_make_prior_run_row(str(uuid.uuid4())) for _ in range(7)]

        # 20 records, rolling average 10.0 -> ratio = 2.0 exactly (not > 2.0)
        session = _build_mock_session(
            current_rows=[_make_current_counts_row("social", "bluesky", 20)],
            prior_run_rows=prior_runs,
            rolling_avg_rows=[_make_rolling_avg_row("social", "bluesky", 10.0)],
        )

        result = await detect_volume_spikes(
            session=session,
            query_design_id=uuid.uuid4(),
            collection_run_id=uuid.uuid4(),
            threshold_multiplier=2.0,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_does_not_flag_when_current_is_below_minimum_absolute_count(self) -> None:
        """detect_volume_spikes() does not flag when current_count < 10 despite high ratio.

        Even with a very high ratio (3x average), a current count below
        _MIN_ABSOLUTE_COUNT (10) must not trigger a spike alert — the ratio
        arithmetic is not meaningful at low absolute counts.
        """
        prior_runs = [_make_prior_run_row(str(uuid.uuid4())) for _ in range(7)]

        # 9 records, rolling average 3.0 -> ratio = 3.0 (exceeds threshold)
        # But 9 < _MIN_ABSOLUTE_COUNT (10) so no spike
        session = _build_mock_session(
            current_rows=[_make_current_counts_row("social", "bluesky", 9)],
            prior_run_rows=prior_runs,
            rolling_avg_rows=[_make_rolling_avg_row("social", "bluesky", 3.0)],
        )

        result = await detect_volume_spikes(
            session=session,
            query_design_id=uuid.uuid4(),
            collection_run_id=uuid.uuid4(),
            threshold_multiplier=2.0,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_custom_threshold_multiplier_applies_correctly(self) -> None:
        """detect_volume_spikes() respects a custom threshold_multiplier value.

        With threshold_multiplier=3.0 and rolling average 10, a count of 25
        (ratio=2.5) must NOT trigger a spike (2.5 <= 3.0).
        A count of 35 (ratio=3.5) MUST trigger a spike (3.5 > 3.0).
        """
        prior_runs = [_make_prior_run_row(str(uuid.uuid4())) for _ in range(7)]

        # 25 records with threshold 3.0: 25/10 = 2.5, not > 3.0 — no spike
        session_no_spike = _build_mock_session(
            current_rows=[_make_current_counts_row("social", "bluesky", 25)],
            prior_run_rows=prior_runs,
            rolling_avg_rows=[_make_rolling_avg_row("social", "bluesky", 10.0)],
        )
        result_no_spike = await detect_volume_spikes(
            session=session_no_spike,
            query_design_id=uuid.uuid4(),
            collection_run_id=uuid.uuid4(),
            threshold_multiplier=3.0,
        )
        assert result_no_spike == []

        # 35 records with threshold 3.0: 35/10 = 3.5, > 3.0 — spike
        prior_runs_2 = [_make_prior_run_row(str(uuid.uuid4())) for _ in range(7)]
        session_spike = _build_mock_session(
            current_rows=[_make_current_counts_row("social", "bluesky", 35)],
            prior_run_rows=prior_runs_2,
            rolling_avg_rows=[_make_rolling_avg_row("social", "bluesky", 10.0)],
            top_terms_rows=[],
        )
        result_spike = await detect_volume_spikes(
            session=session_spike,
            query_design_id=uuid.uuid4(),
            collection_run_id=uuid.uuid4(),
            threshold_multiplier=3.0,
        )
        assert len(result_spike) == 1
        assert result_spike[0].current_count == 35

    @pytest.mark.asyncio
    async def test_spike_result_has_correct_ratio(self) -> None:
        """detect_volume_spikes() computes ratio correctly as current / rolling_average."""
        prior_runs = [_make_prior_run_row(str(uuid.uuid4())) for _ in range(7)]

        session = _build_mock_session(
            current_rows=[_make_current_counts_row("news", "reddit", 30)],
            prior_run_rows=prior_runs,
            rolling_avg_rows=[_make_rolling_avg_row("news", "reddit", 10.0)],
            top_terms_rows=[],
        )

        result = await detect_volume_spikes(
            session=session,
            query_design_id=uuid.uuid4(),
            collection_run_id=uuid.uuid4(),
            threshold_multiplier=2.0,
        )

        assert len(result) == 1
        assert result[0].ratio == pytest.approx(3.0, rel=1e-6)
