"""Admin credential pool management routes (HTMX fragments).

Provides CRUD operations for the ``api_credentials`` table, returning HTML
``<tr>`` fragments for HTMX in-place row swaps.  Credential values are
encrypted with Fernet before storage and are never returned to the browser.

Mounted at ``/admin/credentials`` in ``main.py``.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.api.dependencies import require_admin
from issue_observatory.core.credential_pool import _get_fernet
from issue_observatory.core.database import get_db
from issue_observatory.core.models.credentials import ApiCredential
from issue_observatory.core.models.users import User

router = APIRouter()

# ---------------------------------------------------------------------------
# Platform → credential field names
# ---------------------------------------------------------------------------

_PLATFORM_FIELDS: dict[str, list[str]] = {
    "youtube": ["api_key"],
    "serper": ["api_key"],
    "serpapi": ["api_key"],
    "event_registry": ["api_key"],
    "majestic": ["api_key"],
    "twitterapi_io": ["api_key"],
    "openrouter": ["api_key"],
    "reddit": ["client_id", "client_secret", "user_agent"],
    "tiktok": ["client_key", "client_secret"],
    "gab": ["access_token"],
    "threads": ["access_token"],
    "brightdata_facebook": ["api_token"],
    "brightdata_instagram": ["api_token"],
    "bluesky": ["handle", "app_password"],
    "telegram": ["api_id", "api_hash", "session_string"],
    "discord": ["bot_token"],
    "twitch": ["client_id", "client_secret"],
}

# Platforms that require no credentials at all.
_NO_CREDENTIAL_PLATFORMS = frozenset({"gdelt", "rss_feeds"})


# ---------------------------------------------------------------------------
# HTML row helper
# ---------------------------------------------------------------------------


def _credential_row_html(cred: ApiCredential) -> str:
    """Render a single ``<tr>`` matching the credentials.html template structure."""
    name = cred.credential_name or ""
    platform = cred.platform or ""
    tier = cred.tier or "free"

    if tier == "free":
        tier_badge = (
            '<span class="inline-flex px-2 py-0.5 rounded text-xs font-medium '
            'bg-green-100 text-green-800">Free</span>'
        )
    elif tier == "medium":
        tier_badge = (
            '<span class="inline-flex px-2 py-0.5 rounded text-xs font-medium '
            'bg-yellow-100 text-yellow-800">Medium</span>'
        )
    else:
        tier_badge = (
            '<span class="inline-flex px-2 py-0.5 rounded text-xs font-medium '
            'bg-purple-100 text-purple-800">Premium</span>'
        )

    if cred.is_active:
        status_badge = (
            '<span class="inline-flex px-2 py-0.5 rounded-full text-xs font-medium '
            'bg-green-100 text-green-800">Active</span>'
        )
    else:
        status_badge = (
            '<span class="inline-flex px-2 py-0.5 rounded-full text-xs font-medium '
            'bg-gray-100 text-gray-500">Inactive</span>'
        )

    err_count = cred.error_count or 0
    if err_count > 0:
        err_cls = "text-red-600 font-medium"
    else:
        err_cls = "text-gray-400"
    err_span = f'<span class="{err_cls} text-xs">{err_count}</span>'

    last_used = str(cred.last_used_at)[:16] if cred.last_used_at else "Never"

    # Action buttons
    if cred.is_active:
        toggle_btn = (
            f'<button type="button" '
            f'hx-post="/admin/credentials/{cred.id}/deactivate" '
            f'hx-target="#cred-row-{cred.id}" '
            f'hx-swap="outerHTML" '
            f'class="text-xs text-yellow-700 hover:text-yellow-900 px-2 py-1 rounded '
            f'hover:bg-yellow-50 transition-colors">Deactivate</button>'
        )
    else:
        toggle_btn = (
            f'<button type="button" '
            f'hx-post="/admin/credentials/{cred.id}/activate" '
            f'hx-target="#cred-row-{cred.id}" '
            f'hx-swap="outerHTML" '
            f'class="text-xs text-green-700 hover:text-green-900 px-2 py-1 rounded '
            f'hover:bg-green-50 transition-colors">Activate</button>'
        )

    reset_btn = ""
    if err_count > 0:
        reset_btn = (
            f'<button type="button" '
            f'hx-post="/admin/credentials/{cred.id}/reset-errors" '
            f'hx-target="#cred-row-{cred.id}" '
            f'hx-swap="outerHTML" '
            f'class="text-xs text-gray-500 hover:text-gray-700 px-2 py-1 rounded '
            f'hover:bg-gray-100 transition-colors">Reset errors</button>'
        )

    delete_btn = (
        f'<button type="button" '
        f'hx-delete="/admin/credentials/{cred.id}" '
        f'hx-target="#cred-row-{cred.id}" '
        f'hx-swap="outerHTML" '
        f'hx-confirm="Delete credentials \'{name}\'? This cannot be undone." '
        f'class="text-xs text-red-500 hover:text-red-700 px-2 py-1 rounded '
        f'hover:bg-red-50 transition-colors">Delete</button>'
    )

    return (
        f'<tr class="hover:bg-gray-50" id="cred-row-{cred.id}">'
        f'<td class="px-6 py-4 font-medium text-gray-900">{name}</td>'
        f'<td class="px-6 py-4 text-gray-600">{platform}</td>'
        f'<td class="px-6 py-4">{tier_badge}</td>'
        f'<td class="px-6 py-4">{status_badge}</td>'
        f'<td class="px-6 py-4 text-right">{err_span}</td>'
        f'<td class="px-6 py-4 text-gray-500 text-xs">{last_used}</td>'
        f'<td class="px-6 py-4 text-right">'
        f'<div class="flex items-center justify-end gap-2">'
        f'{toggle_btn}{reset_btn}{delete_btn}'
        f'</div></td></tr>'
    )


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_class=HTMLResponse)
async def create_credential(
    credential_name: Annotated[str, Form()],
    platform: Annotated[str, Form()],
    tier: Annotated[str, Form()] = "free",
    daily_quota: Annotated[int | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
    # Platform-specific credential fields (all optional; which are used
    # depends on the selected platform).
    api_key: Annotated[str | None, Form()] = None,
    client_id: Annotated[str | None, Form()] = None,
    client_secret: Annotated[str | None, Form()] = None,
    client_key: Annotated[str | None, Form()] = None,
    user_agent: Annotated[str | None, Form()] = None,
    access_token: Annotated[str | None, Form()] = None,
    api_token: Annotated[str | None, Form()] = None,
    handle: Annotated[str | None, Form()] = None,
    app_password: Annotated[str | None, Form()] = None,
    api_id: Annotated[str | None, Form()] = None,
    api_hash: Annotated[str | None, Form()] = None,
    session_string: Annotated[str | None, Form()] = None,
    bot_token: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> HTMLResponse:
    """Create a new API credential, encrypt, and return a table row as HTML."""
    # Build credential payload from whichever form fields are non-empty.
    form_values = {
        "api_key": api_key,
        "client_id": client_id,
        "client_secret": client_secret,
        "client_key": client_key,
        "user_agent": user_agent,
        "access_token": access_token,
        "api_token": api_token,
        "handle": handle,
        "app_password": app_password,
        "api_id": api_id,
        "api_hash": api_hash,
        "session_string": session_string,
        "bot_token": bot_token,
    }

    expected_fields = _PLATFORM_FIELDS.get(platform, [])
    payload: dict[str, str] = {}
    for field in expected_fields:
        value = form_values.get(field)
        if value and value.strip():
            payload[field] = value.strip()

    # Encrypt the credential payload with Fernet.
    if payload:
        fernet = _get_fernet()
        encrypted = fernet.encrypt(json.dumps(payload).encode()).decode()
    else:
        # Platforms that need no credentials (gdelt, rss_feeds) store empty.
        encrypted = "{}"

    cred = ApiCredential(
        credential_name=credential_name,
        platform=platform,
        tier=tier,
        credentials=encrypted,
        daily_quota=daily_quota if daily_quota and daily_quota > 0 else None,
        notes=notes or None,
    )
    db.add(cred)
    await db.commit()
    await db.refresh(cred)
    return HTMLResponse(_credential_row_html(cred))


@router.post("/{credential_id:uuid}/activate", response_class=HTMLResponse)
async def activate_credential(
    credential_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> HTMLResponse:
    """Activate a credential and return the updated row as HTML."""
    cred = await db.get(ApiCredential, credential_id)
    if cred is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found.")
    cred.is_active = True
    await db.commit()
    await db.refresh(cred)
    return HTMLResponse(_credential_row_html(cred))


@router.post("/{credential_id:uuid}/deactivate", response_class=HTMLResponse)
async def deactivate_credential(
    credential_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> HTMLResponse:
    """Deactivate a credential and return the updated row as HTML."""
    cred = await db.get(ApiCredential, credential_id)
    if cred is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found.")
    cred.is_active = False
    await db.commit()
    await db.refresh(cred)
    return HTMLResponse(_credential_row_html(cred))


@router.post("/{credential_id:uuid}/reset-errors", response_class=HTMLResponse)
async def reset_errors(
    credential_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> HTMLResponse:
    """Reset the error counter on a credential (circuit-breaker recovery)."""
    cred = await db.get(ApiCredential, credential_id)
    if cred is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found.")
    cred.error_count = 0
    cred.last_error_at = None
    await db.commit()
    await db.refresh(cred)
    return HTMLResponse(_credential_row_html(cred))


@router.delete("/{credential_id:uuid}", response_class=HTMLResponse)
async def delete_credential(
    credential_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> HTMLResponse:
    """Delete a credential permanently. Returns empty string to remove the row."""
    cred = await db.get(ApiCredential, credential_id)
    if cred is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found.")
    await db.delete(cred)
    await db.commit()
    return HTMLResponse("")
