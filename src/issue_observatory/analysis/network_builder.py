"""Network construction for keyword and entity co-occurrence analysis.

Builds bipartite networks (sender <-> keyword/entity) from content records,
with optional projection to unipartite networks and giant component extraction.

Includes network size enforcement (max 500 nodes / 5000 edges) using degree
filtering followed by disparity filter backboning (Serrano et al. 2009).

Inspired by some2net for bipartite construction and guidedLP for projection
weighting and backboning. Pure Python implementation — no networkx dependency.
"""
from __future__ import annotations

import math
import uuid
from collections import defaultdict, deque
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

MAX_NODES = 500
MAX_EDGES = 5000
MAX_PROJECTED_EDGES = 10_000_000


async def build_keyword_network(
    db: AsyncSession,
    mode: str = "bipartite",
    content_mode: str = "full",
    window_size: int | None = None,
    query_design_ids: list[uuid.UUID] | None = None,
    platform: str | list[str] | None = None,
    arena_category: str | list[str] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search_terms: list[str] | None = None,
    min_weight: int = 1,
    giant_component_only: bool = False,
    enforce_limits: bool = True,
    group_by: str = "sender",
    min_items: int | None = None,
    max_items: int | None = None,
    language: str | list[str] | None = None,
) -> dict:
    """Build a keyword co-occurrence network from content records.

    Args:
        db: Async database session.
        mode: Graph mode - "bipartite", "unipartite_sender", or "unipartite_keyword".
        content_mode: "full" for full content, "window" for N words around search terms.
        window_size: Window size for window mode (words before/after).
        query_design_ids: Filter by query designs.
        platform: Filter by platform (single string or list).
        arena_category: Filter by arena category (single string or list).
        date_from: Start date filter.
        date_to: End date filter.
        search_terms: Search terms for window mode extraction.
        min_weight: Minimum edge weight to include.
        giant_component_only: If True, return only the largest connected component.
        enforce_limits: If True, apply node/edge limits with backboning.
        group_by: Grouping dimension — "sender" (author) or "platform".
        min_items: Minimum distinct keywords a group must have to be included.
        max_items: Maximum keywords to keep per group (top by weight).

    Returns:
        Graph dict with nodes and edges lists.
    """
    _VALID_KEYWORD_MODES = {"bipartite", "unipartite_sender", "unipartite_platform", "unipartite_keyword"}
    if mode not in _VALID_KEYWORD_MODES:
        raise ValueError(
            f"Invalid mode {mode!r}. Choose from: {', '.join(sorted(_VALID_KEYWORD_MODES))}"
        )

    from sqlalchemy import text as sa_text

    from issue_observatory.core.queries.content_filters import (
        ContentFilterSpec,
        build_content_where_sql,
    )

    params: dict[str, Any] = {}
    # Apply search_terms as a SQL predicate in both modes.  In "window" mode
    # we widen the predicate with an ILIKE fallback on text_content so records
    # without ``search_terms_matched`` populated (actor-only collection,
    # imports, scraped links) are still included when their text contains the
    # term.  Without the SQL filter, window mode would scan every record in
    # range and throw away all the ones that produce an empty window.
    _arena_list = (
        list(arena_category) if isinstance(arena_category, list)
        else ([arena_category] if isinstance(arena_category, str) and arena_category else [])
    )
    _platform_list = (
        list(platform) if isinstance(platform, list)
        else ([platform] if isinstance(platform, str) and platform else [])
    )
    _language_list = (
        list(language) if isinstance(language, list)
        else ([language] if isinstance(language, str) and language else [])
    )
    spec = ContentFilterSpec(
        query_design_ids=query_design_ids or [],
        arenas=_arena_list,
        platforms=_platform_list,
        date_from=date_from,
        date_to=date_to,
        languages=_language_list,
        search_terms=search_terms or [],
        search_terms_text_fallback=(content_mode == "window"),
        include_linked=True,
        include_duplicates=False,
        ownership_mode="admin",
        # Network analysis aggregates every in-scope record for the selected
        # query designs — we're grouping by sender/platform, not filtering for
        # term hits.  Leaving show_all=False would drop records from actor-only
        # collectors that aren't in ACTOR_ONLY_PLATFORMS (Discord, Twitch,
        # Threads, RSS feeds, Ritzau) because their term_matched is FALSE.
        show_all=True,
    )
    where = build_content_where_sql(spec, table_alias="", params=params)

    # Fetch content with authors in batches
    count_sql = sa_text(
        f"SELECT COUNT(*) FROM content_records {where} "
        f"AND text_content IS NOT NULL AND LENGTH(text_content) > 50"
    )
    total = (await db.execute(count_sql, params)).scalar() or 0
    if total == 0:
        return {"nodes": [], "edges": []}

    warnings: list[str] = []
    if total > 50_000:
        warnings.append(
            f"Processing {total:,} records with RAKE keyword extraction. "
            f"This may take several minutes. Consider narrowing filters "
            f"(platform, date range, arena category) for faster results."
        )

    try:
        from multi_rake import Rake
    except ImportError:
        logger.warning("multi_rake not installed — keyword network unavailable")
        return {"nodes": [], "edges": [], "error": "multi_rake package not installed"}

    rake = Rake(language_code="da")

    # Auto-infer group_by when mode name implies platform grouping
    if mode == "unipartite_platform" and group_by != "platform":
        group_by = "platform"

    # Build bipartite edge list: sender <-> keyword
    sender_keywords: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    keyword_doc_count: dict[str, int] = defaultdict(int)
    sender_doc_count: dict[str, int] = defaultdict(int)

    use_platform = group_by == "platform"
    group_node_type = "platform" if use_platform else "sender"

    batch_size = 1000
    offset = 0
    while offset < total:
        batch_params = {**params, "_limit": batch_size, "_offset": offset}
        sql = sa_text(
            f"SELECT author_display_name, pseudonymized_author_id, text_content, platform "
            f"FROM content_records {where} "
            f"AND text_content IS NOT NULL AND LENGTH(text_content) > 50 "
            f"ORDER BY published_at DESC LIMIT :_limit OFFSET :_offset"
        )
        rows = (await db.execute(sql, batch_params)).fetchall()
        if not rows:
            break

        for row in rows:
            if use_platform:
                group_key = row[3] or "unknown_platform"
            else:
                group_key = row[0] or row[1] or "unknown"
            content = row[2]

            if content_mode == "window" and search_terms:
                from issue_observatory.analysis.keyword_extraction import _extract_window
                content = _extract_window(content, search_terms, window_size or 20)

            try:
                keywords = rake.apply(content)
            except Exception:
                continue

            sender_doc_count[group_key] += 1
            seen: set[str] = set()
            for kw, score in keywords[:15]:
                if score < 1.0:
                    continue
                kw_lower = kw.lower().strip()
                if len(kw_lower) < 2:
                    continue
                sender_keywords[group_key][kw_lower] += 1
                if kw_lower not in seen:
                    keyword_doc_count[kw_lower] += 1
                    seen.add(kw_lower)

        offset += batch_size

    # Apply min/max items filtering per group
    if min_items or max_items:
        sender_keywords = _filter_items_per_group(
            sender_keywords, keyword_doc_count, min_items, max_items,
        )

    # Build graph based on mode (validated above)
    if mode == "bipartite":
        graph = _build_bipartite(
            sender_keywords, sender_doc_count, keyword_doc_count, "keyword", min_weight,
            group_node_type=group_node_type,
        )
    elif mode in ("unipartite_sender", "unipartite_platform"):
        graph = project_to_unipartite(
            sender_keywords, "keyword", sender_doc_count, keyword_doc_count, min_weight,
            retained_node_type=group_node_type,
        )
    elif mode == "unipartite_keyword":
        graph = project_to_unipartite(
            _invert_edges(sender_keywords), group_node_type,
            keyword_doc_count, sender_doc_count, min_weight,
            retained_node_type="keyword",
        )

    if enforce_limits:
        graph = enforce_network_limits(graph)

    if giant_component_only:
        graph = extract_giant_component(graph)

    # Merge warnings from projection and builder
    projection_warnings = graph.get("warnings", [])
    all_warnings = warnings + projection_warnings
    if all_warnings:
        graph["warnings"] = all_warnings

    return graph


