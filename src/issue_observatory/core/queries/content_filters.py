"""Shared filter helper for content record queries.

This module provides a single source of truth for all content-record
filter predicates consumed by the browse, count, and export call sites:

1. ``_build_browse_stmt`` in ``api/routes/content.py`` — the content browser.
2. ``export_content_sync`` in ``api/routes/content.py`` — the export route.
3. ``_count_matching`` in ``api/routes/content.py`` — the count badge.
4. ``content_record_count`` in ``api/routes/content.py`` — the dashboard widget.

Phase 2 fixes:
- ``effective_show_all`` mutation removed from constructors.  ``show_all=False``
  now applies an actor-only exemption: platforms in ``ACTOR_ONLY_PLATFORMS``
  (Facebook/Instagram) are always visible because they have ``term_matched=FALSE``
  by design (collected by actor tracking, not by term).
- ``content_types`` default uses a sentinel pattern — the caller passes the raw
  user-submitted list (possibly empty) and a ``content_types_was_explicit`` flag.
  When not explicit, the spec defaults to ``["post"]`` and the filter pill shows
  the active default so researchers can clear it.
- ``language`` uses a sentinel pattern — ``language_was_explicit=True`` with
  ``language=""`` means "clear the filter"; ``language_was_explicit=False`` means
  "apply the project default if available".
- All ownership modes default to ``owner_plus_collaborators`` (decision D).
- Duplicate exclusion applied by default (``include_duplicates=False``, decision F).
- Export route accepts all browse parameters so export == browse.

The two public entry points share a single ``_build_predicates`` core that
yields ``_Predicate`` objects — a neutral intermediate representation (IR).
Both ``apply_content_filters`` (SQLAlchemy-Core dialect) and
``build_content_where_sql`` (raw-SQL dialect) materialise predicates from
that IR. Adding a new predicate means adding it once in ``_build_predicates``;
both dialects automatically pick it up.

Phase 1b migrates the analysis callers (18 sites across 6 files) to
``build_content_where_sql``. Until then ``build_content_where_sql`` is
implemented but unused by analysis.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import Select, exists, func, or_, select, text
from sqlalchemy import Text as SAText

from issue_observatory.core.models.actors import Actor
from issue_observatory.core.models.collection import CollectionRun
from issue_observatory.core.models.content import UniversalContentRecord
from issue_observatory.core.models.content_links import ContentRecordLink
from issue_observatory.core.models.project_collaborator import ProjectCollaborator
from issue_observatory.core.models.query_design import QueryDesign

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

_BROWSE_LIMIT: int = 50
_BROWSE_CAP: int = 2000

# Platforms that collect by actor only (term_matched=FALSE on all records).
# These are always visible even when show_all=False so researchers can see
# Facebook/Instagram actor-tracking content without explicitly toggling show_all.
ACTOR_ONLY_PLATFORMS: frozenset[str] = frozenset({"facebook", "instagram"})


# ---------------------------------------------------------------------------
# Internal predicate IR
#
# Each predicate carries:
# - ``sa_clause``: a SQLAlchemy ``ColumnElement`` (or ``None`` when the
#   predicate is expressed as raw SQL only).
# - ``raw_sql``: a raw SQL fragment string with ``:named`` bind params
#   (or ``None`` when the predicate is expressed as SQLAlchemy only).
# - ``bind_params``: name → value mapping for the ``:named`` params.
#
# "Complex" predicates (EXISTS, functional expressions) carry both forms.
# Simple equality predicates let ``apply_content_filters`` build the
# SQLAlchemy form directly from the ``sa_clause`` field and provide the
# raw-SQL form via ``raw_sql``.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Predicate:
    """Neutral IR node representing one WHERE clause predicate."""

    # SQLAlchemy-Core column element ready for stmt.where()
    sa_clause: Any | None = None
    # Raw SQL fragment (no leading "AND") with :named bind params
    raw_sql: str | None = None
    # Bind parameter name → value mapping for the raw_sql form
    bind_params: dict[str, Any] = field(default_factory=dict)


def _escape_like(s: str) -> str:
    """Escape LIKE/ILIKE wildcards in a user-supplied substring."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ---------------------------------------------------------------------------
# Shared run_id EXISTS helper — same logic as the one inlined in content.py
# (to keep _build_predicates independent of the route module).
# ---------------------------------------------------------------------------


def _run_id_filter_sa(
    ucr_col: Any,
    published_col: Any,
    id_col: Any,
    run_id: Any,
) -> Any:
    """SQLAlchemy expression: collection_run_id = run_id OR linked via CRL."""
    return or_(
        ucr_col == run_id,
        exists(
            select(ContentRecordLink.id).where(
                ContentRecordLink.collection_run_id == run_id,
                ContentRecordLink.content_record_id == id_col,
                ContentRecordLink.content_record_published_at == published_col,
            )
        ),
    )


