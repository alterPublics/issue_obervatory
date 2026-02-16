"""Query design CRUD routes.

Manages the researcher's configuration of terms, actors, arena selection,
and tier choices for a collection campaign.

All routes are owner-scoped: a researcher can only read and modify their
own query designs.  Admin users can access all designs via the ownership
guard bypass.

Routes:
    GET    /query-designs/                              — list owned query designs (paginated)
    POST   /query-designs/                              — create a new query design
    GET    /query-designs/{design_id}                   — detail with search terms
    PUT    /query-designs/{design_id}                   — partial update
    DELETE /query-designs/{design_id}                   — soft-delete (is_active=False)
    POST   /query-designs/{design_id}/terms             — add a search term
    DELETE /query-designs/{design_id}/terms/{term_id}   — remove a search term
    GET    /query-designs/{design_id}/arena-config      — read per-arena tier config
    POST   /query-designs/{design_id}/arena-config      — write per-arena tier config

Note on arena-config storage:
    The arena config is stored directly on ``query_designs.arenas_config`` (JSONB),
    added by migration 002.  This is the authoritative location for the researcher's
    arena tier preferences.  ``collection_runs.arenas_config`` retains its own copy
    as an immutable snapshot of the config that was active when a run was launched.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from issue_observatory.api.dependencies import (
    PaginationParams,
    get_current_active_user,
    get_pagination,
    ownership_guard,
)
from issue_observatory.core.database import get_db
from issue_observatory.core.models.query_design import QueryDesign, SearchTerm
from issue_observatory.core.models.users import User
from issue_observatory.config.tiers import Tier
from issue_observatory.core.schemas.query_design import (
    QueryDesignCreate,
    QueryDesignRead,
    QueryDesignUpdate,
    SearchTermCreate,
    SearchTermRead,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _get_design_or_404(
    design_id: uuid.UUID,
    db: AsyncSession,
    *,
    load_terms: bool = False,
) -> QueryDesign:
    """Fetch a QueryDesign by primary key or raise HTTP 404.

    Args:
        design_id: UUID of the query design to load.
        db: Active async database session.
        load_terms: When ``True``, eagerly load the ``search_terms``
            relationship so the detail schema can serialise them.

    Returns:
        The ``QueryDesign`` ORM instance.

    Raises:
        HTTPException 404: If no design with ``design_id`` exists.
    """
    stmt = select(QueryDesign).where(QueryDesign.id == design_id)
    if load_terms:
        stmt = stmt.options(selectinload(QueryDesign.search_terms))
    result = await db.execute(stmt)
    design = result.scalar_one_or_none()
    if design is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query design '{design_id}' not found.",
        )
    return design


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[QueryDesignRead])
async def list_query_designs(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    pagination: Annotated[PaginationParams, Depends(get_pagination)],
    is_active: Optional[bool] = None,
) -> list[QueryDesign]:
    """List query designs owned by the current user.

    Results are ordered by ``created_at`` descending (newest first) and
    are cursor-paginated by UUID.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        pagination: Cursor and page-size parameters from query string.
        is_active: Optional filter to show only active (``true``) or
            soft-deleted (``false``) designs.  Omit to show all.

    Returns:
        A list of ``QueryDesignRead`` dicts for designs owned by the caller.
    """
    stmt = (
        select(QueryDesign)
        .where(QueryDesign.owner_id == current_user.id)
        .options(selectinload(QueryDesign.search_terms))
        .order_by(QueryDesign.created_at.desc())
        .limit(pagination.page_size)
    )

    if is_active is not None:
        stmt = stmt.where(QueryDesign.is_active == is_active)

    if pagination.cursor:
        try:
            cursor_id = uuid.UUID(pagination.cursor)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="cursor must be a valid UUID.",
            ) from exc
        # UUID cursor: fetch records with id < cursor (descending order)
        stmt = stmt.where(QueryDesign.id < cursor_id)

    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@router.post("/", response_model=QueryDesignRead, status_code=status.HTTP_201_CREATED)
async def create_query_design(
    payload: QueryDesignCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> QueryDesign:
    """Create a new query design for the current user.

    Search terms included in the request body are created atomically with
    the parent design in a single transaction.

    Args:
        payload: Validated ``QueryDesignCreate`` request body.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The newly created ``QueryDesignRead`` including any attached terms.
    """
    design = QueryDesign(
        owner_id=current_user.id,
        name=payload.name,
        description=payload.description,
        visibility=payload.visibility,
        default_tier=payload.default_tier,
        language=payload.language,
        locale_country=payload.locale_country,
        is_active=True,
    )
    db.add(design)
    await db.flush()  # populate design.id before inserting terms

    for term_data in payload.search_terms:
        term = SearchTerm(
            query_design_id=design.id,
            term=term_data.term,
            term_type=term_data.term_type,
            is_active=True,
        )
        db.add(term)

    await db.commit()
    await db.refresh(design)

    # Re-fetch with terms loaded
    return await _get_design_or_404(design.id, db, load_terms=True)


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------


@router.get("/{design_id}", response_model=QueryDesignRead)
async def get_query_design(
    design_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> QueryDesign:
    """Retrieve a single query design with its search terms.

    Args:
        design_id: UUID of the target query design.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The ``QueryDesignRead`` including all attached search terms.

    Raises:
        HTTPException 404: If the design does not exist.
        HTTPException 403: If the caller is not the owner (and not admin).
    """
    design = await _get_design_or_404(design_id, db, load_terms=True)
    ownership_guard(design.owner_id, current_user)
    return design


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


@router.put("/{design_id}", response_model=QueryDesignRead)
async def update_query_design(
    design_id: uuid.UUID,
    payload: QueryDesignUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> QueryDesign:
    """Partially update a query design.

    Only the fields explicitly included in the request body are applied;
    omitted fields retain their current values.

    Args:
        design_id: UUID of the target query design.
        payload: Validated ``QueryDesignUpdate`` request body.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The updated ``QueryDesignRead`` including all attached search terms.

    Raises:
        HTTPException 404: If the design does not exist.
        HTTPException 403: If the caller is not the owner (and not admin).
    """
    design = await _get_design_or_404(design_id, db)
    ownership_guard(design.owner_id, current_user)

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(design, field, value)

    await db.commit()
    logger.info("query_design_updated", design_id=str(design_id), fields=list(update_data.keys()))
    return await _get_design_or_404(design_id, db, load_terms=True)


# ---------------------------------------------------------------------------
# Soft-delete
# ---------------------------------------------------------------------------


@router.delete("/{design_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_query_design(
    design_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    """Soft-delete a query design by setting ``is_active=False``.

    The design and its historical collection data are preserved; the record
    is simply hidden from the default list view.  Use the ``is_active=false``
    filter parameter on the list endpoint to retrieve soft-deleted designs.

    Args:
        design_id: UUID of the target query design.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Raises:
        HTTPException 404: If the design does not exist.
        HTTPException 403: If the caller is not the owner (and not admin).
    """
    design = await _get_design_or_404(design_id, db)
    ownership_guard(design.owner_id, current_user)
    design.is_active = False
    await db.commit()
    logger.info("query_design_soft_deleted", design_id=str(design_id))


# ---------------------------------------------------------------------------
# Term management
# ---------------------------------------------------------------------------


@router.post(
    "/{design_id}/terms",
    response_model=SearchTermRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_search_term(
    design_id: uuid.UUID,
    payload: SearchTermCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> SearchTerm:
    """Add a search term to an existing query design.

    Args:
        design_id: UUID of the target query design.
        payload: Validated ``SearchTermCreate`` request body.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The newly created ``SearchTermRead``.

    Raises:
        HTTPException 404: If the design does not exist.
        HTTPException 403: If the caller is not the owner (and not admin).
    """
    design = await _get_design_or_404(design_id, db)
    ownership_guard(design.owner_id, current_user)

    term = SearchTerm(
        query_design_id=design_id,
        term=payload.term,
        term_type=payload.term_type,
        is_active=True,
    )
    db.add(term)
    await db.commit()
    await db.refresh(term)
    logger.info("search_term_added", design_id=str(design_id), term=payload.term)
    return term


@router.delete(
    "/{design_id}/terms/{term_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_search_term(
    design_id: uuid.UUID,
    term_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    """Remove a search term from a query design.

    This performs a hard delete of the ``SearchTerm`` row.  If historical
    run data must be preserved, use the ``is_active`` flag on the term
    instead (not yet exposed as an endpoint).

    Args:
        design_id: UUID of the parent query design.
        term_id: UUID of the search term to remove.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Raises:
        HTTPException 404: If the design or term does not exist.
        HTTPException 403: If the caller is not the owner (and not admin).
    """
    design = await _get_design_or_404(design_id, db)
    ownership_guard(design.owner_id, current_user)

    result = await db.execute(
        select(SearchTerm).where(
            SearchTerm.id == term_id,
            SearchTerm.query_design_id == design_id,
        )
    )
    term = result.scalar_one_or_none()
    if term is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Search term '{term_id}' not found on design '{design_id}'.",
        )

    await db.delete(term)
    await db.commit()
    logger.info("search_term_removed", design_id=str(design_id), term_id=str(term_id))


# ---------------------------------------------------------------------------
# Arena configuration
# ---------------------------------------------------------------------------
#
# Arena config is stored on ``query_designs.arenas_config`` (JSONB), added by
# migration 002.  The column on ``collection_runs.arenas_config`` remains as an
# immutable snapshot of the config that was active when a run was launched and
# is written by the collection orchestrator, not by these endpoints.
#
# ---------------------------------------------------------------------------


class ArenaConfigEntry(BaseModel):
    """A single per-arena tier configuration entry.

    Attributes:
        id: Arena identifier string (e.g. ``'bluesky'``, ``'youtube'``).
        enabled: Whether this arena is enabled for collection.
        tier: Tier value; must be one of the ``Tier`` enum values.
    """

    id: str
    enabled: bool
    tier: str


class ArenaConfigPayload(BaseModel):
    """Request body for ``POST /query-designs/{id}/arena-config``.

    Attributes:
        arenas: List of per-arena configuration entries.
    """

    arenas: list[ArenaConfigEntry]


class ArenaConfigResponse(BaseModel):
    """Response body for arena config endpoints.

    Attributes:
        arenas: List of per-arena configuration entries.
    """

    arenas: list[ArenaConfigEntry]


def _raw_config_to_response(raw: Optional[dict]) -> ArenaConfigResponse:
    """Convert a raw ``arenas_config`` JSONB dict to ``ArenaConfigResponse``.

    The stored format written by POST is ``{"arenas": [...]}`` — a list of
    ``ArenaConfigEntry`` dicts.  A legacy dict format
    ``{"arena_id": "tier_string", ...}`` is also handled for any rows that
    predate this endpoint.

    Args:
        raw: The raw ``arenas_config`` dict from the database, or ``None``.

    Returns:
        An ``ArenaConfigResponse`` with a normalised list of entries.
    """
    if not raw:
        return ArenaConfigResponse(arenas=[])

    if "arenas" in raw and isinstance(raw["arenas"], list):
        entries = [ArenaConfigEntry(**item) for item in raw["arenas"]]
    else:
        # Legacy: {"arena_id": "tier_string", ...}
        entries = [
            ArenaConfigEntry(id=arena_id, enabled=True, tier=tier_str)
            for arena_id, tier_str in raw.items()
        ]
    return ArenaConfigResponse(arenas=entries)


@router.get("/{design_id}/arena-config", response_model=ArenaConfigResponse)
async def get_arena_config(
    design_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ArenaConfigResponse:
    """Return the per-arena tier configuration for a query design.

    Reads ``arenas_config`` directly from the ``QueryDesign`` row.  Returns an
    empty arena list when the column holds an empty object (the column default).

    Args:
        design_id: UUID of the query design.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        ``ArenaConfigResponse`` with a list of per-arena entries.

    Raises:
        HTTPException 404: If the design does not exist.
        HTTPException 403: If the caller is not the owner or an admin.
    """
    design = await _get_design_or_404(design_id, db)
    ownership_guard(design.owner_id, current_user)
    return _raw_config_to_response(design.arenas_config)


@router.post("/{design_id}/arena-config", response_model=ArenaConfigResponse)
async def set_arena_config(
    design_id: uuid.UUID,
    payload: ArenaConfigPayload,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ArenaConfigResponse:
    """Update the per-arena tier configuration for a query design.

    Validates that every ``tier`` value in the payload is a valid ``Tier``
    enum member, then persists the config directly on ``query_designs.arenas_config``.

    Args:
        design_id: UUID of the query design.
        payload: Validated ``ArenaConfigPayload`` request body.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The updated ``ArenaConfigResponse``.

    Raises:
        HTTPException 404: If the design does not exist.
        HTTPException 403: If the caller is not the owner or an admin.
        HTTPException 422: If any tier value is not a valid ``Tier`` member.
    """
    design = await _get_design_or_404(design_id, db)
    ownership_guard(design.owner_id, current_user)

    # Validate all tier values against the Tier enum.
    valid_tier_values = {t.value for t in Tier}
    invalid = [
        entry.tier
        for entry in payload.arenas
        if entry.tier not in valid_tier_values
    ]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Invalid tier value(s): {invalid}. "
                f"Must be one of: {sorted(valid_tier_values)}."
            ),
        )

    raw_config = {"arenas": [entry.model_dump() for entry in payload.arenas]}
    design.arenas_config = raw_config

    await db.commit()
    logger.info(
        "arena_config_updated",
        design_id=str(design_id),
        arena_count=len(payload.arenas),
    )
    return _raw_config_to_response(raw_config)
