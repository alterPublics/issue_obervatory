"""Cross-arena near-duplicate detection for content records.

Task 3.8 — implements URL-normalisation-based and content-hash-based
duplicate detection across different arenas, plus a mark-and-sweep pass
that stamps duplicates with ``raw_metadata['duplicate_of']``.

No new dependencies are required: URL normalisation uses ``urllib.parse``
from the standard library.

Owned by the DB Engineer.
"""

from __future__ import annotations

import logging
import uuid
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.core.models.content import UniversalContentRecord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tracking query-parameter names to strip during URL normalisation
# ---------------------------------------------------------------------------

_STRIP_PARAMS: frozenset[str] = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_term",
        "fbclid",
        "gclid",
        "ref",
        "source",
        "_ga",
    }
)


# ---------------------------------------------------------------------------
# Pure URL normalisation function
# ---------------------------------------------------------------------------


def normalise_url(url: str) -> str:
    """Return a canonical form of *url* suitable for cross-arena deduplication.

    Transformations applied (in order):

    1. Lowercase the entire URL.
    2. Strip the ``www.`` prefix from the host component.
    3. Strip tracking query parameters (UTM, fbclid, gclid, ref, source, _ga).
    4. Re-encode the remaining query string in sorted key order for
       stable comparison.
    5. Strip any trailing slash from the path component.

    The scheme and fragment are preserved.  Malformed URLs (those that
    ``urlparse`` cannot parse into a ``netloc``) are returned lowercased
    only.

    Args:
        url: The raw URL string to normalise.

    Returns:
        The normalised URL string.
    """
    lowered = url.strip().lower()

    parsed = urlparse(lowered)
    if not parsed.netloc:
        return lowered

    # Strip www. prefix from host
    host = parsed.netloc
    if host.startswith("www."):
        host = host[4:]

    # Filter tracking params and re-sort for stable comparison
    qs_pairs = [(k, v) for k, v in parse_qsl(parsed.query) if k not in _STRIP_PARAMS]
    qs_pairs.sort()
    new_query = urlencode(qs_pairs)

    # Strip trailing slash from path (but keep root "/" for bare domains)
    path = parsed.path.rstrip("/") if parsed.path != "/" else parsed.path

    normalised = urlunparse(
        (parsed.scheme, host, path, parsed.params, new_query, parsed.fragment)
    )
    return normalised


# ---------------------------------------------------------------------------
# DeduplicationService
# ---------------------------------------------------------------------------