async def build_entity_network(
    db: AsyncSession,
    mode: str = "bipartite",
    entity_types: list[str] | None = None,
    query_design_ids: list[uuid.UUID] | None = None,
    platform: str | list[str] | None = None,
    arena_category: str | list[str] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search_terms: list[str] | None = None,
    min_weight: int = 1,
    giant_component_only: bool = False,
    enforce_limits: bool = True,
    group_by: str = "sender",
    min_items: int | None = None,
    max_items: int | None = None,
    language: str | list[str] | None = None,
) -> dict:
    """Build an entity co-occurrence network from content records.

    Args:
        db: Async database session.
        mode: Graph mode - "bipartite", "unipartite_sender", or "unipartite_entity".
        entity_types: Entity types to include (PERSON, ORG, GPE, LOC).
        query_design_ids: Filter by query designs.
        platform: Filter by platform (single string or list).
        arena_category: Filter by arena category (single string or list).
        date_from: Start date filter.
        date_to: End date filter.
        min_weight: Minimum edge weight to include.
        giant_component_only: If True, return only largest connected component.
        enforce_limits: If True, apply node/edge limits with backboning.
        group_by: Grouping dimension — "sender" (author) or "platform".
        min_items: Minimum distinct entities a group must have to be included.
        max_items: Maximum entities to keep per group (top by weight).

    Returns:
        Graph dict with nodes and edges lists.
    """
    _VALID_ENTITY_MODES = {"bipartite", "unipartite_sender", "unipartite_platform", "unipartite_entity"}
    if mode not in _VALID_ENTITY_MODES:
        raise ValueError(
            f"Invalid mode {mode!r}. Choose from: {', '.join(sorted(_VALID_ENTITY_MODES))}"
        )

    from sqlalchemy import text as sa_text

    from issue_observatory.core.queries.content_filters import (
        ContentFilterSpec,
        build_content_where_sql,
    )

    if entity_types is None:
        entity_types = ["PERSON", "ORG", "GPE", "LOC"]
    entity_type_set = set(entity_types)

    params: dict[str, Any] = {}
    _arena_list_e = (
        list(arena_category) if isinstance(arena_category, list)
        else ([arena_category] if isinstance(arena_category, str) and arena_category else [])
    )
    _platform_list_e = (
        list(platform) if isinstance(platform, list)
        else ([platform] if isinstance(platform, str) and platform else [])
    )
    _language_list_e = (
        list(language) if isinstance(language, list)
        else ([language] if isinstance(language, str) and language else [])
    )
    spec_e = ContentFilterSpec(
        query_design_ids=query_design_ids or [],
        arenas=_arena_list_e,
        platforms=_platform_list_e,
        date_from=date_from,
        date_to=date_to,
        languages=_language_list_e,
        search_terms=search_terms or [],
        include_linked=True,
        include_duplicates=False,
        ownership_mode="admin",
        show_all=True,  # see build_keyword_network — include actor-only records
    )
    where = build_content_where_sql(spec_e, table_alias="", params=params)

    # Fetch content with authors and metadata
    count_sql = sa_text(
        f"SELECT COUNT(*) FROM content_records {where} "
        f"AND text_content IS NOT NULL AND LENGTH(text_content) > 100"
    )
    total = (await db.execute(count_sql, params)).scalar() or 0
    if total == 0:
        return {"nodes": [], "edges": []}

    warnings: list[str] = []
    if total > 100_000:
        warnings.append(
            f"Processing {total:,} records for entity extraction. "
            f"This may take a minute. Consider narrowing filters for faster results."
        )

    # Auto-infer group_by when mode name implies platform grouping
    if mode == "unipartite_platform" and group_by != "platform":
        group_by = "platform"

    sender_entities: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    entity_doc_count: dict[str, int] = defaultdict(int)
    entity_type_map: dict[str, str] = {}
    sender_doc_count: dict[str, int] = defaultdict(int)
    skipped_no_enrichment = 0

    use_platform = group_by == "platform"
    group_node_type = "platform" if use_platform else "sender"

    # Only read records that have pre-computed enrichments — no inline spaCy.
    # The enrichment pipeline (actor_roles enricher) is responsible for NER;
    # the network builder just reads results from raw_metadata.
    batch_size = 1000
    offset = 0
    while offset < total:
        batch_params = {**params, "_limit": batch_size, "_offset": offset}
        sql = sa_text(
            f"SELECT author_display_name, pseudonymized_author_id, raw_metadata, platform "
            f"FROM content_records {where} "
            f"AND text_content IS NOT NULL AND LENGTH(text_content) > 100 "
            f"ORDER BY published_at DESC LIMIT :_limit OFFSET :_offset"
        )
        rows = (await db.execute(sql, batch_params)).fetchall()
        if not rows:
            break

        for row in rows:
            raw_meta = row[2] or {}

            # Read pre-computed enrichments only
            enrichments = raw_meta.get("enrichments", {})
            actor_roles = enrichments.get("actor_roles", {})
            entities_list = actor_roles.get("entities", [])

            if not entities_list:
                skipped_no_enrichment += 1
                continue

            if use_platform:
                group_key = row[3] or "unknown_platform"
            else:
                group_key = row[0] or row[1] or "unknown"
            sender_doc_count[group_key] += 1

            seen: set[str] = set()
            for ent in entities_list:
                ent_type = ent.get("entity_type", "")
                if ent_type in entity_type_set:
                    name = ent.get("name", "").strip()
                    if name and len(name) > 1:
                        sender_entities[group_key][name] += 1
                        entity_type_map[name] = ent_type
                        if name not in seen:
                            entity_doc_count[name] += 1
                            seen.add(name)

        offset += batch_size

    # Apply min/max items filtering per group
    if min_items or max_items:
        sender_entities = _filter_items_per_group(
            sender_entities, entity_doc_count, min_items, max_items,
        )

    if skipped_no_enrichment:
        logger.info(
            "entity_network_skipped_unenriched",
            skipped=skipped_no_enrichment, total=total,
        )

    # Build graph (mode validated above)
    if mode == "bipartite":
        graph = _build_bipartite_entities(
            sender_entities, sender_doc_count, entity_doc_count, entity_type_map, min_weight,
            group_node_type=group_node_type,
        )
    elif mode in ("unipartite_sender", "unipartite_platform"):
        graph = project_to_unipartite(
            sender_entities, "entity", sender_doc_count, entity_doc_count, min_weight,
            retained_node_type=group_node_type,
        )
    elif mode == "unipartite_entity":
        graph = project_to_unipartite(
            _invert_edges(sender_entities), group_node_type,
            entity_doc_count, sender_doc_count, min_weight,
            retained_node_type="entity",
        )

    if enforce_limits:
        graph = enforce_network_limits(graph)

    if giant_component_only:
        graph = extract_giant_component(graph)

    # Merge warnings from projection and builder
    projection_warnings = graph.get("warnings", [])
    all_warnings = warnings + projection_warnings
    if all_warnings:
        graph["warnings"] = all_warnings

    return graph


