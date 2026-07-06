"""User template CRUD routes (admin-only).

Provides endpoints for creating, listing, editing, and deleting user
templates, plus creating a user from a template.  All endpoints are
admin-gated via ``require_admin``.

Mounted at ``/admin/templates`` in ``main.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.api.dependencies import require_admin
from issue_observatory.core.database import get_db
from issue_observatory.core.models.user_template import UserTemplate
from issue_observatory.core.models.users import CreditAllocation, User

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_platform_list(raw: str | None) -> list[str]:
    """Parse a comma-separated or newline-separated platform list from a form."""
    if not raw or not raw.strip():
        return []
    return [p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()]


def _template_row_html(t: UserTemplate) -> str:
    """Render a single ``<tr>`` for the templates table."""
    allowed_count = len(t.allowed_platforms or [])
    disallowed_count = len(t.disallowed_platforms or [])

    if allowed_count:
        platform_badge = (
            f'<span class="text-xs text-green-700">{allowed_count} allowed</span>'
        )
    elif disallowed_count:
        platform_badge = (
            f'<span class="text-xs text-red-700">{disallowed_count} blocked</span>'
        )
    else:
        platform_badge = '<span class="text-xs text-gray-500">All platforms</span>'

    cred_badge = (
        '<span class="inline-flex px-2 py-0.5 rounded text-xs font-medium '
        'bg-blue-100 text-blue-800">Central</span>'
        if t.use_central_credentials
        else '<span class="inline-flex px-2 py-0.5 rounded text-xs font-medium '
        'bg-purple-100 text-purple-800">Own keys</span>'
    )

    created = str(t.created_at)[:10] if t.created_at else ""

    return (
        f'<tr class="hover:bg-gray-50" id="template-row-{t.id}">'
        f'<td class="px-6 py-4 font-medium text-gray-900">{t.name}</td>'
        f'<td class="px-6 py-4 text-gray-500 text-xs">'
        f'{t.description or ""}</td>'
        f'<td class="px-6 py-4 text-right font-mono text-gray-900">'
        f'{t.credits_amount}</td>'
        f'<td class="px-6 py-4">{platform_badge}</td>'
        f'<td class="px-6 py-4">{cred_badge}</td>'
        f'<td class="px-6 py-4 text-gray-500 text-xs">{created}</td>'
        f'<td class="px-6 py-4 text-right">'
        f'<div class="flex items-center justify-end gap-2">'
        f'<button type="button" '
        f'hx-delete="/admin/templates/{t.id}" '
        f'hx-target="#template-row-{t.id}" '
        f'hx-swap="outerHTML" '
        f'hx-confirm="Delete template &quot;{t.name}&quot;?" '
        f'class="text-sm text-red-600 hover:text-red-800 px-2 py-1 rounded '
        f'hover:bg-red-50 transition-colors">Delete</button>'
        f'</div></td></tr>'
    )


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.post("/create", response_class=HTMLResponse)
async def create_template(
    request: Request,
    name: Annotated[str, Form()],
    credits_amount: Annotated[int, Form()] = 0,
    description: Annotated[str, Form()] = "",
    allowed_platforms: Annotated[str, Form()] = "",
    disallowed_platforms: Annotated[str, Form()] = "",
    use_central_credentials: Annotated[bool, Form()] = True,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
) -> HTMLResponse:
    """Create a new user template (admin only).

    Returns an HTML ``<tr>`` fragment for HTMX table append.
    """
    # Check uniqueness
    existing = await db.execute(
        select(UserTemplate).where(UserTemplate.name == name.strip())
    )
    if existing.scalar_one_or_none() is not None:
        return HTMLResponse(
            '<div class="p-3 bg-red-50 border border-red-200 rounded text-sm '
            f'text-red-800">A template named \'{name}\' already exists.</div>',
            status_code=400,
        )

    template = UserTemplate(
        name=name.strip(),
        description=description.strip() or None,
        credits_amount=max(0, credits_amount),
        allowed_platforms=_parse_platform_list(allowed_platforms),
        disallowed_platforms=_parse_platform_list(disallowed_platforms),
        use_central_credentials=use_central_credentials,
        created_by=admin_user.id,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return HTMLResponse(_template_row_html(template))


@router.post("/{template_id:uuid}/edit", response_class=HTMLResponse)
async def edit_template(
    template_id: uuid.UUID,
    name: Annotated[str, Form()],
    credits_amount: Annotated[int, Form()] = 0,
    description: Annotated[str, Form()] = "",
    allowed_platforms: Annotated[str, Form()] = "",
    disallowed_platforms: Annotated[str, Form()] = "",
    use_central_credentials: Annotated[bool, Form()] = True,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> HTMLResponse:
    """Update an existing user template (admin only)."""
    template = await db.get(UserTemplate, template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found."
        )

    template.name = name.strip()
    template.description = description.strip() or None
    template.credits_amount = max(0, credits_amount)
    template.allowed_platforms = _parse_platform_list(allowed_platforms)
    template.disallowed_platforms = _parse_platform_list(disallowed_platforms)
    template.use_central_credentials = use_central_credentials
    await db.commit()
    await db.refresh(template)
    return HTMLResponse(_template_row_html(template))


@router.delete("/{template_id:uuid}", response_class=HTMLResponse)
async def delete_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> HTMLResponse:
    """Delete a user template (admin only).

    Users created from this template keep their settings (SET NULL FK).
    Returns empty content so HTMX removes the row.
    """
    template = await db.get(UserTemplate, template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found."
        )
    await db.delete(template)
    await db.commit()
    return HTMLResponse("")


@router.post("/{template_id:uuid}/create-user", response_class=HTMLResponse)
async def create_user_from_template(
    template_id: uuid.UUID,
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    display_name: Annotated[str, Form()] = "",
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin),
) -> HTMLResponse:
    """Create a new user from a template, copying all settings.

    Copies allowed/disallowed platforms, credential mode, and auto-allocates
    credits from the template's ``credits_amount``.
    """
    template = await db.get(UserTemplate, template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Template not found."
        )

    # Check email uniqueness
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        return HTMLResponse(
            '<div class="p-3 bg-red-50 border border-red-200 rounded text-sm '
            f'text-red-800">A user with email \'{email}\' already exists.</div>',
            status_code=400,
        )

    from fastapi_users.password import PasswordHelper

    password_helper = PasswordHelper()
    hashed = password_helper.hash(password)

    user = User(
        email=email,
        hashed_password=hashed,
        display_name=display_name or None,
        role="researcher",
        is_active=True,
        template_id=template.id,
        use_central_credentials=template.use_central_credentials,
        allowed_platforms=list(template.allowed_platforms or []),
        disallowed_platforms=list(template.disallowed_platforms or []),
    )
    db.add(user)
    await db.flush()  # Get user.id for allocation

    # Auto-allocate credits from template
    if template.credits_amount > 0 and template.use_central_credentials:
        allocation = CreditAllocation(
            user_id=user.id,
            credits_amount=template.credits_amount,
            valid_from=datetime.now(tz=UTC).date(),
            valid_until=None,
            allocated_by=admin_user.id,
            memo=f"Auto-allocated from template: {template.name}",
        )
        db.add(allocation)

    await db.commit()
    await db.refresh(user)

    credit_msg = ""
    if template.credits_amount > 0 and template.use_central_credentials:
        credit_msg = f" with {template.credits_amount} credits"

    return HTMLResponse(
        f'<div class="p-3 bg-green-50 border border-green-200 rounded '
        f'text-sm text-green-800">User <strong>{email}</strong> created '
        f'from template <strong>{template.name}</strong>{credit_msg}.'
        f'</div>'
    )
