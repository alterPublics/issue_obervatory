"""Shared boolean query building utilities for arena collectors.

Terms within a QueryDesign can be grouped for boolean AND/OR logic:

- Terms sharing the same ``group_id`` are ANDed together (they form one group).
- Different groups are ORed against each other.
- Terms with ``group_id=None`` are treated as individual single-term OR groups.

This module provides two public helpers:

``build_boolean_query_groups``
    Converts a list of ``SearchTerm``-like dicts (with ``"term"`` and
    ``"group_id"`` keys) into a ``list[list[str]]`` where each inner list
    is one AND-group that will be ORed with the others.

``format_boolean_query_for_platform``
    Serialises the group structure into a platform-native query string.
    For platforms that have no native boolean support the groups should be
    queried separately and their results combined; this function is only
    needed for the platforms that *do* support native boolean syntax.

Calling convention note
-----------------------
``ArenaCollector.collect_by_terms()`` receives plain ``list[str]`` terms.
To transport boolean group information the callers (Celery tasks / API
endpoints) pass an extra ``term_groups: list[list[str]] | None`` keyword
argument.  When ``term_groups`` is not ``None`` the collector uses those
groups directly and ignores the flat ``terms`` list (which acts as a
compatibility fallback for callers that have not been updated yet).
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Public type aliases
# ---------------------------------------------------------------------------

# A "term group spec" is the minimal dict needed to carry grouping metadata.
# Arena tasks build these from SearchTerm ORM rows, then pass them to
# build_boolean_query_groups().
TermSpec = dict[str, Any]  # {"term": str, "group_id": uuid.UUID | str | None}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def build_boolean_query_groups(
    term_specs: list[TermSpec],
    target_language: str | None = None,
) -> list[list[str]]:
    """Group term dicts into AND/OR groups, applying translations when available.

    Each term dict must have at minimum a ``"term"`` key (str) and a
    ``"group_id"`` key (``uuid.UUID | str | None``).  Optionally a
    ``"translations"`` key (dict mapping ISO 639-1 codes to translated terms)
    may be present.

    Terms that share the same ``group_id`` are placed into the same AND-group.
    Terms with ``group_id=None`` each form their own single-item group (treated
    as independent OR terms, consistent with the SearchTerm schema design).

    When ``target_language`` is provided and a term has a translation for that
    language, the translated term is used instead of the primary term (IP2-052).

    Args:
        term_specs: List of dicts with ``"term"``, ``"group_id"``, and
            optionally ``"translations"`` keys.
        target_language: Optional ISO 639-1 language code (e.g. ``"kl"``, ``"en"``).
            When provided, translated terms are used where available.

    Returns:
        A list of groups.  Each group is a list of term strings to be ANDed.
        The groups themselves are ORed.  Empty input returns an empty list.

    Example::

        specs = [
            {
                "term": "klimaforandringer",
                "group_id": "g1",
                "translations": {"kl": "klima-aasakkanik", "en": "climate change"}
            },
            {"term": "IPCC", "group_id": "g1"},
            {"term": "folketing", "group_id": None},
        ]
        groups = build_boolean_query_groups(specs, target_language="kl")
        # → [["klima-aasakkanik", "IPCC"], ["folketing"]]
    """
    if not term_specs:
        return []

    # Preserve insertion order so that groups are processed deterministically.
    grouped: OrderedDict[str, list[str]] = OrderedDict()
    null_counter = 0

    for spec in term_specs:
        # Resolve the term text (with translation if available).
        term: str = resolve_term_translation(spec, target_language).strip()
        if not term:
            continue

        raw_group_id = spec.get("group_id")

        if raw_group_id is None:
            # Each ungrouped term becomes its own synthetic group key so it
            # stays independent.
            key = f"__null_{null_counter}__"
            null_counter += 1
            grouped[key] = [term]
        else:
            # Normalise to string so UUID objects and string UUIDs both match.
            key = str(raw_group_id)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(term)

    return list(grouped.values())


def format_boolean_query_for_platform(
    groups: list[list[str]],
    platform: str,
) -> str:
    """Format boolean groups into a platform-native query string.

    Only use this function for arenas that have *native* boolean query support.
    For arenas without native support, iterate over groups and issue one
    request per group, then combine the results.

    Platform-specific syntax:

    - ``"generic"`` — ``(term1 AND term2) OR (term3 AND term4)``
    - ``"google"`` — ``(term1 term2) OR (term3 term4)``  [implicit AND]
    - ``"bluesky"`` — ``term1 term2 OR term3 term4``  [space = AND; multi-group
      not natively supported, each group becomes a separate request]
    - ``"reddit"`` — ``title:term1+term2 OR title:term3+term4``
    - ``"youtube"`` — ``term1 term2|term3 term4``  [``|`` = OR, space = AND]
    - ``"gdelt"`` — ``(term1 AND term2) OR (term3 AND term4)``
    - ``"twitter"`` / ``"x_twitter"`` — ``(term1 term2) OR (term3 term4)``
    - ``"event_registry"`` — returns the first group's AND string only; the
      caller must use the ``$query`` structure for full boolean logic.

    For a single-term group no parentheses are added.

    Args:
        groups: Output of :func:`build_boolean_query_groups`.
        platform: Lower-case platform identifier string.

    Returns:
        A query string ready for the platform's search parameter.  Returns
        ``""`` for an empty groups list.
    """
    if not groups:
        return ""

    platform_lower = platform.lower()

    # Flatten single-group, single-term case — no operators needed.
    if len(groups) == 1 and len(groups[0]) == 1:
        return groups[0][0]

    if platform_lower == "google":
        return _format_google(groups)
    if platform_lower in ("twitter", "x_twitter"):
        return _format_twitter(groups)
    if platform_lower == "reddit":
        return _format_reddit(groups)
    if platform_lower == "youtube":
        return _format_youtube(groups)
    if platform_lower == "gdelt":
        return _format_gdelt(groups)
    if platform_lower == "bluesky":
        return _format_bluesky(groups)
    # Fallback: generic boolean with explicit AND/OR
    return _format_generic(groups)


# ---------------------------------------------------------------------------
# Private per-platform formatters
# ---------------------------------------------------------------------------


def _format_generic(groups: list[list[str]]) -> str:
    """Format groups as ``(term1 AND term2) OR (term3 AND term4)``."""
    parts: list[str] = []
    for grp in groups:
        if len(grp) == 1:
            parts.append(grp[0])
        else:
            parts.append("(" + " AND ".join(grp) + ")")
    return " OR ".join(parts)


def _format_google(groups: list[list[str]]) -> str:
    """Format groups for Google (implicit AND via space, OR via ``OR``)."""
    parts: list[str] = []
    for grp in groups:
        if len(grp) == 1:
            parts.append(grp[0])
        else:
            # Parenthesise multi-term groups; space implies AND.
            parts.append("(" + " ".join(grp) + ")")
    return " OR ".join(parts)


def _format_twitter(groups: list[list[str]]) -> str:
    """Format groups for Twitter/X (space = AND, ``OR`` = OR)."""
    parts: list[str] = []
    for grp in groups:
        if len(grp) == 1:
            parts.append(grp[0])
        else:
            parts.append("(" + " ".join(grp) + ")")
    return " OR ".join(parts)


def _format_reddit(groups: list[list[str]]) -> str:
    """Format groups for asyncpraw search (``+`` = AND, space-separated OR).

    Reddit's Lucene query parser uses ``+`` to join AND terms.
    """
    parts: list[str] = []
    for grp in groups:
        if len(grp) == 1:
            parts.append(grp[0])
        else:
            parts.append("+".join(grp))
    return " OR ".join(parts)


def _format_youtube(groups: list[list[str]]) -> str:
    """Format groups for YouTube Data API (space = AND, ``|`` = OR).

    YouTube treats space as AND and pipe as OR in the ``q`` parameter.
    For AND-groups we join with space; groups are joined with ``|``.
    """
    parts: list[str] = []
    for grp in groups:
        if len(grp) == 1:
            parts.append(grp[0])
        else:
            parts.append(" ".join(grp))
    return "|".join(parts)


def _format_gdelt(groups: list[list[str]]) -> str:
    """Format groups for GDELT (explicit ``AND``/``OR`` keywords)."""
    return _format_generic(groups)


def _format_bluesky(groups: list[list[str]]) -> str:
    """Format a single Bluesky AND-group (space = AND).

    The Bluesky search API treats space-separated terms as AND.  Full OR
    across multiple groups requires separate API calls; this function returns
    only the first group's query string.  Callers should iterate over groups
    and merge results when handling boolean Bluesky queries.

    Args:
        groups: All boolean groups; only the first is used.

    Returns:
        Space-joined terms from ``groups[0]``, or ``""`` if groups is empty.
    """
    if not groups:
        return ""
    return " ".join(groups[0])


# ---------------------------------------------------------------------------
# Convenience helper used by arena tasks
# ---------------------------------------------------------------------------


def has_boolean_groups(term_specs: list[TermSpec]) -> bool:
    """Return True if any term has a non-None group_id.

    Args:
        term_specs: List of term dicts with ``"group_id"`` keys.

    Returns:
        ``True`` when at least one term belongs to a named group.
    """
    return any(spec.get("group_id") is not None for spec in term_specs)


# ---------------------------------------------------------------------------
# Translation support (IP2-052)
# ---------------------------------------------------------------------------


def resolve_term_translation(
    term_spec: TermSpec,
    target_language: str | None = None,
) -> str:
    """Resolve the appropriate term text based on the target language.

    When ``target_language`` is provided and the term has a translation for
    that language, returns the translated term.  Otherwise returns the
    primary ``term`` value.

    Args:
        term_spec: Term dict with at minimum ``"term"`` and ``"translations"``
            keys.  ``translations`` should be a dict mapping ISO 639-1 codes
            to translated term strings, or ``None``.
        target_language: ISO 639-1 language code (e.g. ``"kl"``, ``"en"``).
            When ``None`` or ``"da"``, always returns the primary term.

    Returns:
        The resolved term text (translated if available, primary otherwise).

    Example::

        term_spec = {
            "term": "CO2 afgift",
            "translations": {"kl": "CO2-akilerisitsinnaanera", "en": "CO2 tax"}
        }
        resolve_term_translation(term_spec, "kl")
        # → "CO2-akilerisitsinnaanera"
        resolve_term_translation(term_spec, "en")
        # → "CO2 tax"
        resolve_term_translation(term_spec, "da")
        # → "CO2 afgift"
    """
    primary_term: str = term_spec.get("term", "")
    if not primary_term:
        return ""

    # Default or Danish: always use the primary term.
    if not target_language or target_language.lower() == "da":
        return primary_term

    # Check for translation.
    translations = term_spec.get("translations")
    if translations and isinstance(translations, dict):
        translated = translations.get(target_language.lower())
        if translated:
            return translated

    # No translation found; fall back to the primary term.
    return primary_term