async def build_domain_network(
    db: AsyncSession,
    mode: str = "bipartite",
    query_design_ids: list[uuid.UUID] | None = None,
    platform: str | list[str] | None = None,
    arena_category: str | list[str] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search_terms: list[str] | None = None,
    min_weight: int = 1,
    giant_component_only: bool = False,
    enforce_limits: bool = True,
    group_by: str = "sender",
    min_items: int | None = None,
    max_items: int | None = None,
    language: str | list[str] | None = None,
    exclude_self_references: bool = True,
) -> dict:
    """Build a domain co-occurrence network from URL-extraction enrichments.

    Reads ``raw_metadata.enrichments.url_extraction.urls[]`` produced by the
    ``url_extraction`` enricher and aggregates per group (sender or platform)
    → domain.  By default URLs tagged ``type="self_reference"`` (platform
    post permalinks) are excluded so the network surfaces substantive
    outbound linking rather than self-references.

    Args:
        db: Async database session.
        mode: Graph mode — ``bipartite``, ``unipartite_sender``,
            ``unipartite_platform``, or ``unipartite_domain``.
        query_design_ids: Filter by query designs.
        platform: Filter by platform (single string or list).
        arena_category: Filter by arena category.
        date_from: Start date filter.
        date_to: End date filter.
        search_terms: Filter by ``search_terms_matched``.
        min_weight: Minimum edge weight.
        giant_component_only: Keep only the largest connected component.
        enforce_limits: Apply node/edge limits with backboning.
        group_by: ``sender`` (author) or ``platform``.
        min_items: Minimum distinct domains per group.
        max_items: Maximum domains per group (top by weight).
        language: Filter by language code(s).
        exclude_self_references: Drop URLs tagged ``type="self_reference"``
            (default True).

    Returns:
        Graph dict with ``nodes`` and ``edges`` lists.
    """
    _VALID_DOMAIN_MODES = {
        "bipartite", "unipartite_sender", "unipartite_platform", "unipartite_domain",
    }
    if mode not in _VALID_DOMAIN_MODES:
        raise ValueError(
            f"Invalid mode {mode!r}. Choose from: {', '.join(sorted(_VALID_DOMAIN_MODES))}"
        )

    from sqlalchemy import text as sa_text

    from issue_observatory.core.queries.content_filters import (
        ContentFilterSpec,
        build_content_where_sql,
    )

    params: dict[str, Any] = {}
    _arena_list_d = (
        list(arena_category) if isinstance(arena_category, list)
        else ([arena_category] if isinstance(arena_category, str) and arena_category else [])
    )
    _platform_list_d = (
        list(platform) if isinstance(platform, list)
        else ([platform] if isinstance(platform, str) and platform else [])
    )
    _language_list_d = (
        list(language) if isinstance(language, list)
        else ([language] if isinstance(language, str) and language else [])
    )
    spec_d = ContentFilterSpec(
        query_design_ids=query_design_ids or [],
        arenas=_arena_list_d,
        platforms=_platform_list_d,
        date_from=date_from,
        date_to=date_to,
        languages=_language_list_d,
        search_terms=search_terms or [],
        include_linked=True,
        include_duplicates=False,
        show_all=True,  # see build_keyword_network — include actor-only records
        ownership_mode="admin",
    )
    where = build_content_where_sql(spec_d, table_alias="", params=params)

    # Only records with a url_extraction enrichment payload.  Using the
    # JSONB containment operator ``?`` lets Postgres use a GIN index when
    # one exists and sidesteps the need for a text_content length filter
    # (Google Search records have text_content = None but still produce
    # url_extraction output for their link field).
    enrichment_filter = (
        "AND raw_metadata #> '{enrichments,url_extraction,urls}' IS NOT NULL"
    )

    count_sql = sa_text(
        f"SELECT COUNT(*) FROM content_records {where} {enrichment_filter}"
    )
    total = (await db.execute(count_sql, params)).scalar() or 0
    if total == 0:
        return {"nodes": [], "edges": []}

    warnings: list[str] = []
    if total > 200_000:
        warnings.append(
            f"Processing {total:,} records with url_extraction enrichments. "
            f"This may take a minute.  Consider narrowing filters."
        )

    # Auto-infer group_by when the mode name implies platform grouping.
    if mode == "unipartite_platform" and group_by != "platform":
        group_by = "platform"

    sender_domains: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    domain_doc_count: dict[str, int] = defaultdict(int)
    sender_doc_count: dict[str, int] = defaultdict(int)
    skipped_no_urls = 0

    use_platform = group_by == "platform"
    group_node_type = "platform" if use_platform else "sender"

    batch_size = 1000
    offset = 0
    while offset < total:
        batch_params = {**params, "_limit": batch_size, "_offset": offset}
        sql = sa_text(
            f"SELECT author_display_name, pseudonymized_author_id, raw_metadata, platform "
            f"FROM content_records {where} {enrichment_filter} "
            f"ORDER BY published_at DESC LIMIT :_limit OFFSET :_offset"
        )
        rows = (await db.execute(sql, batch_params)).fetchall()
        if not rows:
            break

        for row in rows:
            raw_meta = row[2] or {}
            enrichments = raw_meta.get("enrichments", {})
            url_extraction = enrichments.get("url_extraction", {})
            urls_list = url_extraction.get("urls", []) or []

            if not urls_list:
                skipped_no_urls += 1
                continue

            if use_platform:
                group_key = row[3] or "unknown_platform"
            else:
                group_key = row[0] or row[1] or "unknown"

            seen_in_record: set[str] = set()
            record_had_any = False
            for entry in urls_list:
                if exclude_self_references and entry.get("type") == "self_reference":
                    continue
                dom = (entry.get("domain") or "").strip().lower()
                if not dom:
                    continue
                sender_domains[group_key][dom] += 1
                record_had_any = True
                if dom not in seen_in_record:
                    domain_doc_count[dom] += 1
                    seen_in_record.add(dom)

            if record_had_any:
                sender_doc_count[group_key] += 1

        offset += batch_size

    # Apply min/max items filtering per group.
    if min_items or max_items:
        sender_domains = _filter_items_per_group(
            sender_domains, domain_doc_count, min_items, max_items,
        )

    if skipped_no_urls:
        logger.info(
            "domain_network_skipped_no_urls",
            skipped=skipped_no_urls, total=total,
        )

    # Build graph (mode validated above).
    if mode == "bipartite":
        graph = _build_bipartite(
            sender_domains, sender_doc_count, domain_doc_count, "domain", min_weight,
            group_node_type=group_node_type,
        )
    elif mode in ("unipartite_sender", "unipartite_platform"):
        graph = project_to_unipartite(
            sender_domains, "domain", sender_doc_count, domain_doc_count, min_weight,
            retained_node_type=group_node_type,
        )
    elif mode == "unipartite_domain":
        graph = project_to_unipartite(
            _invert_edges(sender_domains), group_node_type,
            domain_doc_count, sender_doc_count, min_weight,
            retained_node_type="domain",
        )

    if enforce_limits:
        graph = enforce_network_limits(graph)

    if giant_component_only:
        graph = extract_giant_component(graph)

    projection_warnings = graph.get("warnings", [])
    all_warnings = warnings + projection_warnings
    if all_warnings:
        graph["warnings"] = all_warnings

    return graph


