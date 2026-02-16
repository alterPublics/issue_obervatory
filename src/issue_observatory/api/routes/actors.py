"""Actor management routes.

Provides CRUD operations for canonical actors and their platform presences.
Supports both JSON (API clients) and HTML fragment (HTMX) responses — the
``HX-Request`` header is used to detect HTMX requests; when present, the
endpoint returns a minimal HTML fragment instead of JSON.

Access rules:
    - Read:   actor is owned by the current user OR ``is_shared=True``
    - Write:  actor must be owned by the current user (or caller is admin)

Routes:
    GET    /actors/                            list actors (paginated, searchable)
    POST   /actors/                            create actor
    GET    /actors/search                      HTMX search fragment
    GET    /actors/{actor_id}                  actor detail
    PATCH  /actors/{actor_id}                  update actor fields
    DELETE /actors/{actor_id}                  delete actor
    GET    /actors/{actor_id}/content          content records for actor (HTMX)
    POST   /actors/{actor_id}/presences        add platform presence
    DELETE /actors/{actor_id}/presences/{pid}  remove platform presence
"""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from issue_observatory.api.dependencies import (
    PaginationParams,
    get_current_active_user,
    get_pagination,
    ownership_guard,
)
from issue_observatory.core.database import get_db
from issue_observatory.core.models.actors import Actor, ActorPlatformPresence
from issue_observatory.core.models.content import UniversalContentRecord
from issue_observatory.core.models.users import User
from issue_observatory.core.schemas.actors import (
    ActorCreate,
    ActorPresenceCreate,
    ActorResponse,
    ActorUpdate,
    PresenceResponse,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_actor_or_404(
    actor_id: uuid.UUID,
    db: AsyncSession,
    *,
    load_presences: bool = False,
) -> Actor:
    """Fetch an Actor by primary key or raise HTTP 404.

    Args:
        actor_id: UUID of the actor to load.
        db: Active async database session.
        load_presences: When ``True``, eagerly load ``platform_presences``.

    Returns:
        The ``Actor`` ORM instance.

    Raises:
        HTTPException 404: If no actor with ``actor_id`` exists.
    """
    stmt = select(Actor).where(Actor.id == actor_id)
    if load_presences:
        stmt = stmt.options(selectinload(Actor.platform_presences))
    result = await db.execute(stmt)
    actor = result.scalar_one_or_none()
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Actor '{actor_id}' not found.",
        )
    return actor


def _check_actor_readable(actor: Actor, current_user: User) -> None:
    """Raise HTTP 403 if the current user cannot read the actor.

    An actor is readable when it is shared (``is_shared=True``) or when the
    current user is the creator (or an admin).

    Args:
        actor: The ``Actor`` being accessed.
        current_user: The authenticated user making the request.

    Raises:
        HTTPException 403: If the actor is private and the caller is not the
            owner or an admin.
    """
    if actor.is_shared:
        return
    ownership_guard(actor.created_by or uuid.UUID(int=0), current_user)


def _actor_to_html_row(actor: Actor) -> str:
    """Render a single actor as an HTML ``<li>`` fragment for HTMX responses.

    Args:
        actor: The ``Actor`` ORM instance to render.

    Returns:
        An HTML string representing the actor as a list item.
    """
    shared_badge = " (shared)" if actor.is_shared else ""
    actor_type = f" [{actor.actor_type}]" if actor.actor_type else ""
    return (
        f'<li data-actor-id="{actor.id}">'
        f"{actor.canonical_name}{actor_type}{shared_badge}"
        f"</li>"
    )