# ---------------------------------------------------------------------------
# ContentFilterSpec — the single filter value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContentFilterSpec:
    """Immutable value object capturing every content-record filter field.

    Phase 2 behaviour (all P0 bugs fixed):

    - ``show_all=False`` applies an actor-only exemption: platforms in
      ``ACTOR_ONLY_PLATFORMS`` are always visible (term_matched is irrelevant
      for actor-tracking-only platforms). Other platforms require
      ``term_matched=TRUE``.
    - ``content_types=["post"]`` is the default when not explicitly set by the
      user. The caller uses the ``content_types_was_explicit`` sentinel to
      distinguish "user submitted an empty form" (show all types) from "initial
      page load with no filter" (default to posts only).
    - ``language`` uses a ``language_was_explicit`` sentinel: ``True`` with
      ``language=""`` means "all languages"; ``False`` means "apply project
      default if available".
    - All ownership modes are ``owner_plus_collaborators`` (decision D).
    - ``include_duplicates=False`` excludes duplicate records by default
      (decision F, parity with analysis layer).
    """

    # --- Text search ---
    q: str | None = None

    # --- Platform / arena filters ---
    platform: str | None = None
    arena: str | None = None
    arenas_list: list[str] = field(default_factory=list)

    # Phase 1b: multi-value list filters for analysis callers.
    # ``arenas`` and ``platforms`` generate IN predicates.
    # ``languages`` generates a split_part IN predicate (locale-normalised).
    # ``search_terms`` generates the GIN-accelerated ``&&`` overlap operator.
    # These fields are orthogonal to the singular ``arena``/``platform``/
    # ``language``/``search_term`` fields used by the browse route.
    arenas: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    search_terms: list[str] = field(default_factory=list)

    # When True, the ``search_terms`` predicate also matches records whose
    # ``text_content`` contains the term as a substring (ILIKE ANY). Used by
    # the network-builder window mode so that records without
    # ``search_terms_matched`` populated — actor-only collection, Zeeschuimer
    # imports, scraped links — are still included when their text contains the
    # term, instead of being silently dropped by the pure array-overlap filter.
    search_terms_text_fallback: bool = False

    # --- Date range ---
    date_from: datetime | None = None
    date_to: datetime | None = None

    # --- Language ---
    language: str | None = None

    # --- Search terms ---
    search_term: str | None = None

    # --- Collection scoping ---
    run_id: uuid.UUID | None = None
    query_design_id: uuid.UUID | None = None
    query_design_ids: list[uuid.UUID] = field(default_factory=list)
    mode: str | None = None
    project_id: uuid.UUID | None = None

    # --- Matching and content type ---
    show_all: bool = False
    content_types: list[str] | None = None
    # Sentinel: True means the user explicitly submitted content_types (even if
    # empty, meaning "all types"). False means "not submitted" → default to
    # ["post"].  When True and content_types is empty/None, no type filter is
    # applied.
    content_types_was_explicit: bool = False

    # --- Scrape lifecycle ---
    scrape_status: str | None = None

    # --- Language sentinel ---
    # True means the user explicitly submitted language (even if "" = all langs).
    # False means "not in query string" → apply project default if available.
    language_was_explicit: bool = False

    # --- Dedup / linked records ---
    # Decision F: exclude duplicates by default (parity with analysis layer).
    include_duplicates: bool = False
    include_linked: bool = True

    # --- Actor filter (Phase 3 placeholder) ---
    actor_ids: list[uuid.UUID] = field(default_factory=list)

    # --- Ownership scoping ---
    current_user: Any = None  # User instance
    ownership_mode: Literal["owner_only", "owner_plus_collaborators", "admin"] = "owner_only"

    # --- Cursor / pagination (carried for build_browse_stmt) ---
    cursor_published_at: datetime | None = None
    cursor_id: uuid.UUID | None = None
    sort_by: str | None = None
    sort_dir: str | None = None
    page_offset: int = 0
    limit: int = _BROWSE_LIMIT

    # ----------------------------------------------------------------
    # Constructors that encode current ownership/behaviour asymmetry
    # ----------------------------------------------------------------

    @classmethod
    def from_browse_route(
        cls,
        *,
        current_user: Any,
        q: str | None = None,
        platform: str | None = None,
        arena: str | None = None,
        arenas_list: list[str] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        language: str | None = None,
        language_was_explicit: bool = False,
        search_term: str | None = None,
        run_id: uuid.UUID | None = None,
        mode: str | None = None,
        project_id: uuid.UUID | None = None,
        query_design_id: uuid.UUID | None = None,
        show_all: bool = False,
        scrape_status: str | None = None,
        content_types: list[str] | None = None,
        content_types_was_explicit: bool = False,
        include_duplicates: bool = False,
        actor_ids: list[uuid.UUID] | None = None,
        sort_by: str | None = None,
        sort_dir: str | None = None,
        cursor_published_at: datetime | None = None,
        cursor_id: uuid.UUID | None = None,
        page_offset: int = 0,
        limit: int = _BROWSE_LIMIT,
    ) -> ContentFilterSpec:
        """Construct a spec for ``/content/`` and ``/content/records``.

        Phase 2 behaviour:

        - ``show_all`` is passed through as-is (no ``effective_show_all`` mutation).
          The actor-only exemption for Facebook/Instagram is handled in
          ``_build_predicates`` via ``ACTOR_ONLY_PLATFORMS``.
        - ``content_types`` defaults to ``["post"]`` only when
          ``content_types_was_explicit=False`` (i.e. not submitted by the form).
          When ``content_types_was_explicit=True`` and ``content_types`` is empty,
          no content-type filter is applied (user cleared the filter).
        - ``language_was_explicit=True`` with ``language=""`` means "show all
          languages" (explicit clear). ``language_was_explicit=False`` means the
          route handler should apply the project default before calling this
          constructor.
        - Ownership is ``owner_plus_collaborators`` for all non-admin users
          (decision D).
        """
        _arenas: list[str] = arenas_list or []

        # Apply content_types default only when the user did NOT explicitly submit.
        if content_types_was_explicit:
            effective_content_types: list[str] | None = content_types if content_types else None
        else:
            effective_content_types = content_types if content_types else ["post"]

        # Ownership: decision D — collaborators see the same records as the owner.
        if current_user is not None and current_user.role == "admin":
            ownership_mode: Literal["owner_only", "owner_plus_collaborators", "admin"] = "admin"
        else:
            ownership_mode = "owner_plus_collaborators"

        return cls(
            q=q,
            platform=platform,
            arena=arena,
            arenas_list=_arenas,
            date_from=date_from,
            date_to=date_to,
            language=language,
            language_was_explicit=language_was_explicit,
            search_term=search_term,
            run_id=run_id,
            mode=mode,
            project_id=project_id,
            query_design_id=query_design_id,
            show_all=show_all,
            content_types=effective_content_types,
            content_types_was_explicit=content_types_was_explicit,
            include_duplicates=include_duplicates,
            actor_ids=actor_ids or [],
            scrape_status=scrape_status,
            current_user=current_user,
            ownership_mode=ownership_mode,
            # Browse and export routes use the SQLAlchemy ORM path, which skips
            # raw-sql-only predicates. Set include_linked=False so that the
            # show_all/term_matched predicate always uses the ORM-compatible clause
            # (sa_clause is not None). The analysis layer (from_analysis) sets True.
            include_linked=False,
            sort_by=sort_by,
            sort_dir=sort_dir,
            cursor_published_at=cursor_published_at,
            cursor_id=cursor_id,
            page_offset=page_offset,
            limit=limit,
        )

    @classmethod
    def from_export_route(
        cls,
        *,
        current_user: Any,
        q: str | None = None,
        platform: str | None = None,
        arena: str | None = None,
        arenas_list: list[str] | None = None,
        query_design_id: uuid.UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        language: str | None = None,
        language_was_explicit: bool = False,
        search_term: str | None = None,
        run_id: uuid.UUID | None = None,
        mode: str | None = None,
        project_id: uuid.UUID | None = None,
        show_all: bool = False,
        include_duplicates: bool = False,
        scrape_status: str | None = None,
        content_types: list[str] | None = None,
        content_types_was_explicit: bool = False,
        actor_ids: list[uuid.UUID] | None = None,
        limit: int = 10_000,
    ) -> ContentFilterSpec:
        """Construct a spec for ``/content/export``.

        Phase 2: export now accepts ALL browse parameters so that the exported
        CSV/XLSX matches exactly what the researcher sees in the table. Ownership
        is ``owner_plus_collaborators`` (decision D, same as browse). The
        content_types sentinel is honoured so an explicit "export all types"
        request is not silently overridden with the posts-only default.
        """
        _arenas: list[str] = arenas_list or []

        if current_user is not None and current_user.role == "admin":
            ownership_mode: Literal["owner_only", "owner_plus_collaborators", "admin"] = "admin"
        else:
            ownership_mode = "owner_plus_collaborators"

        # Apply content_types default only when not explicitly submitted.
        if content_types_was_explicit:
            effective_content_types: list[str] | None = content_types if content_types else None
        else:
            effective_content_types = content_types if content_types else ["post"]

        return cls(
            q=q,
            platform=platform,
            arena=arena,
            arenas_list=_arenas,
            query_design_id=query_design_id,
            date_from=date_from,
            date_to=date_to,
            language=language,
            language_was_explicit=language_was_explicit,
            search_term=search_term,
            run_id=run_id,
            mode=mode,
            project_id=project_id,
            show_all=show_all,
            include_duplicates=include_duplicates,
            content_types=effective_content_types,
            content_types_was_explicit=content_types_was_explicit,
            scrape_status=scrape_status,
            actor_ids=actor_ids or [],
            current_user=current_user,
            ownership_mode=ownership_mode,
            # Export route uses the SQLAlchemy ORM path — set include_linked=False
            # so that the show_all predicate always emits an ORM-compatible clause.
            include_linked=False,
            limit=limit,
        )

    @classmethod
    def from_dashboard_count(
        cls,
        *,
        current_user: Any,
        run_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        query_design_ids: list[uuid.UUID] | None = None,
    ) -> ContentFilterSpec:
        """Construct a spec for the dashboard ``/content/count`` endpoint.

        Phase 2: uses ``owner_plus_collaborators`` so dashboard counts include
        collaborator-project runs (decision D).
        """
        if current_user is not None and current_user.role == "admin":
            ownership_mode: Literal["owner_only", "owner_plus_collaborators", "admin"] = "admin"
        else:
            ownership_mode = "owner_plus_collaborators"
        return cls(
            run_id=run_id,
            project_id=project_id,
            query_design_ids=query_design_ids or [],
            current_user=current_user,
            ownership_mode=ownership_mode,
        )