def _build_bipartite(
    sender_items: dict[str, dict[str, int]],
    sender_counts: dict[str, int],
    item_counts: dict[str, int],
    item_type: str,
    min_weight: int,
    group_node_type: str = "sender",
) -> dict:
    """Build a bipartite graph dict from sender-item edges.

    Node IDs are prefixed by type (e.g. "sender:alice", "keyword:klima") to
    prevent collisions when a sender name matches an item name.
    """
    nodes: list[dict] = []
    edges: list[dict] = []
    node_ids: set[str] = set()

    for sender, items in sender_items.items():
        sender_id = f"{group_node_type}:{sender}"
        for item, weight in items.items():
            if weight < min_weight:
                continue
            item_id = f"{item_type}:{item}"
            if sender_id not in node_ids:
                nodes.append({
                    "id": sender_id, "label": sender, "node_type": group_node_type,
                    "doc_count": sender_counts.get(sender, 0),
                })
                node_ids.add(sender_id)
            if item_id not in node_ids:
                nodes.append({
                    "id": item_id, "label": item, "node_type": item_type,
                    "doc_count": item_counts.get(item, 0),
                })
                node_ids.add(item_id)
            edges.append({"source": sender_id, "target": item_id, "weight": weight})

    return {"nodes": nodes, "edges": edges}


