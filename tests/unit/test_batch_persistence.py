"""Unit tests for the batch persistence pattern on ArenaCollector.

Tests cover:
- _emit() buffers records and auto-flushes at batch_size
- _emit_many() handles multiple records
- _flush() calls the sink and tracks inserted/skipped
- _flush() error handling: records put back in buffer
- _reset_batch_state() clears counters and buffer
- configure_batch_persistence() sets sink and batch_size
- batch_stats property returns correct cumulative stats
- Backward compatibility: without a sink, records accumulate in buffer
- make_batch_sink() factory creates a working closure

These are pure unit tests — no database, no network, no Celery.
"""

from __future__ import annotations

from typing import Any, ClassVar, NoReturn

from issue_observatory.arenas.base import ArenaCollector, Tier

# ---------------------------------------------------------------------------
# Minimal concrete collector for testing
# ---------------------------------------------------------------------------


class _TestCollector(ArenaCollector):
    arena_name = "_test_batch"
    platform_name = "_test_batch_platform"
    supported_tiers: ClassVar[list[Tier]] = [Tier.FREE]
    temporal_mode = "recent"  # type: ignore[assignment]

    async def collect_by_terms(  # type: ignore[override]
        self, terms: list[str], tier: Tier, **kw: str,
    ) -> list[dict[str, Any]]:
        return []

    async def collect_by_actors(  # type: ignore[override]
        self, actor_ids: list[str], tier: Tier, **kw: str,
    ) -> NoReturn:
        raise NotImplementedError

    def get_tier_config(self, tier: Tier) -> dict[str, Any]:  # type: ignore[override]
        return {}

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:  # type: ignore[override]
        return raw_item


