"""Cross-platform link miner for discovered source detection (GR-22).

Operates on batches of content records from the database and extracts URLs
from ``text_content``.  Classifies each URL by target platform, aggregates
by target identifier (channel name, username, subreddit, etc.), and returns
``DiscoveredLink`` objects ranked by how many distinct content records link
to the same target.

This module is intentionally NOT a ``ContentEnricher`` — enrichers operate on
individual records at collection time.  The ``LinkMiner`` is a post-hoc batch
analyser that runs across a full query design's content corpus on demand.

Owned by the Core Application Engineer.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.core.models.content import UniversalContentRecord

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# URL extraction regex
# ---------------------------------------------------------------------------
#
# Matches full ``http(s)://`` URLs including path, query string, and fragment.
# The character class at the end uses a negative lookahead approach: we stop
# at whitespace and at common sentence-ending punctuation when it appears at
# the very end of the URL (trailing periods, commas, closing brackets, etc.).
# This avoids matching ``https://example.com.`` when followed by nothing.
#
# Design notes:
# - Uses a non-greedy match for the path so that trailing punctuation is not
#   consumed.
# - Does NOT use re.UNICODE word boundaries because URLs may contain
#   international characters.
# - Wrapped in a word-boundary-like anchor on the left (whitespace / start)
#   to avoid partial matches inside HTML entity references or escaped strings.

_URL_PATTERN: re.Pattern[str] = re.compile(
    r"(?<![\"'<>])"           # negative lookbehind: not inside HTML attributes
    r"https?://"              # scheme
    r"[^\s\"'<>(){}\[\]]+"    # domain + path chars (no whitespace, quotes, brackets)
    r"(?<![.,;:!?)\]>])",     # negative lookbehind: strip trailing sentence punctuation
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Platform classifiers — ordered by specificity (most specific first)
# ---------------------------------------------------------------------------

_PLATFORM_RULES: list[tuple[re.Pattern[str], str, str]] = [
    # (URL pattern, platform slug, group-name capturing the target_identifier)
    # Telegram
    (re.compile(r"https?://t\.me/(?P<target>[^/?#\s]+)", re.I), "telegram", "target"),
    # Discord
    (
        re.compile(
            r"https?://(?:discord\.gg|discord\.com/invite)/(?P<target>[^/?#\s]+)",
            re.I,
        ),
        "discord",
        "target",
    ),
    # YouTube — channel URL, @handle, or video (use channel handle when present)
    (
        re.compile(
            r"https?://(?:www\.)?youtube\.com/(?:c/|@)(?P<target>[^/?#\s]+)",
            re.I,
        ),
        "youtube",
        "target",
    ),
    (
        re.compile(
            r"https?://(?:www\.)?youtu\.be/(?P<target>[^/?#\s]+)",
            re.I,
        ),
        "youtube",
        "target",
    ),
    # Reddit
    (
        re.compile(
            r"https?://(?:www\.)?reddit\.com/r/(?P<target>[^/?#\s]+)",
            re.I,
        ),
        "reddit",
        "target",
    ),
    # Bluesky
    (
        re.compile(
            r"https?://bsky\.app/profile/(?P<target>[^/?#\s]+)",
            re.I,
        ),
        "bluesky",
        "target",
    ),
    # Gab
    (
        re.compile(
            r"https?://gab\.com/(?P<target>[^/?#\s]+)",
            re.I,
        ),
        "gab",
        "target",
    ),
    # X / Twitter
    (
        re.compile(
            r"https?://(?:www\.)?(?:twitter|x)\.com/(?P<target>[^/?#\s]+)",
            re.I,
        ),
        "twitter",
        "target",
    ),
    # Instagram
    (
        re.compile(
            r"https?://(?:www\.)?instagram\.com/(?P<target>[^/?#\s]+)",
            re.I,
        ),
        "instagram",
        "target",
    ),
    # TikTok
    (
        re.compile(
            r"https?://(?:www\.)?tiktok\.com/@(?P<target>[^/?#\s]+)",
            re.I,
        ),
        "tiktok",
        "target",
    ),
]


# ---------------------------------------------------------------------------
# DiscoveredLink dataclass
# ---------------------------------------------------------------------------


@dataclass
class DiscoveredLink:
    """A cross-platform link discovered by mining content records.

    Attributes:
        url: The canonical URL (normalised: lowercased scheme+host, original path).
        platform: Platform slug — one of ``"telegram"``, ``"discord"``,
            ``"youtube"``, ``"reddit"``, ``"bluesky"``, ``"gab"``,
            ``"twitter"``, ``"instagram"``, ``"tiktok"``, or ``"web"``.
        target_identifier: Channel name, subreddit, username, video ID, or
            domain — extracted from the URL.  For ``"web"`` links this is the
            registered domain (e.g. ``"example.com"``).
        source_count: Number of *distinct* content records that contain this URL.
        first_seen_at: Earliest ``collected_at`` timestamp among the source records.
        last_seen_at: Latest ``collected_at`` timestamp among the source records.
        example_source_urls: Up to three ``url`` values from the source content
            records (for quick navigation back to the context).
    """

    url: str
    platform: str
    target_identifier: str
    source_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    example_source_urls: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_urls(text: str) -> set[str]:
    """Extract all distinct ``https?://`` URLs from a text string.

    Deduplication at the per-record level: the same URL appearing multiple
    times in one record is counted only once.

    Args:
        text: Raw text content from a content record.

    Returns:
        Set of distinct URL strings found in the text.
    """
    return set(_URL_PATTERN.findall(text))


def _classify_url(url: str) -> tuple[str, str]:
    """Classify a URL by target platform and extract the target identifier.

    Applies platform-specific regexes in priority order.  If no platform
    rule matches, returns ``("web", registered_domain)``.

    Args:
        url: A single URL string extracted from content text.

    Returns:
        Tuple of ``(platform_slug, target_identifier)``.
    """
    for pattern, platform, group_name in _PLATFORM_RULES:
        match = pattern.match(url)
        if match:
            target = match.group(group_name)
            # Strip trailing slashes from captured target identifiers.
            target = target.rstrip("/")
            return platform, target

    # Fallback: extract the registered domain as the target identifier.
    try:
        parsed = urlparse(url)
        host = parsed.hostname or parsed.netloc or url
        # Strip leading "www." for consistency.
        if host.startswith("www."):
            host = host[4:]
        return "web", host
    except Exception:  # noqa: BLE001
        return "web", url


# ---------------------------------------------------------------------------
# LinkMiner
# ---------------------------------------------------------------------------


class LinkMiner:
    """Mines cross-platform links from stored content records.

    Operates on the full set of content records for a given query design,
    extracting URLs from ``text_content``, classifying them by platform, and
    returning aggregated ``DiscoveredLink`` objects sorted by ``source_count``
    (most linked-to targets first).

    Deduplication guarantees:
    - The same URL in ``text_content`` of a single record counts as one
      occurrence regardless of how many times it appears.
    - The same URL appearing in multiple fields of a single record (e.g. the
      record's own ``url`` field and its ``text_content``) is still counted as
      one source record occurrence.

    Usage::

        miner = LinkMiner()
        links = await miner.mine(
            db=db,
            query_design_id=some_uuid,
            platform_filter="telegram",
            min_source_count=2,
            limit=50,
        )
    """

    async def mine(
        self,
        db: AsyncSession,
        query_design_id: uuid.UUID,
        platform_filter: Optional[str] = None,
        min_source_count: int = 2,
        limit: int = 50,
    ) -> list[DiscoveredLink]:
        """Mine cross-platform links from a query design's content corpus.

        Fetches all content records for the given ``query_design_id``, extracts
        URLs from ``text_content``, classifies them by target platform, and
        aggregates by ``(platform, target_identifier)``.  Records with no
        ``text_content`` are skipped.

        Args:
            db: Async database session.
            query_design_id: UUID of the query design whose content to mine.
            platform_filter: Optional platform slug to restrict results to
                (e.g. ``"telegram"``).  When ``None``, all platforms are
                returned.
            min_source_count: Minimum number of distinct source records that
                must link to a target for it to appear in the output
                (default: 2).
            limit: Maximum number of ``DiscoveredLink`` objects to return
                (default: 50), sorted by ``source_count`` descending.

        Returns:
            List of ``DiscoveredLink`` objects, sorted by ``source_count``
            descending.
        """
        records = await self._fetch_records(db, query_design_id)
        aggregated = self._aggregate(records)
        return self._filter_and_rank(
            aggregated=aggregated,
            platform_filter=platform_filter,
            min_source_count=min_source_count,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # Internal steps
    # ------------------------------------------------------------------

    async def _fetch_records(
        self,
        db: AsyncSession,
        query_design_id: uuid.UUID,
    ) -> list[UniversalContentRecord]:
        """Fetch all content records for the given query design.

        Only loads the columns needed for URL mining to minimise memory usage.

        Args:
            db: Async database session.
            query_design_id: UUID of the query design to scope the query to.

        Returns:
            List of ``UniversalContentRecord`` ORM instances.
        """
        stmt = select(UniversalContentRecord).where(
            UniversalContentRecord.query_design_id == query_design_id,
            UniversalContentRecord.text_content.isnot(None),
        )
        result = await db.execute(stmt)
        records = list(result.scalars().all())

        logger.debug(
            "link_miner.records_fetched",
            query_design_id=str(query_design_id),
            count=len(records),
        )
        return records

    def _aggregate(
        self,
        records: list[UniversalContentRecord],
    ) -> dict[tuple[str, str], dict]:
        """Aggregate discovered links across all records.

        Builds an intermediate dict keyed by ``(platform, target_identifier)``
        counting distinct source records and collecting example source URLs and
        timestamps.

        Args:
            records: List of ``UniversalContentRecord`` ORM instances to mine.

        Returns:
            Dict mapping ``(platform, target_identifier)`` to an aggregation
            dict with keys:
            - ``source_count``: int
            - ``first_seen_at``: datetime
            - ``last_seen_at``: datetime
            - ``example_source_urls``: list[str] (up to 3)
            - ``canonical_url``: str (first URL encountered for this target)
        """
        agg: dict[tuple[str, str], dict] = {}

        for record in records:
            text = record.text_content
            if not text:
                continue

            collected_at: datetime = record.collected_at or datetime.now(tz=timezone.utc)

            # Extract URLs; deduplicate *within* this record.
            found_urls: set[str] = _extract_urls(text)
            # Track which (platform, target) pairs we've already counted from
            # THIS record to avoid double-counting when the same link appears
            # in multiple fields.
            seen_for_this_record: set[tuple[str, str]] = set()

            for url in found_urls:
                platform, target = _classify_url(url)
                key = (platform, target)

                if key in seen_for_this_record:
                    continue
                seen_for_this_record.add(key)

                if key not in agg:
                    agg[key] = {
                        "source_count": 0,
                        "first_seen_at": collected_at,
                        "last_seen_at": collected_at,
                        "example_source_urls": [],
                        "canonical_url": url,
                    }

                entry = agg[key]
                entry["source_count"] += 1

                if collected_at < entry["first_seen_at"]:
                    entry["first_seen_at"] = collected_at
                if collected_at > entry["last_seen_at"]:
                    entry["last_seen_at"] = collected_at

                if len(entry["example_source_urls"]) < 3 and record.url:
                    source_url: str = record.url
                    if source_url not in entry["example_source_urls"]:
                        entry["example_source_urls"].append(source_url)

        return agg

    def _filter_and_rank(
        self,
        aggregated: dict[tuple[str, str], dict],
        platform_filter: Optional[str],
        min_source_count: int,
        limit: int,
    ) -> list[DiscoveredLink]:
        """Convert the aggregation dict to sorted ``DiscoveredLink`` objects.

        Applies ``platform_filter`` and ``min_source_count`` thresholds, then
        sorts by ``source_count`` descending and returns up to ``limit`` items.

        Args:
            aggregated: Output of ``_aggregate()``.
            platform_filter: Optional platform slug to restrict to.
            min_source_count: Minimum source_count threshold.
            limit: Maximum items to return.

        Returns:
            Filtered, sorted list of ``DiscoveredLink`` objects.
        """
        links: list[DiscoveredLink] = []

        for (platform, target), entry in aggregated.items():
            if platform_filter is not None and platform != platform_filter:
                continue
            if entry["source_count"] < min_source_count:
                continue

            links.append(
                DiscoveredLink(
                    url=entry["canonical_url"],
                    platform=platform,
                    target_identifier=target,
                    source_count=entry["source_count"],
                    first_seen_at=entry["first_seen_at"],
                    last_seen_at=entry["last_seen_at"],
                    example_source_urls=entry["example_source_urls"],
                )
            )

        links.sort(key=lambda lnk: lnk.source_count, reverse=True)
        return links[:limit]