def _build_bipartite_entities(
    sender_entities: dict[str, dict[str, int]],
    sender_counts: dict[str, int],
    entity_counts: dict[str, int],
    entity_type_map: dict[str, str],
    min_weight: int,
    group_node_type: str = "sender",
) -> dict:
    """Build bipartite graph with entity type metadata.

    Node IDs are prefixed by type to prevent collisions.
    """
    nodes: list[dict] = []
    edges: list[dict] = []
    node_ids: set[str] = set()

    for sender, entities in sender_entities.items():
        sender_id = f"{group_node_type}:{sender}"
        for entity, weight in entities.items():
            if weight < min_weight:
                continue
            entity_id = f"entity:{entity}"
            if sender_id not in node_ids:
                nodes.append({
                    "id": sender_id, "label": sender, "node_type": group_node_type,
                    "doc_count": sender_counts.get(sender, 0),
                })
                node_ids.add(sender_id)
            if entity_id not in node_ids:
                nodes.append({
                    "id": entity_id, "label": entity, "node_type": "entity",
                    "entity_type": entity_type_map.get(entity, "UNKNOWN"),
                    "doc_count": entity_counts.get(entity, 0),
                })
                node_ids.add(entity_id)
            edges.append({"source": sender_id, "target": entity_id, "weight": weight})

    return {"nodes": nodes, "edges": edges}


def _filter_items_per_group(
    group_items: dict[str, dict[str, int]],
    item_doc_count: dict[str, int],
    min_items: int | None,
    max_items: int | None,
) -> dict[str, dict[str, int]]:
    """Filter groups by min/max distinct item count and keep top items per group.

    Args:
        group_items: Mapping of group -> {item: weight}.
        item_doc_count: Doc counts for items (updated in-place to remove pruned items).
        min_items: Groups with fewer distinct items are dropped.
        max_items: Only the top N items by weight are kept per group.

    Returns:
        Filtered copy of group_items.
    """
    filtered: dict[str, dict[str, int]] = {}
    for group, items in group_items.items():
        if min_items and len(items) < min_items:
            continue
        if max_items and len(items) > max_items:
            # Keep top N items by weight
            top = dict(sorted(items.items(), key=lambda x: x[1], reverse=True)[:max_items])
            filtered[group] = top
        else:
            filtered[group] = items
    return filtered


def _invert_edges(
    edges: dict[str, dict[str, int]],
) -> dict[str, dict[str, int]]:
    """Invert a sender->item edge dict to item->sender."""
    inverted: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for sender, items in edges.items():
        for item, weight in items.items():
            inverted[item][sender] += weight
    return dict(inverted)


