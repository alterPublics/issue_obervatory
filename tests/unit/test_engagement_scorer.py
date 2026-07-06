"""Tests for the data-driven engagement score enrichment module."""

from __future__ import annotations

import asyncio
import math

import pytest

from issue_observatory.analysis.enrichments.engagement_scorer import (
    _ENGAGEMENT_PLATFORMS,
    EngagementScalerState,
    _compute_raw_composite,
    _log_fallback_score,
    _yeo_johnson_transform,
)

# ---------------------------------------------------------------------------
# Yeo-Johnson transform
# ---------------------------------------------------------------------------


class TestYeoJohnsonTransform:
    """Pure-Python Yeo-Johnson matches the four-branch formula."""

    def test_positive_nonzero_lambda(self) -> None:
        """Branch: x >= 0, lambda != 0 -> ((x+1)^lambda - 1) / lambda."""
        result = _yeo_johnson_transform(5.0, 0.5)
        expected = ((5.0 + 1) ** 0.5 - 1) / 0.5
        assert abs(result - expected) < 1e-10

    def test_positive_zero_lambda(self) -> None:
        """Branch: x >= 0, lambda ~= 0 -> log1p(x)."""
        result = _yeo_johnson_transform(5.0, 0.0)
        expected = math.log1p(5.0)
        assert abs(result - expected) < 1e-10

    def test_negative_lambda_not_two(self) -> None:
        """Branch: x < 0, lambda != 2 -> -((-x+1)^(2-lambda) - 1) / (2-lambda)."""
        result = _yeo_johnson_transform(-3.0, 1.0)
        expected = -((3.0 + 1) ** (2 - 1.0) - 1) / (2 - 1.0)
        assert abs(result - expected) < 1e-10

    def test_negative_lambda_two(self) -> None:
        """Branch: x < 0, lambda ~= 2 -> -log1p(-x)."""
        result = _yeo_johnson_transform(-3.0, 2.0)
        expected = -math.log1p(3.0)
        assert abs(result - expected) < 1e-10

    def test_zero_input(self) -> None:
        """x = 0 should return 0 for any lambda (positive branch, (1^lmbda - 1)/lmbda = 0)."""
        assert _yeo_johnson_transform(0.0, 0.5) == pytest.approx(0.0, abs=1e-10)
        assert _yeo_johnson_transform(0.0, 0.0) == pytest.approx(0.0, abs=1e-10)


# ---------------------------------------------------------------------------
# MinMaxScaler (via EngagementScalerState)
# ---------------------------------------------------------------------------


class TestEngagementScalerState:
    """EngagementScalerState.transform() applies Yeo-Johnson + MinMax."""

    def test_midpoint_score(self) -> None:
        """A value at the midpoint of the training range maps to ~50."""
        # Fit a scaler where transformed range is [0, 10].
        state = EngagementScalerState(
            lmbda=1.0,  # identity transform for positive x: ((x+1)^1 - 1)/1 = x
            data_min=0.0,
            data_max=10.0,
            fitted_at="2026-01-01T00:00:00+00:00",
        )
        # Input 5.0: Yeo-Johnson(5.0, lambda=1.0) = 5.0, MinMax = (5-0)/(10-0) = 0.5
        score = state.transform(5.0)
        assert score == pytest.approx(50.0, abs=0.01)

    def test_score_clamped_to_100(self) -> None:
        """Values above the training max are clamped to 100."""
        state = EngagementScalerState(
            lmbda=1.0,
            data_min=0.0,
            data_max=10.0,
            fitted_at="2026-01-01T00:00:00+00:00",
        )
        score = state.transform(20.0)
        assert score == 100.0

    def test_score_clamped_to_0(self) -> None:
        """Values below the training min are clamped to 0."""
        state = EngagementScalerState(
            lmbda=1.0,
            data_min=5.0,
            data_max=10.0,
            fitted_at="2026-01-01T00:00:00+00:00",
        )
        score = state.transform(0.0)
        assert score == 0.0

    def test_zero_range_returns_50(self) -> None:
        """When all training data had the same value, return 50 as midpoint."""
        state = EngagementScalerState(
            lmbda=1.0,
            data_min=5.0,
            data_max=5.0,
            fitted_at="2026-01-01T00:00:00+00:00",
        )
        assert state.transform(5.0) == 50.0

    def test_output_range_0_to_100(self) -> None:
        """Scores are always in [0, 100]."""
        state = EngagementScalerState(
            lmbda=0.3,
            data_min=0.0,
            data_max=50.0,
            fitted_at="2026-01-01T00:00:00+00:00",
        )
        for raw in [0, 1, 10, 100, 1000, 100000]:
            score = state.transform(float(raw))
            assert 0.0 <= score <= 100.0, f"score {score} out of range for raw={raw}"


# ---------------------------------------------------------------------------
# is_applicable
# ---------------------------------------------------------------------------


