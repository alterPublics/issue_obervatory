"""Data-driven engagement score enrichment.

Computes per-platform normalized engagement scores (0-100) using fitted
Yeo-Johnson + MinMaxScaler transformers.  The fitting step runs weekly as a
Celery task (requires sklearn); the scoring step uses pure-Python math so that
no optional dependencies are needed at enrichment time.

Inspired by spreadAnalysis's ``create_enga_transformer_actor`` approach: fit
per-platform PowerTransformer(yeo-johnson) + MinMaxScaler to actual engagement
distributions, then apply the fitted parameters to each record's composite
engagement metric.

Platforms without meaningful engagement metrics (news, search, web arenas) are
excluded via ``_ENGAGEMENT_PLATFORMS``.

Owned by the Core Application Engineer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

from issue_observatory.analysis.enrichments.base import ContentEnricher

logger = structlog.get_logger(__name__)

#: Platforms with real user-generated engagement metrics suitable for
#: data-driven normalization.  Platforms with pre-existing semantic scores
#: (Google Autocomplete relevance, Majestic trust flow) or no engagement
#: concept (news, search, web, RSS) are excluded.
_ENGAGEMENT_PLATFORMS: frozenset[str] = frozenset(
    {
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
)

#: Minimum number of records per platform required for stable Yeo-Johnson
#: lambda estimation.
_MIN_SAMPLE_SIZE: int = 100


def _yeo_johnson_transform(x: float, lmbda: float) -> float:
    """Pure-Python Yeo-Johnson power transform for a single value.

    Implements the four-branch formula from Yeo & Johnson (2000).

    Args:
        x: Input value (may be negative).
        lmbda: Fitted lambda parameter.

    Returns:
        Transformed value.
    """
    if x >= 0:
        if abs(lmbda) < 1e-10:
            return math.log1p(x)
        return ((x + 1) ** lmbda - 1) / lmbda
    else:
        if abs(lmbda - 2) < 1e-10:
            return -math.log1p(-x)
        return -((-x + 1) ** (2 - lmbda) - 1) / (2 - lmbda)


@dataclass
class EngagementScalerState:
    """Deserialized per-platform transformer + scaler parameters.

    Provides a ``.transform()`` method that applies the fitted Yeo-Johnson
    power transform followed by MinMax scaling to produce a 0-100 score.

    Attributes:
        lmbda: Yeo-Johnson lambda parameter.
        data_min: MinMaxScaler fitted minimum (post-transform).
        data_max: MinMaxScaler fitted maximum (post-transform).
        fitted_at: ISO timestamp of when the scaler was last fitted.
    """

    lmbda: float
    data_min: float
    data_max: float
    fitted_at: str

    def transform(self, raw_composite: float) -> float:
        """Apply Yeo-Johnson + MinMax scaling to a raw composite engagement value.

        Args:
            raw_composite: Sum of available engagement metrics (views, likes,
                shares, comments).

        Returns:
            Normalized score clamped to [0, 100].
        """
        transformed = _yeo_johnson_transform(raw_composite, self.lmbda)

        # MinMax scaling: (x - min) / (max - min) -> [0, 1] -> [0, 100]
        data_range = self.data_max - self.data_min
        if data_range < 1e-10:
            # All training data had the same value; return 50 as midpoint.
            return 50.0

        scaled = (transformed - self.data_min) / data_range
        # Clamp to [0, 1] — test-time values may exceed training range.
        scaled = max(0.0, min(1.0, scaled))
        return round(scaled * 100, 2)


def _compute_raw_composite(record: dict[str, Any]) -> float:
    """Sum available engagement metrics from a content record dict.

    Args:
        record: Content record dict with engagement count columns.

    Returns:
        Sum of non-null engagement metrics as a float.
    """
    total = 0.0
    for key in ("views_count", "likes_count", "shares_count", "comments_count"):
        val = record.get(key)
        if val is not None and val > 0:
            total += val
    return total


def _log_fallback_score(raw_composite: float) -> float:
    """Cold-start fallback: log-scale engagement to 0-100.

    Uses the same log1p approach as ``normalizer.compute_normalized_engagement``
    but with a fixed scale factor, producing usable scores before any platform
    scaler has been fitted.

    Args:
        raw_composite: Sum of available engagement metrics.

    Returns:
        Score in the [0, 100] range.
    """
    if raw_composite <= 0:
        return 0.0
    score = math.log1p(raw_composite) * 7.0
    return min(100.0, round(score, 2))


class EngagementScorer(ContentEnricher):
    """Data-driven engagement score enricher.

    Uses per-platform Yeo-Johnson + MinMaxScaler parameters (fitted weekly)
    to normalize raw engagement metrics into comparable 0-100 scores across
    platforms.  Falls back to log-scaling when no fitted scaler exists.

    Output in ``raw_metadata.enrichments.engagement_score``::

        {
            "score": 72.5,
            "raw_composite": 1523,
            "method": "yeo_johnson_minmax",
            "scaler_fitted_at": "2026-03-15T01:00:00+00:00",
            "platform": "reddit",
            "scored_at": "2026-03-15T12:34:56+00:00"
        }
    """

    enricher_name: str = "engagement_score"

    def __init__(self) -> None:
        self._scalers: dict[str, EngagementScalerState] = {}
        self._load_scalers()

    def _load_scalers(self) -> None:
        """Load fitted scaler parameters from the DB."""
        try:
            from issue_observatory.workers._enrichment_helpers import (
                fetch_fitted_engagement_scalers,
            )

            raw = fetch_fitted_engagement_scalers()
            for platform, params in raw.items():
                tp = params.get("transformer_params", {})
                sp = params.get("scaler_params", {})
                lmbda = tp.get("lambda")
                data_min = sp.get("data_min")
                data_max = sp.get("data_max")
                fitted_at = params.get("fitted_at", "")
                if lmbda is not None and data_min is not None and data_max is not None:
                    self._scalers[platform] = EngagementScalerState(
                        lmbda=float(lmbda),
                        data_min=float(data_min),
                        data_max=float(data_max),
                        fitted_at=str(fitted_at),
                    )
            logger.info(
                "engagement_scorer: loaded scalers",
                platforms=sorted(self._scalers.keys()),
            )
        except Exception as exc:
            logger.warning(
                "engagement_scorer: could not load scalers — will use log fallback",
                error=str(exc),
            )

    def is_applicable(self, record: dict[str, Any]) -> bool:
        """True when platform has engagement metrics and at least one is nonzero."""
        platform = record.get("platform", "")
        if platform not in _ENGAGEMENT_PLATFORMS:
            return False
        return _compute_raw_composite(record) > 0

    async def enrich(self, record: dict[str, Any]) -> dict[str, Any]:
        """Compute normalized engagement score for a content record.

        Args:
            record: Content record dict with engagement count columns and
                ``platform`` key.

        Returns:
            Enrichment result dict with ``score``, ``raw_composite``,
            ``method``, and metadata fields.
        """
        platform = record.get("platform", "")
        raw_composite = _compute_raw_composite(record)
        scored_at = datetime.now(tz=UTC).isoformat()

        scaler = self._scalers.get(platform)
        if scaler is not None:
            score = scaler.transform(raw_composite)
            method = "yeo_johnson_minmax"
            fitted_at = scaler.fitted_at
        else:
            score = _log_fallback_score(raw_composite)
            method = "log_fallback"
            fitted_at = None

        result: dict[str, Any] = {
            "score": score,
            "raw_composite": raw_composite,
            "method": method,
            "platform": platform,
            "scored_at": scored_at,
        }
        if fitted_at is not None:
            result["scaler_fitted_at"] = fitted_at
        return result

    def write_relational(
        self,
        record: dict[str, Any],
        enrichment_result: dict[str, Any],
    ) -> None:
        """Write the computed score back to the ``engagement_score`` column.

        Args:
            record: The content record dict (must include ``id``).
            enrichment_result: The dict returned by :meth:`enrich`.
        """
        from issue_observatory.workers._enrichment_helpers import (
            update_engagement_score_column,
        )

        record_id = str(record["id"])
        score = enrichment_result.get("score")
        if score is not None:
            update_engagement_score_column([(record_id, score)])


def fit_engagement_scalers() -> dict[str, Any]:
    """Fit per-platform Yeo-Johnson + MinMaxScaler from actual engagement data.

    Samples engagement data per platform from the DB, fits sklearn
    ``PowerTransformer(method='yeo-johnson')`` + ``MinMaxScaler``, and upserts
    the fitted parameters into the ``engagement_scalers`` table.

    Requires ``scikit-learn`` (only for fitting, not for scoring).

    Returns:
        Dict with per-platform fitting results including sample_size and
        diagnostic statistics.
    """
    import json

    import numpy as np
    from sklearn.preprocessing import MinMaxScaler, PowerTransformer
    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session

    results: dict[str, Any] = {}

    for platform in sorted(_ENGAGEMENT_PLATFORMS):
        # Sample engagement data for this platform.
        with get_sync_session() as db:
            stmt = text(
                """
                SELECT
                    COALESCE(views_count, 0) +
                    COALESCE(likes_count, 0) +
                    COALESCE(shares_count, 0) +
                    COALESCE(comments_count, 0) AS composite
                FROM content_records
                WHERE platform = :platform
                  AND (
                      views_count IS NOT NULL AND views_count > 0
                      OR likes_count IS NOT NULL AND likes_count > 0
                      OR shares_count IS NOT NULL AND shares_count > 0
                      OR comments_count IS NOT NULL AND comments_count > 0
                  )
                ORDER BY collected_at DESC
                LIMIT 50000
                """
            )
            rows = db.execute(stmt, {"platform": platform}).fetchall()

        if len(rows) < _MIN_SAMPLE_SIZE:
            logger.info(
                "fit_engagement_scalers: skipping platform — insufficient data",
                platform=platform,
                sample_size=len(rows),
                min_required=_MIN_SAMPLE_SIZE,
            )
            results[platform] = {"status": "skipped", "sample_size": len(rows)}
            continue

        data = np.array([float(row[0]) for row in rows]).reshape(-1, 1)

        # Fit Yeo-Johnson power transform.
        pt = PowerTransformer(method="yeo-johnson", standardize=False)
        transformed = pt.fit_transform(data)

        # Fit MinMaxScaler on the transformed data.
        mm = MinMaxScaler()
        mm.fit(transformed)

        lmbda = float(pt.lambdas_[0])
        data_min = float(mm.data_min_[0])
        data_max = float(mm.data_max_[0])
        data_range = float(mm.data_range_[0])

        # Diagnostic statistics.
        composites = data.flatten()
        stats = {
            "mean": float(np.mean(composites)),
            "median": float(np.median(composites)),
            "std": float(np.std(composites)),
            "min": float(np.min(composites)),
            "max": float(np.max(composites)),
            "p25": float(np.percentile(composites, 25)),
            "p75": float(np.percentile(composites, 75)),
            "p95": float(np.percentile(composites, 95)),
        }
        # Skewness (Fisher definition).
        mean_val = np.mean(composites)
        std_val = np.std(composites)
        if std_val > 0:
            stats["skewness"] = float(np.mean(((composites - mean_val) / std_val) ** 3))
        else:
            stats["skewness"] = 0.0

        fitted_at = datetime.now(tz=UTC)
        transformer_params = {"lambda": lmbda}
        scaler_params = {
            "data_min": data_min,
            "data_max": data_max,
            "data_range": data_range,
        }

        # Upsert into engagement_scalers table.
        with get_sync_session() as db:
            stmt = text(
                """
                INSERT INTO engagement_scalers (
                    platform, transformer_params, scaler_params,
                    sample_size, stats, fitted_at, updated_at
                ) VALUES (
                    :platform,
                    CAST(:transformer_params AS jsonb),
                    CAST(:scaler_params AS jsonb),
                    :sample_size,
                    CAST(:stats AS jsonb),
                    :fitted_at,
                    :fitted_at
                )
                ON CONFLICT (platform) DO UPDATE SET
                    transformer_params = CAST(:transformer_params AS jsonb),
                    scaler_params = CAST(:scaler_params AS jsonb),
                    sample_size = :sample_size,
                    stats = CAST(:stats AS jsonb),
                    fitted_at = :fitted_at,
                    updated_at = :fitted_at
                """
            )
            db.execute(
                stmt,
                {
                    "platform": platform,
                    "transformer_params": json.dumps(transformer_params),
                    "scaler_params": json.dumps(scaler_params),
                    "sample_size": len(rows),
                    "stats": json.dumps(stats),
                    "fitted_at": fitted_at,
                },
            )
            db.commit()

        results[platform] = {
            "status": "fitted",
            "sample_size": len(rows),
            "lambda": lmbda,
            "data_min": data_min,
            "data_max": data_max,
            "stats": stats,
        }
        logger.info(
            "fit_engagement_scalers: platform fitted",
            platform=platform,
            sample_size=len(rows),
            lmbda=round(lmbda, 4),
        )

    return results
