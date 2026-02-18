"""Actor management routes.

Provides CRUD operations for canonical actors and their platform presences.
Supports both JSON (API clients) and HTML fragment (HTMX) responses — the
``HX-Request`` header is used to detect HTMX requests; when present, the
endpoint returns a minimal HTML fragment instead of JSON.

Access rules:
    - Read:   actor is owned by the current user OR ``is_shared=True``
    - Write:  actor must be owned by the current user (or caller is admin)

Routes:
    GET    /actors/                               list actors (paginated, searchable)
    POST   /actors/                               create actor
    GET    /actors/search                         HTMX search fragment
    GET    /actors/resolution                     entity resolution UI page
    GET    /actors/resolution-candidates          cross-platform resolution candidates
    GET    /actors/sampling/snowball/platforms    platforms that support network expansion
    POST   /actors/sampling/snowball              run snowball sampling from seed actors
    GET    /actors/{actor_id}                     actor detail
    PATCH  /actors/{actor_id}                     update actor fields
    DELETE /actors/{actor_id}                     delete actor
    GET    /actors/{actor_id}/content             content records for actor (HTMX)
    POST   /actors/{actor_id}/presences           add platform presence
    DELETE /actors/{actor_id}/presences/{pid}     remove platform presence
    POST   /actors/{actor_id}/merge/{other_actor_id}  merge other actor into actor
    POST   /actors/lists/{list_id}/members/bulk   bulk-add actors to a list
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Annotated, Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from issue_observatory.api.dependencies import (
    PaginationParams,
    get_current_active_user,
    get_pagination,
    ownership_guard,
)
from issue_observatory.core.database import get_db
from issue_observatory.core.models.actors import Actor, ActorAlias, ActorListMember, ActorPlatformPresence
from issue_observatory.core.models.content import UniversalContentRecord
from issue_observatory.core.models.users import User
from issue_observatory.core.schemas.actors import (
    ActorCreate,
    ActorPresenceCreate,
    ActorResponse,
    ActorUpdate,
    PresenceResponse,
)
from issue_observatory.sampling.snowball import SnowballSampler

_py_logger = logging.getLogger(__name__)

#: Platforms that have a dedicated network-expansion strategy in NetworkExpander.
#: Derived from the if/elif dispatch in NetworkExpander.expand_from_actor().
_NETWORK_EXPANSION_PLATFORMS: list[str] = ["bluesky", "reddit", "youtube"]

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas for snowball sampling and bulk-member endpoints
# ---------------------------------------------------------------------------


class SnowballRequest(BaseModel):
    """Request body for the snowball sampling endpoint.

    Attributes:
        seed_actor_ids: UUIDs of actors to start sampling from.
        platforms: Platform identifiers to expand on (e.g. ``["bluesky", "reddit"]``).
        max_depth: Maximum number of expansion waves after the seed level.
        max_actors_per_step: Maximum novel actors added per wave.
        add_to_actor_list_id: When provided, discovered actors are added to
            this ``ActorList`` as ``'snowball'`` members.
    """

    seed_actor_ids: list[uuid.UUID]
    platforms: list[str]
    max_depth: int = 2
    max_actors_per_step: int = 20
    add_to_actor_list_id: Optional[uuid.UUID] = None


class SnowballWaveEntry(BaseModel):
    """Summary of one expansion wave.

    Attributes:
        wave: Depth level (0 = seeds, 1+ = expansions).
        count: Number of actors discovered at this depth.
        methods: Discovery method strings used in this wave.
    """

    wave: int
    count: int
    methods: list[str]


class SnowballActorEntry(BaseModel):
    """A single actor as returned by the snowball sampling result.

    Attributes:
        actor_id: UUID string of the actor if resolved in the DB, else empty.
        canonical_name: Human-readable canonical name.
        platforms: Platform name(s) associated with this actor entry.
        discovery_depth: Wave in which this actor was discovered (0 = seed).
    """

    actor_id: str
    canonical_name: str
    platforms: list[str]
    discovery_depth: int


class SnowballResponse(BaseModel):
    """Response body for the snowball sampling endpoint.

    Attributes:
        total_actors: Total unique actors in the result.
        max_depth_reached: Deepest expansion level actually completed.
        wave_log: Per-wave summary entries.
        actors: All discovered actors in order of discovery.
    """

    total_actors: int
    max_depth_reached: int
    wave_log: list[SnowballWaveEntry]
    actors: list[SnowballActorEntry]


class BulkMemberRequest(BaseModel):
    """Request body for bulk actor list membership.

    Attributes:
        actor_ids: UUIDs of actors to add to the list.
    """

    actor_ids: list[uuid.UUID]


class BulkMemberResponse(BaseModel):
    """Response body for bulk actor list membership.

    Attributes:
        added: Number of actors newly added to the list.
        already_present: Number of actors that were already members.
    """

    added: int
    already_present: int


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
# Entity resolution page — must be declared before parametric /{actor_id}
# routes so that FastAPI does not match "resolution" as an actor_id UUID.
# ---------------------------------------------------------------------------


@router.get("/resolution", include_in_schema=False)
async def actor_resolution_page(
    request: Request,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HTMLResponse:
    """Render the entity resolution UI page.

    The page loads resolution candidates via Alpine.js fetch calls to
    ``GET /actors/resolution-candidates`` and lets the researcher create
    new actors or merge existing ones.

    Args:
        request: The current HTTP request (used to resolve the template engine
            stored on ``request.app.state``).
        current_user: The authenticated, active user making the request.

    Returns:
        Rendered ``actors/resolution.html`` template.
    """
    tpl = request.app.state.templates
    return tpl.TemplateResponse(
        "actors/resolution.html",
        {"request": request, "user": current_user},
    )


@router.get("/resolution-candidates")
async def get_resolution_candidates(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    run_id: Optional[uuid.UUID] = Query(default=None),
    query_design_id: Optional[uuid.UUID] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    """Return entity resolution candidates from content records.

    Finds ``author_display_name`` values that appear across multiple distinct
    platforms — strong evidence of cross-platform identity.  Each candidate
    row shows whether it is already resolved to a canonical ``Actor`` record
    via ``content_records.author_id``.

    Optional filters:
        ``run_id``          — restrict to content from a specific collection run.
        ``query_design_id`` — restrict to content from a specific query design.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        run_id: Optional UUID to filter by collection run.
        query_design_id: Optional UUID to filter by query design.
        limit: Maximum candidates to return (1–200, default 50).

    Returns:
        List of candidate dicts ordered by platform count (desc), each with:
        ``display_name``, ``platforms``, ``platform_count``, ``total_records``,
        ``is_resolved``, ``actor_id``, ``canonical_name``.
    """
    # Build the base content_records subquery.
    # We aggregate over author_display_name to find names that span > 1 platform.
    UCR = UniversalContentRecord

    # Subquery: per (author_display_name, author_id) grouping — collect platforms
    # and record counts.  author_id may be NULL for unresolved names.
    # We use a two-step approach:
    #   Step 1: aggregate platforms and counts per (display_name, author_id) pair.
    #   Step 2: filter to those with platform_count >= 2.

    base_stmt = (
        select(
            UCR.author_display_name.label("display_name"),
            UCR.author_id.label("actor_id"),
            func.array_agg(
                func.distinct(UCR.platform)
            ).label("platforms"),
            func.count(func.distinct(UCR.platform)).label("platform_count"),
            func.count(UCR.id).label("total_records"),
        )
        .where(UCR.author_display_name.isnot(None))
        .group_by(UCR.author_display_name, UCR.author_id)
        .having(func.count(func.distinct(UCR.platform)) >= 2)
        .order_by(func.count(func.distinct(UCR.platform)).desc(), func.count(UCR.id).desc())
        .limit(limit)
    )

    if run_id is not None:
        base_stmt = base_stmt.where(UCR.collection_run_id == run_id)
    if query_design_id is not None:
        base_stmt = base_stmt.where(UCR.query_design_id == query_design_id)

    result = await db.execute(base_stmt)
    rows = result.all()

    # For resolved rows (actor_id IS NOT NULL), fetch canonical names in bulk.
    resolved_actor_ids: list[uuid.UUID] = [
        r.actor_id for r in rows if r.actor_id is not None
    ]
    canonical_names: dict[uuid.UUID, str] = {}
    if resolved_actor_ids:
        actor_result = await db.execute(
            select(Actor.id, Actor.canonical_name).where(
                Actor.id.in_(resolved_actor_ids)
            )
        )
        canonical_names = {a.id: a.canonical_name for a in actor_result.all()}

    candidates: list[dict] = []
    for row in rows:
        actor_id_val = row.actor_id
        is_resolved = actor_id_val is not None
        candidates.append(
            {
                "display_name": row.display_name,
                "platforms": sorted(row.platforms or []),
                "platform_count": row.platform_count,
                "total_records": row.total_records,
                "is_resolved": is_resolved,
                "actor_id": str(actor_id_val) if actor_id_val else None,
                "canonical_name": canonical_names.get(actor_id_val, "") if actor_id_val else "",
            }
        )

    logger.info(
        "resolution_candidates_fetched",
        count=len(candidates),
        user_id=str(current_user.id),
    )
    return candidates


# ---------------------------------------------------------------------------
# Snowball sampling — must be declared before parametric /{actor_id} routes
# ---------------------------------------------------------------------------


@router.get("/sampling/snowball/platforms")
async def list_snowball_platforms(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, list[str]]:
    """Return the platforms that support network expansion.

    Reads the set of platforms with dedicated expansion strategies from the
    ``NetworkExpander`` implementation (Bluesky, Reddit, YouTube).  All other
    platforms fall back to co-mention detection which requires stored content
    records; they are not listed here because the snowball UI should only
    offer platforms with first-class graph traversal.

    Args:
        current_user: The authenticated, active user making the request.

    Returns:
        Dict with key ``"platforms"`` mapped to the supported platform list.
    """
    return {"platforms": _NETWORK_EXPANSION_PLATFORMS}


@router.post("/sampling/snowball", response_model=SnowballResponse)
async def run_snowball_sampling(
    payload: SnowballRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> SnowballResponse:
    """Run snowball sampling starting from a set of seed actors.

    Executes ``SnowballSampler.run()`` synchronously within the request
    lifecycle.  This is a potentially slow operation (network expansion calls
    external platform APIs); the frontend must display a loading indicator.
    If the operation exceeds 30 seconds a warning is logged, but the result
    is still returned.

    When ``add_to_actor_list_id`` is provided, all discovered actors that can
    be resolved to a UUID in the database are added to the specified
    ``ActorList`` with ``added_by='snowball'``.  The caller must own the list.

    Args:
        payload: Validated ``SnowballRequest`` body.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        A ``SnowballResponse`` with the full set of discovered actors and a
        per-wave summary log.

    Raises:
        HTTPException 404: If ``add_to_actor_list_id`` references a list that
            does not exist.
        HTTPException 403: If the caller does not own the target actor list.
    """
    # Validate and guard the target actor list before running the expensive
    # sampling operation so we fail fast on auth errors.
    if payload.add_to_actor_list_id is not None:
        from issue_observatory.core.models.query_design import ActorList  # noqa: PLC0415

        list_result = await db.execute(
            select(ActorList).where(ActorList.id == payload.add_to_actor_list_id)
        )
        actor_list = list_result.scalar_one_or_none()
        if actor_list is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ActorList '{payload.add_to_actor_list_id}' not found.",
            )
        ownership_guard(actor_list.created_by or uuid.UUID(int=0), current_user)

    t_start = time.monotonic()

    sampler = SnowballSampler()
    result = await sampler.run(
        seed_actor_ids=payload.seed_actor_ids,
        platforms=payload.platforms,
        db=db,
        max_depth=payload.max_depth,
        max_actors_per_step=payload.max_actors_per_step,
    )

    elapsed = time.monotonic() - t_start
    if elapsed > 30.0:
        _py_logger.warning(
            "snowball_sampling_slow",
            elapsed_seconds=round(elapsed, 1),
            seed_count=len(payload.seed_actor_ids),
            platforms=payload.platforms,
            total_actors=result.total_actors,
        )

    # Optionally add resolved actors to the requested list.
    if payload.add_to_actor_list_id is not None:
        added_count = await _bulk_add_to_list(
            actor_dicts=result.actors,
            list_id=payload.add_to_actor_list_id,
            added_by="snowball",
            db=db,
        )
        logger.info(
            "snowball_list_populated",
            list_id=str(payload.add_to_actor_list_id),
            added=added_count,
            user_id=str(current_user.id),
        )

    # Build the response.
    wave_log: list[SnowballWaveEntry] = [
        SnowballWaveEntry(
            wave=depth,
            count=info["discovered"],
            methods=info["methods"],
        )
        for depth, info in sorted(result.wave_log.items())
    ]

    actors_out: list[SnowballActorEntry] = []
    for actor_dict in result.actors:
        actors_out.append(
            SnowballActorEntry(
                actor_id=actor_dict.get("actor_uuid", ""),
                canonical_name=actor_dict.get("canonical_name", ""),
                platforms=(
                    [actor_dict["platform"]] if actor_dict.get("platform") else []
                ),
                discovery_depth=int(actor_dict.get("discovery_depth", 0)),
            )
        )

    logger.info(
        "snowball_sampling_complete",
        total_actors=result.total_actors,
        max_depth_reached=result.max_depth_reached,
        elapsed_seconds=round(elapsed, 1),
        user_id=str(current_user.id),
    )

    return SnowballResponse(
        total_actors=result.total_actors,
        max_depth_reached=result.max_depth_reached,
        wave_log=wave_log,
        actors=actors_out,
    )


async def _bulk_add_to_list(
    actor_dicts: list[dict[str, Any]],
    list_id: uuid.UUID,
    added_by: str,
    db: AsyncSession,
) -> int:
    """Add actors from a list of dicts to an ActorList, skipping duplicates.

    Only actors that carry a non-empty ``actor_uuid`` field (i.e. already
    resolved in the database) are inserted.

    Args:
        actor_dicts: Actor dicts as returned by ``SnowballSampler.run()``.
        list_id: UUID of the target ``ActorList``.
        added_by: Source label stored on each ``ActorListMember`` row.
        db: Active async database session.

    Returns:
        Number of newly inserted membership rows.
    """
    # Collect unique resolvable UUIDs from the actor dicts.
    uuids_to_add: list[uuid.UUID] = []
    seen: set[str] = set()
    for actor in actor_dicts:
        raw_uuid = actor.get("actor_uuid", "")
        if not raw_uuid or raw_uuid in seen:
            continue
        try:
            uuids_to_add.append(uuid.UUID(raw_uuid))
            seen.add(raw_uuid)
        except ValueError:
            continue

    if not uuids_to_add:
        return 0

    # Fetch existing members to avoid duplicate-key errors.
    existing_result = await db.execute(
        select(ActorListMember.actor_id).where(
            ActorListMember.actor_list_id == list_id,
            ActorListMember.actor_id.in_(uuids_to_add),
        )
    )
    existing_ids: set[uuid.UUID] = {row[0] for row in existing_result.fetchall()}

    added = 0
    for actor_uuid in uuids_to_add:
        if actor_uuid in existing_ids:
            continue
        db.add(
            ActorListMember(
                actor_list_id=list_id,
                actor_id=actor_uuid,
                added_by=added_by,
            )
        )
        added += 1

    if added:
        await db.commit()

    return added


# ---------------------------------------------------------------------------
# Actor list membership — bulk add
# Must be declared before parametric /{actor_id} routes to avoid routing
# conflicts.  The literal path segment "lists" is unambiguous.
# ---------------------------------------------------------------------------


@router.post(
    "/lists/{list_id}/members/bulk",
    response_model=BulkMemberResponse,
    status_code=status.HTTP_200_OK,
)
async def bulk_add_list_members(
    list_id: uuid.UUID,
    payload: BulkMemberRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> BulkMemberResponse:
    """Bulk-add actors to an actor list.

    Idempotent: actors already present in the list are counted as
    ``already_present`` and are not re-inserted.  Requires ownership of
    the target actor list (or admin role).

    Args:
        list_id: UUID of the ``ActorList`` to add actors to.
        payload: Validated ``BulkMemberRequest`` body with ``actor_ids``.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        A ``BulkMemberResponse`` with counts of newly added and already-present
        actors.

    Raises:
        HTTPException 404: If the actor list does not exist.
        HTTPException 403: If the caller does not own the list.
    """
    from issue_observatory.core.models.query_design import ActorList  # noqa: PLC0415

    list_result = await db.execute(
        select(ActorList).where(ActorList.id == list_id)
    )
    actor_list = list_result.scalar_one_or_none()
    if actor_list is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ActorList '{list_id}' not found.",
        )
    ownership_guard(actor_list.created_by or uuid.UUID(int=0), current_user)

    if not payload.actor_ids:
        return BulkMemberResponse(added=0, already_present=0)

    # Determine which actor IDs are already members.
    existing_result = await db.execute(
        select(ActorListMember.actor_id).where(
            ActorListMember.actor_list_id == list_id,
            ActorListMember.actor_id.in_(payload.actor_ids),
        )
    )
    existing_ids: set[uuid.UUID] = {row[0] for row in existing_result.fetchall()}

    added = 0
    already_present = 0
    for actor_id in payload.actor_ids:
        if actor_id in existing_ids:
            already_present += 1
            continue
        db.add(
            ActorListMember(
                actor_list_id=list_id,
                actor_id=actor_id,
                added_by="manual",
            )
        )
        added += 1

    if added:
        await db.commit()

    logger.info(
        "bulk_list_members_added",
        list_id=str(list_id),
        added=added,
        already_present=already_present,
        user_id=str(current_user.id),
    )

    return BulkMemberResponse(added=added, already_present=already_present)


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


@router.get("/search", response_model=None)
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


@router.delete("/{actor_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
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


@router.get("/{actor_id}/content", response_model=None)
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
    response_model=None,
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


@router.get("/{actor_id}/candidates", response_model=None)
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
                f' @click="if(confirm(\'Merge {c["canonical_name"]} into {actor.canonical_name}? This cannot be undone.\'))'
                f"{{ $dispatch('merge-actor', {{ duplicate_id: '{c['actor_id']}' }}) }}"
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


# ---------------------------------------------------------------------------
# Two-actor merge (entity resolution UI)
# ---------------------------------------------------------------------------


@router.post("/{actor_id}/merge/{other_actor_id}")
async def merge_actors(
    actor_id: uuid.UUID,
    other_actor_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict:
    """Merge ``other_actor_id`` into ``actor_id``.

    The *target* actor (``actor_id``) is preserved.  The *source* actor
    (``other_actor_id``) is deleted after all its related data are
    transferred:

    * ``ActorPlatformPresence`` rows — moved to ``actor_id``; rows that would
      violate the ``UNIQUE(platform, platform_user_id)`` constraint are
      skipped (the target already has that presence).
    * ``ActorAlias`` rows — moved to ``actor_id``; duplicates are skipped.
    * ``ActorListMember`` rows — moved to ``actor_id``; duplicates are skipped.
    * ``content_records.author_id`` — bulk-updated from ``other_actor_id`` to
      ``actor_id``.
    * An ``ActorAlias`` entry is created on ``actor_id`` from the source
      actor's ``canonical_name`` (unless it already exists).

    Requires ownership of both actors (or admin role).

    Args:
        actor_id: UUID of the actor to keep (the merge target).
        other_actor_id: UUID of the actor to absorb (the merge source).
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        Dict with ``presences_moved``, ``aliases_moved``, ``list_members_moved``,
        and ``records_updated`` counts.

    Raises:
        HTTPException 400: If ``actor_id == other_actor_id``.
        HTTPException 404: If either actor does not exist.
        HTTPException 403: If the caller does not own both actors.
    """
    if actor_id == other_actor_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot merge an actor into itself.",
        )

    # Load both actors and enforce ownership.
    target = await _get_actor_or_404(actor_id, db, load_presences=True)
    ownership_guard(target.created_by or uuid.UUID(int=0), current_user)

    source = await _get_actor_or_404(other_actor_id, db, load_presences=True)
    ownership_guard(source.created_by or uuid.UUID(int=0), current_user)

    presences_moved = 0
    aliases_moved = 0
    list_members_moved = 0

    # ------------------------------------------------------------------
    # 1. Move ActorPlatformPresence rows — skip conflicts.
    # ------------------------------------------------------------------
    # Fetch existing (platform, platform_user_id) pairs on target to detect conflicts.
    existing_presence_keys: set[tuple[str, str | None]] = {
        (p.platform, p.platform_user_id) for p in target.platform_presences
    }

    source_presences_result = await db.execute(
        select(ActorPlatformPresence).where(
            ActorPlatformPresence.actor_id == other_actor_id
        )
    )
    source_presences = list(source_presences_result.scalars().all())

    for presence in source_presences:
        key = (presence.platform, presence.platform_user_id)
        if key in existing_presence_keys:
            # Conflict: target already has this presence — skip.
            await db.delete(presence)
        else:
            presence.actor_id = actor_id
            existing_presence_keys.add(key)
            presences_moved += 1

    # ------------------------------------------------------------------
    # 2. Move ActorAlias rows — skip duplicates.
    # ------------------------------------------------------------------
    existing_aliases_result = await db.execute(
        select(ActorAlias.alias).where(ActorAlias.actor_id == actor_id)
    )
    existing_aliases: set[str] = {row[0] for row in existing_aliases_result.all()}

    source_aliases_result = await db.execute(
        select(ActorAlias).where(ActorAlias.actor_id == other_actor_id)
    )
    source_aliases = list(source_aliases_result.scalars().all())

    for alias in source_aliases:
        if alias.alias in existing_aliases:
            await db.delete(alias)
        else:
            alias.actor_id = actor_id
            existing_aliases.add(alias.alias)
            aliases_moved += 1

    # Create an alias on target from the source actor's canonical_name.
    if source.canonical_name not in existing_aliases:
        db.add(ActorAlias(actor_id=actor_id, alias=source.canonical_name))
        existing_aliases.add(source.canonical_name)

    # ------------------------------------------------------------------
    # 3. Move ActorListMember rows — skip duplicates.
    # ActorListMember uses a composite PK (actor_list_id, actor_id), so we
    # cannot mutate actor_id in-place via the ORM.  Instead we delete the
    # source rows and insert new ones for the target actor where no conflict
    # exists.
    # ------------------------------------------------------------------
    existing_memberships_result = await db.execute(
        select(ActorListMember.actor_list_id).where(
            ActorListMember.actor_id == actor_id
        )
    )
    existing_list_ids: set[uuid.UUID] = {row[0] for row in existing_memberships_result.all()}

    source_memberships_result = await db.execute(
        select(ActorListMember).where(ActorListMember.actor_id == other_actor_id)
    )
    source_memberships = list(source_memberships_result.scalars().all())

    for membership in source_memberships:
        if membership.actor_list_id not in existing_list_ids:
            db.add(
                ActorListMember(
                    actor_list_id=membership.actor_list_id,
                    actor_id=actor_id,
                    added_by=membership.added_by,
                )
            )
            existing_list_ids.add(membership.actor_list_id)
            list_members_moved += 1
        await db.delete(membership)

    # ------------------------------------------------------------------
    # 4. Re-point content_records.author_id from source to target.
    # ------------------------------------------------------------------
    update_result = await db.execute(
        update(UniversalContentRecord)
        .where(UniversalContentRecord.author_id == other_actor_id)
        .values(author_id=actor_id)
        .execution_options(synchronize_session="fetch")
    )
    records_updated: int = update_result.rowcount

    # ------------------------------------------------------------------
    # 5. Flush pending changes then delete the source actor.
    # ------------------------------------------------------------------
    await db.flush()
    await db.delete(source)
    await db.commit()

    logger.info(
        "actors_merged",
        target_actor_id=str(actor_id),
        source_actor_id=str(other_actor_id),
        presences_moved=presences_moved,
        aliases_moved=aliases_moved,
        list_members_moved=list_members_moved,
        records_updated=records_updated,
        performed_by=str(current_user.id),
    )

    return {
        "presences_moved": presences_moved,
        "aliases_moved": aliases_moved,
        "list_members_moved": list_members_moved,
        "records_updated": records_updated,
    }
