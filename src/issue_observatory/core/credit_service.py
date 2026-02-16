"""Credit reservation, settlement, balance management, and pre-flight estimation.

The credit system maps directly to API cost units so that administrators can
allocate meaningful budgets:

  - Free-tier arenas:       0 credits  (no monetary cost)
  - YouTube Data API v3:    1 credit   = 1 API unit  (a search call = 100 credits)
  - Serper.dev:             1 credit   = 1 SERP query
  - TwitterAPI.io:          1 credit   = 1 tweet retrieved
  - TikTok Research API:    1 credit   = 1 API request

Balance formula
---------------
  available = SUM(credit_allocations.credits_amount)   # valid today
            - SUM(credit_transactions WHERE type IN ('reservation', 'settlement'))
            + SUM(credit_transactions WHERE type = 'refund')

The reservation+settlement pattern prevents users from exceeding their budget:

  1. Pre-flight:   estimate() computes expected cost without writing anything.
  2. Reservation:  reserve() writes a 'reservation' row and locks those credits.
  3. Settlement:   settle() writes a 'settlement' row; if actual < reserved,
                   refund() is called automatically for the difference.
  4. Refund:       refund() releases credits on task failure or cancellation.

Owned by the DB Engineer.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.core.database import get_db
from issue_observatory.core.exceptions import (
    CreditReservationError,
    InsufficientCreditError,
)
from issue_observatory.core.models.collection import CreditTransaction
from issue_observatory.core.models.users import CreditAllocation

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _today() -> date:
    """Return today's date in UTC."""
    return datetime.now(tz=timezone.utc).date()


# ---------------------------------------------------------------------------
# CreditService
# ---------------------------------------------------------------------------