def _content_record_to_html(record: UniversalContentRecord) -> str:
    """Render a single content record as an HTML ``<li>`` fragment.

    Args:
        record: The ``UniversalContentRecord`` ORM instance to render.

    Returns:
        An HTML string representing the record as a list item.
    """
    title = record.title or record.text_content or ""
    title_truncated = (title[:120] + "...") if len(title) > 120 else title
    url_part = f' <a href="{record.url}" target="_blank">link</a>' if record.url else ""
    pub = record.published_at.date().isoformat() if record.published_at else "unknown date"
    return (
        f'<li data-content-id="{record.id}">'
        f"[{record.platform}] {pub} — {title_truncated}{url_part}"
        f"</li>"
    )


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[ActorResponse])
async def list_actors(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    pagination: Annotated[PaginationParams, Depends(get_pagination)],
    search: Optional[str] = Query(default=None, description="Filter by canonical_name substring."),
    hx_request: Optional[str] = Header(default=None, alias="HX-Request"),
) -> list[Actor] | HTMLResponse:
    """List actors visible to the current user.

    Returns actors that either belong to the current user or are shared with
    all researchers.  Results are ordered by ``created_at`` descending and
    are cursor-paginated by UUID.

    When the ``HX-Request`` header is present, returns an HTML ``<ul>``
    fragment instead of JSON.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        pagination: Cursor and page-size parameters.
        search: Optional substring filter on ``canonical_name``.
        hx_request: HTMX header; when set, response is HTML.

    Returns:
        JSON list of ``ActorResponse`` dicts, or an HTML fragment when HTMX.
    """
    stmt = (
        select(Actor)
        .where(
            or_(
                Actor.created_by == current_user.id,
                Actor.is_shared.is_(True),
            )
        )
        .options(selectinload(Actor.platform_presences))
        .order_by(Actor.created_at.desc())
        .limit(pagination.page_size)
    )

    if search:
        stmt = stmt.where(Actor.canonical_name.ilike(f"%{search}%"))

    if pagination.cursor:
        try:
            cursor_id = uuid.UUID(pagination.cursor)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="cursor must be a valid UUID.",
            ) from exc
        stmt = stmt.where(Actor.id < cursor_id)

    result = await db.execute(stmt)
    actors = list(result.scalars().all())

    if hx_request:
        rows = "".join(_actor_to_html_row(a) for a in actors)
        return HTMLResponse(content=f"<ul>{rows}</ul>")

    return actors


# ---------------------------------------------------------------------------
# Search (HTMX fragment endpoint)
# ---------------------------------------------------------------------------