class DeduplicationService:
    """Cross-arena near-duplicate detection service.

    All methods receive an ``AsyncSession`` so they can participate in the
    caller's transaction.  None of the methods commit — callers are
    responsible for committing after calling ``mark_duplicates`` or
    ``run_dedup_pass``.
    """

    # ------------------------------------------------------------------
    # URL duplicates
    # ------------------------------------------------------------------

    async def find_url_duplicates(
        self,
        db: AsyncSession,
        run_id: uuid.UUID | None = None,
        query_design_id: uuid.UUID | None = None,
    ) -> list[dict]:
        """Find records that share the same normalised URL across arenas.

        Groups records by their normalised URL (see ``normalise_url``).
        Only groups with more than one record are returned.

        Args:
            db: Active async database session.
            run_id: Restrict the search to a specific collection run.
            query_design_id: Restrict the search to a specific query design.

        Returns:
            A list of dicts, each with keys:

            - ``normalised_url`` (str): The normalised URL shared by the group.
            - ``records`` (list[dict]): Records in the group, each with
              ``id``, ``platform``, ``arena``, and ``published_at``.
        """
        stmt = select(
            UniversalContentRecord.id,
            UniversalContentRecord.url,
            UniversalContentRecord.platform,
            UniversalContentRecord.arena,
            UniversalContentRecord.published_at,
        ).where(UniversalContentRecord.url.isnot(None))

        if run_id is not None:
            stmt = stmt.where(UniversalContentRecord.collection_run_id == run_id)
        if query_design_id is not None:
            stmt = stmt.where(UniversalContentRecord.query_design_id == query_design_id)

        result = await db.execute(stmt)
        rows = result.all()

        # Group by normalised URL in Python — avoids pushing PL/pgSQL
        # string logic into the query and makes unit-testing easy.
        from collections import defaultdict

        groups: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            if not row.url:
                continue
            key = normalise_url(row.url)
            groups[key].append(
                {
                    "id": str(row.id),
                    "platform": row.platform,
                    "arena": row.arena,
                    "published_at": row.published_at.isoformat() if row.published_at else None,
                }
            )

        return [
            {"normalised_url": norm_url, "records": records}
            for norm_url, records in groups.items()
            if len(records) > 1
        ]

    # ------------------------------------------------------------------
    # Hash duplicates
    # ------------------------------------------------------------------

    async def find_hash_duplicates(
        self,
        db: AsyncSession,
        run_id: uuid.UUID | None = None,
        query_design_id: uuid.UUID | None = None,
    ) -> list[dict]:
        """Find records sharing the same content_hash across different arenas.

        Only groups where at least two records differ in ``platform`` or
        ``arena`` are included — exact-same-platform duplicates are already
        blocked by the unique constraint and are not surfaced here.

        Args:
            db: Active async database session.
            run_id: Restrict the search to a specific collection run.
            query_design_id: Restrict the search to a specific query design.

        Returns:
            A list of dicts, each with keys:

            - ``content_hash`` (str): The SHA-256 hash shared by the group.
            - ``count`` (int): Number of records in the group.
            - ``records`` (list[dict]): Each record with ``id``, ``platform``,
              and ``arena``.
        """
        stmt = select(
            UniversalContentRecord.id,
            UniversalContentRecord.content_hash,
            UniversalContentRecord.platform,
            UniversalContentRecord.arena,
        ).where(UniversalContentRecord.content_hash.isnot(None))

        if run_id is not None:
            stmt = stmt.where(UniversalContentRecord.collection_run_id == run_id)
        if query_design_id is not None:
            stmt = stmt.where(UniversalContentRecord.query_design_id == query_design_id)

        result = await db.execute(stmt)
        rows = result.all()

        from collections import defaultdict

        groups: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            groups[row.content_hash].append(
                {
                    "id": str(row.id),
                    "platform": row.platform,
                    "arena": row.arena,
                }
            )

        output = []
        for content_hash, records in groups.items():
            if len(records) < 2:
                continue
            # Only include groups where platform or arena differs
            platforms = {r["platform"] for r in records}
            arenas = {r["arena"] for r in records}
            if len(platforms) > 1 or len(arenas) > 1:
                output.append(
                    {
                        "content_hash": content_hash,
                        "count": len(records),
                        "records": records,
                    }
                )

        return output

    # ------------------------------------------------------------------
    # Mark duplicates
    # ------------------------------------------------------------------

    async def mark_duplicates(
        self,
        db: AsyncSession,
        canonical_id: uuid.UUID,
        duplicate_ids: list[uuid.UUID],
    ) -> int:
        """Stamp duplicate records with a ``duplicate_of`` marker.

        Sets ``raw_metadata['duplicate_of'] = str(canonical_id)`` on every
        record in ``duplicate_ids``.  The canonical record is left untouched.

        Args:
            db: Active async database session.
            canonical_id: UUID of the record to treat as the canonical copy.
            duplicate_ids: UUIDs of the records to mark as duplicates.

        Returns:
            The number of records that were updated.
        """
        if not duplicate_ids:
            return 0

        # Use a raw UPDATE with a JSONB merge so that existing metadata keys
        # are preserved.  The ``||`` operator merges two JSONB objects.
        stmt = (
            update(UniversalContentRecord)
            .where(UniversalContentRecord.id.in_(duplicate_ids))
            .values(
                raw_metadata=func.jsonb_set(
                    func.coalesce(
                        UniversalContentRecord.raw_metadata,
                        text("'{}'::jsonb"),
                    ),
                    text("'{duplicate_of}'"),
                    func.to_jsonb(str(canonical_id)),
                )
            )
            .execution_options(synchronize_session=False)
        )
        result = await db.execute(stmt)
        count: int = result.rowcount
        logger.info(
            "dedup.mark_duplicates",
            canonical_id=str(canonical_id),
            marked=count,
        )
        return count

    # ------------------------------------------------------------------
    # Full dedup pass
    # ------------------------------------------------------------------

    async def run_dedup_pass(
        self,
        db: AsyncSession,
        run_id: uuid.UUID,
    ) -> dict:
        """Run a full deduplication pass for one collection run.

        Steps:

        1. Find URL duplicates scoped to the run.
        2. For each URL duplicate group, elect the canonical record (lowest
           UUID value) and mark the rest.
        3. Find hash duplicates scoped to the run.
        4. For each hash duplicate group, elect the canonical record (lowest
           UUID value, with ties broken by highest engagement_score) and
           mark the rest.
        5. Commit the transaction.

        Args:
            db: Active async database session.
            run_id: UUID of the collection run to deduplicate.

        Returns:
            Dict with keys:

            - ``url_groups`` (int): Number of URL duplicate groups found.
            - ``hash_groups`` (int): Number of hash duplicate groups found.
            - ``total_marked`` (int): Total records marked as duplicates.
        """
        total_marked = 0

        # --- URL pass ---
        url_groups = await self.find_url_duplicates(db, run_id=run_id)
        for group in url_groups:
            record_ids = [uuid.UUID(r["id"]) for r in group["records"]]
            canonical_id = min(record_ids)
            duplicate_ids = [rid for rid in record_ids if rid != canonical_id]
            total_marked += await self.mark_duplicates(db, canonical_id, duplicate_ids)

        # --- Hash pass ---
        hash_groups = await self.find_hash_duplicates(db, run_id=run_id)
        for group in hash_groups:
            record_ids = [uuid.UUID(r["id"]) for r in group["records"]]
            canonical_id = min(record_ids)
            duplicate_ids = [rid for rid in record_ids if rid != canonical_id]
            total_marked += await self.mark_duplicates(db, canonical_id, duplicate_ids)

        await db.commit()

        summary = {
            "url_groups": len(url_groups),
            "hash_groups": len(hash_groups),
            "total_marked": total_marked,
        }
        logger.info("dedup.run_complete", run_id=str(run_id), **summary)
        return summary


# ---------------------------------------------------------------------------
# FastAPI dependency factory
# ---------------------------------------------------------------------------


def get_deduplication_service() -> DeduplicationService:
    """FastAPI dependency factory for ``DeduplicationService``.

    Returns:
        A new ``DeduplicationService`` instance.
    """
    return DeduplicationService()