def project_to_unipartite(
    bipartite_edges: dict[str, dict[str, int]],
    collapse_type: str,
    retained_counts: dict[str, int],
    collapsed_counts: dict[str, int],
    min_weight: int = 1,
    retained_node_type: str | None = None,
    max_projected_edges: int = MAX_PROJECTED_EDGES,
) -> dict:
    """Project bipartite graph to unipartite by collapsing one node type.

    For each pair of retained-type nodes sharing neighbors in collapsed type:
    weight(A, B) = sum(min(w(A, X), w(B, X))) for all shared neighbors X.

    Large projections are handled with a three-stage strategy:

    1. **Pre-flight estimation** — before the O(N²) loop, estimate total
       projected pairs from the inverted index.
    2. **Top-K retained node reduction** — if estimated pairs exceed
       ``max_projected_edges``, keep only the top-K retained nodes ranked
       by bipartite degree (number of collapsed neighbors) and total weight.
       K is found via binary search to bring estimated pairs just under the cap.
    3. **Hard cap during projection** — if unique edges exceed the cap during
       the inner loop, projection halts and the top edges by weight are kept.

    Args:
        bipartite_edges: Dict mapping retained nodes to their collapsed neighbors with weights.
        collapse_type: Type label being collapsed (for logging).
        retained_counts: Doc counts for retained node type.
        collapsed_counts: Doc counts for collapsed node type.
        min_weight: Minimum projected edge weight.
        retained_node_type: Explicit node_type label for retained nodes. If None,
            inferred as "sender" (when collapsing non-senders) or "keyword" (when
            collapsing senders) for backward compatibility.
        max_projected_edges: Maximum unique edges allowed during projection.

    Returns:
        Unipartite graph dict with optional ``"warnings"`` list describing
        any caps or reductions that were applied.
    """
    if retained_node_type is None:
        retained_node_type = "sender" if collapse_type != "sender" else "keyword"

    warnings: list[str] = []

    # Build inverted index: collapsed_node -> {retained_node: weight}
    inverted: dict[str, dict[str, int]] = defaultdict(dict)
    for retained, neighbors in bipartite_edges.items():
        for collapsed, weight in neighbors.items():
            inverted[collapsed][retained] = weight

    # --- Stage 1: Pre-flight estimation ---
    original_retained_count = len(bipartite_edges)
    estimated_pairs = _estimate_projected_pairs(inverted)

    logger.info(
        "unipartite_projection_estimate",
        retained_nodes=original_retained_count,
        collapsed_nodes=len(inverted),
        estimated_pairs=estimated_pairs,
        max_projected_edges=max_projected_edges,
    )

    # --- Stage 2: Top-K retained node reduction ---
    if estimated_pairs > max_projected_edges:
        inverted, kept_count = _reduce_retained_nodes(
            inverted, bipartite_edges, max_projected_edges,
        )
        new_estimate = _estimate_projected_pairs(inverted)
        warnings.append(
            f"Pre-projection reduction: kept top {kept_count:,} of "
            f"{original_retained_count:,} nodes by bipartite degree to bring "
            f"estimated pairs from {estimated_pairs:,} to {new_estimate:,} "
            f"(cap: {max_projected_edges:,})."
        )
        logger.info(
            "unipartite_projection_reduced",
            original_nodes=original_retained_count,
            kept_nodes=kept_count,
            original_estimate=estimated_pairs,
            new_estimate=new_estimate,
        )
        estimated_pairs = new_estimate

    # --- Stage 3: Projection with hard cap ---
    projected_edges, capped = _project_edges(inverted, max_projected_edges)
    if capped:
        warnings.append(
            f"Projection reached {max_projected_edges:,} unique edge cap. "
            f"Some low-weight edges may be missing."
        )

    # Build graph
    nodes: list[dict] = []
    edges: list[dict] = []
    node_ids: set[str] = set()

    for (a, b), weight in projected_edges.items():
        if weight < min_weight:
            continue
        for node_id in (a, b):
            if node_id not in node_ids:
                nodes.append({
                    "id": node_id, "label": node_id,
                    "node_type": retained_node_type,
                    "doc_count": retained_counts.get(node_id, 0),
                })
                node_ids.add(node_id)
        edges.append({"source": a, "target": b, "weight": weight})

    result: dict = {"nodes": nodes, "edges": edges}
    if warnings:
        result["warnings"] = warnings
    return result


def _estimate_projected_pairs(
    inverted: dict[str, dict[str, int]],
    keep_set: set[str] | None = None,
) -> int:
    """Estimate upper bound on projected edges from the inverted index.

    For each collapsed node with k retained neighbors, the contribution is
    C(k, 2) = k*(k-1)/2 unique pairs. The sum over-counts edges shared across
    multiple collapsed nodes, so it is an upper bound.
    """
    total = 0
    for retained_nodes in inverted.values():
        if keep_set is not None:
            k = sum(1 for r in retained_nodes if r in keep_set)
        else:
            k = len(retained_nodes)
        total += k * (k - 1) // 2
    return total