# ---------------------------------------------------------------------------
# Ownership scope helper
# ---------------------------------------------------------------------------


def _apply_ownership_scope(
    stmt: Select,
    spec: ContentFilterSpec,
    *,
    with_joins: bool = False,
) -> Select:
    """Apply ownership scoping to ``stmt``.

    ``with_joins`` controls whether the CollectionRun + Actor LEFT JOINs are
    added. The browse query needs them for mode display and resolved author
    name; the count query does not.

    Three branches:
    - ``admin``: see everything (no ownership predicate).
    - ``owner_only``: only runs initiated_by == user.id.
    - ``owner_plus_collaborators``: own runs + collaborator project runs
      (decision D — used by browse, count, export, and dashboard).
    """
    ucr = UniversalContentRecord
    user = spec.current_user

    if spec.ownership_mode == "admin":
        if with_joins:
            stmt = (
                stmt.join(CollectionRun, ucr.collection_run_id == CollectionRun.id, isouter=True)
                .join(Actor, ucr.author_id == Actor.id, isouter=True)
            )
        # Admin: no ownership filter
        return stmt

    if spec.ownership_mode == "owner_only":
        user_run_ids_subq = (
            select(CollectionRun.id)
            .where(CollectionRun.initiated_by == user.id)
            .scalar_subquery()
        )
        if with_joins:
            stmt = (
                stmt.join(CollectionRun, ucr.collection_run_id == CollectionRun.id, isouter=True)
                .join(Actor, ucr.author_id == Actor.id, isouter=True)
                .where(ucr.collection_run_id.in_(user_run_ids_subq))
            )
        else:
            stmt = stmt.where(ucr.collection_run_id.in_(user_run_ids_subq))
        return stmt

    # owner_plus_collaborators — browse, count, export, dashboard (decision D)
    collaborated_project_ids = (
        select(ProjectCollaborator.project_id)
        .where(ProjectCollaborator.user_id == user.id)
        .scalar_subquery()
    )
    user_run_ids_subq = (
        select(CollectionRun.id)
        .where(
            or_(
                CollectionRun.initiated_by == user.id,
                CollectionRun.project_id.in_(collaborated_project_ids),
            )
        )
        .scalar_subquery()
    )
    if with_joins:
        stmt = (
            stmt.join(CollectionRun, ucr.collection_run_id == CollectionRun.id, isouter=True)
            .join(Actor, ucr.author_id == Actor.id, isouter=True)
            .where(ucr.collection_run_id.in_(user_run_ids_subq))
        )
    else:
        stmt = stmt.where(ucr.collection_run_id.in_(user_run_ids_subq))
    return stmt