def _make_record(n: int) -> dict[str, Any]:
    """Create a minimal record dict for testing."""
    return {"id": n, "content_hash": f"hash_{n}", "text": f"record {n}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBatchPersistenceInit:
    """Test initial state of batch persistence attributes."""

    def test_default_batch_size_is_100(self) -> None:
        collector = _TestCollector()
        assert collector._batch_size == 100

    def test_default_sink_is_none(self) -> None:
        collector = _TestCollector()
        assert collector._record_sink is None

    def test_default_counters_are_zero(self) -> None:
        collector = _TestCollector()
        assert collector._total_emitted == 0
        assert collector._total_inserted == 0
        assert collector._total_skipped == 0

    def test_default_buffer_is_empty(self) -> None:
        collector = _TestCollector()
        assert collector._batch_buffer == []


class TestConfigureBatchPersistence:
    """Test configure_batch_persistence()."""

    def test_sets_sink_and_batch_size(self) -> None:
        collector = _TestCollector()

        def sink(records: list[dict[str, Any]]) -> tuple[int, int]:
            return (len(records), 0)

        collector.configure_batch_persistence(sink=sink, batch_size=50)

        assert collector._record_sink is sink
        assert collector._batch_size == 50

    def test_default_batch_size(self) -> None:
        collector = _TestCollector()

        def sink(records: list[dict[str, Any]]) -> tuple[int, int]:
            return (0, 0)

        collector.configure_batch_persistence(sink=sink)

        assert collector._batch_size == 100


class TestResetBatchState:
    """Test _reset_batch_state()."""

    def test_clears_buffer_and_counters(self) -> None:
        collector = _TestCollector()
        collector._batch_buffer = [{"x": 1}]
        collector._total_emitted = 42
        collector._total_inserted = 30
        collector._total_skipped = 12
        collector._batch_errors = ["some error"]

        collector._reset_batch_state()

        assert collector._batch_buffer == []
        assert collector._total_emitted == 0
        assert collector._total_inserted == 0
        assert collector._total_skipped == 0
        assert collector._batch_errors == []


class TestEmit:
    """Test _emit() record buffering and auto-flush."""

    def test_emit_buffers_record(self) -> None:
        collector = _TestCollector()
        record = _make_record(1)
        collector._emit(record)

        assert len(collector._batch_buffer) == 1
        assert collector._batch_buffer[0] is record
        assert collector._total_emitted == 1

    def test_emit_increments_total_emitted(self) -> None:
        collector = _TestCollector()
        for i in range(5):
            collector._emit(_make_record(i))
        assert collector._total_emitted == 5

    def test_emit_does_not_flush_without_sink(self) -> None:
        """Without a sink, records accumulate in buffer (backward compat)."""
        collector = _TestCollector()
        collector._batch_size = 3

        for i in range(5):
            collector._emit(_make_record(i))

        # _flush() is called but does nothing without a sink
        assert collector._total_emitted == 5
        # Buffer may or may not have all 5 depending on flush behavior
        # Without a sink, _flush() is a no-op, so buffer keeps growing
        assert len(collector._batch_buffer) == 5

    def test_emit_auto_flushes_at_batch_size(self) -> None:
        """With a sink, auto-flush when buffer reaches batch_size."""
        flushed: list[list[dict[str, Any]]] = []

        def sink(records: list[dict[str, Any]]) -> tuple[int, int]:
            flushed.append(list(records))
            return (len(records), 0)

        collector = _TestCollector()
        collector.configure_batch_persistence(sink=sink, batch_size=3)

        for i in range(7):
            collector._emit(_make_record(i))

        # 7 records with batch_size=3: should have flushed twice (at 3 and 6)
        assert len(flushed) == 2
        assert len(flushed[0]) == 3
        assert len(flushed[1]) == 3
        # 1 record remains in buffer
        assert len(collector._batch_buffer) == 1
        assert collector._total_emitted == 7
        assert collector._total_inserted == 6

    def test_emit_exact_batch_size_flushes(self) -> None:
        """Buffer of exactly batch_size records triggers flush."""
        flush_count = 0

        def sink(records: list[dict[str, Any]]) -> tuple[int, int]:
            nonlocal flush_count
            flush_count += 1
            return (len(records), 0)

        collector = _TestCollector()
        collector.configure_batch_persistence(sink=sink, batch_size=5)

        for i in range(5):
            collector._emit(_make_record(i))

        assert flush_count == 1
        assert collector._batch_buffer == []


class TestEmitMany:
    """Test _emit_many() for batch record submission."""

    def test_emit_many_buffers_all_records(self) -> None:
        collector = _TestCollector()
        records = [_make_record(i) for i in range(5)]
        collector._emit_many(records)

        assert collector._total_emitted == 5
        assert len(collector._batch_buffer) == 5

    def test_emit_many_auto_flushes(self) -> None:
        flushed: list[list[dict[str, Any]]] = []

        def sink(records: list[dict[str, Any]]) -> tuple[int, int]:
            flushed.append(list(records))
            return (len(records), 0)

        collector = _TestCollector()
        collector.configure_batch_persistence(sink=sink, batch_size=3)

        records = [_make_record(i) for i in range(8)]
        collector._emit_many(records)

        assert len(flushed) == 2  # flushed at 3 and 6
        assert collector._total_emitted == 8
        assert len(collector._batch_buffer) == 2  # 2 remaining


class TestFlush:
    """Test _flush() persistence behavior."""

    def test_flush_calls_sink_with_buffer(self) -> None:
        received: list[dict[str, Any]] = []

        def sink(records: list[dict[str, Any]]) -> tuple[int, int]:
            received.extend(records)
            return (len(records), 0)

        collector = _TestCollector()
        collector.configure_batch_persistence(sink=sink)
        collector._batch_buffer = [_make_record(1), _make_record(2)]

        collector._flush()

        assert len(received) == 2
        assert collector._batch_buffer == []
        assert collector._total_inserted == 2

    def test_flush_tracks_skipped(self) -> None:
        def sink(records: list[dict[str, Any]]) -> tuple[int, int]:
            return (1, 2)  # 1 inserted, 2 skipped (duplicates)

        collector = _TestCollector()
        collector.configure_batch_persistence(sink=sink)
        collector._batch_buffer = [_make_record(1), _make_record(2), _make_record(3)]

        collector._flush()

        assert collector._total_inserted == 1
        assert collector._total_skipped == 2

    def test_flush_noop_without_sink(self) -> None:
        """Flush is a no-op when no sink is configured."""
        collector = _TestCollector()
        collector._batch_buffer = [_make_record(1)]

        collector._flush()

        assert len(collector._batch_buffer) == 1  # unchanged

    def test_flush_noop_with_empty_buffer(self) -> None:
        """Flush is a no-op when buffer is empty."""
        call_count = 0

        def sink(records: list[dict[str, Any]]) -> tuple[int, int]:
            nonlocal call_count
            call_count += 1
            return (0, 0)

        collector = _TestCollector()
        collector.configure_batch_persistence(sink=sink)

        collector._flush()

        assert call_count == 0

    def test_flush_error_puts_records_back(self) -> None:
        """On sink error, records are put back in buffer for fallback."""

        def failing_sink(records: list[dict[str, Any]]) -> tuple[int, int]:
            raise ConnectionError("DB unavailable")

        collector = _TestCollector()
        collector.configure_batch_persistence(sink=failing_sink)
        original_records = [_make_record(1), _make_record(2)]
        collector._batch_buffer = list(original_records)

        collector._flush()

        # Records should be back in buffer
        assert len(collector._batch_buffer) == 2
        assert collector._batch_buffer[0]["id"] == 1
        assert collector._batch_buffer[1]["id"] == 2
        # Counters should not be updated
        assert collector._total_inserted == 0
        assert collector._total_skipped == 0
        # Error should be recorded
        assert len(collector._batch_errors) == 1
        assert "DB unavailable" in collector._batch_errors[0]

    def test_flush_error_preserves_new_buffer_records(self) -> None:
        """On error, records added after the flush started are preserved."""

        def failing_sink(records: list[dict[str, Any]]) -> tuple[int, int]:
            raise RuntimeError("fail")

        collector = _TestCollector()
        collector.configure_batch_persistence(sink=failing_sink)
        collector._batch_buffer = [_make_record(1)]

        collector._flush()

        assert len(collector._batch_buffer) == 1

    def test_cumulative_flush_stats(self) -> None:
        """Multiple flushes accumulate inserted/skipped counts."""

        def sink(records: list[dict[str, Any]]) -> tuple[int, int]:
            return (len(records) - 1, 1)  # 1 dupe per batch

        collector = _TestCollector()
        collector.configure_batch_persistence(sink=sink, batch_size=3)

        for i in range(9):
            collector._emit(_make_record(i))

        # 3 auto-flushes of 3 records each
        assert collector._total_inserted == 6  # (3-1)*3 = 6
        assert collector._total_skipped == 3  # 1 * 3 = 3


class TestBatchStats:
    """Test the batch_stats property."""

    def test_batch_stats_returns_correct_dict(self) -> None:
        collector = _TestCollector()
        collector._total_emitted = 100
        collector._total_inserted = 90
        collector._total_skipped = 10

        stats = collector.batch_stats

        assert stats == {"emitted": 100, "inserted": 90, "skipped": 10}

    def test_batch_stats_default_values(self) -> None:
        collector = _TestCollector()
        stats = collector.batch_stats

        assert stats == {"emitted": 0, "inserted": 0, "skipped": 0}


class TestBackwardCompatibility:
    """Test that collectors work identically when no sink is configured."""

    def test_emit_without_sink_accumulates_records(self) -> None:
        """Without a sink, _emit just buffers and _flush is a no-op."""
        collector = _TestCollector()

        for i in range(200):
            collector._emit(_make_record(i))

        collector._flush()

        # All records stay in the buffer
        assert len(collector._batch_buffer) == 200
        assert collector._total_emitted == 200
        assert collector._total_inserted == 0
        assert collector._total_skipped == 0

    def test_buffer_can_be_returned_as_list(self) -> None:
        """The buffer can be converted to a return list (backward compat)."""
        collector = _TestCollector()
        for i in range(5):
            collector._emit(_make_record(i))

        result = list(collector._batch_buffer)

        assert len(result) == 5
        assert result[0]["id"] == 0


class TestEndToEndFlow:
    """Test the complete flow: configure → emit → flush → stats."""

    def test_full_collection_flow(self) -> None:
        """Simulate a full collection with batch persistence."""
        all_persisted: list[dict[str, Any]] = []

        def sink(records: list[dict[str, Any]]) -> tuple[int, int]:
            all_persisted.extend(records)
            skipped = sum(1 for r in records if r["id"] % 5 == 0)
            inserted = len(records) - skipped
            return (inserted, skipped)

        collector = _TestCollector()
        collector.configure_batch_persistence(sink=sink, batch_size=10)
        collector._reset_batch_state()

        # Simulate collection
        for i in range(25):
            collector._emit(_make_record(i))

        # Final flush
        collector._flush()

        stats = collector.batch_stats
        assert stats["emitted"] == 25
        assert all_persisted  # records were persisted
        assert len(all_persisted) == 25

        # Buffer should be empty after successful flush
        remaining = list(collector._batch_buffer)
        assert remaining == []

    def test_partial_failure_flow(self) -> None:
        """Simulate a collection where one batch fails mid-way."""
        call_count = 0

        def sometimes_failing_sink(records: list[dict[str, Any]]) -> tuple[int, int]:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ConnectionError("Transient DB error")
            return (len(records), 0)

        collector = _TestCollector()
        collector.configure_batch_persistence(sink=sometimes_failing_sink, batch_size=5)
        collector._reset_batch_state()

        # Emit 15 records
        for i in range(15):
            collector._emit(_make_record(i))

        # Auto-flushes at 5, 10, 15
        # Flush 1 (records 0-4): succeeds → 5 inserted
        # Flush 2 (records 5-9): fails → records back in buffer
        # Flush 3 (records 10-14 + 5-9 from failed flush): succeeds → 10 inserted

        # Final flush for anything remaining
        collector._flush()

        stats = collector.batch_stats
        assert stats["emitted"] == 15
        # First batch: 5 inserted, third batch includes failed + new: 10 inserted
        assert stats["inserted"] == 15
        assert len(collector._batch_errors) == 1


class TestMakeBatchSink:
    """Test the make_batch_sink() factory function."""

    def test_make_batch_sink_creates_callable(self) -> None:
        from issue_observatory.workers._task_helpers import make_batch_sink

        sink = make_batch_sink("run-123", "design-456", terms=["test"])
        assert callable(sink)

    def test_make_batch_sink_delegates_to_persist(self) -> None:
        from unittest.mock import patch

        from issue_observatory.workers._task_helpers import make_batch_sink

        with patch(
            "issue_observatory.workers._task_helpers.persist_collected_records"
        ) as mock_persist:
            mock_persist.return_value = (5, 2)

            sink = make_batch_sink("run-123", "design-456", terms=["test"])
            result = sink([{"id": 1}, {"id": 2}])

            assert result == (5, 2)
            mock_persist.assert_called_once_with(
                [{"id": 1}, {"id": 2}], "run-123", "design-456", ["test"]
            )

    def test_make_batch_sink_without_optional_params(self) -> None:
        from unittest.mock import patch

        from issue_observatory.workers._task_helpers import make_batch_sink

        with patch(
            "issue_observatory.workers._task_helpers.persist_collected_records"
        ) as mock_persist:
            mock_persist.return_value = (3, 0)

            sink = make_batch_sink("run-789")
            result = sink([{"id": 1}])

            assert result == (3, 0)
            mock_persist.assert_called_once_with(
                [{"id": 1}], "run-789", None, None
            )