@router.get("/search")
async def search_actors(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    q: str = Query(default="", description="Name substring to search for."),
    hx_request: Optional[str] = Header(default=None, alias="HX-Request"),
) -> list[ActorResponse] | HTMLResponse:
    """Search actors by canonical name substring.

    Intended as an HTMX target for live-search UI components.  Returns an
    HTML ``<ul>`` fragment when the ``HX-Request`` header is present, or a
    JSON list otherwise.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        q: Substring to match against ``canonical_name``.
        hx_request: HTMX header; when set, response is HTML.

    Returns:
        Up to 20 matching actors as JSON or an HTML fragment.
    """
    stmt = (
        select(Actor)
        .where(
            and_(
                or_(
                    Actor.created_by == current_user.id,
                    Actor.is_shared.is_(True),
                ),
                Actor.canonical_name.ilike(f"%{q}%") if q else True,
            )
        )
        .options(selectinload(Actor.platform_presences))
        .order_by(Actor.canonical_name)
        .limit(20)
    )

    result = await db.execute(stmt)
    actors = list(result.scalars().all())

    if hx_request:
        rows = "".join(_actor_to_html_row(a) for a in actors)
        return HTMLResponse(content=f"<ul>{rows}</ul>")

    return actors


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@router.post("/", response_model=ActorResponse, status_code=status.HTTP_201_CREATED)
async def create_actor(
    payload: ActorCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Actor:
    """Create a new actor, optionally with an initial platform presence.

    Args:
        payload: Validated ``ActorCreate`` request body.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The newly created ``ActorResponse`` including any attached presences.
    """
    actor = Actor(
        canonical_name=payload.canonical_name,
        actor_type=payload.actor_type,
        description=payload.description,
        created_by=current_user.id,
        is_shared=payload.is_shared,
    )
    db.add(actor)
    await db.flush()  # populate actor.id before inserting presence

    if payload.presence is not None:
        presence = ActorPlatformPresence(
            actor_id=actor.id,
            platform=payload.presence.platform,
            platform_user_id=payload.presence.platform_user_id,
            platform_username=payload.presence.platform_username,
            profile_url=payload.presence.profile_url,
        )
        db.add(presence)

    await db.commit()
    logger.info(
        "actor_created",
        actor_id=str(actor.id),
        canonical_name=actor.canonical_name,
        created_by=str(current_user.id),
    )
    return await _get_actor_or_404(actor.id, db, load_presences=True)


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------


@router.get("/{actor_id}", response_model=ActorResponse)
async def get_actor(
    actor_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Actor:
    """Retrieve a single actor with all linked platform presences.

    Args:
        actor_id: UUID of the target actor.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The ``ActorResponse`` including all presences.

    Raises:
        HTTPException 404: If the actor does not exist.
        HTTPException 403: If the actor is private and the caller is not
            the owner or an admin.
    """
    actor = await _get_actor_or_404(actor_id, db, load_presences=True)
    _check_actor_readable(actor, current_user)
    return actor


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


@router.patch("/{actor_id}", response_model=ActorResponse)
async def update_actor(
    actor_id: uuid.UUID,
    payload: ActorUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Actor:
    """Partially update an actor's fields.

    Only the fields explicitly included in the request body are applied;
    omitted fields retain their current values.

    Args:
        actor_id: UUID of the target actor.
        payload: Validated ``ActorUpdate`` request body.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The updated ``ActorResponse``.

    Raises:
        HTTPException 404: If the actor does not exist.
        HTTPException 403: If the caller is not the owner or an admin.
    """
    actor = await _get_actor_or_404(actor_id, db)
    ownership_guard(actor.created_by or uuid.UUID(int=0), current_user)

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(actor, field, value)

    await db.commit()
    logger.info(
        "actor_updated",
        actor_id=str(actor_id),
        fields=list(update_data.keys()),
    )
    return await _get_actor_or_404(actor_id, db, load_presences=True)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@router.delete("/{actor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_actor(
    actor_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    """Hard-delete an actor and all its related records (cascade).

    Requires the caller to be the actor's creator or an admin.

    Args:
        actor_id: UUID of the target actor.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Raises:
        HTTPException 404: If the actor does not exist.
        HTTPException 403: If the caller is not the owner or an admin.
    """
    actor = await _get_actor_or_404(actor_id, db)
    ownership_guard(actor.created_by or uuid.UUID(int=0), current_user)

    await db.delete(actor)
    await db.commit()
    logger.info("actor_deleted", actor_id=str(actor_id))


# ---------------------------------------------------------------------------
# Content records for actor (cursor-paginated, HTMX-aware)
# ---------------------------------------------------------------------------


@router.get("/{actor_id}/content")
async def get_actor_content(
    actor_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    hx_request: Optional[str] = Header(default=None, alias="HX-Request"),
    cursor_published_at: Optional[str] = Query(
        default=None,
        description="ISO 8601 cursor timestamp (published_at of last record).",
    ),
    cursor_id: Optional[uuid.UUID] = Query(
        default=None,
        description="UUID cursor (id of last record).",
    ),
    page_size: int = Query(default=50, ge=1, le=200),
) -> list[dict] | HTMLResponse:
    """List content records attributed to an actor, cursor-paginated.

    Uses a ``(published_at DESC, id DESC)`` keyset cursor for stable
    pagination over the partitioned ``content_records`` table.

    When the ``HX-Request`` header is present, returns an HTML ``<ul>``
    fragment of ``<li>`` items for HTMX infinite-scroll UIs.

    Args:
        actor_id: UUID of the target actor.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        hx_request: HTMX header; when set, response is HTML.
        cursor_published_at: ISO 8601 ``published_at`` of the last seen record.
        cursor_id: UUID ``id`` of the last seen record.
        page_size: Number of records per page (1–200).

    Returns:
        JSON list of content record dicts, or an HTML ``<ul>`` fragment.

    Raises:
        HTTPException 404: If the actor does not exist.
        HTTPException 403: If the caller cannot access the actor.
    """
    actor = await _get_actor_or_404(actor_id, db)
    _check_actor_readable(actor, current_user)

    stmt = (
        select(UniversalContentRecord)
        .where(UniversalContentRecord.author_id == actor_id)
        .order_by(
            UniversalContentRecord.published_at.desc().nullslast(),
            UniversalContentRecord.id.desc(),
        )
        .limit(page_size)
    )

    if cursor_published_at is not None and cursor_id is not None:
        from datetime import datetime  # noqa: PLC0415

        try:
            cursor_ts = datetime.fromisoformat(cursor_published_at)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="cursor_published_at must be a valid ISO 8601 timestamp.",
            ) from exc

        stmt = stmt.where(
            or_(
                UniversalContentRecord.published_at < cursor_ts,
                and_(
                    UniversalContentRecord.published_at == cursor_ts,
                    UniversalContentRecord.id < cursor_id,
                ),
            )
        )

    result = await db.execute(stmt)
    records = list(result.scalars().all())

    if hx_request:
        items = "".join(_content_record_to_html(r) for r in records)
        return HTMLResponse(content=f"<ul>{items}</ul>")

    return [
        {
            "id": str(r.id),
            "platform": r.platform,
            "arena": r.arena,
            "content_type": r.content_type,
            "title": r.title,
            "text_content": r.text_content,
            "url": r.url,
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "language": r.language,
            "likes_count": r.likes_count,
            "shares_count": r.shares_count,
            "comments_count": r.comments_count,
        }
        for r in records
    ]


# ---------------------------------------------------------------------------
# Platform presences
# ---------------------------------------------------------------------------


@router.post(
    "/{actor_id}/presences",
    response_model=PresenceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_presence(
    actor_id: uuid.UUID,
    payload: ActorPresenceCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ActorPlatformPresence:
    """Add a platform presence to an existing actor.

    Args:
        actor_id: UUID of the target actor.
        payload: Validated ``ActorPresenceCreate`` request body.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The newly created ``PresenceResponse``.

    Raises:
        HTTPException 404: If the actor does not exist.
        HTTPException 403: If the caller is not the owner or an admin.
        HTTPException 409: If a presence for the same platform+user_id already exists.
    """
    actor = await _get_actor_or_404(actor_id, db)
    ownership_guard(actor.created_by or uuid.UUID(int=0), current_user)

    presence = ActorPlatformPresence(
        actor_id=actor_id,
        platform=payload.platform,
        platform_user_id=payload.platform_user_id,
        platform_username=payload.platform_username,
        profile_url=payload.profile_url,
    )
    db.add(presence)

    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        # UniqueConstraint violation on (platform, platform_user_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A presence for platform '{payload.platform}' with "
                f"user_id '{payload.platform_user_id}' already exists."
            ),
        ) from exc

    await db.refresh(presence)
    logger.info(
        "actor_presence_added",
        actor_id=str(actor_id),
        platform=payload.platform,
        presence_id=str(presence.id),
    )
    return presence


@router.delete(
    "/{actor_id}/presences/{presence_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_presence(
    actor_id: uuid.UUID,
    presence_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    """Remove a platform presence from an actor.

    Args:
        actor_id: UUID of the parent actor.
        presence_id: UUID of the presence to remove.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Raises:
        HTTPException 404: If the actor or presence does not exist.
        HTTPException 403: If the caller is not the owner or an admin.
    """
    actor = await _get_actor_or_404(actor_id, db)
    ownership_guard(actor.created_by or uuid.UUID(int=0), current_user)

    result = await db.execute(
        select(ActorPlatformPresence).where(
            ActorPlatformPresence.id == presence_id,
            ActorPlatformPresence.actor_id == actor_id,
        )
    )
    presence = result.scalar_one_or_none()
    if presence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Presence '{presence_id}' not found on actor '{actor_id}'.",
        )

    await db.delete(presence)
    await db.commit()
    logger.info(
        "actor_presence_removed",
        actor_id=str(actor_id),
        presence_id=str(presence_id),
    )


# ---------------------------------------------------------------------------
# Entity Resolution — Task 3.9
# ---------------------------------------------------------------------------


@router.get("/{actor_id}/candidates")
async def find_merge_candidates(
    actor_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    threshold: float = Query(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum trigram similarity threshold (0–1).",
    ),
    hx_request: Optional[str] = Header(default=None, alias="HX-Request"),
) -> list[dict] | HTMLResponse:
    """Find actors that may be the same real-world entity as *actor_id*.

    Uses three matching strategies in priority order: exact canonical name
    match, shared platform username, and pg_trgm trigram similarity.

    Args:
        actor_id: UUID of the actor to find candidates for.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        threshold: Trigram similarity threshold (default 0.7).
        hx_request: HTMX header; when set, returns an HTML table fragment.

    Returns:
        JSON list of candidate dicts, or an HTML fragment when HTMX.

    Raises:
        HTTPException 404: If the actor does not exist.
        HTTPException 403: If the actor is not accessible.
    """
    from issue_observatory.core.entity_resolver import EntityResolver

    actor = await _get_actor_or_404(actor_id, db, load_presences=True)
    _check_actor_readable(actor, current_user)

    resolver = EntityResolver()
    candidates = await resolver.find_candidate_matches(db, actor_id, threshold=threshold)

    if hx_request:
        rows_html = ""
        for c in candidates:
            rows_html += (
                f'<tr class="hover:bg-gray-50">'
                f'<td class="px-4 py-2 text-sm text-gray-900">{c["canonical_name"]}</td>'
                f'<td class="px-4 py-2 text-sm text-gray-500">{c["match_reason"]}</td>'
                f'<td class="px-4 py-2 text-sm font-mono text-gray-500">{c["similarity"]:.2f}</td>'
                f'<td class="px-4 py-2 text-sm text-gray-500">{", ".join(c["platforms"])}</td>'
                f'<td class="px-4 py-2 text-right">'
                f'<button type="button"'
                f' x-data=""'
                f' @click="if(confirm(\'Merge {c[&quot;canonical_name&quot;]} into {actor.canonical_name}? This cannot be undone.\'))'
                f"{{ $dispatch('merge-actor', {{ duplicate_id: '{c[\"actor_id\"]}' }}) }}"
                f'"'
                f' class="text-xs text-red-600 hover:text-red-800 px-2 py-1 rounded hover:bg-red-50">'
                f"Merge"
                f"</button>"
                f"</td>"
                f"</tr>"
            )
        html = (
            f'<table class="min-w-full divide-y divide-gray-200 text-sm" id="candidates-table">'
            f'<thead class="bg-gray-50">'
            f'<tr>'
            f'<th class="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Name</th>'
            f'<th class="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Reason</th>'
            f'<th class="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Score</th>'
            f'<th class="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Platforms</th>'
            f'<th class="px-4 py-3"><span class="sr-only">Actions</span></th>'
            f'</tr></thead>'
            f'<tbody class="divide-y divide-gray-100">{rows_html}</tbody>'
            f"</table>"
            if candidates
            else '<p class="text-sm text-gray-400 px-4 py-4">No candidates found above the similarity threshold.</p>'
        )
        return HTMLResponse(content=html)

    return candidates


@router.post("/{actor_id}/merge")
async def merge_actor(
    actor_id: uuid.UUID,
    payload: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict:
    """Merge one or more duplicate actors into the canonical actor.

    Re-points all content records from the duplicate actors to *actor_id*,
    moves platform presences (skipping conflicts), creates ``ActorAlias``
    entries from the duplicates' names, then deletes the duplicate actors.

    Requires ownership of *actor_id* or admin role.

    Args:
        actor_id: UUID of the canonical actor (the one to keep).
        payload: JSON body with key ``duplicate_ids`` (list of UUID strings).
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        Dict with ``merged``, ``records_updated``, ``presences_moved`` counts.

    Raises:
        HTTPException 400: If ``duplicate_ids`` is missing or empty.
        HTTPException 404: If the canonical actor does not exist.
        HTTPException 403: If the caller is not the owner or an admin.
    """
    from issue_observatory.core.entity_resolver import EntityResolver

    actor = await _get_actor_or_404(actor_id, db)
    ownership_guard(actor.created_by or uuid.UUID(int=0), current_user)

    raw_ids = payload.get("duplicate_ids", [])
    if not raw_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'duplicate_ids' must be a non-empty list of UUID strings.",
        )

    try:
        duplicate_ids = [uuid.UUID(str(i)) for i in raw_ids]
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="All values in 'duplicate_ids' must be valid UUIDs.",
        ) from exc

    resolver = EntityResolver()
    result = await resolver.merge_actors(
        db=db,
        canonical_id=actor_id,
        duplicate_ids=duplicate_ids,
        performed_by=current_user.id,
    )

    logger.info(
        "actor_merge_complete",
        canonical_id=str(actor_id),
        performed_by=str(current_user.id),
        **result,
    )
    return result


@router.post("/{actor_id}/split")
async def split_actor(
    actor_id: uuid.UUID,
    payload: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict:
    """Split selected platform presences from an actor into a new actor.

    Creates a new ``Actor`` with ``new_canonical_name``, moves the specified
    platform presences to it, re-points relevant content records, and records
    an alias on the original actor.

    Requires ownership of *actor_id* or admin role.

    Args:
        actor_id: UUID of the actor to split from.
        payload: JSON body with keys:

            - ``presence_ids`` (list[str]): UUIDs of platform presences to move.
            - ``new_canonical_name`` (str): Canonical name for the new actor.

        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        Dict with ``new_actor_id``, ``presences_moved``, ``records_updated``.

    Raises:
        HTTPException 400: If required fields are missing.
        HTTPException 404: If the actor does not exist.
        HTTPException 403: If the caller is not the owner or an admin.
    """
    from issue_observatory.core.entity_resolver import EntityResolver

    actor = await _get_actor_or_404(actor_id, db)
    ownership_guard(actor.created_by or uuid.UUID(int=0), current_user)

    raw_presence_ids = payload.get("presence_ids", [])
    new_canonical_name = payload.get("new_canonical_name", "").strip()

    if not raw_presence_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'presence_ids' must be a non-empty list of UUID strings.",
        )
    if not new_canonical_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'new_canonical_name' must be a non-empty string.",
        )

    try:
        presence_ids = [uuid.UUID(str(i)) for i in raw_presence_ids]
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="All values in 'presence_ids' must be valid UUIDs.",
        ) from exc

    resolver = EntityResolver()
    result = await resolver.split_actor(
        db=db,
        actor_id=actor_id,
        platform_presence_ids=presence_ids,
        new_canonical_name=new_canonical_name,
        performed_by=current_user.id,
    )

    logger.info(
        "actor_split_complete",
        original_actor_id=str(actor_id),
        performed_by=str(current_user.id),
        **result,
    )
    return result