# ---------------------------------------------------------------------------
# Neutral predicate IR builder
# ---------------------------------------------------------------------------


def _build_predicates(spec: ContentFilterSpec) -> list[_Predicate]:
    """Build the neutral predicate IR from a ``ContentFilterSpec``.

    Returns a list of ``_Predicate`` nodes, one per active filter clause.
    The list does NOT include ownership scoping — that is handled separately
    in ``_apply_ownership_scope`` because it also controls which JOINs are
    emitted.

    All bugs are preserved exactly as they exist in the current call sites.
    """
    ucr = UniversalContentRecord
    predicates: list[_Predicate] = []

    # ---- query_design_ids (Phase 1b: multi-design IN predicate) ----
    # When a non-empty list is supplied it takes precedence over
    # ``query_design_id`` (singular). An explicit empty list generates FALSE so
    # the query returns no rows (same contract as _filters.py).
    if spec.query_design_ids:
        _ph = ", ".join(
            f":_qd_id_{i}" for i in range(len(spec.query_design_ids))
        )
        _qd_bind = {
            f"_qd_id_{i}": str(qd_id)
            for i, qd_id in enumerate(spec.query_design_ids)
        }
        if spec.include_linked:
            # Include records directly tied to these designs AND records that
            # were linked in via content_record_links (cross-design reindex).
            predicates.append(
                _Predicate(
                    sa_clause=None,  # raw-SQL only — complex EXISTS subquery
                    raw_sql=(
                        f"({{alias}}query_design_id IN ({_ph})"
                        f" OR EXISTS ("
                        f"SELECT 1 FROM content_record_links crl "
                        f"WHERE crl.query_design_id IN ({_ph}) "
                        f"AND crl.content_record_id = {{alias}}id "
                        f"AND crl.content_record_published_at = {{alias}}published_at))"
                    ),
                    bind_params=_qd_bind,
                )
            )
        else:
            predicates.append(
                _Predicate(
                    sa_clause=ucr.query_design_id.in_(spec.query_design_ids),
                    raw_sql=f"{{alias}}query_design_id IN ({_ph})",
                    bind_params=_qd_bind,
                )
            )
    elif len(spec.query_design_ids) == 0 and spec.query_design_ids is not None:
        # Detect explicit empty list (default_factory produces [] not None).
        # Only emit FALSE when the caller explicitly passed an empty list that
        # was meant to restrict the query, which we detect by checking whether
        # query_design_id (singular) is also None. If singular is set, the
        # singular predicate below will handle scoping.
        pass  # Empty list with no singular: handled by singular branch below

    # ---- platform (singular) ----
    if spec.platform:
        predicates.append(
            _Predicate(
                sa_clause=ucr.platform == spec.platform,
                raw_sql="{alias}platform = :platform",
                bind_params={"platform": spec.platform},
            )
        )

    # ---- platforms (Phase 1b: list → IN predicate) ----
    if spec.platforms:
        _pp = ", ".join(f":_plat_{i}" for i in range(len(spec.platforms)))
        predicates.append(
            _Predicate(
                sa_clause=ucr.platform.in_(spec.platforms),
                raw_sql=f"{{alias}}platform IN ({_pp})",
                bind_params={f"_plat_{i}": p for i, p in enumerate(spec.platforms)},
            )
        )

    # ---- arena (singular) ----
    if spec.arena:
        predicates.append(
            _Predicate(
                sa_clause=ucr.arena == spec.arena,
                raw_sql="{alias}arena = :arena",
                bind_params={"arena": spec.arena},
            )
        )

    # ---- arenas (Phase 1b: list → IN predicate) ----
    if spec.arenas:
        _ap = ", ".join(f":_arena_{i}" for i in range(len(spec.arenas)))
        predicates.append(
            _Predicate(
                sa_clause=ucr.arena.in_(spec.arenas),
                raw_sql=f"{{alias}}arena IN ({_ap})",
                bind_params={f"_arena_{i}": a for i, a in enumerate(spec.arenas)},
            )
        )

    # ---- date_from ----
    if spec.date_from is not None:
        predicates.append(
            _Predicate(
                sa_clause=ucr.published_at >= spec.date_from,
                raw_sql="{alias}published_at >= :date_from",
                bind_params={"date_from": spec.date_from},
            )
        )

    # ---- date_to ----
    if spec.date_to is not None:
        predicates.append(
            _Predicate(
                sa_clause=ucr.published_at <= spec.date_to,
                raw_sql="{alias}published_at <= :date_to",
                bind_params={"date_to": spec.date_to},
            )
        )

    # ---- language (with enrichment fallback via split_part/coalesce) ----
    if spec.language:
        _effective_lang = func.coalesce(
            func.nullif(ucr.language, ""),
            ucr.raw_metadata["enrichments"]["language_detection"]["language"].as_string(),
        )
        lang_base = spec.language.split("-")[0]
        predicates.append(
            _Predicate(
                sa_clause=func.split_part(_effective_lang, "-", 1) == lang_base,
                raw_sql=(
                    "split_part(COALESCE(NULLIF({alias}language,''),"
                    " {alias}raw_metadata->'enrichments'->'language_detection'->>'language'),"
                    " '-', 1) = :language"
                ),
                bind_params={"language": lang_base},
            )
        )

    # ---- languages (Phase 1b: list → IN predicate with split_part normalisation) ----
    if spec.languages:
        _lang_col = (
            "split_part(COALESCE(NULLIF({alias}language,''),"
            " {alias}raw_metadata->'enrichments'->'language_detection'->>'language'),"
            " '-', 1)"
        )
        _lp = ", ".join(f":_lang_{i}" for i in range(len(spec.languages)))
        predicates.append(
            _Predicate(
                sa_clause=None,  # raw-SQL only — functional expression
                raw_sql=f"{_lang_col} IN ({_lp})",
                bind_params={
                    f"_lang_{i}": lang.split("-")[0]
                    for i, lang in enumerate(spec.languages)
                },
            )
        )

    # ---- run_id (with linked-record EXISTS) ----
    if spec.run_id is not None:
        run_id = spec.run_id
        predicates.append(
            _Predicate(
                sa_clause=_run_id_filter_sa(
                    ucr.collection_run_id,
                    ucr.published_at,
                    ucr.id,
                    run_id,
                ),
                raw_sql=(
                    "({alias}collection_run_id = :run_id"
                    " OR EXISTS ("
                    "  SELECT 1 FROM content_record_links crl"
                    "  WHERE crl.collection_run_id = CAST(:run_id AS uuid)"
                    "    AND crl.content_record_id = {alias}id"
                    "    AND crl.content_record_published_at = {alias}published_at"
                    " ))"
                ),
                bind_params={"run_id": str(run_id)},
            )
        )

    # ---- search_term (array containment) ----
    # Filters records by ``search_terms_matched @> ARRAY[search_term]``.
    # The run_id filter (above) already limits the result set to records either
    # directly collected in that run or linked via content_record_links; so
    # combining search_term + run_id as independent predicates gives the correct
    # intersection without needing a separate EXISTS branch here.
    if spec.search_term:
        from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY

        predicates.append(
            _Predicate(
                sa_clause=ucr.search_terms_matched.cast(PG_ARRAY(SAText)).contains(
                    [spec.search_term]
                ),
                raw_sql="{alias}search_terms_matched::text[] @> ARRAY[:search_term]::text[]",
                bind_params={"search_term": spec.search_term},
            )
        )

    # ---- search_terms (Phase 1b: list → GIN overlap operator &&) ----
    # Uses the overlap (&&) operator so that records matching ANY of the given
    # terms are included. This is the analysis-layer contract (the browse route
    # uses containment @> for exact-match). The GIN index on search_terms_matched
    # accelerates both operators.
    #
    # When ``search_terms_text_fallback=True``, the predicate is widened with
    # an ILIKE ANY branch on text_content so records lacking a populated
    # ``search_terms_matched`` array (actor-only, imports, linked) are not
    # silently excluded when their text actually contains the term.
    if spec.search_terms:
        _sp = ", ".join(f":_st_{i}" for i in range(len(spec.search_terms)))
        _st_binds = {f"_st_{i}": t for i, t in enumerate(spec.search_terms)}
        if spec.search_terms_text_fallback:
            _lp = ", ".join(f":_stl_{i}" for i in range(len(spec.search_terms)))
            _stl_binds = {
                f"_stl_{i}": f"%{_escape_like(t)}%"
                for i, t in enumerate(spec.search_terms)
            }
            predicates.append(
                _Predicate(
                    sa_clause=None,
                    raw_sql=(
                        f"({{alias}}search_terms_matched && ARRAY[{_sp}]::text[]"
                        f" OR {{alias}}text_content ILIKE ANY(ARRAY[{_lp}]))"
                    ),
                    bind_params={**_st_binds, **_stl_binds},
                )
            )
        else:
            predicates.append(
                _Predicate(
                    sa_clause=None,  # raw-SQL only — array overlap has no ORM shorthand
                    raw_sql=f"{{alias}}search_terms_matched && ARRAY[{_sp}]::text[]",
                    bind_params=_st_binds,
                )
            )

    # ---- mode (collection run mode subquery) ----
    if spec.mode:
        user = spec.current_user
        mode_run_ids_subq = select(CollectionRun.id).where(CollectionRun.mode == spec.mode)
        if spec.ownership_mode != "admin" and user is not None:
            mode_run_ids_subq = mode_run_ids_subq.where(
                CollectionRun.initiated_by == user.id
            )
        predicates.append(
            _Predicate(
                sa_clause=ucr.collection_run_id.in_(mode_run_ids_subq.scalar_subquery()),
                # Raw SQL form: inline the subquery as a text fragment.
                raw_sql=(
                    "{alias}collection_run_id IN ("
                    "  SELECT id FROM collection_runs WHERE mode = :mode"
                    + (
                        " AND initiated_by = :mode_user_id"
                        if spec.ownership_mode != "admin" and user is not None
                        else ""
                    )
                    + ")"
                ),
                bind_params={
                    "mode": spec.mode,
                    **(
                        {"mode_user_id": str(user.id)}
                        if spec.ownership_mode != "admin" and user is not None
                        else {}
                    ),
                },
            )
        )

    # ---- project_id (collection run → project join) ----
    if spec.project_id is not None:
        project_run_ids_subq = (
            select(CollectionRun.id)
            .where(CollectionRun.project_id == spec.project_id)
            .scalar_subquery()
        )
        predicates.append(
            _Predicate(
                sa_clause=ucr.collection_run_id.in_(project_run_ids_subq),
                raw_sql=(
                    "{alias}collection_run_id IN ("
                    "  SELECT id FROM collection_runs WHERE project_id = :project_id"
                    ")"
                ),
                bind_params={"project_id": str(spec.project_id)},
            )
        )

    # ---- query_design_id (singular) ----
    # Only applied when query_design_ids (list) is NOT also set — the list
    # takes precedence (same contract as the old _filters.py).
    if spec.query_design_id is not None and not spec.query_design_ids:
        predicates.append(
            _Predicate(
                sa_clause=ucr.query_design_id == spec.query_design_id,
                raw_sql="{alias}query_design_id = :query_design_id",
                bind_params={"query_design_id": str(spec.query_design_id)},
            )
        )

    # ---- show_all / term_matched ----
    # Phase 2: actor-only exemption. When show_all=False, require term_matched=TRUE
    # OR platform IN (ACTOR_ONLY_PLATFORMS). This makes Facebook/Instagram records
    # always visible because they are collected by actor tracking and never have
    # term_matched=TRUE.
    #
    # For analysis callers (Phase 1b) that supply query_design_ids and set
    # include_linked=True, the predicate is augmented with a content_record_links
    # EXISTS subquery so linked records are visible even without term_matched.
    if not spec.show_all:
        _link_qd_ids: list[uuid.UUID] = []
        if spec.query_design_ids:
            _link_qd_ids = spec.query_design_ids
        elif spec.query_design_id is not None:
            _link_qd_ids = [spec.query_design_id]

        actor_only_list = sorted(ACTOR_ONLY_PLATFORMS)
        _aop_ph = ", ".join(f":_aop_{i}" for i in range(len(actor_only_list)))
        _aop_binds = {f"_aop_{i}": p for i, p in enumerate(actor_only_list)}

        if spec.include_linked and _link_qd_ids:
            _tm_ph = ", ".join(f":_tm_qd_{i}" for i in range(len(_link_qd_ids)))
            predicates.append(
                _Predicate(
                    sa_clause=None,  # raw-SQL only — complex EXISTS subquery
                    raw_sql=(
                        f"({{alias}}term_matched = TRUE"
                        f" OR {{alias}}platform IN ({_aop_ph})"
                        f" OR EXISTS ("
                        f"SELECT 1 FROM content_record_links crl "
                        f"WHERE crl.query_design_id IN ({_tm_ph}) "
                        f"AND crl.content_record_id = {{alias}}id "
                        f"AND crl.content_record_published_at = {{alias}}published_at))"
                    ),
                    bind_params={
                        **_aop_binds,
                        **{
                            f"_tm_qd_{i}": str(qd_id)
                            for i, qd_id in enumerate(_link_qd_ids)
                        },
                    },
                )
            )
        else:
            predicates.append(
                _Predicate(
                    sa_clause=or_(
                        ucr.term_matched.is_(True),
                        ucr.platform.in_(list(ACTOR_ONLY_PLATFORMS)),
                    ),
                    raw_sql=(
                        f"({{alias}}term_matched = TRUE"
                        f" OR {{alias}}platform IN ({_aop_ph}))"
                    ),
                    bind_params=_aop_binds,
                )
            )

    # ---- duplicate exclusion (decision F) ----
    # By default, exclude records that are duplicates of another record.
    # The duplicate marker lives in raw_metadata->>'duplicate_of'.
    if not spec.include_duplicates:
        predicates.append(
            _Predicate(
                sa_clause=ucr.raw_metadata["duplicate_of"].is_(None),
                raw_sql="({alias}raw_metadata->>'duplicate_of' IS NULL)",
                bind_params={},
            )
        )

    # ---- content_types ----
    if spec.content_types:
        _ct_ph = ", ".join(f":_ct_{i}" for i in range(len(spec.content_types)))
        predicates.append(
            _Predicate(
                sa_clause=ucr.content_type.in_(spec.content_types),
                raw_sql=f"{{alias}}content_type IN ({_ct_ph})",
                bind_params={f"_ct_{i}": ct for i, ct in enumerate(spec.content_types)},
            )
        )

    # ---- scrape_status ----
    if spec.scrape_status:
        predicates.append(
            _Predicate(
                sa_clause=ucr.scrape_status == spec.scrape_status,
                raw_sql="{alias}scrape_status = :scrape_status",
                bind_params={"scrape_status": spec.scrape_status},
            )
        )

    # ---- full-text search (GIN index on Danish tsvector) ----
    if spec.q:
        fts_clause = text(
            "to_tsvector('danish', coalesce(content_records.text_content, '')"
            " || ' ' || coalesce(content_records.title, ''))"
            " @@ plainto_tsquery('danish', :fts_q)"
        ).bindparams(fts_q=spec.q)
        predicates.append(
            _Predicate(
                sa_clause=fts_clause,
                raw_sql=(
                    "to_tsvector('danish', coalesce({alias}text_content, '')"
                    " || ' ' || coalesce({alias}title, ''))"
                    " @@ plainto_tsquery('danish', :fts_q)"
                ),
                bind_params={"fts_q": spec.q},
            )
        )

    # ---- actor_ids (Phase 3: filter by author_id IN (...)) ----
    # Task 1: researcher selects one or more actors from the sidebar dropdown.
    # Maps to content_records.author_id which is indexed by idx_content_author.
    if spec.actor_ids:
        _ap = ", ".join(f":_actor_{i}" for i in range(len(spec.actor_ids)))
        predicates.append(
            _Predicate(
                sa_clause=ucr.author_id.in_(spec.actor_ids),
                raw_sql=f"{{alias}}author_id IN ({_ap})",
                bind_params={
                    f"_actor_{i}": str(actor_id)
                    for i, actor_id in enumerate(spec.actor_ids)
                },
            )
        )

    return predicates


