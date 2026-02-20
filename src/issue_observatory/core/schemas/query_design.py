"""Pydantic request/response schemas for query designs and search terms.

These schemas are used by the query-designs API routes for validation,
serialisation, and OpenAPI documentation generation.  They are kept
separate from the SQLAlchemy ORM models in ``core/models/query_design.py``
to avoid coupling transport concerns to persistence concerns.

Multilingual support (IP2-052)
-------------------------------
The ``language`` field on :class:`QueryDesignCreate` and
:class:`QueryDesignUpdate` accepts either a single ISO 639-1 code (``"da"``)
or a comma-separated list of codes (``"da,en"``).  The stored string is
normalised (whitespace stripped, lower-cased, deduped) before persistence.
Use :func:`parse_language_codes` to convert the stored string back to a list
of codes at the point of dispatch.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Language-code utilities (IP2-052)
# ---------------------------------------------------------------------------

#: Regex that a single ISO 639-1 language code must match.
_LANG_CODE_RE = re.compile(r"^[a-zA-Z]{2,3}$")


def parse_language_codes(language: str) -> list[str]:
    """Parse a comma-separated language string into a deduplicated list.

    Accepts a single code (``"da"``) or a comma-separated string
    (``"da,en"``).  Strips whitespace, lowercases, and deduplicates while
    preserving insertion order.

    Args:
        language: The stored ``QueryDesign.language`` value.

    Returns:
        List of normalised ISO 639-1 codes, e.g. ``["da", "en"]``.

    Examples::

        >>> parse_language_codes("da")
        ['da']
        >>> parse_language_codes("da, EN, da")
        ['da', 'en']
    """
    codes: list[str] = []
    seen: set[str] = set()
    for part in language.split(","):
        code = part.strip().lower()
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    return codes or ["da"]


def _normalise_language(value: str) -> str:
    """Normalise a comma-separated language string for storage.

    Strips whitespace, lowercases each code, deduplicates, and re-joins
    with ``","`` (no spaces).

    Args:
        value: Raw language string from the request body.

    Returns:
        Normalised language string.

    Raises:
        ValueError: If any code segment does not match ``[a-zA-Z]{2,3}``.
    """
    parts = [p.strip().lower() for p in value.split(",") if p.strip()]
    if not parts:
        return "da"
    for code in parts:
        if not _LANG_CODE_RE.match(code):
            raise ValueError(
                f"Invalid language code: {code!r}. "
                "Each code must be a 2-3 letter ISO 639-1/639-2 code."
            )
    # Deduplicate preserving order.
    seen: set[str] = set()
    normalised: list[str] = []
    for code in parts:
        if code not in seen:
            seen.add(code)
            normalised.append(code)
    return ",".join(normalised)


class SearchTermCreate(BaseModel):
    """Payload for adding a new search term to a query design.

    Attributes:
        term: The search term string (keyword, phrase, hashtag, or URL pattern).
        term_type: How arena collectors should interpret this term.
            One of ``'keyword'``, ``'phrase'``, ``'hashtag'``, ``'url_pattern'``.
        group_id: Optional UUID that groups related terms together.  All terms
            sharing the same ``group_id`` are displayed as one named group in
            the editor.  ``None`` means the term is ungrouped.
        group_label: Human-readable display name for the group (max 200 chars).
            Should be identical for all terms with the same ``group_id``.
            Ignored when ``group_id`` is ``None``.
        target_arenas: Optional list of arena platform_names (e.g. ``["reddit", "youtube"]``)
            to which this term should be dispatched. ``None`` means all enabled arenas.
    """

    term: str = Field(..., min_length=1, description="The search term string.")
    term_type: str = Field(
        default="keyword",
        description="Interpretation type: keyword, phrase, hashtag, url_pattern.",
    )
    group_id: Optional[uuid.UUID] = Field(
        default=None,
        description="UUID grouping this term with others in the same named group.",
    )
    group_label: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Display name for the group (e.g. 'Primary terms').",
    )
    target_arenas: Optional[list[str]] = Field(
        default=None,
        description=(
            "Optional list of arena platform_names to which this term applies. "
            "NULL or empty list means all enabled arenas."
        ),
    )
    translations: Optional[dict[str, str]] = Field(
        default=None,
        description=(
            "Optional dict mapping ISO 639-1 language codes to translated terms. "
            "Example: {'kl': 'CO2-akilerisitsinnaanera', 'en': 'CO2 tax'}. "
            "NULL means no translations available (use the primary term)."
        ),
    )


class SearchTermRead(SearchTermCreate):
    """Full representation of a persisted search term.

    Extends ``SearchTermCreate`` with database-generated fields.

    Attributes:
        id: Unique identifier of the search term.
        query_design_id: Parent query design UUID.
        is_active: Whether the term is currently active.
        added_at: Timestamp when the term was added.
    """

    id: uuid.UUID
    query_design_id: uuid.UUID
    is_active: bool
    added_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QueryDesignCreate(BaseModel):
    """Payload for creating a new query design.

    Attributes:
        name: Human-readable name for this research design (max 200 chars).
        description: Optional free-text description of the research purpose.
        visibility: Access control level — ``'private'``, ``'team'``, or ``'public'``.
        default_tier: Default collection tier — ``'free'``, ``'medium'``, or ``'premium'``.
        language: ISO 639-1 language code(s) for locale-aware arena filters.
            Accepts a single code (``'da'``) or a comma-separated list
            (``'da,en'``).  Each code is validated as 2–3 alphabetic characters.
        locale_country: ISO 3166-1 alpha-2 country code for geo filters (e.g. ``'dk'``).
        search_terms: Initial list of search terms to attach on creation.
    """

    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    visibility: str = Field(default="private", pattern="^(private|team|public)$")
    default_tier: str = Field(default="free", pattern="^(free|medium|premium)$")
    language: str = Field(
        default="da",
        max_length=10,
        description=(
            "ISO 639-1 language code or comma-separated codes (e.g. 'da' or 'da,en'). "
            "Limited to 10 characters to match the database column size."
        ),
    )
    locale_country: str = Field(default="dk", max_length=5)
    search_terms: list[SearchTermCreate] = Field(default_factory=list)

    @field_validator("language")
    @classmethod
    def normalise_language(cls, v: str) -> str:
        """Normalise and validate comma-separated language codes.

        Args:
            v: Raw language field value from the request body.

        Returns:
            Normalised comma-separated language string (e.g. ``"da,en"``).

        Raises:
            ValueError: If any code segment is not a valid 2–3 letter code.
        """
        return _normalise_language(v)


class QueryDesignRead(BaseModel):
    """Full representation of a persisted query design.

    Returned by detail and list endpoints.  ``search_terms`` is populated
    on detail fetches where the relationship is eagerly loaded.

    Attributes:
        id: Unique identifier of the query design.
        owner_id: UUID of the user who owns this design.
        name: Human-readable name.
        description: Optional research purpose description.
        visibility: Access control level.
        created_at: Timestamp of initial creation.
        updated_at: Timestamp of last modification.
        is_active: Whether the design is active (soft-delete flag).
        default_tier: Default collection tier.
        language: ISO 639-1 language code.
        locale_country: ISO 3166-1 alpha-2 country code.
        search_terms: Attached search terms (may be empty on list views).
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: Optional[str]
    visibility: str
    created_at: datetime
    updated_at: datetime
    is_active: bool
    default_tier: str
    language: str
    locale_country: str
    search_terms: list[SearchTermRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class QueryDesignUpdate(BaseModel):
    """Partial update payload for a query design.

    All fields are optional; only provided fields are applied.  Send an
    empty body to perform a no-op update (useful for testing ownership).

    Attributes:
        name: New name (max 200 chars).
        description: New description (pass ``null`` to clear).
        visibility: New visibility level.
        default_tier: New default tier.
        language: New language code(s).  Accepts a single code (``'da'``)
            or a comma-separated list (``'da,en'``).
        is_active: Set to ``false`` to soft-delete.
    """

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    visibility: Optional[str] = Field(default=None, pattern="^(private|team|public)$")
    default_tier: Optional[str] = Field(
        default=None, pattern="^(free|medium|premium)$"
    )
    language: Optional[str] = Field(
        default=None,
        max_length=10,
        description=(
            "ISO 639-1 language code or comma-separated codes (e.g. 'da' or 'da,en'). "
            "Limited to 10 characters to match the database column size."
        ),
    )
    is_active: Optional[bool] = None

    @field_validator("language")
    @classmethod
    def normalise_language(cls, v: str | None) -> str | None:
        """Normalise and validate comma-separated language codes.

        Args:
            v: Raw language field value, or ``None`` if not updating language.

        Returns:
            Normalised comma-separated language string, or ``None``.

        Raises:
            ValueError: If any code segment is not a valid 2–3 letter code.
        """
        if v is None:
            return None
        return _normalise_language(v)