class CreditService:
    """Manages credit balance, reservations, and settlement for collection runs.

    Credits map 1:1 to API cost units. The reservation+settlement pattern
    ensures users cannot exceed their allocated budget:

    1. Pre-flight: estimate() computes expected cost without committing
    2. Reservation: reserve() locks credits at run start (transaction_type='reservation')
    3. Settlement: settle() records actual cost at run completion (transaction_type='settlement')
    4. Refund: refund() releases unused reserved credits on failure (transaction_type='refund')

    Balance = SUM(allocations valid today) - SUM(credit_transactions where type='reservation'
                or type='settlement') + SUM(refunds)

    All write methods commit immediately so that concurrent Celery workers
    operating in separate sessions see up-to-date balances.

    Args:
        session: An open :class:`sqlalchemy.ext.asyncio.AsyncSession`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Balance queries
    # ------------------------------------------------------------------

    async def get_balance(self, user_id: uuid.UUID) -> dict:
        """Return credit balance breakdown for a user.

        Returns:
            Dict with keys: total_allocated, reserved, settled, refunded,
            available.

            available = total_allocated - reserved - settled + refunded
        """
        today = _today()

        # Total allocated: sum of valid non-expired allocations
        alloc_stmt = (
            select(func.coalesce(func.sum(CreditAllocation.credits_amount), 0))
            .where(CreditAllocation.user_id == user_id)
            .where(CreditAllocation.valid_from <= today)
            .where(
                (CreditAllocation.valid_until.is_(None))
                | (CreditAllocation.valid_until >= today)
            )
        )
        alloc_result = await self.session.execute(alloc_stmt)
        total_allocated: int = int(alloc_result.scalar_one())

        # Reserved: sum of all 'reservation' transactions
        reserved_stmt = (
            select(func.coalesce(func.sum(CreditTransaction.credits_consumed), 0))
            .where(CreditTransaction.user_id == user_id)
            .where(CreditTransaction.transaction_type == "reservation")
        )
        reserved_result = await self.session.execute(reserved_stmt)
        reserved: int = int(reserved_result.scalar_one())

        # Settled: sum of all 'settlement' transactions
        settled_stmt = (
            select(func.coalesce(func.sum(CreditTransaction.credits_consumed), 0))
            .where(CreditTransaction.user_id == user_id)
            .where(CreditTransaction.transaction_type == "settlement")
        )
        settled_result = await self.session.execute(settled_stmt)
        settled: int = int(settled_result.scalar_one())

        # Refunded: sum of all 'refund' transactions
        refunded_stmt = (
            select(func.coalesce(func.sum(CreditTransaction.credits_consumed), 0))
            .where(CreditTransaction.user_id == user_id)
            .where(CreditTransaction.transaction_type == "refund")
        )
        refunded_result = await self.session.execute(refunded_stmt)
        refunded: int = int(refunded_result.scalar_one())

        available = total_allocated - reserved - settled + refunded

        logger.info(
            "Credit balance lookup",
            extra={
                "user_id": str(user_id),
                "total_allocated": total_allocated,
                "reserved": reserved,
                "settled": settled,
                "refunded": refunded,
                "available": available,
            },
        )

        return {
            "total_allocated": total_allocated,
            "reserved": reserved,
            "settled": settled,
            "refunded": refunded,
            "available": available,
        }

    async def get_available_credits(self, user_id: uuid.UUID) -> int:
        """Return spendable credit balance (total allocated minus consumed).

        This is the scalar equivalent of ``get_balance()["available"]``,
        used in hot paths such as the reservation check where only the
        availability decision is needed.

        Returns:
            Non-negative integer of spendable credits.
        """
        balance = await self.get_balance(user_id)
        return balance["available"]

    # ------------------------------------------------------------------
    # Pre-flight estimation
    # ------------------------------------------------------------------

    async def estimate(
        self,
        query_design_id: uuid.UUID,
        tier: str,
        arenas_config: dict,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> dict:
        """Compute pre-flight credit estimate without committing any state.

        For each arena listed in *arenas_config*, the method attempts to
        call ``estimate_credits()`` on the registered collector. If the
        arena is not in the registry (e.g. during Phase 0 before arenas are
        implemented) it falls back to ``TIER_DEFAULTS`` from
        :mod:`issue_observatory.config.tiers`. Arenas for which no cost can
        be determined default to 0 (free tier behaviour).

        Args:
            query_design_id: UUID of the query design being estimated.
                Reserved for future use (e.g. counting terms to refine
                the estimate).
            tier: Default tier (``"free"``, ``"medium"``, ``"premium"``)
                applied to arenas not listed in *arenas_config*.
            arenas_config: Per-arena tier overrides, e.g.
                ``{"youtube": "medium", "bluesky": "free"}``.
            date_from: Start of collection window (batch mode).
            date_to: End of collection window (batch mode).

        Returns:
            Dict with:

            - ``total_credits`` (int): Sum of all arena estimates.
            - ``per_arena`` (dict[str, int]): Per-arena credit cost.
        """
        # Lazy imports to avoid circular dependencies and to allow tests to
        # run without a fully-wired arena registry.
        from issue_observatory.arenas import registry as _registry  # noqa: PLC0415
        from issue_observatory.config.tiers import TIER_DEFAULTS, Tier as TierEnum  # noqa: PLC0415

        per_arena: dict[str, int] = {}

        for arena_name, arena_tier_str in arenas_config.items():
            resolved_tier_str: str = arena_tier_str or tier
            try:
                resolved_tier = TierEnum(resolved_tier_str)
            except ValueError:
                resolved_tier = TierEnum.FREE

            credits_for_arena: int = 0

            try:
                collector_cls = _registry.get_arena(arena_name)
                collector = collector_cls()
                credits_for_arena = await collector.estimate_credits(
                    tier=resolved_tier,
                    date_from=date_from,
                    date_to=date_to,
                )
            except KeyError:
                # Arena not in registry — fall back to TIER_DEFAULTS
                tier_config = TIER_DEFAULTS.get(resolved_tier)
                credits_for_arena = (
                    tier_config.estimated_credits_per_1k
                    if tier_config is not None
                    else 0
                )
                logger.debug(
                    "Arena '%s' not registered; TIER_DEFAULTS fallback gives %d credits",
                    arena_name,
                    credits_for_arena,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "estimate_credits() failed for arena '%s' (tier=%s): %s; defaulting to 0",
                    arena_name,
                    resolved_tier_str,
                    exc,
                )
                credits_for_arena = 0

            per_arena[arena_name] = credits_for_arena

        total_credits: int = sum(per_arena.values())

        logger.info(
            "Credit estimate computed",
            extra={
                "query_design_id": str(query_design_id),
                "tier": tier,
                "total_credits": total_credits,
                "per_arena": per_arena,
            },
        )

        return {
            "total_credits": total_credits,
            "per_arena": per_arena,
        }

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def reserve(
        self,
        user_id: uuid.UUID,
        collection_run_id: uuid.UUID,
        arena: str,
        platform: str,
        tier: str,
        credits_amount: int,
        description: str = "",
    ) -> uuid.UUID:
        """Reserve credits for an in-progress collection run.

        Creates a credit_transactions record with transaction_type='reservation'.
        The reservation reduces the user's available balance immediately so that
        concurrent runs cannot double-spend the same credits.

        Args:
            user_id: Owner of the credits.
            collection_run_id: The run that is consuming these credits.
            arena: Arena identifier (e.g. ``"social_media"``).
            platform: Platform identifier (e.g. ``"youtube"``).
            tier: Tier string.
            credits_amount: Number of credits to lock. Must be >= 0.
            description: Human-readable note stored on the transaction row.

        Returns:
            UUID of the newly created :class:`CreditTransaction` row.

        Raises:
            InsufficientCreditError: If the user's available balance is less
                than *credits_amount*.
            CreditReservationError: If the transaction row cannot be
                persisted (wraps unexpected database errors).
        """
        available = await self.get_available_credits(user_id)

        if available < credits_amount:
            logger.warning(
                "Insufficient credits for reservation",
                extra={
                    "user_id": str(user_id),
                    "collection_run_id": str(collection_run_id),
                    "arena": arena,
                    "platform": platform,
                    "required": credits_amount,
                    "available": available,
                },
            )
            raise InsufficientCreditError(
                required=credits_amount,
                available=available,
                user_id=str(user_id),
            )

        try:
            txn = CreditTransaction(
                user_id=user_id,
                collection_run_id=collection_run_id,
                arena=arena,
                platform=platform,
                tier=tier,
                credits_consumed=credits_amount,
                transaction_type="reservation",
                description=description or (
                    f"Reservation: {platform} ({arena}) [{tier}]"
                ),
            )
            self.session.add(txn)
            await self.session.commit()
            await self.session.refresh(txn)
        except Exception as exc:
            await self.session.rollback()
            raise CreditReservationError(
                message=f"Failed to create reservation transaction: {exc}",
                collection_run_id=str(collection_run_id),
            ) from exc

        logger.info(
            "Credits reserved",
            extra={
                "user_id": str(user_id),
                "collection_run_id": str(collection_run_id),
                "arena": arena,
                "platform": platform,
                "tier": tier,
                "credits_reserved": credits_amount,
                "transaction_id": str(txn.id),
            },
        )

        return txn.id

    async def settle(
        self,
        user_id: uuid.UUID,
        collection_run_id: uuid.UUID,
        arena: str,
        platform: str,
        tier: str,
        actual_credits: int,
        description: str = "",
    ) -> uuid.UUID:
        """Settle actual credit consumption after a collection task completes.

        Creates a settlement transaction. If actual_credits is less than the
        total previously reserved for this run+arena+platform combination, the
        surplus is automatically refunded via :meth:`refund` so the user's
        balance is restored.

        Args:
            user_id: Owner of the credits.
            collection_run_id: The run being settled.
            arena: Arena identifier.
            platform: Platform identifier.
            tier: Tier string.
            actual_credits: Actual credits consumed (may be 0 for free arenas
                or aborted tasks).
            description: Human-readable note stored on the transaction row.

        Returns:
            UUID of the ``'settlement'`` :class:`CreditTransaction` row.

        Raises:
            CreditReservationError: If the settlement transaction cannot be
                persisted.
        """
        # Sum reservations for this run+arena+platform to determine auto-refund
        reserved_stmt = (
            select(func.coalesce(func.sum(CreditTransaction.credits_consumed), 0))
            .where(CreditTransaction.user_id == user_id)
            .where(CreditTransaction.collection_run_id == collection_run_id)
            .where(CreditTransaction.arena == arena)
            .where(CreditTransaction.platform == platform)
            .where(CreditTransaction.transaction_type == "reservation")
        )
        reserved_result = await self.session.execute(reserved_stmt)
        total_reserved: int = int(reserved_result.scalar_one())

        try:
            txn = CreditTransaction(
                user_id=user_id,
                collection_run_id=collection_run_id,
                arena=arena,
                platform=platform,
                tier=tier,
                credits_consumed=actual_credits,
                transaction_type="settlement",
                description=description or (
                    f"Settlement: {platform} ({arena}) [{tier}]"
                ),
            )
            self.session.add(txn)
            await self.session.commit()
            await self.session.refresh(txn)
        except Exception as exc:
            await self.session.rollback()
            raise CreditReservationError(
                message=f"Failed to create settlement transaction: {exc}",
                collection_run_id=str(collection_run_id),
            ) from exc

        logger.info(
            "Credits settled",
            extra={
                "user_id": str(user_id),
                "collection_run_id": str(collection_run_id),
                "arena": arena,
                "platform": platform,
                "tier": tier,
                "actual_credits": actual_credits,
                "total_reserved": total_reserved,
                "transaction_id": str(txn.id),
            },
        )

        # Auto-refund surplus between reserved and actual consumption
        surplus = total_reserved - actual_credits
        if surplus > 0:
            await self.refund(
                user_id=user_id,
                collection_run_id=collection_run_id,
                arena=arena,
                platform=platform,
                tier=tier,
                credits_amount=surplus,
                description=(
                    f"Auto-refund: reserved {total_reserved}, "
                    f"settled {actual_credits}, surplus {surplus}"
                ),
            )

        return txn.id

    async def refund(
        self,
        user_id: uuid.UUID,
        collection_run_id: uuid.UUID,
        arena: str,
        platform: str,
        tier: str,
        credits_amount: int,
        description: str = "",
    ) -> uuid.UUID:
        """Refund reserved credits when a collection task fails or is cancelled.

        Creates a credit_transactions record with transaction_type='refund'.
        Refunds increase the user's available balance because the balance
        formula adds refund rows back.

        Args:
            user_id: Owner of the credits.
            collection_run_id: The run whose reservation is being released.
            arena: Arena identifier.
            platform: Platform identifier.
            tier: Tier string.
            credits_amount: Number of credits to refund. Must be >= 0.
            description: Human-readable note stored on the transaction row.

        Returns:
            UUID of the ``'refund'`` :class:`CreditTransaction` row.

        Raises:
            CreditReservationError: If the refund transaction cannot be
                persisted.
        """
        try:
            txn = CreditTransaction(
                user_id=user_id,
                collection_run_id=collection_run_id,
                arena=arena,
                platform=platform,
                tier=tier,
                credits_consumed=credits_amount,
                transaction_type="refund",
                description=description or (
                    f"Refund: {platform} ({arena}) [{tier}]"
                ),
            )
            self.session.add(txn)
            await self.session.commit()
            await self.session.refresh(txn)
        except Exception as exc:
            await self.session.rollback()
            raise CreditReservationError(
                message=f"Failed to create refund transaction: {exc}",
                collection_run_id=str(collection_run_id),
            ) from exc

        logger.info(
            "Credits refunded",
            extra={
                "user_id": str(user_id),
                "collection_run_id": str(collection_run_id),
                "arena": arena,
                "platform": platform,
                "tier": tier,
                "credits_refunded": credits_amount,
                "transaction_id": str(txn.id),
            },
        )

        return txn.id

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    async def get_transaction_history(
        self,
        user_id: uuid.UUID,
        limit: int = 50,
        cursor: uuid.UUID | None = None,
    ) -> list[CreditTransaction]:
        """Return paginated credit transaction history for a user.

        Uses keyset pagination over (created_at DESC, id DESC) for stable,
        efficient paging over large transaction logs. Pass the ``id`` of the
        last returned row as *cursor* to retrieve the next page.

        Args:
            user_id: User whose transaction history to retrieve.
            limit: Maximum rows per page (hard-capped at 200 to avoid
                memory pressure on large accounts).
            cursor: ``CreditTransaction.id`` of the last row from the
                previous page. If ``None``, returns from the most recent
                transaction.

        Returns:
            List of :class:`CreditTransaction` ORM objects ordered from
            most recent to oldest.
        """
        limit = min(limit, 200)

        stmt = (
            select(CreditTransaction)
            .where(CreditTransaction.user_id == user_id)
            .order_by(
                CreditTransaction.created_at.desc(),
                CreditTransaction.id.desc(),
            )
            .limit(limit)
        )

        if cursor is not None:
            # Resolve the created_at timestamp of the cursor row so we can
            # apply a stable keyset condition without relying on UUID ordering.
            cursor_ts_stmt = select(CreditTransaction.created_at).where(
                CreditTransaction.id == cursor
            )
            cursor_ts_result = await self.session.execute(cursor_ts_stmt)
            cursor_ts = cursor_ts_result.scalar_one_or_none()
            if cursor_ts is not None:
                stmt = stmt.where(
                    (CreditTransaction.created_at < cursor_ts)
                    | (
                        (CreditTransaction.created_at == cursor_ts)
                        & (CreditTransaction.id < cursor)
                    )
                )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# FastAPI dependency factory
# ---------------------------------------------------------------------------


async def get_credit_service(
    session: AsyncSession = Depends(get_db),
) -> CreditService:
    """FastAPI dependency that yields a :class:`CreditService` bound to the
    current request's database session.

    Usage in a route::

        from fastapi import Depends
        from issue_observatory.core.credit_service import (
            CreditService,
            get_credit_service,
        )

        @router.get("/credits/balance")
        async def balance(
            current_user: User = Depends(get_current_user),
            credit_svc: CreditService = Depends(get_credit_service),
        ):
            return await credit_svc.get_balance(current_user.id)

    Args:
        session: Injected by :func:`issue_observatory.core.database.get_db`.

    Returns:
        A :class:`CreditService` instance backed by the request session.
    """
    return CreditService(session=session)