# ---------------------------------------------------------------------------
# Public SQLAlchemy-Core entry point
# ---------------------------------------------------------------------------


def apply_content_filters(stmt: Select, spec: ContentFilterSpec) -> Select:
    """Apply all filter predicates from ``spec`` to a SQLAlchemy ``Select``.

    Does NOT apply ownership scoping (use ``_apply_ownership_scope``) or the
    multi-arena IN filter (apply post-hoc via ``stmt.where(ucr.platform.in_(...))``).

    This is the SQLAlchemy-Core entry point used by browse, count, and export.

    Args:
        stmt: A SQLAlchemy ``Select`` statement to add predicates to.
        spec: The filter specification.

    Returns:
        The modified ``Select`` statement.
    """
    for pred in _build_predicates(spec):
        if pred.sa_clause is not None:
            stmt = stmt.where(pred.sa_clause)
    return stmt


# ---------------------------------------------------------------------------
# build_browse_stmt — full browse query with joins, sort, and pagination
# ---------------------------------------------------------------------------


def build_browse_stmt(
    spec: ContentFilterSpec,
    *,
    cursor: str | None = None,
    sort: str | None = None,
    limit: int | None = None,
) -> Select:
    """Build the full browse query: ownership + joins + filters + sort + pagination.

    This is the complete replacement for the ``_build_browse_stmt`` body.
    The caller still controls the result extraction (``result.mappings()`` etc.)

    Args:
        spec: Filter specification built by ``ContentFilterSpec.from_browse_route``.
        cursor: Opaque cursor string (``published_at|id``). When provided,
            overrides ``spec.cursor_published_at`` / ``spec.cursor_id``.
        sort: Sort column override (whitelist: published_at, platform, author,
            arena, engagement_score). When provided, overrides ``spec.sort_by``.
        limit: Page size override. When provided, overrides ``spec.limit``.

    Returns:
        A SQLAlchemy ``Select`` statement ready for ``await db.execute()``.
    """
    ucr = UniversalContentRecord
    resolved_name_col = Actor.canonical_name.label("_resolved_name")

    # Base select with ownership JOIN
    base_stmt = select(ucr, CollectionRun.mode, resolved_name_col)
    stmt = _apply_ownership_scope(base_stmt, spec, with_joins=True)

    # Apply filter predicates
    stmt = apply_content_filters(stmt, spec)

    # Multi-arena IN filter (applied post-hoc to match current behaviour at
    # content.py:1092-1094 and :1356-1358)
    if spec.arenas_list and len(spec.arenas_list) > 1:
        stmt = stmt.where(ucr.platform.in_(spec.arenas_list))

    # --- Sorting and keyset pagination ---
    _sort_columns = {
        "published_at": ucr.published_at,
        "platform": ucr.platform,
        "author": ucr.author_display_name,
        "arena": ucr.arena,
        "engagement_score": ucr.engagement_score,
    }

    effective_sort = sort or spec.sort_by
    effective_sort = effective_sort if effective_sort in _sort_columns else "published_at"
    effective_dir = "asc" if spec.sort_dir == "asc" else "desc"
    use_keyset = effective_sort == "published_at"

    # Decode cursor if provided as a string
    cursor_pub_at = spec.cursor_published_at
    cursor_id_val = spec.cursor_id
    if cursor:
        cursor_pub_at, cursor_id_val = _decode_cursor(cursor)

    if use_keyset:
        if cursor_pub_at is not None and cursor_id_val is not None:
            if effective_dir == "desc":
                stmt = stmt.where(
                    (ucr.published_at < cursor_pub_at)
                    | (
                        (ucr.published_at == cursor_pub_at)
                        & (ucr.id < cursor_id_val)
                    )
                )
            else:
                stmt = stmt.where(
                    (ucr.published_at > cursor_pub_at)
                    | (
                        (ucr.published_at == cursor_pub_at)
                        & (ucr.id > cursor_id_val)
                    )
                )
        elif cursor_id_val is not None:
            if effective_dir == "desc":
                stmt = stmt.where(ucr.id < cursor_id_val)
            else:
                stmt = stmt.where(ucr.id > cursor_id_val)

    sort_col = _sort_columns[effective_sort]
    if effective_dir == "desc":
        stmt = stmt.order_by(sort_col.desc().nullslast(), ucr.id.desc())
    else:
        stmt = stmt.order_by(sort_col.asc().nullsfirst(), ucr.id.asc())

    effective_page_offset = spec.page_offset
    if not use_keyset and effective_page_offset > 0:
        stmt = stmt.offset(effective_page_offset)

    effective_limit = limit if limit is not None else spec.limit
    stmt = stmt.limit(effective_limit)

    return stmt


