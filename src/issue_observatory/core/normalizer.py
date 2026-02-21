"""Normalizer pipeline: raw platform data -> universal content records.

The ``Normalizer`` class maps platform-specific data dicts to the universal
``content_records`` schema defined in the database. It handles missing fields
gracefully, computes a SHA-256 ``content_hash`` for deduplication, and
pseudonymizes author identifiers.

The pseudonymization salt is loaded from the ``PSEUDONYMIZATION_SALT``
environment variable (via ``Settings``). **Never** compute
``pseudonymized_author_id`` using a hard-coded salt — the salt must be a
secret so that re-identification requires knowledge of both the data and the
application secret.

Example usage::

    from issue_observatory.core.normalizer import Normalizer

    normalizer = Normalizer()
    record = normalizer.normalize(
        raw_item={"id": "abc123", "text": "Hello world"},
        platform="bluesky",
        arena="social_media",
    )
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from issue_observatory.core.deduplication import compute_simhash

logger = logging.getLogger(__name__)

# Fields that every normalized record must contain.  Optional fields are
# included with a ``None`` value when the platform does not provide them.
_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "platform",
        "arena",
        "content_type",
        "collected_at",
        "collection_tier",
    }
)

# Platform-specific engagement normalization configuration (IP2-030).
# Each platform defines: weights for engagement metrics, and a scale_factor
# to map typical content to 30-50 range after log-scaling.
_ENGAGEMENT_WEIGHTS: dict[str, dict[str, float]] = {
    "reddit": {
        "likes": 1.0,
        "comments": 2.0,
        "scale_factor": 8.0,
    },
    "youtube": {
        "views": 0.001,
        "likes": 0.1,
        "comments": 1.0,
        "scale_factor": 6.0,
    },
    "bluesky": {
        "likes": 1.0,
        "shares": 2.0,
        "comments": 1.0,
        "scale_factor": 8.0,
    },
    "x_twitter": {
        "likes": 0.5,
        "shares": 2.0,
        "comments": 1.0,
        "scale_factor": 7.0,
    },
    "facebook": {
        "likes": 1.0,
        "shares": 3.0,
        "comments": 2.0,
        "scale_factor": 7.0,
    },
    "instagram": {
        "likes": 0.5,
        "comments": 2.0,
        "scale_factor": 7.0,
    },
    "tiktok": {
        "views": 0.001,
        "likes": 0.1,
        "shares": 1.0,
        "comments": 1.0,
        "scale_factor": 5.0,
    },
    # Default weights for platforms not explicitly configured
    "_default": {
        "likes": 1.0,
        "shares": 2.0,
        "comments": 1.0,
        "scale_factor": 8.0,
    },
}


class Normalizer:
    """Maps raw platform data dicts to the universal content record schema.

    The normalizer is stateless apart from the pseudonymization salt, which
    is loaded once from ``Settings`` on construction. A single instance can
    be shared across threads/tasks.

    Args:
        pseudonymization_salt: Secret salt for SHA-256 author hashing.
            If ``None``, the salt is read from
            ``Settings().pseudonymization_salt``.

    Raises:
        NormalizationError: When the pseudonymization salt is empty or
            missing. This is a GDPR hard requirement — collection cannot
            proceed without a valid salt. Always configure
            ``PSEUDONYMIZATION_SALT`` in production.
    """

    def __init__(self, pseudonymization_salt: str | None = None) -> None:
        if pseudonymization_salt is not None:
            self._salt = pseudonymization_salt
        else:
            # Prefer the Settings class; fall back to direct env-var read so
            # that the normalizer can be constructed outside a fully configured
            # application (e.g. unit tests that set only this env var).
            import os  # noqa: PLC0415

            from issue_observatory.config.danish_defaults import (  # noqa: PLC0415
                PSEUDONYMIZATION_SALT_ENV_VAR,
            )

            try:
                from issue_observatory.config.settings import get_settings  # noqa: PLC0415

                settings = get_settings()
                salt = settings.pseudonymization_salt
                # Support both plain str and SecretStr (settings may evolve).
                self._salt = (
                    salt.get_secret_value() if hasattr(salt, "get_secret_value") else str(salt)
                )
            except Exception:
                self._salt = os.environ.get(PSEUDONYMIZATION_SALT_ENV_VAR, "")

        # BB-01: GDPR compliance requires a valid pseudonymization salt.
        # Collection must not proceed without it. Raise an error rather than
        # silently degrading to None pseudonymized_author_id values.
        if not self._salt:
            from issue_observatory.core.exceptions import NormalizationError  # noqa: PLC0415

            logger.critical(
                "PSEUDONYMIZATION_SALT is empty or missing. "
                "Data collection cannot proceed without a valid salt. "
                "Set the %s environment variable.",
                "PSEUDONYMIZATION_SALT",
            )
            raise NormalizationError(
                "PSEUDONYMIZATION_SALT is required for GDPR-compliant data collection. "
                "Set the PSEUDONYMIZATION_SALT environment variable before starting the application."
            )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def normalize(
        self,
        raw_item: dict[str, Any],
        platform: str,
        arena: str,
        collection_tier: str = "free",
        collection_run_id: str | None = None,
        query_design_id: str | None = None,
        search_terms_matched: list[str] | None = None,
        is_public_figure: bool = False,
        platform_username: str | None = None,
        public_figure_ids: set[str] | None = None,
        skip_pseudonymization: bool = False,
    ) -> dict[str, Any]:
        """Map a raw platform record to the universal ``content_records`` schema.

        All fields from the raw item are preserved in ``raw_metadata`` so
        that no upstream information is lost. Fields not provided by the
        platform are set to ``None`` rather than being omitted, ensuring
        downstream code can always rely on key presence.

        Author identifiers are pseudonymized via SHA-256 before storage.
        When ``is_public_figure`` is ``True`` (GR-14), or when
        ``public_figure_ids`` is supplied and the record's
        ``author_platform_id`` is a member of that set, the plain
        ``platform_username`` (or ``author_platform_id`` as fallback) is
        stored instead of the hash.  An audit note is added to
        ``raw_metadata`` in both cases.

        When ``skip_pseudonymization`` is ``True``, author identifiers
        are stored in plain text for all records regardless of public
        figure status.  The researcher assumes full GDPR responsibility.
        An audit note is added to ``raw_metadata``.

        The ``content_hash`` is computed from the normalized text content for
        cross-platform deduplication.

        Args:
            raw_item: Raw dict as returned by the upstream API / collector.
            platform: Platform identifier (e.g. ``"bluesky"``, ``"reddit"``).
                Stored in the ``platform`` column.
            arena: Logical arena group (e.g. ``"social_media"``). Stored in
                the ``arena`` column.
            collection_tier: Tier used for this collection
                (``"free"`` | ``"medium"`` | ``"premium"``).
            collection_run_id: UUID string of the owning collection run.
            query_design_id: UUID string of the owning query design.
            search_terms_matched: Query terms that matched this record.
            is_public_figure: When ``True``, bypass SHA-256 pseudonymization
                for this record (GR-14 — GDPR Art. 89(1) research exemption).
                The plain ``platform_username`` is stored as
                ``pseudonymized_author_id`` instead of the hash.  Defaults to
                ``False`` — existing callers are unaffected.
            skip_pseudonymization: When ``True``, store plain author
                identifiers for all records.  Pseudonymization is on by
                default; the researcher opts out explicitly.  Defaults
                to ``False``.
            platform_username: Plain-text platform handle to use as the
                ``pseudonymized_author_id`` when ``is_public_figure=True``.
                If not supplied, ``author_platform_id`` is used as fallback.
                Ignored when ``is_public_figure=False``.
            public_figure_ids: Optional pre-built set of platform user IDs
                known to be public figures.  When provided, the normalizer
                automatically sets ``is_public_figure=True`` for any record
                whose ``author_platform_id`` appears in this set, without
                requiring the caller to perform a per-record lookup.
                Takes precedence over the ``is_public_figure`` argument only
                when the author is found in the set; if the author is *not*
                in the set, the explicit ``is_public_figure`` argument still
                applies.

        Returns:
            Dict with all ``content_records`` columns populated. Optional
            fields are ``None`` when not provided.
        """
        collected_at = datetime.now(tz=timezone.utc).isoformat()

        # Attempt to extract common fields using well-known key names.
        platform_id = self._extract_str(raw_item, ["id", "post_id", "item_id", "url"])
        title = self._extract_str(raw_item, ["title", "headline", "subject"])
        text_content = self._extract_str(
            raw_item,
            ["text", "body", "content", "text_content", "description", "snippet"],
        )
        url = self._extract_str(raw_item, ["url", "link", "permalink", "canonical_url"])
        language = self._extract_str(raw_item, ["language", "lang", "locale"])
        content_type = self._extract_str(
            raw_item,
            ["content_type", "type", "kind"],
        ) or "post"

        # Publication timestamp
        published_at = self._extract_datetime(
            raw_item,
            ["published_at", "created_at", "timestamp", "date", "pub_date", "created_utc"],
        )

        # Author fields
        author_platform_id = self._extract_str(
            raw_item,
            [
                "author_id",
                "author_platform_id",
                "user_id",
                "from_id",
                "owner_id",
                "channel_id",
            ],
        )
        author_display_name = self._extract_str(
            raw_item,
            [
                "author",
                "author_name",
                "author_display_name",
                "username",
                "screen_name",
                "display_name",
                "from_name",
            ],
        )

        # GR-14: resolve whether this author is a known public figure.
        # The public_figure_ids set (built at run-dispatch time from the DB)
        # takes priority: if the author's platform_user_id appears in the set
        # we override is_public_figure to True regardless of the caller's
        # explicit argument.
        effective_is_public_figure = is_public_figure
        if (
            public_figure_ids is not None
            and author_platform_id is not None
            and author_platform_id in public_figure_ids
        ):
            effective_is_public_figure = True

        # When pseudonymization is explicitly skipped by the researcher,
        # treat every author as a public figure so plain IDs are stored.
        if skip_pseudonymization:
            effective_is_public_figure = True

        # Pseudonymize the author if we have an identifier.
        # For public figures (GR-14) the plain handle is stored instead.
        pseudonymized_author_id: str | None = None
        if author_platform_id:
            pseudonymized_author_id = self.pseudonymize_author(
                platform=platform,
                platform_user_id=author_platform_id,
                is_public_figure=effective_is_public_figure,
                platform_username=platform_username or author_display_name,
            )

        # Engagement metrics
        views_count = self._extract_int(raw_item, ["views", "view_count", "views_count"])
        likes_count = self._extract_int(
            raw_item, ["likes", "like_count", "likes_count", "score", "ups"]
        )
        shares_count = self._extract_int(
            raw_item,
            ["shares", "share_count", "shares_count", "retweets", "repost_count", "reposts"],
        )
        comments_count = self._extract_int(
            raw_item,
            ["comments", "comment_count", "comments_count", "num_comments", "reply_count"],
        )

        # Content hash for exact deduplication
        content_hash: str | None = None
        if text_content:
            content_hash = self.compute_content_hash(text_content)
        elif url:
            content_hash = self.compute_content_hash(url)

        # SimHash fingerprint for near-duplicate detection (Item 15).
        # Only computed when text_content is non-empty; URL-only records
        # and records without text content are left as NULL.
        simhash_value: int | None = None
        if text_content:
            simhash_value = compute_simhash(text_content)

        # Media URLs (list of strings)
        media_urls = self._extract_list(
            raw_item,
            ["media_urls", "media", "images", "attachments"],
        )

        # IP2-030: compute normalized engagement score if any metrics present.
        # However, if the collector has already set engagement_score (e.g. from
        # a relevance field in the API response), preserve it.
        normalized_engagement: float | None = raw_item.get("engagement_score")
        if normalized_engagement is None and any(
            [views_count, likes_count, shares_count, comments_count]
        ):
            normalized_engagement = self.compute_normalized_engagement(
                platform=platform,
                likes=likes_count,
                shares=shares_count,
                comments=comments_count,
                views=views_count,
            )

        # GR-14: Build the raw_metadata dict.  When the public-figure bypass
        # was applied, annotate the record so the DPO audit trail is complete.
        raw_metadata: dict[str, Any] = dict(raw_item)
        if skip_pseudonymization:
            raw_metadata["pseudonymization_disabled"] = True
            raw_metadata["bypass_reason"] = (
                "Pseudonymization disabled by researcher"
            )
        elif effective_is_public_figure:
            raw_metadata["public_figure_bypass"] = True
            raw_metadata["bypass_reason"] = (
                "Actor flagged as public figure per GDPR "
                "Art. 89(1) research exemption"
            )
            logger.debug(
                "normalizer: GR-14 bypass applied "
                "— author_platform_id=%s platform=%s",
                author_platform_id,
                platform,
            )

        return {
            # Core identifiers
            "platform": platform,
            "arena": arena,
            "platform_id": platform_id,
            "content_type": content_type,
            # Content
            "text_content": text_content,
            "title": title,
            "url": url,
            "language": language,
            # Timestamps
            "published_at": published_at,
            "collected_at": collected_at,
            # Author
            "author_platform_id": author_platform_id,
            "author_display_name": author_display_name,
            "author_id": None,  # resolved later by EntityResolver
            "pseudonymized_author_id": pseudonymized_author_id,
            # Engagement
            "views_count": views_count,
            "likes_count": likes_count,
            "shares_count": shares_count,
            "comments_count": comments_count,
            "engagement_score": normalized_engagement,  # IP2-030: normalized 0-100 score
            # Collection context
            "collection_run_id": collection_run_id,
            "query_design_id": query_design_id,
            "search_terms_matched": search_terms_matched or [],
            "collection_tier": collection_tier,
            # Platform-specific passthrough (with optional GR-14 audit annotation)
            "raw_metadata": raw_metadata,
            "media_urls": media_urls,
            # Deduplication
            "content_hash": content_hash,
            "simhash": simhash_value,
        }

    def pseudonymize_author(
        self,
        platform: str,
        platform_user_id: str,
        is_public_figure: bool = False,
        platform_username: str | None = None,
    ) -> str | None:
        """Compute a pseudonymized (or plain) author identifier.

        Default behaviour: returns ``SHA-256(platform + ":" +
        platform_user_id + ":" + salt)`` as mandated by the DPIA.  The colon
        separators prevent collisions between platform values with common
        prefixes.  The salt is the ``PSEUDONYMIZATION_SALT`` application
        secret.

        GR-14 bypass (``is_public_figure=True``): returns the plain
        ``platform_username`` so that content by publicly elected or
        appointed officials can be attributed by name.  Falls back to
        ``platform_user_id`` when ``platform_username`` is not supplied.
        This path bypasses the salt check — a plain identifier is always
        returned regardless of salt configuration.

        Returns ``None`` when ``is_public_figure=False`` and the salt is
        empty (misconfigured environment), to avoid storing insecure
        pseudo-IDs that could be trivially reversed.

        Args:
            platform: Platform identifier (e.g. ``"bluesky"``).
            platform_user_id: Native platform user ID (not the display name).
            is_public_figure: When ``True``, skip hashing and return the
                plain ``platform_username`` (or ``platform_user_id`` as
                fallback).  Defaults to ``False`` — existing callers are
                unaffected.
            platform_username: Plain-text handle to return when
                ``is_public_figure=True``.  Ignored when
                ``is_public_figure=False``.

        Returns:
            When ``is_public_figure=True``: plain ``platform_username`` or
            ``platform_user_id`` string.
            When ``is_public_figure=False`` and salt is configured:
            64-character lowercase hex SHA-256 digest.
            When ``is_public_figure=False`` and salt is empty: ``None``.
        """
        if is_public_figure:
            # GR-14: return raw handle so the actor can be attributed by name.
            return platform_username or platform_user_id
        if not self._salt:
            return None
        payload = f"{platform}:{platform_user_id}:{self._salt}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def compute_normalized_engagement(
        self,
        platform: str,
        likes: int | None = None,
        shares: int | None = None,
        comments: int | None = None,
        views: int | None = None,
    ) -> float:
        """Compute a cross-platform normalized engagement score (0-100).

        Uses platform-specific weights and log-scaling to produce a
        0-100 score where typical content scores 30-50 and viral content
        approaches 100.  The formula is:

            weighted_sum = (likes * w_likes) + (shares * w_shares) + …
            score = min(100, log1p(weighted_sum) * scale_factor)

        Platform weights are defined in ``_ENGAGEMENT_WEIGHTS``.  Platforms
        not explicitly configured use the ``_default`` weights.

        Args:
            platform: Platform identifier (e.g. ``"reddit"``, ``"youtube"``).
            likes: Raw like/upvote count.
            shares: Raw share/retweet/repost count.
            comments: Raw comment/reply count.
            views: Raw view count (only used by video platforms).

        Returns:
            Normalized engagement score on a 0-100 scale.  Returns 0.0 when
            all metrics are None or zero.

        Example:
            >>> normalizer = Normalizer()
            >>> normalizer.compute_normalized_engagement(
            ...     "reddit", likes=100, comments=25
            ... )
            42.5
        """
        weights = _ENGAGEMENT_WEIGHTS.get(platform, _ENGAGEMENT_WEIGHTS["_default"])
        weighted_sum = 0.0

        if likes is not None and likes > 0:
            weighted_sum += likes * weights.get("likes", 0.0)
        if shares is not None and shares > 0:
            weighted_sum += shares * weights.get("shares", 0.0)
        if comments is not None and comments > 0:
            weighted_sum += comments * weights.get("comments", 0.0)
        if views is not None and views > 0:
            weighted_sum += views * weights.get("views", 0.0)

        if weighted_sum <= 0.0:
            return 0.0

        scale_factor = weights.get("scale_factor", 8.0)
        # log1p avoids log(0) and handles small values gracefully.
        score = math.log1p(weighted_sum) * scale_factor
        return min(100.0, round(score, 2))

    def compute_content_hash(self, text: str) -> str:
        """Compute a content deduplication hash.

        Normalizes whitespace and Unicode before hashing so that minor
        formatting differences between platforms do not produce different
        hashes for semantically identical content.

        Normalization steps:
        1. Unicode NFC normalization.
        2. Strip leading/trailing whitespace.
        3. Collapse internal runs of whitespace to a single space.
        4. Lowercase.

        Args:
            text: Raw text content from the platform.

        Returns:
            64-character lowercase hex SHA-256 digest.
        """
        normalized = unicodedata.normalize("NFC", text)
        normalized = normalized.strip()
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = normalized.lower()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Private extraction helpers
    # ------------------------------------------------------------------

    def _extract_str(
        self,
        raw: dict[str, Any],
        keys: list[str],
    ) -> str | None:
        """Return the first non-empty string value found under any of *keys*.

        Args:
            raw: Source dict.
            keys: Candidate keys to try in order.

        Returns:
            First non-empty string value, or ``None``.
        """
        for key in keys:
            value = raw.get(key)
            if value and isinstance(value, str):
                return value.strip() or None
        return None

    def _extract_int(
        self,
        raw: dict[str, Any],
        keys: list[str],
    ) -> int | None:
        """Return the first integer value found under any of *keys*.

        Args:
            raw: Source dict.
            keys: Candidate keys to try in order.

        Returns:
            First integer-castable value as ``int``, or ``None``.
        """
        for key in keys:
            value = raw.get(key)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
        return None

    def _extract_datetime(
        self,
        raw: dict[str, Any],
        keys: list[str],
    ) -> str | None:
        """Return the first recognizable datetime value as an ISO 8601 string.

        Handles:
        - Already-formatted ISO 8601 strings.
        - Unix epoch integers/floats.
        - ``datetime`` objects.

        Args:
            raw: Source dict.
            keys: Candidate keys to try in order.

        Returns:
            ISO 8601 string (with UTC timezone suffix) or ``None``.
        """
        for key in keys:
            value = raw.get(key)
            if value is None:
                continue

            if isinstance(value, datetime):
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                return value.isoformat()

            if isinstance(value, (int, float)):
                try:
                    dt = datetime.fromtimestamp(value, tz=timezone.utc)
                    return dt.isoformat()
                except (OSError, OverflowError, ValueError):
                    continue

            if isinstance(value, str):
                value = value.strip()
                if not value:
                    continue
                # Attempt common ISO 8601 parsing
                for fmt in (
                    "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%SZ",
                    "%Y-%m-%dT%H:%M:%S.%f%z",
                    "%Y-%m-%dT%H:%M:%S.%fZ",
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%d",
                ):
                    try:
                        dt = datetime.strptime(value, fmt)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        return dt.isoformat()
                    except ValueError:
                        continue
                logger.debug("Could not parse datetime string '%s' for key '%s'", value, key)

        return None

    def _extract_list(
        self,
        raw: dict[str, Any],
        keys: list[str],
    ) -> list[str]:
        """Return the first list of strings found under any of *keys*.

        Args:
            raw: Source dict.
            keys: Candidate keys to try in order.

        Returns:
            List of strings (may be empty).
        """
        for key in keys:
            value = raw.get(key)
            if isinstance(value, list):
                return [str(item) for item in value if item is not None]
        return []
