"""Query design CRUD routes.

Manages the researcher's configuration of terms, actors, arena selection,
and tier choices for a collection campaign.

All routes are owner-scoped: a researcher can only read and modify their
own query designs.  Admin users can access all designs via the ownership
guard bypass.

Routes:
    GET    /query-designs/                               — list owned query designs (paginated)
    POST   /query-designs/                               — create a new query design
    GET    /query-designs/{design_id}                    — detail with search terms
    PUT    /query-designs/{design_id}                    — partial update
    DELETE /query-designs/{design_id}                    — soft-delete (is_active=False)
    POST   /query-designs/{design_id}/terms              — add a search term
    POST   /query-designs/{design_id}/terms/bulk         — add multiple search terms (YF-03)
    DELETE /query-designs/{design_id}/terms/{term_id}    — remove a search term
    GET    /query-designs/{design_id}/arena-config       — read per-arena tier config
    POST   /query-designs/{design_id}/arena-config       — write per-arena tier config
    POST   /query-designs/{design_id}/actors             — add actor (create-or-link Actor record)
    POST   /query-designs/{design_id}/actors/bulk        — add multiple actors (YF-07)
    DELETE /query-designs/{design_id}/actors/{member_id} — remove actor list member

Note on arena-config storage:
    The arena config is stored directly on ``query_designs.arenas_config`` (JSONB),
    added by migration 002.  This is the authoritative location for the researcher's
    arena tier preferences.  ``collection_runs.arenas_config`` retains its own copy
    as an immutable snapshot of the config that was active when a run was launched.

Note on actor synchronization (IP2-007):
    The POST /actors endpoint always creates or links a canonical ``Actor`` record
    in the actor directory, then adds an ``ActorListMember`` row connecting it to
    the query design's default actor list.  This ensures actors added through the
    query design editor are visible in the Actor Directory and available for
    snowball sampling.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Body, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from issue_observatory.api.dependencies import (
    PaginationParams,
    get_current_active_user,
    get_pagination,
    ownership_guard,
)
from issue_observatory.arenas.registry import list_arenas
from issue_observatory.core.database import get_db
from issue_observatory.core.models.actors import Actor, ActorListMember
from issue_observatory.core.models.query_design import ActorList, QueryDesign, SearchTerm
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
        # Derive group_id from group_label if not explicitly provided
        # (same logic as the form-based and bulk term endpoints).
        resolved_group_id = term_data.group_id
        resolved_group_label = term_data.group_label
        if resolved_group_label and resolved_group_label.strip():
            resolved_group_label = resolved_group_label.strip()
            if resolved_group_id is None:
                resolved_group_id = uuid.uuid5(design.id, resolved_group_label.lower())
        else:
            resolved_group_label = None

        term = SearchTerm(
            query_design_id=design.id,
            term=term_data.term,
            term_type=term_data.term_type,
            group_id=resolved_group_id,
            group_label=resolved_group_label,
            is_active=True,
        )
        db.add(term)

    await db.commit()
    await db.refresh(design)

    # Re-fetch with terms loaded
    return await _get_design_or_404(design.id, db, load_terms=True)


@router.post("/form", status_code=status.HTTP_303_SEE_OTHER)
async def create_query_design_form(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    name: Annotated[str, Form()],
    description: Annotated[Optional[str], Form()] = None,
    default_tier: Annotated[str, Form()] = "free",
    language: Annotated[str, Form()] = "da",
    locale_country: Annotated[str, Form()] = "dk",
    visibility: Annotated[str, Form()] = "private",
    project_id: Annotated[Optional[str], Form()] = None,
) -> RedirectResponse:
    """Create a new query design from a browser form submission.

    Accepts application/x-www-form-urlencoded data from HTMX and creates
    a minimal query design with no search terms. The user is redirected to
    the editor page to add terms and configure arenas.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        name: Human-readable name for the query design (form field).
        description: Optional longer description (form field).
        default_tier: Default tier (form field, default "free").
        language: ISO 639-1 language code (form field, default "da").
        locale_country: ISO 3166-1 country code (form field, default "dk").
        visibility: Visibility setting (form field, default "private").
        project_id: Optional project UUID to attach the design to (form field).

    Returns:
        HTTP 303 See Other redirect to the query design editor page.

    Raises:
        HTTPException 400: If name is empty after stripping whitespace.
    """
    name = name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query design name must not be empty.",
        )

    # Parse project_id if provided
    parsed_project_id: uuid.UUID | None = None
    if project_id and project_id.strip():
        try:
            parsed_project_id = uuid.UUID(project_id.strip())
        except ValueError:
            pass  # Ignore invalid UUIDs silently

    design = QueryDesign(
        owner_id=current_user.id,
        name=name,
        description=description.strip() if description else "",
        visibility=visibility,
        default_tier=default_tier,
        language=language,
        locale_country=locale_country,
        is_active=True,
        project_id=parsed_project_id,
    )
    db.add(design)
    await db.commit()
    await db.refresh(design)

    logger.info(
        "query_design_created_via_form",
        design_id=str(design.id),
        user_id=str(current_user.id),
    )

    return RedirectResponse(
        url=f"/query-designs/{design.id}/edit",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------


@router.get("/{design_id:uuid}", response_model=QueryDesignRead)
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


@router.put("/{design_id:uuid}", response_model=QueryDesignRead)
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


@router.post("/{design_id:uuid}/update", status_code=status.HTTP_303_SEE_OTHER)
async def update_query_design_form(
    design_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    name: Annotated[Optional[str], Form()] = None,
    description: Annotated[Optional[str], Form()] = None,
    default_tier: Annotated[Optional[str], Form()] = None,
    language: Annotated[Optional[str], Form()] = None,
    locale_country: Annotated[Optional[str], Form()] = None,
    visibility: Annotated[Optional[str], Form()] = None,
) -> RedirectResponse:
    """Update a query design from a browser form submission.

    Accepts application/x-www-form-urlencoded data from HTMX and applies
    a partial update. Only form fields that are explicitly provided (not None)
    are updated; omitted fields retain their current values.

    Args:
        design_id: UUID of the query design to update.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        name: New name (form field, optional).
        description: New description (form field, optional).
        default_tier: New default tier (form field, optional).
        language: New language code (form field, optional).
        locale_country: New country code (form field, optional).
        visibility: New visibility setting (form field, optional).

    Returns:
        HTTP 303 See Other redirect to the query design detail page.

    Raises:
        HTTPException 404: If the design does not exist.
        HTTPException 403: If the caller is not the owner (and not admin).
    """
    design = await _get_design_or_404(design_id, db)
    ownership_guard(design.owner_id, current_user)

    updated_fields: list[str] = []
    if name is not None:
        design.name = name.strip()
        updated_fields.append("name")
    if description is not None:
        design.description = description.strip()
        updated_fields.append("description")
    if default_tier is not None:
        design.default_tier = default_tier
        updated_fields.append("default_tier")
    if language is not None:
        design.language = language
        updated_fields.append("language")
    if locale_country is not None:
        design.locale_country = locale_country
        updated_fields.append("locale_country")
    if visibility is not None:
        design.visibility = visibility
        updated_fields.append("visibility")

    await db.commit()

    logger.info(
        "query_design_updated_via_form",
        design_id=str(design_id),
        fields=updated_fields,
        user_id=str(current_user.id),
    )

    return RedirectResponse(
        url=f"/query-designs/{design_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# Soft-delete
# ---------------------------------------------------------------------------


@router.delete("/{design_id:uuid}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
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
# Clone (IP2-051)
# ---------------------------------------------------------------------------


@router.post("/{design_id:uuid}/clone", status_code=status.HTTP_303_SEE_OTHER)
async def clone_query_design(
    design_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HTMLResponse:
    """Clone a query design including all search terms and actor lists.

    Creates a deep copy of the specified query design owned by the current
    user.  The clone includes:

    - A new ``QueryDesign`` with the name "{original_name} (copy)",
      copying ``description``, ``default_tier``, ``language``,
      ``locale_country``, and ``arenas_config`` from the original.
    - New ``SearchTerm`` rows with new UUIDs, preserving ``term``,
      ``term_type``, ``group_id``, ``group_label``, and ``is_active``.
    - New ``ActorList`` rows for each actor list, each with new UUIDs.
    - New ``ActorListMember`` rows for each list member.
    - The ``parent_design_id`` of the new design is set to the original's
      ``id`` to track cloning lineage.

    Args:
        design_id: UUID of the query design to clone.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        HTTP 303 See Other redirect to
        ``/query-designs/{new_design_id}`` (the clone's editor page).

    Raises:
        HTTPException 404: If the design does not exist.
        HTTPException 403: If the caller is not the owner (and not admin).
    """
    # Load original with search terms and actor lists (including members).
    stmt = (
        select(QueryDesign)
        .where(QueryDesign.id == design_id)
        .options(
            selectinload(QueryDesign.search_terms),
            selectinload(QueryDesign.actor_lists).selectinload(ActorList.members),
        )
    )
    result = await db.execute(stmt)
    original = result.scalar_one_or_none()

    if original is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query design '{design_id}' not found.",
        )

    ownership_guard(original.owner_id, current_user)

    # Create the cloned QueryDesign.
    clone = QueryDesign(
        owner_id=current_user.id,
        name=f"{original.name} (copy)",
        description=original.description,
        visibility="private",
        default_tier=original.default_tier,
        language=original.language,
        locale_country=original.locale_country,
        arenas_config=dict(original.arenas_config) if original.arenas_config else {},
        is_active=True,
        parent_design_id=original.id,
    )
    db.add(clone)
    await db.flush()  # populate clone.id before creating children

    # Deep-copy search terms (including target_arenas per YF-01 and translations per IP2-052).
    for term in original.search_terms:
        new_term = SearchTerm(
            query_design_id=clone.id,
            term=term.term,
            term_type=term.term_type,
            group_id=term.group_id,
            group_label=term.group_label,
            target_arenas=term.target_arenas,
            translations=term.translations,
            is_active=term.is_active,
        )
        db.add(new_term)

    # Deep-copy actor lists and their members.
    for actor_list in original.actor_lists:
        new_list = ActorList(
            query_design_id=clone.id,
            name=actor_list.name,
            description=actor_list.description,
            created_by=current_user.id,
            sampling_method=actor_list.sampling_method,
        )
        db.add(new_list)
        await db.flush()  # populate new_list.id

        for member in actor_list.members:
            new_member = ActorListMember(
                actor_list_id=new_list.id,
                actor_id=member.actor_id,
                added_by="clone",
            )
            db.add(new_member)

    await db.commit()

    logger.info(
        "query_design_cloned",
        original_id=str(design_id),
        clone_id=str(clone.id),
        user_id=str(current_user.id),
    )

    return RedirectResponse(
        url=f"/query-designs/{clone.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# Term management
# ---------------------------------------------------------------------------


def _render_term_list_item(term: SearchTerm, design_id: uuid.UUID) -> str:
    """Render a single search term as an HTMX-compatible HTML fragment.

    The fragment is inserted by HTMX ``hx-swap="beforeend"`` into the
    ``#terms-list`` ``<ul>`` element in the query design editor template.
    When the term belongs to a named group, a group-scoped ``data-group``
    attribute is added so JavaScript can maintain visual grouping headers
    on the client side.

    Args:
        term: The ``SearchTerm`` ORM instance to render.
        design_id: UUID of the parent query design (used in the delete URL).

    Returns:
        An HTML ``<li>`` fragment string.
    """
    ttype = term.term_type or "keyword"

    type_badge_map: dict[str, tuple[str, str]] = {
        "hashtag": ("bg-blue-100 text-blue-700", "#"),
        "phrase": ("bg-purple-100 text-purple-700", '""'),
        "url_pattern": ("bg-orange-100 text-orange-700", "URL"),
    }
    badge_classes, badge_label = type_badge_map.get(
        ttype, ("bg-gray-100 text-gray-600", "keyword")
    )

    inactive_badge = (
        '<span class="text-xs text-gray-400 italic">(inactive)</span>'
        if not term.is_active
        else ""
    )
    group_attr = (
        f' data-group="{_html_escape(term.group_label)}"'
        if term.group_label
        else ""
    )

    # YF-01: Show arena scoping indicator when target_arenas is set.
    arena_badge = ""
    if term.target_arenas:
        count = len(term.target_arenas)
        # Show first 2 arena names if count <= 2, otherwise show count
        if count <= 2:
            display = ", ".join(term.target_arenas)
        else:
            display = f"{count} arenas"
        arena_badge = (
            f'<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded '
            f'text-xs font-medium bg-indigo-100 text-indigo-700 flex-shrink-0" '
            f'title="{_html_escape(", ".join(term.target_arenas))}">'
            f'<svg class="w-3 h-3" xmlns="http://www.w3.org/2000/svg" fill="none" '
            f'viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">'
            f'<path stroke-linecap="round" stroke-linejoin="round" '
            f'd="M3 4h13M3 8h9m-9 4h6m4 0l4-4m0 0l4 4m-4-4v12"/>'
            f"</svg>"
            f"{_html_escape(display)}"
            f"</span>"
        )

    return (
        f'<li id="term-{term.id}"'
        f'{group_attr}'
        f' class="flex items-center justify-between gap-3 py-2 px-3 rounded-md'
        f" bg-gray-50 border border-gray-200 group\">"
        f'<div class="flex items-center gap-2 min-w-0">'
        f'<span class="inline-flex px-1.5 py-0.5 rounded text-xs font-medium'
        f' {badge_classes} flex-shrink-0">{badge_label}</span>'
        f'<span class="text-sm text-gray-900 font-medium truncate">'
        f"{_html_escape(term.term)}</span>"
        f"{arena_badge}"
        f"{inactive_badge}"
        f"</div>"
        f'<button type="button"'
        f' hx-delete="/query-designs/{design_id}/terms/{term.id}"'
        f' hx-target="#term-{term.id}"'
        f' hx-swap="outerHTML"'
        f" hx-confirm=\"Delete search term '{_html_escape(term.term)}'?\""
        f' class="flex-shrink-0 opacity-0 group-hover:opacity-100'
        f" transition-opacity p-1 rounded text-gray-400"
        f' hover:text-red-600 hover:bg-red-50"'
        f' aria-label="Delete term">'
        f'<svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none"'
        f' viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"'
        f' aria-hidden="true">'
        f'<path stroke-linecap="round" stroke-linejoin="round"'
        f' d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858'
        f"L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16\"/>"
        f"</svg>"
        f"</button>"
        f"</li>"
    )


def _html_escape(text: str) -> str:
    """Minimally escape ``text`` for safe embedding in HTML attributes and text.

    Only the characters that would break HTML structure are escaped.  This
    avoids a heavy dependency while being safe for the use cases here (term
    text, group labels, actor names) which are already validated by Pydantic.

    Args:
        text: The raw string to escape.

    Returns:
        The escaped string.
    """
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


@router.post(
    "/{design_id:uuid}/terms",
    status_code=status.HTTP_201_CREATED,
    response_class=HTMLResponse,
)
async def add_search_term(
    design_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    term: Annotated[str, Form()],
    term_type: Annotated[str, Form()] = "keyword",
    group_label: Annotated[Optional[str], Form()] = None,
    target_arenas: Annotated[Optional[str], Form()] = None,
    translations: Annotated[Optional[str], Form()] = None,
) -> HTMLResponse:
    """Add a search term to an existing query design.

    Accepts ``application/x-www-form-urlencoded`` data (submitted by the
    HTMX term form in the editor).  Returns an HTML ``<li>`` fragment
    that HTMX appends into ``#terms-list`` via ``hx-swap="beforeend"``.

    Args:
        design_id: UUID of the target query design.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        term: The search term string (form field).
        term_type: Interpretation type — ``keyword``, ``phrase``,
            ``hashtag``, or ``url_pattern`` (form field, default ``keyword``).
        group_label: Optional human-readable group name (form field).
            When provided, a stable ``group_id`` UUID is derived from the
            combination of ``design_id`` and the normalised label so that
            all terms with the same label share the same UUID.
        target_arenas: Optional comma-separated list of platform_name strings
            (YF-01). When provided, the term applies only to specified arenas.
            When NULL or empty, the term applies to all arenas (default).
        translations: Optional JSON string encoding a dict mapping ISO 639-1
            language codes to translated terms (IP2-052). When provided and valid,
            arena collectors use the appropriate translation when querying in
            non-default languages. Example: ``'{"kl": "CO2-afgift", "en": "CO2 tax"}'``.

    Returns:
        HTML ``<li>`` fragment for HTMX ``hx-swap="beforeend"`` insertion.

    Raises:
        HTTPException 400: If ``term`` is empty after stripping whitespace.
        HTTPException 404: If the design does not exist.
        HTTPException 403: If the caller is not the owner (and not admin).
        HTTPException 422: If ``translations`` is provided but is not valid JSON.
    """
    import json  # noqa: PLC0415

    term = term.strip()
    if not term:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Search term must not be empty.",
        )

    design = await _get_design_or_404(design_id, db)
    ownership_guard(design.owner_id, current_user)

    # Derive a stable group_id from (design_id, normalised group_label) so
    # that terms added with identical labels are grouped together without
    # requiring the client to manage UUIDs.
    resolved_group_id: uuid.UUID | None = None
    resolved_group_label: str | None = None
    if group_label:
        resolved_group_label = group_label.strip() or None
    if resolved_group_label:
        resolved_group_id = uuid.uuid5(design_id, resolved_group_label.lower())

    # YF-01: Parse target_arenas from comma-separated string to list.
    # Empty string or None means "all arenas" (stored as NULL).
    resolved_target_arenas: list[str] | None = None
    if target_arenas:
        arenas_list = [a.strip() for a in target_arenas.split(",") if a.strip()]
        if arenas_list:
            registered = {a["platform_name"] for a in list_arenas()}
            invalid = [a for a in arenas_list if a not in registered]
            if invalid:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid arena platform names: {invalid}",
                )
            resolved_target_arenas = arenas_list

    # IP2-052: Parse translations from JSON string to dict.
    # Empty string or None means no translations (stored as NULL).
    resolved_translations: dict[str, str] | None = None
    if translations and translations.strip():
        try:
            parsed = json.loads(translations)
            if not isinstance(parsed, dict):
                raise ValueError("translations must be a JSON object (dict)")
            # Validate all keys are strings (language codes) and values are strings (terms)
            for lang_code, translated_term in parsed.items():
                if not isinstance(lang_code, str) or not isinstance(translated_term, str):
                    raise ValueError("translations dict must have string keys and string values")
            resolved_translations = parsed
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid translations JSON: {exc}",
            ) from exc

    new_term = SearchTerm(
        query_design_id=design_id,
        term=term,
        term_type=term_type,
        group_id=resolved_group_id,
        group_label=resolved_group_label,
        target_arenas=resolved_target_arenas,
        translations=resolved_translations,
        is_active=True,
    )
    db.add(new_term)
    await db.commit()
    await db.refresh(new_term)
    logger.info(
        "search_term_added",
        design_id=str(design_id),
        term=term,
        group_label=resolved_group_label,
    )
    fragment = _render_term_list_item(new_term, design_id)
    return HTMLResponse(content=fragment, status_code=status.HTTP_201_CREATED)


@router.post(
    "/{design_id:uuid}/terms/bulk",
    status_code=status.HTTP_201_CREATED,
    response_model=list[SearchTermRead],
)
async def add_search_terms_bulk(
    design_id: uuid.UUID,
    terms_data: list[SearchTermCreate],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[SearchTerm]:
    """Add multiple search terms to a query design in a single atomic operation.

    All terms are validated before any are inserted.  If validation fails
    for any term, the entire batch is rejected and no terms are added.

    This endpoint is designed for scenarios where researchers prepare term
    lists in external tools (spreadsheets, text editors) and want to import
    them all at once rather than adding them one by one.

    Args:
        design_id: UUID of the target query design.
        terms_data: List of ``SearchTermCreate`` objects to add.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        List of newly created ``SearchTermRead`` objects ordered by insertion.

    Raises:
        HTTPException 400: If ``terms_data`` is empty.
        HTTPException 404: If the design does not exist.
        HTTPException 403: If the caller is not the owner (and not admin).
        HTTPException 422: If any term fails validation.
    """
    if not terms_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must contain at least one search term.",
        )

    design = await _get_design_or_404(design_id, db)
    ownership_guard(design.owner_id, current_user)

    # YF-01: Validate all target_arenas values against the arena registry.
    registered = {a["platform_name"] for a in list_arenas()}
    for term_data in terms_data:
        if term_data.target_arenas:
            invalid = [a for a in term_data.target_arenas if a not in registered]
            if invalid:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Term {term_data.term!r} has invalid arena platform "
                        f"names: {invalid}"
                    ),
                )

    new_terms: list[SearchTerm] = []
    for term_data in terms_data:
        # Strip and validate term text.
        term_text = term_data.term.strip()
        if not term_text:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Search term must not be empty: {term_data.term!r}",
            )

        # Resolve group_id from group_label if provided (same logic as single-term endpoint).
        resolved_group_id: uuid.UUID | None = term_data.group_id
        resolved_group_label: str | None = term_data.group_label
        if resolved_group_label and resolved_group_label.strip():
            resolved_group_label = resolved_group_label.strip()
            # Derive stable UUID from design_id + normalised label if not provided.
            if resolved_group_id is None:
                resolved_group_id = uuid.uuid5(design_id, resolved_group_label.lower())
        else:
            resolved_group_label = None
            resolved_group_id = None

        # Construct the SearchTerm ORM instance.
        new_term = SearchTerm(
            query_design_id=design_id,
            term=term_text,
            term_type=term_data.term_type or "keyword",
            group_id=resolved_group_id,
            group_label=resolved_group_label,
            target_arenas=term_data.target_arenas,
            translations=term_data.translations,
            is_active=True,
        )
        new_terms.append(new_term)

    # Bulk insert all terms atomically.
    db.add_all(new_terms)
    await db.commit()

    # Refresh all new terms to populate generated fields (id, added_at).
    for term in new_terms:
        await db.refresh(term)

    logger.info(
        "search_terms_bulk_added",
        design_id=str(design_id),
        count=len(new_terms),
        user_id=str(current_user.id),
    )

    return new_terms


@router.delete(
    "/{design_id:uuid}/terms/{term_id}",
    status_code=status.HTTP_200_OK,
    response_model=None,
)
async def remove_search_term(
    design_id: uuid.UUID,
    term_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HTMLResponse:
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
    return HTMLResponse(content="", status_code=status.HTTP_200_OK)


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


@router.get("/{design_id:uuid}/arena-config", response_model=ArenaConfigResponse)
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


class ArenaCustomConfigResponse(BaseModel):
    """Response body for the per-arena custom config PATCH endpoint (GR-01 through GR-05).

    Attributes:
        arena_name: The arena or ``"global"`` section that was updated.
        arenas_config_section: The updated sub-dict from ``arenas_config``.
    """

    arena_name: str
    arenas_config_section: dict


@router.patch(
    "/{design_id:uuid}/arena-config/{arena_name}",
    response_model=ArenaCustomConfigResponse,
)
async def patch_arena_custom_config(
    design_id: uuid.UUID,
    arena_name: str,
    payload: Annotated[dict, Body()],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ArenaCustomConfigResponse:
    """Deep-merge researcher-supplied settings into ``arenas_config[arena_name]``.

    Supports all per-arena custom configuration keys introduced by GR-01
    through GR-05:

    - ``rss`` — ``{"custom_feeds": ["https://..."]}``
    - ``telegram`` — ``{"custom_channels": ["channel_username"]}``
    - ``reddit`` — ``{"custom_subreddits": ["SubredditName"]}``
    - ``discord`` — ``{"custom_channel_ids": ["12345"]}``
    - ``wikipedia`` — ``{"seed_articles": ["Article Title"]}``
    - ``global`` — ``{"languages": ["da", "en"]}`` (GR-05; written to
      ``arenas_config`` root rather than a sub-key)

    The request body is a JSON object of key-value pairs to merge into
    ``arenas_config[arena_name]``.  Existing keys at the same level are
    preserved; only the supplied keys are overwritten (shallow merge within
    the arena section).

    Args:
        design_id: UUID of the target query design.
        arena_name: Arena identifier (e.g. ``"rss"``, ``"telegram"``) or
            ``"global"`` for root-level keys such as ``"languages"``.
        payload: Dict of key-value pairs to merge into the arena section.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        ``ArenaCustomConfigResponse`` with the updated section.

    Raises:
        HTTPException 400: If ``arena_name`` is empty or ``payload`` is empty.
        HTTPException 404: If the design does not exist.
        HTTPException 403: If the caller is not the owner or an admin.
    """
    if not arena_name or not arena_name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="arena_name must not be empty.",
        )
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must be a non-empty JSON object.",
        )

    design = await _get_design_or_404(design_id, db)
    ownership_guard(design.owner_id, current_user)

    # Start with the existing arenas_config (copy to avoid mutating ORM state).
    current_config: dict = dict(design.arenas_config) if design.arenas_config else {}

    if arena_name == "global":
        # Global keys are written directly at the arenas_config root level.
        current_config.update(payload)
        updated_section = {k: current_config[k] for k in payload if k in current_config}
    else:
        # Per-arena sub-dict: deep-merge the payload into arenas_config[arena_name].
        existing_section: dict = dict(current_config.get(arena_name) or {})
        existing_section.update(payload)
        current_config[arena_name] = existing_section
        updated_section = existing_section

    design.arenas_config = current_config
    await db.commit()

    logger.info(
        "arena_custom_config_patched",
        design_id=str(design_id),
        arena_name=arena_name,
        keys=list(payload.keys()),
    )
    return ArenaCustomConfigResponse(
        arena_name=arena_name,
        arenas_config_section=updated_section,
    )


@router.post("/{design_id:uuid}/arena-config", response_model=ArenaConfigResponse)
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

    # Preserve existing per-arena custom configs (GR-01 through GR-05) that were
    # set via the PATCH endpoint (e.g. custom_subreddits, seed_articles, custom_feeds).
    # Only overwrite the "arenas" key (tier/enable grid data).
    existing_config: dict = dict(design.arenas_config) if design.arenas_config else {}
    existing_config["arenas"] = [entry.model_dump() for entry in payload.arenas]
    design.arenas_config = existing_config

    await db.commit()
    logger.info(
        "arena_config_updated",
        design_id=str(design_id),
        arena_count=len(payload.arenas),
    )
    return _raw_config_to_response(existing_config)


# ---------------------------------------------------------------------------
# Actor management (IP2-007)
#
# Actor synchronization: adding an actor to a query design always creates or
# links a canonical ``Actor`` record in the actor directory, then stores an
# ``ActorListMember`` row connecting it to the design's default actor list.
#
# This ensures every actor added via the query design editor:
#   1. Appears in the Actor Directory for profile enrichment.
#   2. Is available as a seed for snowball sampling.
#   3. Has a stable ``actor_id`` FK on ``ActorListMember`` so the "Profile"
#      link renders in the editor template.
#
# Precedence for actor lookup (case-insensitive ``canonical_name`` match):
#   a. Existing Actor owned by the current user.
#   b. Existing shared Actor (``is_shared=True``).
#   c. New Actor created and owned by the current user (``is_shared=False``).
# ---------------------------------------------------------------------------

#: Label used for the default actor list auto-created per query design.
_DEFAULT_ACTOR_LIST_NAME: str = "Default"


async def _get_or_create_default_actor_list(
    design_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> ActorList:
    """Return (or create) the default ActorList for a query design.

    Each query design has at most one list named ``"Default"``.  If it does
    not exist yet, one is created in the same transaction.

    Args:
        design_id: UUID of the parent query design.
        user_id: UUID of the user creating the list (stored as ``created_by``).
        db: Active async database session.

    Returns:
        The existing or newly created :class:`ActorList` instance.
    """
    result = await db.execute(
        select(ActorList).where(
            ActorList.query_design_id == design_id,
            ActorList.name == _DEFAULT_ACTOR_LIST_NAME,
        )
    )
    actor_list = result.scalar_one_or_none()
    if actor_list is None:
        actor_list = ActorList(
            query_design_id=design_id,
            name=_DEFAULT_ACTOR_LIST_NAME,
            created_by=user_id,
            sampling_method="manual",
        )
        db.add(actor_list)
        await db.flush()  # Populate actor_list.id before use.
    return actor_list


async def _find_or_create_actor(
    name: str,
    actor_type: str,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> Actor:
    """Find an existing canonical Actor or create a new one.

    Lookup is case-insensitive on ``canonical_name``.  Priority order:
    1. Actor owned by ``user_id`` with matching name.
    2. Shared actor (``is_shared=True``) with matching name.
    3. New actor owned by ``user_id`` with ``is_shared=False``.

    Args:
        name: Human-readable canonical name for the actor.
        actor_type: Actor type string (``"person"``, ``"organization"``, etc.).
        user_id: UUID of the creating user.
        db: Active async database session.

    Returns:
        The matched or newly created :class:`Actor` instance.
    """
    name_lower = name.strip().lower()

    result = await db.execute(
        select(Actor).where(
            func.lower(Actor.canonical_name) == name_lower,
            or_(
                Actor.created_by == user_id,
                Actor.is_shared.is_(True),
            ),
        )
        .order_by(
            # Prefer actors owned by this user over shared ones.
            (Actor.created_by == user_id).desc()
        )
        .limit(1)
    )
    actor = result.scalar_one_or_none()

    if actor is None:
        actor = Actor(
            canonical_name=name.strip(),
            actor_type=actor_type,
            created_by=user_id,
            is_shared=False,
        )
        db.add(actor)
        await db.flush()  # Populate actor.id before linking.
        logger.info(
            "actor_created",
            actor_id=str(actor.id),
            canonical_name=actor.canonical_name,
            actor_type=actor_type,
            created_by=str(user_id),
        )
    else:
        logger.debug(
            "actor_linked_existing",
            actor_id=str(actor.id),
            canonical_name=actor.canonical_name,
        )

    return actor


def _render_actor_list_item(
    member_id: uuid.UUID,
    design_id: uuid.UUID,
    actor: Actor,
) -> str:
    """Render a single actor row as an HTMX-compatible HTML fragment.

    The fragment is inserted by HTMX ``hx-swap="beforeend"`` into the
    ``#actors-list`` ``<ul>`` element in the query design editor template.

    Args:
        member_id: UUID of the ``ActorListMember`` row (used in the DELETE URL
            and as the element's ``id`` attribute).
        design_id: UUID of the parent query design.
        actor: The canonical ``Actor`` record linked to this member.

    Returns:
        An HTML ``<li>`` fragment string.
    """
    actor_type = actor.actor_type or "unknown"
    name = actor.canonical_name

    type_badge_map: dict[str, tuple[str, str]] = {
        "person": ("bg-blue-100 text-blue-700", "Person"),
        "organization": ("bg-purple-100 text-purple-700", "Org"),
        "media_outlet": ("bg-orange-100 text-orange-700", "Media"),
    }
    badge_classes, badge_label = type_badge_map.get(
        actor_type, ("bg-gray-100 text-gray-600", "Account")
    )

    profile_link = (
        f'<a href="/actors/{actor.id}" '
        f'class="text-xs text-blue-500 hover:text-blue-700 flex-shrink-0" '
        f'title="View actor profile">Profile</a>'
    )

    # YF-16: Add prominent link to configure platform presences
    configure_presences_link = (
        f'<a href="/actors/{actor.id}#presences" '
        f'target="_blank" '
        f'class="inline-flex items-center gap-1 text-xs text-blue-600 '
        f'hover:text-blue-800 hover:underline flex-shrink-0" '
        f'title="Add platform presences (opens in new tab)">'
        f'<svg class="w-3.5 h-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" '
        f'viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true">'
        f'<path stroke-linecap="round" stroke-linejoin="round" '
        f'd="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 '
        f'005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/>'
        f'</svg>'
        f'Add presences'
        f'</a>'
    )

    return (
        f'<li id="actor-{member_id}" '
        f'class="flex items-center justify-between gap-3 py-2 px-3 rounded-md '
        f'bg-gray-50 border border-gray-200 group">'
        f'<div class="flex items-center gap-2 min-w-0">'
        f'<span class="inline-flex px-1.5 py-0.5 rounded text-xs font-medium '
        f'{badge_classes} flex-shrink-0">{badge_label}</span>'
        f'<span class="text-sm text-gray-900 font-medium truncate">{name}</span>'
        f"{profile_link}"
        f'<span class="text-gray-300 flex-shrink-0">|</span>'
        f"{configure_presences_link}"
        f"</div>"
        f'<button type="button" '
        f'hx-delete="/query-designs/{design_id}/actors/{member_id}" '
        f'hx-target="#actor-{member_id}" '
        f'hx-swap="outerHTML" '
        f"hx-confirm=\"Remove '{name}' from this actor list?\" "
        f'class="flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity '
        f'p-1 rounded text-gray-400 hover:text-red-600 hover:bg-red-50" '
        f'aria-label="Remove actor">'
        f'<svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" '
        f'viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true">'
        f'<path stroke-linecap="round" stroke-linejoin="round" '
        f'd="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 '
        f'4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>'
        f"</svg>"
        f"</button>"
        f"</li>"
    )


class ActorBulkItem(BaseModel):
    """One item in a bulk actor import request.

    Attributes:
        name: Actor's canonical name (required).
        actor_type: Actor type classification (defaults to ``"person"``).
            One of: person, organization, political_party, educational_institution,
            teachers_union, think_tank, media_outlet, government_body, ngo,
            company, unknown.
    """

    name: str
    actor_type: str = "person"


class ActorBulkAddResponse(BaseModel):
    """Response body for the bulk actor add endpoint.

    Attributes:
        added: List of actor names that were successfully added.
        skipped: List of actor names that were already in the list.
        actor_ids: List of UUIDs for all actors (added or skipped).
        total: Total items processed.
    """

    added: list[str]
    skipped: list[str]
    actor_ids: list[str]
    total: int


@router.post(
    "/{design_id:uuid}/actors",
    status_code=status.HTTP_201_CREATED,
    response_class=HTMLResponse,
)
async def add_actor_to_design(
    design_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    name: Annotated[str, Form()],
    actor_type: Annotated[str, Form()] = "unknown",
) -> HTMLResponse:
    """Add an actor to a query design, creating or linking a canonical Actor record.

    This endpoint:
    1. Validates design ownership.
    2. Finds or creates a canonical ``Actor`` record in the actor directory
       using a case-insensitive ``canonical_name`` match.
    3. Finds or creates the design's ``Default`` ``ActorList``.
    4. Adds an ``ActorListMember`` linking the actor to the list, skipping
       the insert if the actor is already a member.
    5. Returns an HTMX-compatible HTML ``<li>`` fragment for immediate
       DOM insertion into the editor's actor list.

    Actor lookup precedence (case-insensitive name match):
    - Existing actor owned by the current user (preferred).
    - Existing shared actor (``is_shared=True``).
    - New actor created with ``is_shared=False``.

    Args:
        design_id: UUID of the target query design.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        name: Actor name or handle (form field).
        actor_type: Actor type string — ``"person"``, ``"organization"``,
            ``"media_outlet"``, or ``"unknown"`` (form field, default ``"unknown"``).

    Returns:
        HTML ``<li>`` fragment for HTMX ``hx-swap="beforeend"`` insertion.

    Raises:
        HTTPException 400: If ``name`` is empty after stripping whitespace.
        HTTPException 404: If the query design does not exist.
        HTTPException 403: If the caller is not the design owner (or admin).
    """
    name = name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Actor name must not be empty.",
        )

    design = await _get_design_or_404(design_id, db)
    ownership_guard(design.owner_id, current_user)

    # Step 1 — find or create canonical Actor record.
    actor = await _find_or_create_actor(
        name=name,
        actor_type=actor_type,
        user_id=current_user.id,
        db=db,
    )

    # Step 2 — find or create the design's default ActorList.
    actor_list = await _get_or_create_default_actor_list(
        design_id=design_id,
        user_id=current_user.id,
        db=db,
    )

    # Step 3 — add ActorListMember if not already present.
    existing = await db.execute(
        select(ActorListMember).where(
            ActorListMember.actor_list_id == actor_list.id,
            ActorListMember.actor_id == actor.id,
        )
    )
    member = existing.scalar_one_or_none()

    if member is None:
        member = ActorListMember(
            actor_list_id=actor_list.id,
            actor_id=actor.id,
            added_by="manual",
        )
        db.add(member)
        await db.commit()
        await db.refresh(member)
        logger.info(
            "actor_list_member_added",
            design_id=str(design_id),
            actor_id=str(actor.id),
            actor_list_id=str(actor_list.id),
            canonical_name=actor.canonical_name,
        )
    else:
        # Actor already in the list; still commit any pending Actor creation.
        await db.commit()
        logger.debug(
            "actor_list_member_already_exists",
            design_id=str(design_id),
            actor_id=str(actor.id),
        )

    # ActorListMember uses a composite PK (actor_list_id, actor_id).
    # Use actor.id as the stable per-actor element id within this design.
    fragment = _render_actor_list_item(
        member_id=actor.id,
        design_id=design_id,
        actor=actor,
    )
    return HTMLResponse(content=fragment, status_code=status.HTTP_201_CREATED)


@router.post(
    "/{design_id:uuid}/actors/bulk",
    status_code=status.HTTP_201_CREATED,
    response_model=ActorBulkAddResponse,
)
async def add_actors_to_design_bulk(
    design_id: uuid.UUID,
    actors_data: list[ActorBulkItem],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ActorBulkAddResponse:
    """Add multiple actors to a query design in a single atomic operation.

    All actors are validated before any are inserted.  Actors already present
    in the query design's default actor list are skipped (no error raised).

    This endpoint is designed for scenarios where researchers have a prepared
    list of 8-15 seed actors and want to import them all at once rather than
    adding them one by one through the query design editor.

    For each actor in the request:
    1. Validate the actor name is not empty.
    2. Find or create a canonical ``Actor`` record (case-insensitive name match).
    3. Find or create the query design's ``Default`` ``ActorList``.
    4. Add an ``ActorListMember`` linking the actor to the list (skip if already present).

    Args:
        design_id: UUID of the target query design.
        actors_data: List of ``ActorBulkItem`` objects to add.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        ``ActorBulkAddResponse`` with counts of added/skipped actors and their IDs.

    Raises:
        HTTPException 400: If ``actors_data`` is empty.
        HTTPException 404: If the design does not exist.
        HTTPException 403: If the caller is not the owner (and not admin).
        HTTPException 422: If any actor name is empty after stripping.
    """
    if not actors_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must contain at least one actor.",
        )

    # Pre-validate all names before any DB writes (atomic: all or nothing).
    for item in actors_data:
        if not item.name.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Actor name must not be empty: {item.name!r}",
            )

    design = await _get_design_or_404(design_id, db)
    ownership_guard(design.owner_id, current_user)

    # Find or create the design's default ActorList once for all actors.
    actor_list = await _get_or_create_default_actor_list(
        design_id=design_id,
        user_id=current_user.id,
        db=db,
    )

    added_names: list[str] = []
    skipped_names: list[str] = []
    actor_ids: list[str] = []
    # Track actor IDs added during this batch to prevent duplicate member inserts.
    batch_added_actor_ids: set[uuid.UUID] = set()

    for item in actors_data:
        name = item.name.strip()

        # Find or create canonical Actor record.
        actor = await _find_or_create_actor(
            name=name,
            actor_type=item.actor_type,
            user_id=current_user.id,
            db=db,
        )
        actor_ids.append(str(actor.id))

        # Skip if already added during this batch (within-batch dedup).
        if actor.id in batch_added_actor_ids:
            skipped_names.append(actor.canonical_name)
            continue

        # Check if actor is already a member of this list (pre-existing).
        existing = await db.execute(
            select(ActorListMember).where(
                ActorListMember.actor_list_id == actor_list.id,
                ActorListMember.actor_id == actor.id,
            )
        )
        member = existing.scalar_one_or_none()

        if member is None:
            # Add new membership.
            member = ActorListMember(
                actor_list_id=actor_list.id,
                actor_id=actor.id,
                added_by="bulk_import",
            )
            db.add(member)
            added_names.append(actor.canonical_name)
            batch_added_actor_ids.add(actor.id)
        else:
            # Actor already in the list.
            skipped_names.append(actor.canonical_name)

    # Commit all changes atomically.
    await db.commit()

    logger.info(
        "actors_bulk_added",
        design_id=str(design_id),
        total=len(actors_data),
        added=len(added_names),
        skipped=len(skipped_names),
        user_id=str(current_user.id),
    )

    return ActorBulkAddResponse(
        added=added_names,
        skipped=skipped_names,
        actor_ids=actor_ids,
        total=len(actors_data),
    )


@router.delete(
    "/{design_id:uuid}/actors/{actor_id}",
    status_code=status.HTTP_200_OK,
    response_class=HTMLResponse,
)
async def remove_actor_from_design(
    design_id: uuid.UUID,
    actor_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HTMLResponse:
    """Remove an actor from a query design's default actor list.

    Finds the ``Default`` ``ActorList`` for this design and deletes the
    ``ActorListMember`` row for the given actor.  The canonical ``Actor``
    record is NOT deleted — only the list membership is removed.

    Returns an empty HTTP 200 response so HTMX ``hx-swap="outerHTML"``
    removes the ``<li>`` element from the DOM.

    Args:
        design_id: UUID of the target query design.
        actor_id: UUID of the canonical ``Actor`` to remove.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        Empty HTML response (HTTP 200) for HTMX ``hx-swap="outerHTML"``.

    Raises:
        HTTPException 404: If the design or membership does not exist.
        HTTPException 403: If the caller is not the design owner (or admin).
    """
    design = await _get_design_or_404(design_id, db)
    ownership_guard(design.owner_id, current_user)

    # Find the default actor list for this design.
    list_result = await db.execute(
        select(ActorList).where(
            ActorList.query_design_id == design_id,
            ActorList.name == _DEFAULT_ACTOR_LIST_NAME,
        )
    )
    actor_list = list_result.scalar_one_or_none()
    if actor_list is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No actor list found for query design '{design_id}'.",
        )

    # Find and delete the membership row.
    member_result = await db.execute(
        select(ActorListMember).where(
            ActorListMember.actor_list_id == actor_list.id,
            ActorListMember.actor_id == actor_id,
        )
    )
    member = member_result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Actor '{actor_id}' is not a member of the actor list "
                f"for query design '{design_id}'."
            ),
        )

    await db.delete(member)
    await db.commit()
    logger.info(
        "actor_list_member_removed",
        design_id=str(design_id),
        actor_id=str(actor_id),
        actor_list_id=str(actor_list.id),
    )
    # Return empty body — HTMX outerHTML swap removes the <li> element.
    return HTMLResponse(content="", status_code=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Actor lists for a query design — GR-17 (frontend modal picker)
# ---------------------------------------------------------------------------


@router.get(
    "/{design_id:uuid}/actor-lists",
    summary="List actor lists for a query design",
)
async def list_actor_lists_for_design(
    design_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[dict]:
    """Return all actor lists belonging to a query design.

    Used by the Content Browser quick-add modal so the researcher can pick
    which actor list a newly discovered author should be added to.

    Only lists that belong to a query design the caller owns (or is admin)
    are returned.

    Args:
        design_id: UUID of the target query design.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        List of dicts with keys ``id`` (UUID string) and ``name`` (str).
        Returns an empty list when the design has no actor lists.

    Raises:
        HTTPException 404: If the query design does not exist.
        HTTPException 403: If the caller does not own the query design.
    """
    design = await _get_design_or_404(design_id, db)
    ownership_guard(design.owner_id, current_user)

    result = await db.execute(
        select(ActorList.id, ActorList.name)
        .where(ActorList.query_design_id == design_id)
        .order_by(ActorList.name)
    )
    rows = result.all()

    logger.info(
        "actor_lists_for_design_fetched",
        design_id=str(design_id),
        count=len(rows),
        user_id=str(current_user.id),
    )

    return [{"id": str(row.id), "name": row.name} for row in rows]


# ---------------------------------------------------------------------------
# GR-09: Volume spike alerts
# ---------------------------------------------------------------------------


@router.get("/{design_id:uuid}/alerts")
async def get_volume_spike_alerts(
    design_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    days: int = 30,
) -> list[dict]:
    """Return volume spike alerts recorded for a query design in the last N days.

    Reads spike events stored in ``collection_runs.arenas_config["_volume_spikes"]``
    across all completed runs for the query design.  Each alert record contains
    the run ID, completion timestamp, and the list of spiking arena/platform
    combinations with their counts and top matched terms.

    Spike events are written by the ``check_volume_spikes`` Celery task
    (GR-09), which is dispatched automatically after each collection run
    settles its credits.

    Args:
        design_id: UUID of the query design to query alerts for.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        days: Number of past days to look back.  Defaults to 30.

    Returns:
        List of alert dicts ordered by ``completed_at`` descending::

            [
              {
                "run_id": "...",
                "completed_at": "2026-02-15T10:47:32+00:00",
                "volume_spikes": [
                  {
                    "arena_name": "social",
                    "platform": "bluesky",
                    "current_count": 842,
                    "rolling_7d_average": 210.0,
                    "ratio": 4.01,
                    "top_terms": ["klimakrisen", "COP", "paris"]
                  }
                ]
              },
              ...
            ]

        Returns an empty list when no spikes have been detected in the window.

    Raises:
        HTTPException 404: If the query design does not exist.
        HTTPException 403: If the caller does not own the query design (and
            is not an admin user).
        HTTPException 422: If ``days`` is not a positive integer.
    """
    from issue_observatory.analysis.alerting import (  # noqa: PLC0415
        fetch_recent_volume_spikes,
    )

    if days < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="days must be a positive integer.",
        )

    design = await _get_design_or_404(design_id, db)
    ownership_guard(design.owner_id, current_user)

    alerts = await fetch_recent_volume_spikes(
        session=db,
        query_design_id=design_id,
        days=days,
    )

    logger.info(
        "volume_spike_alerts_fetched",
        design_id=str(design_id),
        days=days,
        alert_count=len(alerts),
        user_id=str(current_user.id),
    )
    return alerts


# ---------------------------------------------------------------------------
# SB-09: RSS feed autodiscovery (P2)
# ---------------------------------------------------------------------------


@router.post("/{design_id:uuid}/discover-feeds")
async def discover_rss_feeds(
    design_id: uuid.UUID,
    url: Annotated[str, Body(embed=True)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[dict[str, str]]:
    """Discover RSS/Atom feeds from a website URL.

    Performs automated feed discovery for a given website URL:
    1. Fetches the page HTML.
    2. Parses ``<link rel="alternate" type="application/rss+xml">`` and
       ``<link rel="alternate" type="application/atom+xml">`` tags.
    3. If no link tags are found, probes common feed path patterns
       (``/rss``, ``/feed``, ``/atom.xml``, etc.).
    4. Returns a list of discovered feed URLs with titles for one-click
       addition to the query design's ``arenas_config["rss"]["custom_feeds"]``.

    This endpoint is part of SB-09 (socialt bedrageri recommendations, P2) to
    help researchers quickly discover and add new Danish RSS feeds.

    Args:
        design_id: UUID of the query design.
        url: Website URL to discover feeds from (request body).
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        List of dicts, each with keys:
        - ``url`` (str): Absolute feed URL.
        - ``title`` (str): Feed title extracted from the ``<link>`` tag's
          ``title`` attribute, or derived from the URL path if not available.
        - ``feed_type`` (str): ``"rss"`` or ``"atom"`` based on the declared
          content type or discovered path pattern.

        Returns an empty list when no feeds are found.

    Raises:
        HTTPException 400: If ``url`` is empty after stripping whitespace.
        HTTPException 404: If the query design does not exist.
        HTTPException 403: If the caller does not own the query design (and
            is not an admin user).
        HTTPException 500: If feed discovery fails due to a connection error
            or timeout.
    """
    from issue_observatory.arenas.rss_feeds.feed_discovery import (  # noqa: PLC0415
        discover_feeds,
    )

    url = url.strip()
    if not url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL must not be empty.",
        )

    design = await _get_design_or_404(design_id, db)
    ownership_guard(design.owner_id, current_user)

    try:
        feeds = await discover_feeds(url)
    except Exception as exc:
        logger.error(
            "discover_feeds_failed",
            design_id=str(design_id),
            url=url,
            error=str(exc),
            user_id=str(current_user.id),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Feed discovery failed: {exc}",
        ) from exc

    logger.info(
        "rss_feeds_discovered",
        design_id=str(design_id),
        url=url,
        feed_count=len(feeds),
        user_id=str(current_user.id),
    )
    return feeds


# ---------------------------------------------------------------------------
# SB-10: Reddit subreddit suggestion (P2)
# ---------------------------------------------------------------------------


@router.get("/{design_id:uuid}/suggest-subreddits")
async def suggest_subreddits(
    design_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    query: Optional[str] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Suggest Reddit subreddits relevant to a query design's search terms.

    Uses the query design's search terms as the search query (unless
    ``query`` is explicitly provided) to search Reddit's subreddit directory
    via the ``/subreddits/search`` API.  Returns a list of suggested
    subreddits with metadata (name, subscriber count, description) for
    one-click addition to the query design's
    ``arenas_config["reddit"]["custom_subreddits"]``.

    This is a FREE-tier Reddit API call via asyncpraw (SB-10).

    Args:
        design_id: UUID of the query design.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        query: Optional explicit search query.  When ``None``, uses the
            concatenation of all active search terms from the query design.
        limit: Maximum number of subreddit results to return.  Defaults to 20.
            Must not exceed 100 (Reddit API limit).

    Returns:
        List of dicts, each with keys:
        - ``name`` (str): Subreddit name without the ``r/`` prefix.
        - ``display_name`` (str): Subreddit display name (same as ``name``).
        - ``display_name_prefixed`` (str): Subreddit name with ``r/`` prefix.
        - ``subscribers`` (int): Subscriber count.
        - ``description`` (str): Public description.
        - ``active_user_count`` (int | None): Current active user count (may be null).

        Returns an empty list when no matching subreddits are found or when
        Reddit API credentials are unavailable.

    Raises:
        HTTPException 404: If the query design does not exist.
        HTTPException 403: If the caller does not own the query design (and
            is not an admin user).
        HTTPException 422: If ``limit`` is not in the valid range (1-100).
        HTTPException 500: If the Reddit API call fails due to rate limiting,
            authentication failure, or other API errors.
    """
    from issue_observatory.arenas.reddit.collector import (  # noqa: PLC0415
        RedditCollector,
    )
    from issue_observatory.arenas.reddit.subreddit_suggestion import (  # noqa: PLC0415
        suggest_subreddits as suggest_subreddits_impl,
    )
    from issue_observatory.core.credential_pool import (  # noqa: PLC0415
        CredentialPool,
    )

    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="limit must be between 1 and 100.",
        )

    design = await _get_design_or_404(design_id, db, load_terms=True)
    ownership_guard(design.owner_id, current_user)

    # Build search query from the query design's active search terms if not provided
    if query is None or not query.strip():
        active_terms = [t.term for t in design.search_terms if t.is_active]
        if not active_terms:
            logger.warning(
                "suggest_subreddits: no active search terms in design_id=%s",
                design_id,
            )
            return []
        # Use individual terms and combine results for better coverage
        # Reddit's subreddit search works better with single keywords than multi-word queries
        query = active_terms[0] if active_terms else ""

    # Acquire a Reddit credential and build an asyncpraw client
    # Use the RedditCollector's credential acquisition logic
    collector = RedditCollector(credential_pool=None)  # Env-var fallback
    try:
        cred = await collector._acquire_credential()  # noqa: SLF001
    except Exception as exc:
        logger.warning(
            "suggest_subreddits: failed to acquire Reddit credential: %s",
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Reddit API credentials not available.",
        ) from exc

    try:
        reddit = await collector._build_reddit_client(cred)  # noqa: SLF001
        async with reddit:
            suggestions = await suggest_subreddits_impl(reddit, query, limit)

            # If no results found, try English translation as fallback
            # (Grønland -> Greenland, Danmark -> Denmark, etc.)
            if not suggestions and query:
                translations = {
                    "grønland": "greenland",
                    "danmark": "denmark",
                    "København": "copenhagen",
                    "Aarhus": "aarhus",
                }
                english_query = translations.get(query.lower())
                if english_query:
                    logger.info(
                        "suggest_subreddits: no results for '%s', trying English '%s'",
                        query,
                        english_query,
                    )
                    suggestions = await suggest_subreddits_impl(reddit, english_query, limit)
    except Exception as exc:
        logger.error(
            "suggest_subreddits_failed",
            design_id=str(design_id),
            query=query,
            error=str(exc),
            user_id=str(current_user.id),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Subreddit suggestion failed: {exc}",
        ) from exc

    logger.info(
        "subreddits_suggested",
        design_id=str(design_id),
        query=query,
        result_count=len(suggestions),
        user_id=str(current_user.id),
    )
    return suggestions


# ---------------------------------------------------------------------------
# Arena Override Terms
# ---------------------------------------------------------------------------


@router.post(
    "/{design_id:uuid}/terms/override",
    status_code=status.HTTP_201_CREATED,
)
async def add_override_term(
    design_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    parent_term_id: Annotated[str, Form()],
    override_arena: Annotated[str, Form()],
    term: Annotated[str, Form()],
    term_type: Annotated[str, Form()] = "keyword",
) -> HTMLResponse:
    """Create an arena-specific override term linked to a parent default term.

    When override terms exist for an arena, they completely replace the default
    terms for that arena during collection.

    Args:
        design_id: UUID of the target query design.
        db: Injected async database session.
        current_user: The authenticated, active user.
        parent_term_id: UUID string of the parent default term.
        override_arena: Arena platform_name this override applies to.
        term: The override term string.
        term_type: Interpretation type (keyword, phrase, hashtag, url_pattern).

    Returns:
        HTML ``<li>`` fragment for HTMX insertion.
    """
    term = term.strip()
    if not term:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Override term must not be empty.",
        )

    override_arena = override_arena.strip()
    if not override_arena:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Override arena must not be empty.",
        )

    design = await _get_design_or_404(design_id, db)
    ownership_guard(design.owner_id, current_user)

    # Validate parent term exists and belongs to this design
    try:
        parent_uuid = uuid.UUID(parent_term_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid parent_term_id UUID.",
        ) from exc

    parent = await db.get(SearchTerm, parent_uuid)
    if parent is None or parent.query_design_id != design_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parent term not found in this query design.",
        )
    if parent.parent_term_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot create an override of an override. Parent must be a default term.",
        )

    # Inherit group_id from parent for boolean grouping continuity
    new_term = SearchTerm(
        query_design_id=design_id,
        term=term,
        term_type=term_type,
        group_id=parent.group_id,
        group_label=parent.group_label,
        parent_term_id=parent_uuid,
        override_arena=override_arena,
        is_active=True,
    )
    db.add(new_term)
    await db.commit()
    await db.refresh(new_term)

    logger.info(
        "override_term_added",
        design_id=str(design_id),
        term=term,
        parent_term_id=str(parent_uuid),
        override_arena=override_arena,
    )

    # Render a compact override item HTML fragment
    fragment = (
        f'<li id="term-{new_term.id}" class="flex items-center justify-between gap-3 py-1.5 px-3'
        f' rounded-md bg-amber-50 border border-amber-200 group text-sm">'
        f'<div class="flex items-center gap-2 min-w-0">'
        f'<span class="inline-flex px-1.5 py-0.5 rounded text-xs font-medium'
        f' bg-amber-100 text-amber-700 flex-shrink-0">{_html_escape(override_arena)}</span>'
        f'<span class="text-gray-900 font-medium truncate">{_html_escape(term)}</span>'
        f'<span class="text-xs text-gray-400">overrides: {_html_escape(parent.term)}</span>'
        f"</div>"
        f'<button type="button"'
        f' hx-delete="/query-designs/{design_id}/terms/{new_term.id}"'
        f' hx-target="#term-{new_term.id}"'
        f' hx-swap="outerHTML"'
        f' hx-confirm="Delete override term \'{_html_escape(term)}\'?"'
        f' class="flex-shrink-0 opacity-0 group-hover:opacity-100'
        f' transition-opacity p-1 rounded text-gray-400'
        f' hover:text-red-500 hover:bg-red-50">'
        f'<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
        f'<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"'
        f' d="M6 18L18 6M6 6l12 12"/></svg></button></li>'
    )
    return HTMLResponse(content=fragment, status_code=status.HTTP_201_CREATED)


@router.get(
    "/{design_id:uuid}/overrides/{arena_name}",
    response_model=list[SearchTermRead],
)
async def list_override_terms(
    design_id: uuid.UUID,
    arena_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[SearchTermRead]:
    """List all override terms for a specific arena in a query design.

    Returns override terms with their parent term info, allowing the UI
    to display which default term each override derives from.

    Args:
        design_id: UUID of the target query design.
        arena_name: Platform name of the arena (e.g. "tiktok", "bluesky").
        db: Injected async database session.
        current_user: The authenticated, active user.

    Returns:
        List of SearchTermRead objects for the arena's overrides.
    """
    design = await _get_design_or_404(design_id, db)
    ownership_guard(design.owner_id, current_user)

    stmt = (
        select(SearchTerm)
        .where(SearchTerm.query_design_id == design_id)
        .where(SearchTerm.override_arena == arena_name)
        .where(SearchTerm.parent_term_id.isnot(None))
        .order_by(SearchTerm.added_at)
    )
    result = await db.execute(stmt)
    terms = result.scalars().all()
    return [SearchTermRead.model_validate(t) for t in terms]