class TestIsApplicable:
    """EngagementScorer.is_applicable filters by platform and metrics."""

    def test_applicable_platform_with_metrics(self) -> None:
        """Social media platforms with engagement metrics are applicable."""
        from issue_observatory.analysis.enrichments.engagement_scorer import (
            EngagementScorer,
        )

        scorer = EngagementScorer.__new__(EngagementScorer)
        scorer._scalers = {}  # skip DB load

        record = {
            "platform": "reddit",
            "likes_count": 42,
            "views_count": None,
            "shares_count": None,
            "comments_count": 5,
        }
        assert scorer.is_applicable(record) is True

    def test_non_applicable_platform(self) -> None:
        """News, search, and web platforms are not applicable."""
        from issue_observatory.analysis.enrichments.engagement_scorer import (
            EngagementScorer,
        )

        scorer = EngagementScorer.__new__(EngagementScorer)
        scorer._scalers = {}

        for platform in ("google_search", "event_registry", "rss_feeds", "gdelt", "domain_crawler"):
            record = {
                "platform": platform,
                "likes_count": 10,
                "views_count": None,
                "shares_count": None,
                "comments_count": None,
            }
            assert scorer.is_applicable(record) is False, f"{platform} should not be applicable"

    def test_applicable_platform_zero_metrics(self) -> None:
        """Even applicable platforms with all-zero metrics are skipped."""
        from issue_observatory.analysis.enrichments.engagement_scorer import (
            EngagementScorer,
        )

        scorer = EngagementScorer.__new__(EngagementScorer)
        scorer._scalers = {}

        record = {
            "platform": "reddit",
            "likes_count": 0,
            "views_count": 0,
            "shares_count": 0,
            "comments_count": 0,
        }
        assert scorer.is_applicable(record) is False


# ---------------------------------------------------------------------------
# enrich
# ---------------------------------------------------------------------------


class TestEnrich:
    """EngagementScorer.enrich produces correct output."""

    def test_enrich_with_fitted_scaler(self) -> None:
        """When a fitted scaler exists, use yeo_johnson_minmax method."""
        from issue_observatory.analysis.enrichments.engagement_scorer import (
            EngagementScorer,
        )

        scorer = EngagementScorer.__new__(EngagementScorer)
        scorer._scalers = {
            "reddit": EngagementScalerState(
                lmbda=0.5,
                data_min=0.0,
                data_max=20.0,
                fitted_at="2026-03-15T01:00:00+00:00",
            ),
        }

        record = {
            "platform": "reddit",
            "views_count": None,
            "likes_count": 100,
            "shares_count": None,
            "comments_count": 25,
        }
        result = asyncio.run(scorer.enrich(record))

        assert result["method"] == "yeo_johnson_minmax"
        assert result["raw_composite"] == 125.0
        assert 0 <= result["score"] <= 100
        assert result["platform"] == "reddit"
        assert result["scaler_fitted_at"] == "2026-03-15T01:00:00+00:00"
        assert "scored_at" in result

    def test_enrich_with_log_fallback(self) -> None:
        """When no scaler exists, use log_fallback method."""
        from issue_observatory.analysis.enrichments.engagement_scorer import (
            EngagementScorer,
        )

        scorer = EngagementScorer.__new__(EngagementScorer)
        scorer._scalers = {}  # no scalers loaded

        record = {
            "platform": "bluesky",
            "views_count": None,
            "likes_count": 50,
            "shares_count": 10,
            "comments_count": 5,
        }
        result = asyncio.run(scorer.enrich(record))

        assert result["method"] == "log_fallback"
        assert result["raw_composite"] == 65.0
        assert 0 <= result["score"] <= 100
        assert result["platform"] == "bluesky"
        assert "scaler_fitted_at" not in result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    """Test raw composite and log fallback helper functions."""

    def test_compute_raw_composite_all_present(self) -> None:
        record = {"views_count": 100, "likes_count": 50, "shares_count": 10, "comments_count": 5}
        assert _compute_raw_composite(record) == 165.0

    def test_compute_raw_composite_partial(self) -> None:
        record = {"views_count": None, "likes_count": 42, "shares_count": 0, "comments_count": None}
        assert _compute_raw_composite(record) == 42.0

    def test_compute_raw_composite_all_none(self) -> None:
        record = {
            "views_count": None,
            "likes_count": None,
            "shares_count": None,
            "comments_count": None,
        }
        assert _compute_raw_composite(record) == 0.0

    def test_log_fallback_zero(self) -> None:
        assert _log_fallback_score(0.0) == 0.0

    def test_log_fallback_positive(self) -> None:
        score = _log_fallback_score(100.0)
        assert 0 < score <= 100

    def test_log_fallback_max_cap(self) -> None:
        """Very large values should cap at 100."""
        score = _log_fallback_score(1e12)
        assert score == 100.0

    def test_engagement_platforms_set(self) -> None:
        """Verify the expected platforms are in the set."""
        expected = {
            "youtube",
            "reddit",
            "bluesky",
            "x_twitter",
            "tiktok",
            "instagram",
            "facebook",
            "threads",
            "discord",
        }
        assert _ENGAGEMENT_PLATFORMS == expected
