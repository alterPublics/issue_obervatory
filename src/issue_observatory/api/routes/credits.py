"""Credit balance and transaction history routes."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.api.dependencies import get_current_active_user, require_admin
from issue_observatory.core.credit_service import CreditService, get_credit_service
from issue_observatory.core.database import get_db
from issue_observatory.core.models.users import CreditAllocation, User

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /balance — Returns HTML fragment for credit badge
# ---------------------------------------------------------------------------


@router.get("/balance", response_class=HTMLResponse)
async def get_balance(
    request: Request,
    current_user: Annotated[User, Depends(get_current_active_user)],
    credit_svc: Annotated[CreditService, Depends(get_credit_service)],
) -> HTMLResponse:
    """Return credit balance as HTML fragment for the credit badge partial.

    This endpoint is polled every 30 seconds by the credit_badge.html partial.

    Returns:
        HTML fragment with credits_available and credits_reserved context.
    """
    templates: Jinja2Templates | None = getattr(request.app.state, "templates", None)
    if templates is None:
        return HTMLResponse("<span>Error: templates not configured</span>")

    balance = await credit_svc.get_balance(current_user.id)

    return templates.TemplateResponse(
        "_partials/credit_badge.html",
        {
            "request": request,
            "credits_available": balance["available"],
            "credits_reserved": balance["reserved"],
        },
    )


# ---------------------------------------------------------------------------
# POST /admin/credits/allocate — Allocate credits to a user
# ---------------------------------------------------------------------------


@router.post("/allocate", response_class=HTMLResponse)
async def allocate_credits(
    request: Request,
    user_id: Annotated[str, Form()],
    credits_amount: Annotated[int, Form()],
    valid_until: Annotated[str | None, Form()] = None,
    memo: Annotated[str | None, Form()] = None,
    admin_user: Annotated[User, Depends(require_admin)] = None,
    session: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Allocate credits to a user (admin only).

    Args:
        user_id: UUID of the target user.
        credits_amount: Number of credits to allocate (must be >= 1).
        valid_until: Optional expiry date (ISO format YYYY-MM-DD).
        memo: Optional description/note.
        admin_user: Current admin user (injected).
        session: Database session.

    Returns:
        HTML fragment confirming allocation or showing error.
    """
    templates: Jinja2Templates | None = getattr(request.app.state, "templates", None)
    if templates is None:
        return HTMLResponse("<span class='text-red-600'>Error: templates not configured</span>")

    try:
        # Parse user_id
        target_user_id = uuid.UUID(user_id)

        # Parse valid_until if provided
        valid_until_date: date | None = None
        if valid_until and valid_until.strip():
            valid_until_date = date.fromisoformat(valid_until)

        # Create allocation record
        allocation = CreditAllocation(
            user_id=target_user_id,
            credits_amount=credits_amount,
            valid_from=datetime.now(tz=timezone.utc).date(),
            valid_until=valid_until_date,
            allocated_by=admin_user.id,
            memo=memo or "",
        )
        session.add(allocation)
        await session.commit()
        await session.refresh(allocation)

        return HTMLResponse(
            f"""<div class="p-3 bg-green-50 border border-green-200 rounded text-sm text-green-800">
            Successfully allocated {credits_amount} credits.
            </div>""",
            status_code=200,
        )

    except ValueError as e:
        return HTMLResponse(
            f"""<div class="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-800">
            Invalid input: {str(e)}
            </div>""",
            status_code=400,
        )
    except Exception as e:
        return HTMLResponse(
            f"""<div class="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-800">
            Allocation failed: {str(e)}
            </div>""",
            status_code=500,
        )