def _reduce_retained_nodes(
    inverted: dict[str, dict[str, int]],
    bipartite_edges: dict[str, dict[str, int]],
    max_projected_edges: int,
) -> tuple[dict[str, dict[str, int]], int]:
    """Reduce retained nodes via top-K selection to fit within the edge cap.

    Ranks retained nodes by (bipartite_degree, total_weight) descending, then
    binary-searches for the smallest K where estimated pairs <= cap.

    Returns:
        Tuple of (rebuilt inverted index, K kept).
    """
    # Rank retained nodes by bipartite degree and total weight
    retained_degree: dict[str, int] = defaultdict(int)
    retained_total_weight: dict[str, int] = defaultdict(int)
    for retained, neighbors in bipartite_edges.items():
        retained_degree[retained] = len(neighbors)
        retained_total_weight[retained] = sum(neighbors.values())

    ranked = sorted(
        retained_degree.keys(),
        key=lambda r: (retained_degree[r], retained_total_weight[r]),
        reverse=True,
    )

    # Binary search for the largest K where estimated pairs <= cap.
    # More K → more pairs (monotonically increasing), so find the rightmost
    # K where the estimate fits.
    lo, hi = 10, len(ranked)
    while lo < hi:
        mid = (lo + hi + 1) // 2  # round up to avoid infinite loop
        keep = set(ranked[:mid])
        est = _estimate_projected_pairs(inverted, keep)
        if est <= max_projected_edges:
            lo = mid  # this K fits, try keeping more
        else:
            hi = mid - 1  # too many pairs, try fewer nodes

    keep = set(ranked[:lo])

    # Rebuild inverted index with only kept retained nodes
    reduced_inverted: dict[str, dict[str, int]] = {}
    for collapsed_node, retained_nodes in inverted.items():
        filtered = {r: w for r, w in retained_nodes.items() if r in keep}
        if len(filtered) >= 2:
            reduced_inverted[collapsed_node] = filtered

    return reduced_inverted, lo


def _project_edges(
    inverted: dict[str, dict[str, int]],
    max_edges: int,
) -> tuple[dict[tuple[str, str], int], bool]:
    """Run the O(N²) projection loop with a hard edge cap.

    Returns:
        Tuple of (projected_edges dict, capped bool).
    """
    projected_edges: dict[tuple[str, str], int] = {}
    capped = False

    for _collapsed_node, retained_nodes in inverted.items():
        retained_list = list(retained_nodes.keys())
        n = len(retained_list)
        for i in range(n):
            for j in range(i + 1, n):
                a, b = retained_list[i], retained_list[j]
                key = (min(a, b), max(a, b))
                w = min(retained_nodes[a], retained_nodes[b])
                if key in projected_edges:
                    projected_edges[key] += w
                else:
                    projected_edges[key] = w
                    if len(projected_edges) >= max_edges:
                        capped = True
                        return projected_edges, capped

    return projected_edges, capped


def extract_giant_component(graph: dict) -> dict:
    """Extract the largest connected component using BFS.

    Args:
        graph: Graph dict with nodes and edges.

    Returns:
        Graph dict containing only nodes and edges in the giant component.
    """
    if not graph["nodes"]:
        return graph

    # Build adjacency list
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in graph["edges"]:
        adjacency[edge["source"]].add(edge["target"])
        adjacency[edge["target"]].add(edge["source"])

    # Also add isolated nodes
    all_node_ids = {n["id"] for n in graph["nodes"]}

    # BFS to find connected components
    visited: set[str] = set()
    components: list[set[str]] = []

    for node_id in all_node_ids:
        if node_id in visited:
            continue
        component: set[str] = set()
        queue: deque[str] = deque([node_id])
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            component.add(current)
            for neighbor in adjacency.get(current, set()):
                if neighbor not in visited:
                    queue.append(neighbor)
        components.append(component)

    if not components:
        return graph

    # Find largest component
    giant = max(components, key=len)

    # Filter nodes and edges
    filtered_nodes = [n for n in graph["nodes"] if n["id"] in giant]
    filtered_edges = [
        e for e in graph["edges"]
        if e["source"] in giant and e["target"] in giant
    ]

    return {"nodes": filtered_nodes, "edges": filtered_edges}