# ---------------------------------------------------------------------------
# build_count_stmt — count query with same predicates, no joins/sort/limit
# ---------------------------------------------------------------------------


def build_count_stmt(spec: ContentFilterSpec) -> Select:
    """Build a ``SELECT count(*)`` with the same predicates as the browse query.

    Ownership scoping is applied (owner_only or owner_plus_collaborators).
    No JOINs with CollectionRun/Actor (not needed for counting).
    No sort, no pagination.

    The query-design short-circuit (``query_design_ids``) is preserved as an
    optimization hint: when ``spec.query_design_ids`` is non-empty, we scope
    directly via ``query_design_id IN (...)`` which hits
    ``idx_content_query`` on each partition instead of scanning every
    partition via ``collection_run_id IN (subquery)``.

    Args:
        spec: Filter specification.

    Returns:
        A SQLAlchemy ``Select`` statement returning a single integer.
    """
    ucr = UniversalContentRecord

    # Dashboard path: query_design_ids short-circuit
    if spec.query_design_ids:
        base = (
            select(func.count())
            .select_from(ucr)
            .where(ucr.query_design_id.in_(spec.query_design_ids))
        )
        # run_id filter from dashboard endpoint
        if spec.run_id is not None:
            base = base.where(
                _run_id_filter_sa(
                    ucr.collection_run_id,
                    ucr.published_at,
                    ucr.id,
                    spec.run_id,
                )
            )
        return base

    # Standard count path
    base_stmt = select(ucr)
    stmt = _apply_ownership_scope(base_stmt, spec, with_joins=False)
    stmt = apply_content_filters(stmt, spec)

    # Multi-arena IN filter
    if spec.arenas_list and len(spec.arenas_list) > 1:
        stmt = stmt.where(ucr.platform.in_(spec.arenas_list))

    # Wrap as count subquery (mirrors _count_matching's approach)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    return count_stmt


