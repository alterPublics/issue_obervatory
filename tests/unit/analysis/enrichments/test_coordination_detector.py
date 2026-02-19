"""Unit tests for analysis/enrichments/coordination_detector.py (GR-11).

Covers:
- A cluster with 5 distinct authors within 1 hour IS flagged (at default threshold=5)
- A cluster with 4 distinct authors (below threshold=5) is NOT flagged
- A single-record cluster is handled without error
- enrich() raises EnrichmentError (cluster-scoped enricher)
- enrich_cluster() raises EnrichmentError on empty cluster
- coordination_score is 1.0 for a flagged single-cluster call without max_distinct_authors
- coordination_score is 0.0 for a non-flagged single-cluster call
- Records without published_at are tagged with the cluster result but excluded from
  the time-window calculation
- discovery_method and cluster_id are correctly set on the result dict
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Env bootstrap (must run before any application imports)
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault(
    "CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA=="
)

from issue_observatory.analysis.enrichments.base import EnrichmentError  # noqa: E402
from issue_observatory.analysis.enrichments.coordination_detector import (  # noqa: E402
    CoordinationDetector,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CLUSTER_ID = str(uuid.uuid4())
_BASE_TIME = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)


def _make_record(
    author_id: str | None,
    minutes_offset: int = 0,
    platform: str = "telegram",
    cluster_id: str = _CLUSTER_ID,
) -> dict[str, Any]:
    """Build a minimal content record dict for coordination enrichment tests.

    Args:
        author_id: UUID string or None for anonymous records.
        minutes_offset: Minutes after _BASE_TIME for published_at.
        platform: Platform slug.
        cluster_id: near_duplicate_cluster_id value.

    Returns:
        Dict with keys required by CoordinationDetector.enrich_cluster().
    """
    published_at = _BASE_TIME + timedelta(minutes=minutes_offset)
    return {
        "id": str(uuid.uuid4()),
        "author_id": author_id,
        "platform": platform,
        "published_at": published_at.isoformat(),
        "near_duplicate_cluster_id": cluster_id,
        "text_content": "Grønland bør have selvstændighed fra Danmark.",
    }


def _make_record_no_timestamp(
    author_id: str | None,
    platform: str = "telegram",
    cluster_id: str = _CLUSTER_ID,
) -> dict[str, Any]:
    """Build a content record dict with no published_at field."""
    return {
        "id": str(uuid.uuid4()),
        "author_id": author_id,
        "platform": platform,
        "published_at": None,
        "near_duplicate_cluster_id": cluster_id,
        "text_content": "Grønland bør have selvstændighed fra Danmark.",
    }


# ---------------------------------------------------------------------------
# enrich() — single-record interface (must raise)
# ---------------------------------------------------------------------------


class TestCoordinationDetectorEnrichSingleRecord:
    @pytest.mark.asyncio
    async def test_enrich_raises_enrichment_error(self) -> None:
        """enrich() raises EnrichmentError because coordination is cluster-scoped.

        The CoordinationDetector is not usable as a single-record enricher.
        Callers must use enrich_cluster() with the full cluster list.
        """
        detector = CoordinationDetector()
        record = _make_record(author_id=str(uuid.uuid4()))

        with pytest.raises(EnrichmentError, match="cluster context"):
            await detector.enrich(record)

    @pytest.mark.asyncio
    async def test_enrich_cluster_raises_enrichment_error_on_empty_cluster(self) -> None:
        """enrich_cluster() raises EnrichmentError when called with an empty list."""
        detector = CoordinationDetector()

        with pytest.raises(EnrichmentError, match="empty cluster"):
            await detector.enrich_cluster([])


# ---------------------------------------------------------------------------
# enrich_cluster() — threshold: 5 authors within 1 hour
# ---------------------------------------------------------------------------


class TestCoordinationDetectorClusterFlagging:
    @pytest.mark.asyncio
    async def test_five_distinct_authors_within_one_hour_is_flagged(self) -> None:
        """enrich_cluster() flags a cluster with 5 distinct authors in 1-hour window.

        Five records from five different authors, all posted within 45 minutes
        of each other, should trigger a coordination flag at the default
        threshold of 5.
        """
        detector = CoordinationDetector(coordination_threshold=5, time_window_hours=1.0)

        records = [
            _make_record(author_id=str(uuid.uuid4()), minutes_offset=i * 9)
            for i in range(5)
        ]
        # All 5 records span 36 minutes (0, 9, 18, 27, 36) — well within 1 hour

        result = await detector.enrich_cluster(records)

        assert len(result) == 5
        for rec_id, payload in result.items():
            assert payload["flagged"] is True
            assert payload["distinct_authors_in_window"] >= 5

    @pytest.mark.asyncio
    async def test_four_distinct_authors_below_threshold_is_not_flagged(self) -> None:
        """enrich_cluster() does not flag a cluster with only 4 distinct authors.

        Four records from four different authors within 1 hour is below the
        default coordination_threshold of 5 and must NOT be flagged.
        """
        detector = CoordinationDetector(coordination_threshold=5, time_window_hours=1.0)

        records = [
            _make_record(author_id=str(uuid.uuid4()), minutes_offset=i * 10)
            for i in range(4)
        ]
        # 4 records: 0, 10, 20, 30 minutes — all within 1 hour

        result = await detector.enrich_cluster(records)

        assert len(result) == 4
        for rec_id, payload in result.items():
            assert payload["flagged"] is False

    @pytest.mark.asyncio
    async def test_five_authors_outside_time_window_is_not_flagged(self) -> None:
        """enrich_cluster() does not flag 5 authors spread over more than 1 hour.

        Five records from five different authors, but spread 30 minutes apart
        (spanning 2 hours total), should NOT trigger the 1-hour window threshold.
        """
        detector = CoordinationDetector(coordination_threshold=5, time_window_hours=1.0)

        records = [
            _make_record(author_id=str(uuid.uuid4()), minutes_offset=i * 30)
            for i in range(5)
        ]
        # Records at 0, 30, 60, 90, 120 minutes — no 1-hour window contains all 5

        result = await detector.enrich_cluster(records)

        # With a 1-hour window, at most 3 records (e.g. 0, 30, 60) fall together
        # — below the threshold of 5
        for rec_id, payload in result.items():
            assert payload["flagged"] is False

    @pytest.mark.asyncio
    async def test_single_record_cluster_handled_without_error(self) -> None:
        """enrich_cluster() handles a single-record cluster without error.

        A cluster with only one member cannot meet any multi-author threshold.
        The result must be unflagged and returned without raising.
        """
        detector = CoordinationDetector(coordination_threshold=5, time_window_hours=1.0)
        records = [_make_record(author_id=str(uuid.uuid4()), minutes_offset=0)]

        result = await detector.enrich_cluster(records)

        assert len(result) == 1
        rec_id = list(result.keys())[0]
        assert result[rec_id]["flagged"] is False
        assert result[rec_id]["distinct_authors_in_window"] < 5


# ---------------------------------------------------------------------------
# enrich_cluster() — coordination_score logic
# ---------------------------------------------------------------------------


class TestCoordinationDetectorScore:
    @pytest.mark.asyncio
    async def test_flagged_cluster_has_score_1_0_without_max_distinct_authors(self) -> None:
        """enrich_cluster() sets coordination_score=1.0 for flagged clusters.

        When max_distinct_authors is not provided, the normalisation denominator
        defaults to the current cluster's own count, giving score=1.0.
        """
        detector = CoordinationDetector(coordination_threshold=3, time_window_hours=1.0)
        records = [
            _make_record(author_id=str(uuid.uuid4()), minutes_offset=i * 5)
            for i in range(5)
        ]

        result = await detector.enrich_cluster(records)

        for rec_id, payload in result.items():
            if payload["flagged"]:
                assert payload["coordination_score"] == 1.0

    @pytest.mark.asyncio
    async def test_non_flagged_cluster_has_score_0_0_without_max_distinct_authors(self) -> None:
        """enrich_cluster() sets coordination_score=0.0 for non-flagged clusters."""
        detector = CoordinationDetector(coordination_threshold=10, time_window_hours=1.0)
        # 3 authors — below threshold of 10
        records = [
            _make_record(author_id=str(uuid.uuid4()), minutes_offset=i * 5)
            for i in range(3)
        ]

        result = await detector.enrich_cluster(records)

        for rec_id, payload in result.items():
            assert payload["flagged"] is False
            # Non-flagged clusters do not include coordination_score in the payload
            # (the score key is only present for flagged clusters per the design doc)
            assert payload.get("coordination_score", 0.0) == 0.0

    @pytest.mark.asyncio
    async def test_coordination_score_normalised_by_max_distinct_authors(self) -> None:
        """enrich_cluster() uses max_distinct_authors to normalise the score.

        When max_distinct_authors=10 and best_distinct=5 for a flagged cluster,
        the score should be 5/10 = 0.5.
        """
        detector = CoordinationDetector(coordination_threshold=3, time_window_hours=1.0)
        records = [
            _make_record(author_id=str(uuid.uuid4()), minutes_offset=i * 5)
            for i in range(5)
        ]

        result = await detector.enrich_cluster(records, max_distinct_authors=10)

        for rec_id, payload in result.items():
            if payload["flagged"]:
                assert payload["coordination_score"] == pytest.approx(0.5, rel=1e-4)


# ---------------------------------------------------------------------------
# enrich_cluster() — records without timestamps
# ---------------------------------------------------------------------------


class TestCoordinationDetectorNoTimestamp:
    @pytest.mark.asyncio
    async def test_records_without_published_at_are_tagged_with_cluster_result(self) -> None:
        """Records with no published_at receive the cluster enrichment result.

        Timestampless records are excluded from the time-window calculation but
        must still appear in the returned result dict, tagged with the cluster-level
        flagged/unflagged outcome.
        """
        detector = CoordinationDetector(coordination_threshold=5, time_window_hours=1.0)

        timestamped_records = [
            _make_record(author_id=str(uuid.uuid4()), minutes_offset=i * 5)
            for i in range(5)
        ]
        no_timestamp_record = _make_record_no_timestamp(
            author_id=str(uuid.uuid4()),
            cluster_id=_CLUSTER_ID,
        )
        all_records = timestamped_records + [no_timestamp_record]

        result = await detector.enrich_cluster(all_records)

        # All 6 records must appear in the result
        assert len(result) == 6
        # The no-timestamp record must have a cluster_id field
        no_ts_id = no_timestamp_record["id"]
        assert no_ts_id in result
        assert result[no_ts_id]["cluster_id"] == _CLUSTER_ID


# ---------------------------------------------------------------------------
# enrich_cluster() — cluster_id and basic payload shape
# ---------------------------------------------------------------------------


class TestCoordinationDetectorPayloadShape:
    @pytest.mark.asyncio
    async def test_result_keyed_by_record_id(self) -> None:
        """enrich_cluster() returns a dict keyed by each record's str(id)."""
        detector = CoordinationDetector(coordination_threshold=5, time_window_hours=1.0)
        records = [_make_record(author_id=str(uuid.uuid4()), minutes_offset=i) for i in range(3)]

        result = await detector.enrich_cluster(records)

        assert set(result.keys()) == {r["id"] for r in records}

    @pytest.mark.asyncio
    async def test_payload_contains_required_keys_for_non_flagged_cluster(self) -> None:
        """enrich_cluster() payload has at minimum: cluster_id, flagged, distinct_authors_in_window,
        time_window_hours, computed_at."""
        detector = CoordinationDetector(coordination_threshold=10, time_window_hours=1.0)
        records = [_make_record(author_id=str(uuid.uuid4()), minutes_offset=0)]

        result = await detector.enrich_cluster(records)

        for rec_id, payload in result.items():
            assert "cluster_id" in payload
            assert "flagged" in payload
            assert "distinct_authors_in_window" in payload
            assert "time_window_hours" in payload
            assert "computed_at" in payload

    @pytest.mark.asyncio
    async def test_payload_contains_extra_keys_for_flagged_cluster(self) -> None:
        """Flagged cluster payloads include coordination_score, earliest/latest, platforms_involved."""
        detector = CoordinationDetector(coordination_threshold=3, time_window_hours=1.0)
        records = [
            _make_record(author_id=str(uuid.uuid4()), minutes_offset=i * 5, platform="telegram")
            for i in range(5)
        ]

        result = await detector.enrich_cluster(records)

        for rec_id, payload in result.items():
            if payload["flagged"]:
                assert "coordination_score" in payload
                assert "earliest_in_window" in payload
                assert "latest_in_window" in payload
                assert "platforms_involved" in payload

    @pytest.mark.asyncio
    async def test_cluster_id_matches_records_near_duplicate_cluster_id(self) -> None:
        """enrich_cluster() uses near_duplicate_cluster_id from the first record as cluster_id."""
        expected_cluster_id = str(uuid.uuid4())
        detector = CoordinationDetector(coordination_threshold=5, time_window_hours=1.0)
        records = [
            _make_record(
                author_id=str(uuid.uuid4()),
                minutes_offset=i,
                cluster_id=expected_cluster_id,
            )
            for i in range(3)
        ]

        result = await detector.enrich_cluster(records)

        for rec_id, payload in result.items():
            assert payload["cluster_id"] == expected_cluster_id


# ---------------------------------------------------------------------------
# is_applicable()
# ---------------------------------------------------------------------------


class TestCoordinationDetectorIsApplicable:
    def test_returns_true_when_cluster_id_present(self) -> None:
        """is_applicable() returns True when near_duplicate_cluster_id is set."""
        detector = CoordinationDetector()
        record = _make_record(author_id=str(uuid.uuid4()))
        assert detector.is_applicable(record) is True

    def test_returns_false_when_cluster_id_absent(self) -> None:
        """is_applicable() returns False when near_duplicate_cluster_id is None."""
        detector = CoordinationDetector()
        record = _make_record(author_id=str(uuid.uuid4()))
        record["near_duplicate_cluster_id"] = None
        assert detector.is_applicable(record) is False

    def test_returns_false_when_cluster_id_missing_from_dict(self) -> None:
        """is_applicable() returns False when the key is absent from the record."""
        detector = CoordinationDetector()
        record: dict[str, Any] = {"id": str(uuid.uuid4()), "platform": "telegram"}
        assert detector.is_applicable(record) is False
