"""Unit tests for CreditService.

Tests use a mocked AsyncSession so they run without any database infrastructure.
This covers the credit balance formula, reservation/settlement/refund state
transitions, and InsufficientCreditError enforcement.

Integration tests that verify the full SQL against a live PostgreSQL database
live in tests/integration/test_credit_service_integration.py.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from issue_observatory.core.credit_service import CreditService
from issue_observatory.core.exceptions import InsufficientCreditError


# ---------------------------------------------------------------------------
# Mock session factory
# ---------------------------------------------------------------------------


def _make_mock_session(
    *,
    total_allocated: int = 0,
    reserved: int = 0,
    settled: int = 0,
    refunded: int = 0,
) -> MagicMock:
    """Build a mock AsyncSession whose execute() returns preset scalar values.

    The CreditService.get_balance() method executes four queries in sequence:
    1. SUM(credit_allocations.credits_amount) → total_allocated
    2. SUM(reservation transactions) → reserved
    3. SUM(settlement transactions) → settled
    4. SUM(refund transactions) → refunded

    This factory wires up the mock to return those values in that order.
    """
    session = MagicMock()

    # Return values for successive execute() calls (in get_balance order)
    scalar_results = [total_allocated, reserved, settled, refunded]
    call_count: list[int] = [0]

    async def _fake_execute(stmt: object) -> MagicMock:
        idx = call_count[0] % len(scalar_results)
        call_count[0] += 1
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = scalar_results[idx]
        result_mock.scalar_one_or_none.return_value = scalar_results[idx]
        return result_mock

    session.execute = _fake_execute
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()

    return session


# ---------------------------------------------------------------------------
# get_balance / get_available_credits
# ---------------------------------------------------------------------------


class TestGetBalance:
    async def test_get_balance_empty_returns_zero(self) -> None:
        """New user with no allocations and no transactions has 0 available."""
        session = _make_mock_session(
            total_allocated=0, reserved=0, settled=0, refunded=0
        )
        service = CreditService(session=session)
        user_id = uuid.uuid4()

        balance = await service.get_balance(user_id)

        assert balance["total_allocated"] == 0
        assert balance["reserved"] == 0
        assert balance["settled"] == 0
        assert balance["refunded"] == 0
        assert balance["available"] == 0

    async def test_get_balance_allocation_minus_settled(self) -> None:
        """available = total_allocated - reserved - settled + refunded."""
        session = _make_mock_session(
            total_allocated=1000,
            reserved=200,
            settled=300,
            refunded=50,
        )
        service = CreditService(session=session)
        user_id = uuid.uuid4()

        balance = await service.get_balance(user_id)

        # 1000 - 200 - 300 + 50 = 550
        assert balance["available"] == 550

    async def test_get_available_credits_scalar(self) -> None:
        """get_available_credits() returns the scalar available balance."""
        session = _make_mock_session(total_allocated=500, reserved=100, settled=0, refunded=0)
        service = CreditService(session=session)
        user_id = uuid.uuid4()

        available = await service.get_available_credits(user_id)

        assert available == 400  # 500 - 100 - 0 + 0


# ---------------------------------------------------------------------------
# reserve()
# ---------------------------------------------------------------------------


class TestReserve:
    async def test_reserve_insufficient_credits_raises(self) -> None:
        """InsufficientCreditError is raised when available < credits_amount.

        This is the primary budget guard — it must fire before any transaction
        row is written to the database.
        """
        user_id = uuid.uuid4()
        run_id = uuid.uuid4()

        # User has only 50 credits available
        session = _make_mock_session(total_allocated=100, reserved=50, settled=0, refunded=0)
        service = CreditService(session=session)

        with pytest.raises(InsufficientCreditError) as exc_info:
            await service.reserve(
                user_id=user_id,
                collection_run_id=run_id,
                arena="google_search",
                platform="google",
                tier="medium",
                credits_amount=100,  # more than the 50 available
            )

        err = exc_info.value
        assert err.required == 100
        assert err.available == 50
        assert str(user_id) in (err.user_id or "")

    async def test_reserve_with_sufficient_credits_writes_transaction(self) -> None:
        """reserve() adds a CreditTransaction row when balance is sufficient."""
        user_id = uuid.uuid4()
        run_id = uuid.uuid4()
        session = _make_mock_session(total_allocated=500, reserved=0, settled=0, refunded=0)

        # Mock the refresh to populate transaction.id
        mock_txn_id = uuid.uuid4()

        async def _fake_refresh(obj: object) -> None:
            obj.id = mock_txn_id  # type: ignore[attr-defined]

        session.refresh = _fake_refresh
        service = CreditService(session=session)

        result = await service.reserve(
            user_id=user_id,
            collection_run_id=run_id,
            arena="google_search",
            platform="google",
            tier="medium",
            credits_amount=100,
        )

        # session.add() and session.commit() must have been called
        session.add.assert_called_once()
        session.commit.assert_called_once()
        assert result == mock_txn_id

    async def test_reserve_zero_credits_always_succeeds(self) -> None:
        """Reserving 0 credits succeeds even with 0 balance (free-tier arenas)."""
        user_id = uuid.uuid4()
        run_id = uuid.uuid4()
        session = _make_mock_session(total_allocated=0, reserved=0, settled=0, refunded=0)

        mock_txn_id = uuid.uuid4()

        async def _fake_refresh(obj: object) -> None:
            obj.id = mock_txn_id  # type: ignore[attr-defined]

        session.refresh = _fake_refresh
        service = CreditService(session=session)

        # Should not raise
        result = await service.reserve(
            user_id=user_id,
            collection_run_id=run_id,
            arena="rss_feeds",
            platform="dr_rss",
            tier="free",
            credits_amount=0,
        )

        assert result == mock_txn_id


# ---------------------------------------------------------------------------
# refund()
# ---------------------------------------------------------------------------


class TestRefund:
    async def test_refund_restores_balance(self) -> None:
        """After a refund, get_available_credits reflects the restored credits.

        The balance formula adds refund rows back:
        available = allocated - reserved - settled + refunded.
        """
        user_id = uuid.uuid4()
        run_id = uuid.uuid4()

        # Simulate: 500 allocated, 200 reserved, 0 settled → 300 available
        # After refund of 200 → effective available = 500 (all reserved back)
        # We test that refund() writes to the DB; the formula is tested in get_balance tests.
        session = _make_mock_session(
            total_allocated=500, reserved=200, settled=0, refunded=0
        )
        mock_txn_id = uuid.uuid4()

        async def _fake_refresh(obj: object) -> None:
            obj.id = mock_txn_id  # type: ignore[attr-defined]

        session.refresh = _fake_refresh
        service = CreditService(session=session)

        result = await service.refund(
            user_id=user_id,
            collection_run_id=run_id,
            arena="google_search",
            platform="google",
            tier="medium",
            credits_amount=200,
            description="Task failed — releasing reservation",
        )

        session.add.assert_called_once()
        session.commit.assert_called_once()
        assert result == mock_txn_id

    async def test_refund_creates_refund_transaction_type(self) -> None:
        """The CreditTransaction written by refund() has transaction_type='refund'."""
        user_id = uuid.uuid4()
        run_id = uuid.uuid4()
        session = _make_mock_session(total_allocated=500, reserved=100, settled=0, refunded=0)

        captured_txn: list = []

        def _capture_add(obj: object) -> None:
            captured_txn.append(obj)

        session.add = _capture_add

        async def _fake_refresh(obj: object) -> None:
            obj.id = uuid.uuid4()  # type: ignore[attr-defined]

        session.refresh = _fake_refresh
        service = CreditService(session=session)

        await service.refund(
            user_id=user_id,
            collection_run_id=run_id,
            arena="google_search",
            platform="google",
            tier="medium",
            credits_amount=100,
        )

        assert len(captured_txn) == 1
        txn = captured_txn[0]
        assert txn.transaction_type == "refund"


# ---------------------------------------------------------------------------
# settle() auto-refund
# ---------------------------------------------------------------------------


class TestSettle:
    async def test_settle_calls_refund_for_surplus(self) -> None:
        """settle() automatically refunds the surplus when actual < reserved.

        If a user reserved 200 credits but only consumed 150, the remaining
        50 must be refunded so the user's balance is correctly restored.
        This is handled by settle() without any caller action.
        """
        user_id = uuid.uuid4()
        run_id = uuid.uuid4()

        # The settle() method executes an additional query to sum reservations.
        # We need a session mock that returns the correct values for each call.
        call_seq: list[int] = []
        # Call order in settle():
        # 1. get_available_credits → (allocated, reserved, settled, refunded) × 4 queries
        #    Actually settle() does NOT call get_balance; it only queries total reserved
        #    for the specific run+arena+platform. Let's trace through the code:
        #    - One execute() for the reserved_stmt (sum reservations for run)
        #    → returns total_reserved = 200
        # Then it writes settlement txn.
        # Then checks surplus (200 - 150 = 50) and calls refund().
        # refund() writes another txn.

        total_reserved_for_run = 200

        results_iter = iter([total_reserved_for_run])

        async def _fake_execute(stmt: object) -> MagicMock:
            try:
                val = next(results_iter)
            except StopIteration:
                val = 0
            r = MagicMock()
            r.scalar_one.return_value = val
            r.scalar_one_or_none.return_value = val
            return r

        session = MagicMock()
        session.execute = _fake_execute
        session.add = MagicMock()
        session.commit = AsyncMock()

        add_calls: list = []

        def _capture_add(obj: object) -> None:
            add_calls.append(obj)

        session.add = _capture_add

        async def _fake_refresh(obj: object) -> None:
            obj.id = uuid.uuid4()  # type: ignore[attr-defined]

        session.refresh = _fake_refresh
        session.rollback = AsyncMock()

        service = CreditService(session=session)

        await service.settle(
            user_id=user_id,
            collection_run_id=run_id,
            arena="google_search",
            platform="google",
            tier="medium",
            actual_credits=150,  # consumed less than reserved
        )

        # Two CreditTransaction rows: one settlement + one refund
        assert len(add_calls) == 2

        settlement_txn = add_calls[0]
        refund_txn = add_calls[1]

        assert settlement_txn.transaction_type == "settlement"
        assert settlement_txn.credits_consumed == 150

        assert refund_txn.transaction_type == "refund"
        assert refund_txn.credits_consumed == 50  # 200 - 150 surplus