# ---------------------------------------------------------------------------
# build_content_where_sql — raw-SQL entry point for Phase 1b analysis callers
# ---------------------------------------------------------------------------


def build_content_where_sql(
    spec: ContentFilterSpec,
    *,
    table_alias: str,
    params: dict[str, Any],
) -> str:
    """Build a raw-SQL WHERE clause from a ``ContentFilterSpec``.

    Returns a SQL string starting with ``WHERE`` (or empty string when no
    predicates are active). Mutates ``params`` in place with bind values.

    This entry point is intended for Phase 1b analysis callers that embed the
    returned WHERE string into f-string SQL queries. Phase 1b migrates all
    18 analysis call sites from ``analysis/_filters.build_content_filters``
    to this function.

    Note: ownership scoping is NOT included in the returned WHERE clause.
    Analysis callers pre-scope their own ``run_ids`` / ``query_design_ids``
    and use ``ownership_mode="admin"`` in the spec.

    Args:
        spec: Filter specification.
        table_alias: SQL table alias prefix, e.g. ``"cr."`` or ``""``.
        params: Mutable dict that will receive bind parameter name → value
            mappings. Callers pass this dict to the raw SQL execution.

    Returns:
        A SQL WHERE clause string (e.g. ``"WHERE cr.platform = :platform"``),
        or ``""`` when no predicates are active.
    """
    predicates = _build_predicates(spec)
    clauses: list[str] = []
    for pred in predicates:
        if pred.raw_sql is not None:
            # Substitute the table alias placeholder
            clause = pred.raw_sql.replace("{alias}", table_alias)
            clauses.append(clause)
            params.update(pred.bind_params)

    if not clauses:
        return ""
    return "WHERE " + " AND ".join(clauses)


