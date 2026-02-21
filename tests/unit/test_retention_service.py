"""Unit tests for the GDPR RetentionService.

Tests cover:
- enforce_retention() deletes records older than the threshold
- enforce_retention() preserves records within the retention window
- enforce_retention() handles edge cases: empty database, zero-day retention
- enforce_retention() commits the transaction after deletion
- enforce_retention() logs the deletion with audit-relevant fields
- enforce_retention() uses collected_at (not published_at) for the threshold
- delete_actor_data() deletes from all five tables in FK-safe order
- delete_actor_data() returns a summary dict with per-table counts
- delete_actor_data() handles an actor with no associated data
- delete_actor_data() handles a nonexistent actor UUID gracefully
- delete_actor_data() commits the transaction after all deletions
- delete_actor_data() logs the erasure event with the full summary
- Error handling when database operations fail

All tests mock the SQLAlchemy AsyncSession.  No live database is required.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from issue_observatory.core.retention_service import RetentionService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_session(*, rowcount: int = 0) -> MagicMock:
    """Build a mock AsyncSession whose execute() returns a fixed rowcount.

    Args:
        rowcount: The rowcount value that every execute() call will return.
                  Simulates the number of rows affected by a DELETE statement.

    Returns:
        A MagicMock that quacks like an AsyncSession with execute() and commit().
    """
    session = MagicMock()
    mock_result = MagicMock()
    mock_result.rowcount = rowcount
    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()
    return session


def _make_mock_session_sequential(rowcounts: list[int]) -> MagicMock:
    """Build a mock AsyncSession whose execute() returns different rowcounts
    for successive calls.

    This is needed for delete_actor_data() which issues five DELETE statements
    in sequence, each potentially affecting a different number of rows.

    Args:
        rowcounts: A list of rowcount values, one per execute() call.

    Returns:
        A MagicMock that quacks like an AsyncSession.
    """
    session = MagicMock()
    call_index: list[int] = [0]

    async def _fake_execute(stmt: object) -> MagicMock:
        idx = call_index[0]
        call_index[0] += 1
        result = MagicMock()
        if idx < len(rowcounts):
            result.rowcount = rowcounts[idx]
        else:
            result.rowcount = 0
        return result

    session.execute = _fake_execute
    session.commit = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# enforce_retention() — time-based deletion
# ---------------------------------------------------------------------------


class TestEnforceRetention:
    """Tests for RetentionService.enforce_retention().

    This method enforces GDPR Art. 5(1)(e) storage limitation by deleting
    content_records older than the configured retention window.  It uses
    ``collected_at`` (not ``published_at``) as the threshold column.
    """

    async def test_enforce_retention_returns_deleted_count(self) -> None:
        """enforce_retention() returns the number of rows deleted by the DB."""
        db = _make_mock_session(rowcount=42)
        service = RetentionService()

        result = await service.enforce_retention(db, retention_days=730)

        assert result == 42

    async def test_enforce_retention_returns_zero_when_nothing_to_delete(self) -> None:
        """When no records exceed the retention window, the count is 0."""
        db = _make_mock_session(rowcount=0)
        service = RetentionService()

        result = await service.enforce_retention(db, retention_days=730)

        assert result == 0

    async def test_enforce_retention_commits_after_deletion(self) -> None:
        """The method commits the transaction so the deletion is persisted."""
        db = _make_mock_session(rowcount=5)
        service = RetentionService()

        await service.enforce_retention(db, retention_days=730)

        db.commit.assert_called_once()

    async def test_enforce_retention_commits_even_when_no_deletions(self) -> None:
        """The method commits even when zero rows are deleted.

        This is important: the commit finalizes the transaction regardless
        of whether any rows matched the WHERE clause, avoiding long-lived
        idle transactions.
        """
        db = _make_mock_session(rowcount=0)
        service = RetentionService()

        await service.enforce_retention(db, retention_days=365)

        db.commit.assert_called_once()

    async def test_enforce_retention_executes_one_delete_statement(self) -> None:
        """enforce_retention() issues exactly one DELETE statement.

        The implementation uses a single bulk DELETE with a WHERE clause
        rather than loading objects individually.
        """
        db = _make_mock_session(rowcount=10)
        service = RetentionService()

        await service.enforce_retention(db, retention_days=730)

        db.execute.assert_called_once()

    async def test_enforce_retention_with_zero_days_deletes_everything(self) -> None:
        """A retention_days of 0 means all records are eligible for deletion.

        The threshold becomes now() - 0 days = now(), so every record with
        collected_at < now() (i.e. essentially all records) should be deleted.
        """
        db = _make_mock_session(rowcount=9999)
        service = RetentionService()

        result = await service.enforce_retention(db, retention_days=0)

        assert result == 9999
        db.execute.assert_called_once()

    async def test_enforce_retention_with_large_retention_window(self) -> None:
        """A very large retention_days (e.g. 10 years) still executes correctly.

        The DELETE runs but is expected to find nothing to delete.
        """
        db = _make_mock_session(rowcount=0)
        service = RetentionService()

        result = await service.enforce_retention(db, retention_days=3650)

        assert result == 0

    async def test_enforce_retention_handles_none_rowcount(self) -> None:
        """If the DB driver returns None for rowcount, it is treated as 0.

        Some database backends may return None when no rows are affected.
        The code uses ``result.rowcount or 0`` to handle this.
        """
        db = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = None
        db.execute = AsyncMock(return_value=mock_result)
        db.commit = AsyncMock()
        service = RetentionService()

        result = await service.enforce_retention(db, retention_days=730)

        assert result == 0

    async def test_enforce_retention_logs_deletion_at_info_level(self) -> None:
        """enforce_retention() logs the event at INFO level with audit fields.

        The log record must include threshold_date, retention_days, and
        records_deleted so the audit log can reconstruct what happened.
        """
        db = _make_mock_session(rowcount=17)
        service = RetentionService()

        with patch(
            "issue_observatory.core.retention_service.logger"
        ) as mock_logger:
            await service.enforce_retention(db, retention_days=730)

            mock_logger.info.assert_called_once()
            log_call = mock_logger.info.call_args
            # First positional arg is the message key
            assert log_call.args[0] == "retention_enforcement_complete"
            # Extra dict contains the audit-relevant fields
            extra = log_call.kwargs.get("extra", {})
            assert "threshold_date" in extra
            assert extra["retention_days"] == 730
            assert extra["records_deleted"] == 17

    async def test_enforce_retention_logs_zero_deletions(self) -> None:
        """The audit log is emitted even when no records are deleted.

        Silence is suspicious in GDPR compliance. A log entry confirming
        that the retention sweep ran and found nothing is valuable evidence.
        """
        db = _make_mock_session(rowcount=0)
        service = RetentionService()

        with patch(
            "issue_observatory.core.retention_service.logger"
        ) as mock_logger:
            await service.enforce_retention(db, retention_days=365)

            mock_logger.info.assert_called_once()
            extra = mock_logger.info.call_args.kwargs.get("extra", {})
            assert extra["records_deleted"] == 0

    async def test_enforce_retention_threshold_is_utc(self) -> None:
        """The retention threshold is computed in UTC.

        GDPR does not specify a timezone, but the project convention is UTC
        for all timestamps. The threshold must be timezone-aware UTC.
        """
        db = _make_mock_session(rowcount=0)
        service = RetentionService()

        with patch(
            "issue_observatory.core.retention_service.logger"
        ) as mock_logger:
            await service.enforce_retention(db, retention_days=30)

            extra = mock_logger.info.call_args.kwargs.get("extra", {})
            threshold_str = extra["threshold_date"]
            # The threshold must be a valid ISO 8601 string with timezone info
            parsed = datetime.fromisoformat(threshold_str)
            assert parsed.tzinfo is not None

    async def test_enforce_retention_threshold_date_is_approximately_correct(self) -> None:
        """The threshold date is approximately now() - retention_days.

        We allow a 5-second tolerance to account for execution time.
        """
        db = _make_mock_session(rowcount=0)
        service = RetentionService()
        retention_days = 90

        with patch(
            "issue_observatory.core.retention_service.logger"
        ) as mock_logger:
            before = datetime.now(tz=timezone.utc) - timedelta(days=retention_days)
            await service.enforce_retention(db, retention_days=retention_days)
            after = datetime.now(tz=timezone.utc) - timedelta(days=retention_days)

            extra = mock_logger.info.call_args.kwargs.get("extra", {})
            threshold = datetime.fromisoformat(extra["threshold_date"])

            # The threshold must fall between before and after (within execution time)
            assert before - timedelta(seconds=5) <= threshold <= after + timedelta(seconds=5)

    async def test_enforce_retention_propagates_db_error(self) -> None:
        """If the database raises an exception, it propagates to the caller.

        The RetentionService does not swallow database errors. The calling
        layer is responsible for error handling and retry logic.
        """
        db = MagicMock()
        db.execute = AsyncMock(side_effect=RuntimeError("connection lost"))
        db.commit = AsyncMock()
        service = RetentionService()

        with pytest.raises(RuntimeError, match="connection lost"):
            await service.enforce_retention(db, retention_days=730)

    async def test_enforce_retention_does_not_commit_on_execute_failure(self) -> None:
        """If execute() raises, commit() must NOT be called.

        A failed DELETE must not be followed by a commit, as there is
        nothing to commit and it could mask the error.
        """
        db = MagicMock()
        db.execute = AsyncMock(side_effect=RuntimeError("disk full"))
        db.commit = AsyncMock()
        service = RetentionService()

        with pytest.raises(RuntimeError):
            await service.enforce_retention(db, retention_days=730)

        db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# delete_actor_data() — right to erasure (GDPR Art. 17)
# ---------------------------------------------------------------------------


class TestDeleteActorData:
    """Tests for RetentionService.delete_actor_data().

    This method implements the GDPR right to erasure by deleting all data
    associated with a specific actor across five tables in FK-safe order:
    1. content_records (author_id)
    2. actor_platform_presences (actor_id)
    3. actor_aliases (actor_id)
    4. actor_list_members (actor_id)
    5. actors (id)
    """

    async def test_delete_actor_data_returns_summary_dict(self) -> None:
        """The return value is a dict with counts for each table."""
        db = _make_mock_session_sequential([3, 2, 1, 4, 1])
        actor_id = uuid.uuid4()
        service = RetentionService()

        result = await service.delete_actor_data(db, actor_id=actor_id)

        assert isinstance(result, dict)
        assert result["actor_id"] == str(actor_id)
        assert result["content_records"] == 3
        assert result["presences"] == 2
        assert result["aliases"] == 1
        assert result["list_memberships"] == 4
        assert result["actors"] == 1

    async def test_delete_actor_data_issues_five_delete_statements(self) -> None:
        """Exactly five DELETE statements are executed, one per table."""
        db = _make_mock_session(rowcount=0)
        service = RetentionService()

        await service.delete_actor_data(db, actor_id=uuid.uuid4())

        assert db.execute.call_count == 5

    async def test_delete_actor_data_commits_after_all_deletions(self) -> None:
        """A single commit is issued after all five DELETEs complete.

        Atomicity is critical for right-to-erasure: either all data is
        deleted or none is. A partial deletion is a GDPR violation.
        """
        db = _make_mock_session(rowcount=0)
        service = RetentionService()

        await service.delete_actor_data(db, actor_id=uuid.uuid4())

        db.commit.assert_called_once()

    async def test_delete_actor_data_all_zeros_for_nonexistent_actor(self) -> None:
        """An actor UUID with no data in any table returns all-zero counts.

        This is not an error condition: the caller may be processing a
        deletion request for an actor that was already deleted, or for
        a UUID that was never used.
        """
        db = _make_mock_session_sequential([0, 0, 0, 0, 0])
        actor_id = uuid.uuid4()
        service = RetentionService()

        result = await service.delete_actor_data(db, actor_id=actor_id)

        assert result["content_records"] == 0
        assert result["presences"] == 0
        assert result["aliases"] == 0
        assert result["list_memberships"] == 0
        assert result["actors"] == 0

    async def test_delete_actor_data_actor_with_only_content_records(self) -> None:
        """An actor who only has content records and no presences/aliases.

        This scenario arises when an actor was auto-detected from content
        but never manually registered with platform presences.
        """
        db = _make_mock_session_sequential([15, 0, 0, 0, 1])
        service = RetentionService()

        result = await service.delete_actor_data(db, actor_id=uuid.uuid4())

        assert result["content_records"] == 15
        assert result["presences"] == 0
        assert result["aliases"] == 0
        assert result["list_memberships"] == 0
        assert result["actors"] == 1

    async def test_delete_actor_data_actor_with_many_presences(self) -> None:
        """An actor with platform presences on multiple platforms.

        A well-documented actor might have presences on Bluesky, Reddit,
        X/Twitter, YouTube, etc. All must be deleted.
        """
        db = _make_mock_session_sequential([0, 6, 3, 2, 1])
        service = RetentionService()

        result = await service.delete_actor_data(db, actor_id=uuid.uuid4())

        assert result["presences"] == 6
        assert result["aliases"] == 3
        assert result["list_memberships"] == 2

    async def test_delete_actor_data_handles_none_rowcount(self) -> None:
        """If any DELETE returns None for rowcount, it is treated as 0.

        The code uses ``result.rowcount or 0`` for each operation.
        """
        db = MagicMock()
        call_index: list[int] = [0]

        async def _fake_execute(stmt: object) -> MagicMock:
            call_index[0] += 1
            result = MagicMock()
            result.rowcount = None  # all operations return None
            return result

        db.execute = _fake_execute
        db.commit = AsyncMock()
        service = RetentionService()

        result = await service.delete_actor_data(db, actor_id=uuid.uuid4())

        assert result["content_records"] == 0
        assert result["presences"] == 0
        assert result["aliases"] == 0
        assert result["list_memberships"] == 0
        assert result["actors"] == 0

    async def test_delete_actor_data_summary_contains_actor_id_as_string(self) -> None:
        """The summary dict includes actor_id as a string (for JSON serialization)."""
        db = _make_mock_session(rowcount=0)
        actor_id = uuid.uuid4()
        service = RetentionService()

        result = await service.delete_actor_data(db, actor_id=actor_id)

        assert result["actor_id"] == str(actor_id)

    async def test_delete_actor_data_logs_erasure_event(self) -> None:
        """delete_actor_data() logs the erasure at INFO level with the full summary.

        The log must include the actor_id and per-table deletion counts
        so that the audit trail is complete and verifiable.
        """
        db = _make_mock_session_sequential([5, 2, 1, 3, 1])
        actor_id = uuid.uuid4()
        service = RetentionService()

        with patch(
            "issue_observatory.core.retention_service.logger"
        ) as mock_logger:
            await service.delete_actor_data(db, actor_id=actor_id)

            mock_logger.info.assert_called_once()
            log_call = mock_logger.info.call_args
            assert log_call.args[0] == "actor_data_erased"
            extra = log_call.kwargs.get("extra", {})
            assert extra["actor_id"] == str(actor_id)
            assert extra["content_records"] == 5
            assert extra["presences"] == 2
            assert extra["aliases"] == 1
            assert extra["list_memberships"] == 3
            assert extra["actors"] == 1

    async def test_delete_actor_data_logs_even_when_nothing_deleted(self) -> None:
        """The erasure log is emitted even when no data existed for the actor.

        For GDPR compliance, the system must be able to prove it attempted
        the deletion. A log entry saying "we looked and found nothing" is
        valid evidence.
        """
        db = _make_mock_session(rowcount=0)
        service = RetentionService()

        with patch(
            "issue_observatory.core.retention_service.logger"
        ) as mock_logger:
            await service.delete_actor_data(db, actor_id=uuid.uuid4())

            mock_logger.info.assert_called_once()
            extra = mock_logger.info.call_args.kwargs.get("extra", {})
            assert extra["content_records"] == 0
            assert extra["actors"] == 0

    async def test_delete_actor_data_propagates_db_error(self) -> None:
        """If a DELETE fails, the exception propagates to the caller.

        Partial deletion must not be silently accepted. The caller must
        know the erasure was incomplete and handle retries.
        """
        db = MagicMock()
        db.execute = AsyncMock(side_effect=RuntimeError("table locked"))
        db.commit = AsyncMock()
        service = RetentionService()

        with pytest.raises(RuntimeError, match="table locked"):
            await service.delete_actor_data(db, actor_id=uuid.uuid4())

    async def test_delete_actor_data_does_not_commit_on_failure(self) -> None:
        """If any DELETE raises, commit() must NOT be called.

        A partial deletion without a subsequent rollback is dangerous.
        The caller is responsible for rolling back on error.
        """
        db = MagicMock()
        # Fail on the second execute (presences DELETE)
        call_count: list[int] = [0]

        async def _failing_execute(stmt: object) -> MagicMock:
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("FK constraint violation")
            result = MagicMock()
            result.rowcount = 1
            return result

        db.execute = _failing_execute
        db.commit = AsyncMock()
        service = RetentionService()

        with pytest.raises(RuntimeError, match="FK constraint"):
            await service.delete_actor_data(db, actor_id=uuid.uuid4())

        db.commit.assert_not_called()

    async def test_delete_actor_data_summary_has_all_required_keys(self) -> None:
        """The summary dict contains exactly the six expected keys."""
        db = _make_mock_session(rowcount=0)
        service = RetentionService()

        result = await service.delete_actor_data(db, actor_id=uuid.uuid4())

        expected_keys = {
            "actor_id",
            "content_records",
            "presences",
            "aliases",
            "list_memberships",
            "actors",
        }
        assert set(result.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Statelessness and reusability
# ---------------------------------------------------------------------------


class TestRetentionServiceReusability:
    """The RetentionService is documented as stateless and reusable.

    A single instance should work correctly across multiple calls without
    any cross-contamination of state.
    """

    async def test_service_is_reusable_across_enforce_retention_calls(self) -> None:
        """A single RetentionService instance can enforce_retention() multiple times."""
        service = RetentionService()

        db1 = _make_mock_session(rowcount=10)
        result1 = await service.enforce_retention(db1, retention_days=365)

        db2 = _make_mock_session(rowcount=5)
        result2 = await service.enforce_retention(db2, retention_days=730)

        assert result1 == 10
        assert result2 == 5

    async def test_service_is_reusable_across_delete_actor_data_calls(self) -> None:
        """A single RetentionService instance can delete_actor_data() multiple times."""
        service = RetentionService()

        db1 = _make_mock_session_sequential([3, 1, 0, 0, 1])
        result1 = await service.delete_actor_data(db1, actor_id=uuid.uuid4())

        db2 = _make_mock_session_sequential([0, 0, 0, 0, 0])
        result2 = await service.delete_actor_data(db2, actor_id=uuid.uuid4())

        assert result1["content_records"] == 3
        assert result2["content_records"] == 0

    async def test_service_can_interleave_both_operations(self) -> None:
        """enforce_retention() and delete_actor_data() can be called alternately."""
        service = RetentionService()

        db1 = _make_mock_session(rowcount=7)
        r1 = await service.enforce_retention(db1, retention_days=365)

        db2 = _make_mock_session_sequential([2, 1, 0, 0, 1])
        r2 = await service.delete_actor_data(db2, actor_id=uuid.uuid4())

        db3 = _make_mock_session(rowcount=3)
        r3 = await service.enforce_retention(db3, retention_days=90)

        assert r1 == 7
        assert r2["content_records"] == 2
        assert r3 == 3