def enforce_network_limits(
    graph: dict,
    max_nodes: int = MAX_NODES,
    max_edges: int = MAX_EDGES,
) -> dict:
    """Enforce size limits on a network graph.

    Strategy:
    1. If within limits, return unchanged.
    2. Remove all nodes with degree < 2 (and their edges).
    3. If still over limits, apply disparity filter backboning with
       progressively stricter alpha until the graph fits.

    Args:
        graph: Graph dict with ``nodes`` and ``edges`` lists.
        max_nodes: Maximum number of nodes allowed.
        max_edges: Maximum number of edges allowed.

    Returns:
        Graph dict within the specified limits, with an added
        ``"reduced"`` key describing any filtering that was applied.
    """
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    if len(nodes) <= max_nodes and len(edges) <= max_edges:
        return graph

    original_node_count = len(nodes)
    original_edge_count = len(edges)
    reduction_steps: list[str] = []

    # --- Step 1: remove nodes with degree < 2 ---
    degree: dict[str, int] = defaultdict(int)
    for e in edges:
        degree[e["source"]] += 1
        degree[e["target"]] += 1

    high_degree_ids = {nid for nid, d in degree.items() if d >= 2}

    if len(high_degree_ids) < len(nodes):
        nodes = [n for n in nodes if n["id"] in high_degree_ids]
        edges = [
            e for e in edges
            if e["source"] in high_degree_ids and e["target"] in high_degree_ids
        ]
        reduction_steps.append(
            f"Removed degree<2 nodes: {original_node_count} -> {len(nodes)} nodes, "
            f"{original_edge_count} -> {len(edges)} edges"
        )

    # --- Step 2: disparity filter backboning if still over limits ---
    if len(nodes) > max_nodes or len(edges) > max_edges:
        # Try progressively stricter alpha values
        for alpha in [0.4, 0.2, 0.1, 0.05, 0.02, 0.01, 0.005, 0.001]:
            candidate = _apply_disparity_backbone(
                {"nodes": nodes, "edges": edges}, alpha
            )
            c_nodes = candidate["nodes"]
            c_edges = candidate["edges"]
            if len(c_nodes) <= max_nodes and len(c_edges) <= max_edges:
                nodes = c_nodes
                edges = c_edges
                reduction_steps.append(
                    f"Disparity backbone (alpha={alpha}): "
                    f"{len(nodes)} nodes, {len(edges)} edges"
                )
                break
        else:
            # If even the strictest alpha isn't enough, take top edges by weight
            nodes = candidate["nodes"]
            edges = candidate["edges"]
            if len(edges) > max_edges:
                edges = sorted(edges, key=lambda e: e["weight"], reverse=True)[:max_edges]
                connected_ids = set()
                for e in edges:
                    connected_ids.add(e["source"])
                    connected_ids.add(e["target"])
                nodes = [n for n in nodes if n["id"] in connected_ids]
            if len(nodes) > max_nodes:
                # Keep top nodes by degree in remaining edges
                deg: dict[str, int] = defaultdict(int)
                for e in edges:
                    deg[e["source"]] += 1
                    deg[e["target"]] += 1
                top_ids = {
                    nid
                    for nid, _ in sorted(deg.items(), key=lambda x: x[1], reverse=True)[
                        :max_nodes
                    ]
                }
                nodes = [n for n in nodes if n["id"] in top_ids]
                edges = [
                    e for e in edges
                    if e["source"] in top_ids and e["target"] in top_ids
                ]
            reduction_steps.append(
                f"Hard truncation: {len(nodes)} nodes, {len(edges)} edges"
            )

    logger.info(
        "network_limits_enforced",
        original_nodes=original_node_count,
        original_edges=original_edge_count,
        final_nodes=len(nodes),
        final_edges=len(edges),
        steps=reduction_steps,
    )

    result = {"nodes": nodes, "edges": edges}
    result["reduced"] = {
        "original_nodes": original_node_count,
        "original_edges": original_edge_count,
        "steps": reduction_steps,
    }
    return result


def _apply_disparity_backbone(graph: dict, alpha: float) -> dict:
    """Apply disparity filter (Serrano et al. 2009) to a graph dict.

    For each node *i* with degree *k* and strength (weight sum) *s*:
        p_ij = w_ij / s_i
        disparity_ij = (1 - p_ij)^(k - 1)

    An edge is kept if it is significant from *either* endpoint:
        min(disparity_ij, disparity_ji) < alpha

    After filtering edges, isolated nodes are removed.

    Args:
        graph: Graph dict with ``nodes`` and ``edges``.
        alpha: Significance threshold — lower keeps fewer edges.

    Returns:
        Filtered graph dict.
    """
    edges = graph["edges"]
    nodes_by_id = {n["id"]: n for n in graph["nodes"]}

    # Calculate node strength (sum of incident edge weights) and degree
    strength: dict[str, float] = defaultdict(float)
    degree: dict[str, int] = defaultdict(int)
    for e in edges:
        w = e["weight"]
        strength[e["source"]] += w
        strength[e["target"]] += w
        degree[e["source"]] += 1
        degree[e["target"]] += 1

    kept_edges: list[dict] = []
    for e in edges:
        src, tgt, w = e["source"], e["target"], e["weight"]

        # Compute disparity score from source side
        k_src = degree[src]
        s_src = strength[src]
        if k_src > 1 and s_src > 0:
            p_src = w / s_src
            d_src = _safe_power(1.0 - p_src, k_src - 1)
        else:
            d_src = 1.0

        # Compute disparity score from target side
        k_tgt = degree[tgt]
        s_tgt = strength[tgt]
        if k_tgt > 1 and s_tgt > 0:
            p_tgt = w / s_tgt
            d_tgt = _safe_power(1.0 - p_tgt, k_tgt - 1)
        else:
            d_tgt = 1.0

        # Keep if significant from either direction
        if min(d_src, d_tgt) < alpha:
            kept_edges.append(e)

    # Collect surviving node ids
    surviving_ids: set[str] = set()
    for e in kept_edges:
        surviving_ids.add(e["source"])
        surviving_ids.add(e["target"])

    kept_nodes = [nodes_by_id[nid] for nid in surviving_ids if nid in nodes_by_id]

    return {"nodes": kept_nodes, "edges": kept_edges}


def _safe_power(base: float, exponent: float) -> float:
    """Numerically stable (1 - p)^(k-1) for the disparity filter."""
    if base <= 0.0:
        return 0.0
    if base >= 1.0:
        return 1.0
    if exponent <= 0:
        return 1.0
    try:
        log_result = exponent * math.log(base)
        if log_result < -700:
            return 0.0
        return math.exp(log_result)
    except (OverflowError, ValueError):
        return 0.0