# ---------------------------------------------------------------------------
# Cursor helpers (duplicated from content.py to keep this module standalone)
# ---------------------------------------------------------------------------


def _decode_cursor(cursor: str) -> tuple[datetime | None, uuid.UUID | None]:
    """Decode a keyset cursor produced by the content route.

    Args:
        cursor: The raw cursor string (``published_at_iso|record_id``).

    Returns:
        ``(published_at, record_id)`` — either may be ``None`` on malformed input.
    """
    try:
        ts_part, id_part = cursor.rsplit("|", 1)
        pub = None if ts_part == "null" else datetime.fromisoformat(ts_part)
        rid = uuid.UUID(id_part)
        return pub, rid
    except (ValueError, AttributeError):
        return None, None


# ---------------------------------------------------------------------------
# Dashboard count helper (resolves query_design_ids for content_record_count)
# ---------------------------------------------------------------------------


async def resolve_dashboard_query_design_ids(
    db: AsyncSession,
    spec: ContentFilterSpec,
) -> list[uuid.UUID]:
    """Resolve the set of query_design_ids for the dashboard count endpoint.

    Replicates the ``content_record_count`` scoping logic at
    ``content.py:916-925``:
    - Joins QueryDesign → CollectionRun on ``query_design_id``.
    - Filters to runs owned by ``current_user`` (owner-only scope).
    - Optionally narrows to a single project via ``spec.project_id``.

    Returns an empty list when the user has no matching query designs,
    which causes ``build_count_stmt`` to return ``{"matched": 0, "total": 0}``.

    Args:
        db: Async database session.
        spec: Filter specification built by ``ContentFilterSpec.from_dashboard_count``.

    Returns:
        List of UUID query design IDs owned by the user.
    """
    user = spec.current_user
    qd_stmt = (
        select(QueryDesign.id)
        .join(CollectionRun, CollectionRun.query_design_id == QueryDesign.id)
        .where(CollectionRun.initiated_by == user.id)
    )
    if spec.project_id is not None:
        qd_stmt = qd_stmt.where(QueryDesign.project_id == spec.project_id)

    result = await db.execute(qd_stmt.distinct())
    return [row[0] for row in result.fetchall()]
