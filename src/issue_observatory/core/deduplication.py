"""Cross-arena near-duplicate detection for content records.

Task 3.8 — implements URL-normalisation-based and content-hash-based
duplicate detection across different arenas, plus a mark-and-sweep pass
that stamps duplicates with ``raw_metadata['duplicate_of']``.

Item 15 — adds SimHash-based near-duplicate detection.  SimHash is a
64-bit locality-sensitive hash: two records with Hamming distance <= 3
over their SimHash fingerprints are considered near-duplicates and stamped
with ``raw_metadata['near_duplicate_of']`` (distinct from exact-duplicate
``raw_metadata['duplicate_of']``).

GR-08 — adds ``run_propagation_analysis()`` which groups all records that
carry a ``near_duplicate_cluster_id`` into clusters, runs
``PropagationEnricher.enrich_cluster()`` on each multi-arena cluster, and
persists the resulting enrichment into ``raw_metadata.enrichments.propagation``
for every record in the cluster.

GR-11 — adds ``run_coordination_analysis()`` which groups records into the
same near-duplicate clusters and runs ``CoordinationDetector.enrich_cluster()``
to flag potential coordinated inauthentic behaviour (CIB).  The coordination
score is normalised across all clusters in the batch and persisted into
``raw_metadata.enrichments.coordination``.

No new dependencies are required: URL normalisation uses ``urllib.parse``
and SimHash computation uses ``hashlib`` — both from the standard library.

Owned by the DB Engineer.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import structlog
from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.core.models.content import UniversalContentRecord

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# SimHash — 64-bit locality-sensitive hashing for near-duplicate detection
# ---------------------------------------------------------------------------

_SIMHASH_BITS: int = 64
_SIMHASH_MOD: int = 1 << _SIMHASH_BITS  # 2^64, used to keep values unsigned


def compute_simhash(text_content: str) -> int:
    """Compute a 64-bit SimHash fingerprint for *text_content*.

    Algorithm (Charikar 2002, adapted for 64 bits using MD5 truncation):

    1. Tokenize the text into overlapping character 2-grams (bigrams).
       Bigrams are robust to minor typos, reorderings of short words, and
       minor rephrasing.
    2. For each token, compute the MD5 digest of the UTF-8 encoded token and
       take the first 8 bytes as an unsigned 64-bit integer (the "token hash").
    3. Accumulate a 64-element integer weight vector ``v``.  For each token
       hash, for each bit position ``i`` (0–63):
       - If bit ``i`` of the token hash is 1, add +1 to ``v[i]``.
       - Otherwise add -1 to ``v[i]``.
    4. Reduce ``v`` to a 64-bit fingerprint: set bit ``i`` of the result if
       ``v[i] > 0``, else clear it.

    Args:
        text_content: The raw text to fingerprint.  Whitespace normalisation
            is applied before tokenisation (strip and collapse).

    Returns:
        An unsigned 64-bit integer representing the SimHash fingerprint.
        Returns 0 for empty strings after normalisation.
    """
    normalized = " ".join(text_content.lower().split())
    if not normalized:
        return 0

    # Build 2-gram token list
    tokens: list[str] = []
    for i in range(len(normalized) - 1):
        tokens.append(normalized[i : i + 2])
    if not tokens:
        # Single-character text — use the character itself as the only token.
        tokens = [normalized]

    # Accumulate weight vector
    v: list[int] = [0] * _SIMHASH_BITS
    for token in tokens:
        digest = hashlib.md5(token.encode("utf-8")).digest()  # noqa: S324
        # Take first 8 bytes as unsigned big-endian 64-bit integer.
        token_hash = int.from_bytes(digest[:8], byteorder="big", signed=False)
        for bit in range(_SIMHASH_BITS):
            if (token_hash >> bit) & 1:
                v[bit] += 1
            else:
                v[bit] -= 1

    # Reduce to fingerprint
    fingerprint: int = 0
    for bit in range(_SIMHASH_BITS):
        if v[bit] > 0:
            fingerprint |= 1 << bit

    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    """Return the Hamming distance (bit-flip count) between two SimHash values.

    Args:
        a: First 64-bit SimHash fingerprint.
        b: Second 64-bit SimHash fingerprint.

    Returns:
        The number of bit positions at which ``a`` and ``b`` differ (0–64).
    """
    return bin(a ^ b).count("1")


async def find_near_duplicates(
    db: AsyncSession,
    run_id: uuid.UUID | None = None,
    query_design_id: uuid.UUID | None = None,
    hamming_threshold: int = 3,
) -> list[dict]:
    """Find content records whose SimHash fingerprints are within *hamming_threshold* bits.

    Loads all records with a non-NULL simhash (scoped to the optional
    ``run_id`` / ``query_design_id`` filters) and groups them by Hamming
    distance.  Records within the threshold form a near-duplicate cluster.

    Args:
        db: Active async database session.
        run_id: Restrict the search to a specific collection run.
        query_design_id: Restrict the search to a specific query design.
        hamming_threshold: Maximum Hamming distance (inclusive) for two records
            to be considered near-duplicates.  Defaults to 3.

    Returns:
        A list of dicts, each representing a near-duplicate cluster::

            [
                {
                    "canonical_id": "...",      # lowest UUID in the cluster
                    "near_duplicate_ids": [...], # UUIDs of the other members
                    "members": [                # all cluster members
                        {"id": "...", "platform": "...", "simhash": 12345},
                        ...
                    ],
                },
                ...
            ]

        Only clusters with two or more members are returned.
    """
    stmt = select(
        UniversalContentRecord.id,
        UniversalContentRecord.platform,
        UniversalContentRecord.arena,
        UniversalContentRecord.simhash,
    ).where(UniversalContentRecord.simhash.isnot(None))

    if run_id is not None:
        stmt = stmt.where(UniversalContentRecord.collection_run_id == run_id)
    if query_design_id is not None:
        stmt = stmt.where(UniversalContentRecord.query_design_id == query_design_id)

    result = await db.execute(stmt)
    rows = result.all()

    if not rows:
        return []

    # Union-Find to group records into near-duplicate clusters.
    # O(n^2) in record count — suitable for per-run batches (typically < 50K).
    parent: dict[str, str] = {str(row.id): str(row.id) for row in rows}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path compression
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            # Elect the lexicographically smaller UUID as the cluster root.
            if rx < ry:
                parent[ry] = rx
            else:
                parent[rx] = ry

    records_by_id = {str(row.id): row for row in rows}
    ids = list(records_by_id.keys())

    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a_hash = records_by_id[ids[i]].simhash
            b_hash = records_by_id[ids[j]].simhash
            if a_hash is not None and b_hash is not None:
                if hamming_distance(a_hash, b_hash) <= hamming_threshold:
                    union(ids[i], ids[j])

    # Group by cluster root
    from collections import defaultdict

    clusters: dict[str, list[str]] = defaultdict(list)
    for record_id in ids:
        root = find(record_id)
        clusters[root].append(record_id)

    output = []
    for root, member_ids in clusters.items():
        if len(member_ids) < 2:
            continue
        canonical_id = root
        near_duplicate_ids = [mid for mid in member_ids if mid != canonical_id]
        output.append(
            {
                "canonical_id": canonical_id,
                "near_duplicate_ids": near_duplicate_ids,
                "members": [
                    {
                        "id": mid,
                        "platform": records_by_id[mid].platform,
                        "arena": records_by_id[mid].arena,
                        "simhash": records_by_id[mid].simhash,
                    }
                    for mid in member_ids
                ],
            }
        )

    return output


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
    # SimHash near-duplicate detection
    # ------------------------------------------------------------------

    async def detect_and_mark_near_duplicates(
        self,
        db: AsyncSession,
        run_id: uuid.UUID,
        hamming_threshold: int = 3,
    ) -> int:
        """Detect and mark near-duplicate records for a collection run.

        Fetches all records for *run_id* that have a non-NULL ``simhash``,
        groups them into near-duplicate clusters using Hamming distance, then
        stamps each non-canonical member with
        ``raw_metadata['near_duplicate_of'] = str(canonical_id)``.

        This is distinct from exact-duplicate marking (``duplicate_of``):
        near-duplicates have similar but not identical text content and share
        the same SimHash cluster, while exact duplicates share the same
        ``content_hash``.

        Args:
            db: Active async database session.  The caller is responsible for
                committing after this method returns.
            run_id: UUID of the collection run to process.
            hamming_threshold: Maximum Hamming distance (inclusive) for two
                records to be considered near-duplicates.  Defaults to 3.

        Returns:
            The total number of records marked as near-duplicates.
        """
        clusters = await find_near_duplicates(
            db, run_id=run_id, hamming_threshold=hamming_threshold
        )
        if not clusters:
            logger.info(
                "dedup.near_duplicates.none_found",
                run_id=str(run_id),
                threshold=hamming_threshold,
            )
            return 0

        total_marked = 0
        for cluster in clusters:
            canonical_id = uuid.UUID(cluster["canonical_id"])
            duplicate_ids = [uuid.UUID(did) for did in cluster["near_duplicate_ids"]]
            if not duplicate_ids:
                continue

            stmt = (
                update(UniversalContentRecord)
                .where(UniversalContentRecord.id.in_(duplicate_ids))
                .values(
                    raw_metadata=func.jsonb_set(
                        func.coalesce(
                            UniversalContentRecord.raw_metadata,
                            text("'{}'::jsonb"),
                        ),
                        text("'{near_duplicate_of}'"),
                        func.to_jsonb(str(canonical_id)),
                    )
                )
                .execution_options(synchronize_session=False)
            )
            result = await db.execute(stmt)
            total_marked += result.rowcount

        logger.info(
            "dedup.near_duplicates.marked",
            run_id=str(run_id),
            clusters=len(clusters),
            marked=total_marked,
            threshold=hamming_threshold,
        )
        return total_marked

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


    # ------------------------------------------------------------------
    # GR-08: Propagation analysis
    # ------------------------------------------------------------------

    async def run_propagation_analysis(
        self,
        db: AsyncSession,
        run_id: uuid.UUID | None = None,
        query_design_id: uuid.UUID | None = None,
        min_distinct_arenas: int = 2,
    ) -> dict:
        """Compute cross-arena temporal propagation for all near-duplicate clusters.

        Queries all content records that have a non-NULL
        ``near_duplicate_cluster_id`` (set by a prior SimHash deduplication
        pass), groups them by cluster, and for each cluster that spans at
        least *min_distinct_arenas* distinct arenas runs
        :class:`~issue_observatory.analysis.enrichments.propagation_detector.PropagationEnricher`
        to compute the temporal propagation sequence.

        The enrichment result is written into
        ``raw_metadata.enrichments.propagation`` for every record in the
        qualifying clusters.  Existing enrichment keys are preserved via the
        PostgreSQL JSONB merge operator ``||``.

        Callers are responsible for committing the transaction after this
        method returns.

        Args:
            db: Active async database session.
            run_id: Restrict the analysis to records from a specific collection
                run.  When ``None`` all records with a cluster id are included.
            query_design_id: Restrict to a specific query design.
            min_distinct_arenas: Minimum number of distinct arenas a cluster
                must span to qualify for propagation analysis.  Defaults to 2
                (at least one cross-arena propagation event).

        Returns:
            A summary dict with keys:

            - ``clusters_found`` (int): Total clusters with ≥ 2 records.
            - ``clusters_analysed`` (int): Clusters that met the
              *min_distinct_arenas* threshold and were enriched.
            - ``records_enriched`` (int): Total records updated.
        """
        # Lazy import to avoid a circular dependency at module load time.
        from issue_observatory.analysis.enrichments.propagation_detector import (  # noqa: PLC0415
            PropagationEnricher,
        )

        # Fetch all records that belong to a near-duplicate cluster.
        stmt = select(
            UniversalContentRecord.id,
            UniversalContentRecord.arena,
            UniversalContentRecord.platform,
            UniversalContentRecord.published_at,
            UniversalContentRecord.raw_metadata,
        ).where(
            # The cluster id is stored in raw_metadata->>'near_duplicate_cluster_id'
            # by detect_and_mark_near_duplicates, OR as the canonical_id root
            # from the Union-Find process.  We query records that carry either
            # the 'near_duplicate_of' marker or are the canonical member (whose
            # UUID is the root).  In practice the safest approach is to query
            # all records whose raw_metadata contains 'near_duplicate_of', plus
            # the canonical records identified by find_near_duplicates().
            #
            # For GR-08 we take the approach of re-running find_near_duplicates
            # to obtain fresh cluster membership, then enriching in Python.
            UniversalContentRecord.simhash.isnot(None)
        )

        if run_id is not None:
            stmt = stmt.where(UniversalContentRecord.collection_run_id == run_id)
        if query_design_id is not None:
            stmt = stmt.where(UniversalContentRecord.query_design_id == query_design_id)

        result = await db.execute(stmt)
        all_rows = result.all()

        if not all_rows:
            logger.info(
                "dedup.propagation.no_records",
                run_id=str(run_id) if run_id else None,
                query_design_id=str(query_design_id) if query_design_id else None,
            )
            return {"clusters_found": 0, "clusters_analysed": 0, "records_enriched": 0}

        # Re-derive clusters using find_near_duplicates so we have consistent
        # cluster membership without relying on a pre-populated cluster_id column.
        clusters = await find_near_duplicates(
            db, run_id=run_id, query_design_id=query_design_id
        )

        # Build a lookup of row data keyed by id string.
        rows_by_id: dict[str, object] = {str(row.id): row for row in all_rows}

        enricher = PropagationEnricher()
        clusters_found = len(clusters)
        clusters_analysed = 0
        records_enriched = 0

        for cluster in clusters:
            member_ids: list[str] = [
                cluster["canonical_id"],
                *cluster["near_duplicate_ids"],
            ]

            # Build record dicts for members that are in our fetched rows.
            member_records: list[dict] = []
            for mid in member_ids:
                row = rows_by_id.get(mid)
                if row is None:
                    continue
                member_records.append(
                    {
                        "id": str(row.id),
                        "arena": row.arena,
                        "platform": row.platform,
                        "published_at": row.published_at,
                        # Store the canonical cluster root id as the cluster id.
                        "near_duplicate_cluster_id": cluster["canonical_id"],
                        "raw_metadata": row.raw_metadata or {},
                    }
                )

            if len(member_records) < 2:
                continue

            # Check distinct arenas.
            distinct_arenas: set[str] = {r["arena"] for r in member_records}
            if len(distinct_arenas) < min_distinct_arenas:
                continue

            clusters_analysed += 1

            # Run the propagation enricher.
            try:
                enrichment_by_id = await enricher.enrich_cluster(member_records)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "dedup.propagation.enrichment_error",
                    cluster_id=cluster["canonical_id"],
                    error=str(exc),
                )
                continue

            # Persist enrichment into raw_metadata for each record.
            for rec in member_records:
                rec_id_str = rec["id"]
                rec_uuid = uuid.UUID(rec_id_str)
                enrichment_data = enrichment_by_id.get(rec_id_str)
                if enrichment_data is None:
                    continue

                # Write the propagation enrichment into the nested JSONB path:
                #   raw_metadata -> 'enrichments' -> 'propagation'
                #
                # Using a raw parameterised UPDATE so that the JSON value is
                # passed as a bind parameter (avoiding any quoting/injection
                # issues).  jsonb_set with create_missing=true creates the
                # intermediate 'enrichments' key if absent, preserving sibling
                # keys (e.g. 'language_detection') already stored there.
                propagation_json_str = json.dumps(enrichment_data)

                raw_sql = text(
                    """
                    UPDATE content_records
                    SET raw_metadata = jsonb_set(
                        COALESCE(raw_metadata, '{}'::jsonb),
                        '{enrichments,propagation}',
                        :prop_json::jsonb,
                        true
                    )
                    WHERE id = :record_id
                    """
                )
                await db.execute(
                    raw_sql,
                    {
                        "prop_json": propagation_json_str,
                        "record_id": str(rec_uuid),
                    },
                )
                records_enriched += 1

        summary = {
            "clusters_found": clusters_found,
            "clusters_analysed": clusters_analysed,
            "records_enriched": records_enriched,
        }
        logger.info(
            "dedup.propagation.complete",
            run_id=str(run_id) if run_id else None,
            query_design_id=str(query_design_id) if query_design_id else None,
            **summary,
        )
        return summary

    # ------------------------------------------------------------------
    # GR-11: Coordination analysis
    # ------------------------------------------------------------------

    async def run_coordination_analysis(
        self,
        db: AsyncSession,
        run_id: uuid.UUID | None = None,
        query_design_id: uuid.UUID | None = None,
        min_cluster_size: int = 3,
        coordination_threshold: int = 5,
        time_window_hours: float = 1.0,
    ) -> dict:
        """Compute coordinated inauthentic behaviour signals for near-duplicate clusters.

        Queries all content records that share near-duplicate SimHash clusters,
        groups them by cluster, and for each cluster with at least
        *min_cluster_size* records runs
        :class:`~issue_observatory.analysis.enrichments.coordination_detector.CoordinationDetector`
        to detect potential coordinated posting patterns.

        The coordination score is normalised across all processed clusters so
        that the cluster with the highest distinct-author count in a time window
        receives score 1.0.

        The enrichment result is written into
        ``raw_metadata.enrichments.coordination`` for every record in all
        qualifying clusters (both flagged and non-flagged).  Existing enrichment
        keys are preserved via the PostgreSQL JSONB merge operator.

        Callers are responsible for committing the transaction after this
        method returns.

        Args:
            db: Active async database session.
            run_id: Restrict the analysis to records from a specific collection
                run.  When ``None`` all records with a simhash are included.
            query_design_id: Restrict to a specific query design.
            min_cluster_size: Minimum number of records a cluster must contain
                to qualify for coordination analysis.  Defaults to 3.
            coordination_threshold: Distinct-author count within the time window
                that triggers a coordination flag.  Passed to
                :class:`~issue_observatory.analysis.enrichments.coordination_detector.CoordinationDetector`.
                Defaults to 5.
            time_window_hours: Width of the sliding time window in hours.
                Defaults to 1.0.

        Returns:
            A summary dict with keys:

            - ``clusters_found`` (int): Total clusters with >= *min_cluster_size*
              records.
            - ``clusters_analysed`` (int): Clusters that were passed to the
              enricher (same as clusters_found here — all qualifying clusters
              are analysed regardless of flagging outcome).
            - ``clusters_flagged`` (int): Clusters where coordination was
              flagged.
            - ``records_enriched`` (int): Total records updated.
        """
        # Lazy import to avoid a circular dependency at module load time.
        from issue_observatory.analysis.enrichments.coordination_detector import (  # noqa: PLC0415
            CoordinationDetector,
        )

        # Fetch all records that have a simhash (proxy for cluster membership).
        stmt = select(
            UniversalContentRecord.id,
            UniversalContentRecord.arena,
            UniversalContentRecord.platform,
            UniversalContentRecord.published_at,
            UniversalContentRecord.author_id,
            UniversalContentRecord.raw_metadata,
        ).where(UniversalContentRecord.simhash.isnot(None))

        if run_id is not None:
            stmt = stmt.where(UniversalContentRecord.collection_run_id == run_id)
        if query_design_id is not None:
            stmt = stmt.where(UniversalContentRecord.query_design_id == query_design_id)

        result = await db.execute(stmt)
        all_rows = result.all()

        if not all_rows:
            logger.info(
                "dedup.coordination.no_records",
                run_id=str(run_id) if run_id else None,
                query_design_id=str(query_design_id) if query_design_id else None,
            )
            return {
                "clusters_found": 0,
                "clusters_analysed": 0,
                "clusters_flagged": 0,
                "records_enriched": 0,
            }

        # Re-derive clusters via find_near_duplicates for consistent membership.
        clusters = await find_near_duplicates(
            db, run_id=run_id, query_design_id=query_design_id
        )

        rows_by_id: dict[str, object] = {str(row.id): row for row in all_rows}

        enricher = CoordinationDetector(
            coordination_threshold=coordination_threshold,
            time_window_hours=time_window_hours,
        )

        # Inline datetime coercion used only in the normalisation pre-pass.
        # Mirrors _parse_published_at in coordination_detector without importing
        # from the enricher module at this stage (the enricher is lazy-imported
        # below to avoid circular imports at load time).
        def _coerce_dt(value: object) -> datetime | None:
            if value is None:
                return None
            if isinstance(value, datetime):
                return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
            if isinstance(value, str):
                stripped = value.strip()
                if not stripped:
                    return None
                try:
                    parsed = datetime.fromisoformat(stripped)
                    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
                except ValueError:
                    return None
            return None

        # First pass: collect best distinct-author count per cluster so we can
        # normalise coordination_score across all clusters in this batch.
        qualifying_clusters: list[tuple[list[str], list[dict]]] = []
        for cluster in clusters:
            member_ids: list[str] = [
                cluster["canonical_id"],
                *cluster["near_duplicate_ids"],
            ]
            member_records: list[dict] = []
            for mid in member_ids:
                row = rows_by_id.get(mid)
                if row is None:
                    continue
                member_records.append(
                    {
                        "id": str(row.id),
                        "arena": row.arena,
                        "platform": row.platform,
                        "published_at": row.published_at,
                        "author_id": str(row.author_id) if row.author_id else None,
                        "near_duplicate_cluster_id": cluster["canonical_id"],
                        "raw_metadata": row.raw_metadata or {},
                    }
                )
            if len(member_records) >= min_cluster_size:
                qualifying_clusters.append((member_ids, member_records))

        clusters_found = len(qualifying_clusters)

        # Determine max distinct authors across all qualifying clusters for
        # cross-cluster score normalisation.
        max_distinct: int = 0
        cluster_best_counts: list[int] = []
        for _, member_records in qualifying_clusters:
            best_count, _, _, _ = enricher._find_best_window(
                sorted(
                    [
                        (
                            _coerce_dt(r.get("published_at")),
                            r.get("author_id"),
                            str(r.get("platform") or ""),
                        )
                        for r in member_records
                        if _coerce_dt(r.get("published_at")) is not None
                    ],
                    key=lambda t: t[0],  # type: ignore[arg-type]
                )
            )
            cluster_best_counts.append(best_count)
            if best_count > max_distinct:
                max_distinct = best_count

        # Second pass: enrich each cluster with the normalised score.
        clusters_analysed = 0
        clusters_flagged = 0
        records_enriched = 0

        for (member_ids, member_records), best_count in zip(
            qualifying_clusters, cluster_best_counts
        ):
            clusters_analysed += 1
            try:
                enrichment_by_id = await enricher.enrich_cluster(
                    member_records,
                    max_distinct_authors=max_distinct if max_distinct > 0 else None,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "dedup.coordination.enrichment_error",
                    cluster_id=member_records[0].get("near_duplicate_cluster_id"),
                    error=str(exc),
                )
                continue

            # Check if this cluster was flagged (all records share the same flag).
            first_payload = next(iter(enrichment_by_id.values()), {})
            if first_payload.get("flagged"):
                clusters_flagged += 1

            # Persist enrichment into raw_metadata for each record.
            for rec in member_records:
                rec_id_str = rec["id"]
                rec_uuid = uuid.UUID(rec_id_str)
                enrichment_data = enrichment_by_id.get(rec_id_str)
                if enrichment_data is None:
                    continue

                coordination_json_str = json.dumps(enrichment_data)

                raw_sql = text(
                    """
                    UPDATE content_records
                    SET raw_metadata = jsonb_set(
                        COALESCE(raw_metadata, '{}'::jsonb),
                        '{enrichments,coordination}',
                        :coord_json::jsonb,
                        true
                    )
                    WHERE id = :record_id
                    """
                )
                await db.execute(
                    raw_sql,
                    {
                        "coord_json": coordination_json_str,
                        "record_id": str(rec_uuid),
                    },
                )
                records_enriched += 1

        summary = {
            "clusters_found": clusters_found,
            "clusters_analysed": clusters_analysed,
            "clusters_flagged": clusters_flagged,
            "records_enriched": records_enriched,
        }
        logger.info(
            "dedup.coordination.complete",
            run_id=str(run_id) if run_id else None,
            query_design_id=str(query_design_id) if query_design_id else None,
            **summary,
        )
        return summary


# ---------------------------------------------------------------------------
# Module-level convenience wrapper
# ---------------------------------------------------------------------------


async def run_propagation_analysis(
    db: AsyncSession,
    run_id: uuid.UUID | None = None,
    query_design_id: uuid.UUID | None = None,
    min_distinct_arenas: int = 2,
) -> dict:
    """Module-level wrapper around :meth:`DeduplicationService.run_propagation_analysis`.

    Convenience entry point so callers do not need to instantiate
    ``DeduplicationService`` when they only need propagation analysis.

    Args:
        db: Active async database session.
        run_id: Restrict analysis to a specific collection run.
        query_design_id: Restrict analysis to a specific query design.
        min_distinct_arenas: Minimum distinct arenas for a cluster to qualify.

    Returns:
        Summary dict — see :meth:`DeduplicationService.run_propagation_analysis`
        for the full key description.
    """
    service = DeduplicationService()
    return await service.run_propagation_analysis(
        db,
        run_id=run_id,
        query_design_id=query_design_id,
        min_distinct_arenas=min_distinct_arenas,
    )


async def run_coordination_analysis(
    db: AsyncSession,
    run_id: uuid.UUID | None = None,
    query_design_id: uuid.UUID | None = None,
    min_cluster_size: int = 3,
    coordination_threshold: int = 5,
    time_window_hours: float = 1.0,
) -> dict:
    """Module-level wrapper around :meth:`DeduplicationService.run_coordination_analysis`.

    Convenience entry point so callers do not need to instantiate
    ``DeduplicationService`` when they only need coordination analysis.

    Args:
        db: Active async database session.
        run_id: Restrict analysis to a specific collection run.
        query_design_id: Restrict analysis to a specific query design.
        min_cluster_size: Minimum cluster size to qualify for analysis.
        coordination_threshold: Distinct-author count that triggers a CIB flag.
        time_window_hours: Width of the sliding time window in hours.

    Returns:
        Summary dict — see :meth:`DeduplicationService.run_coordination_analysis`
        for the full key description.
    """
    service = DeduplicationService()
    return await service.run_coordination_analysis(
        db,
        run_id=run_id,
        query_design_id=query_design_id,
        min_cluster_size=min_cluster_size,
        coordination_threshold=coordination_threshold,
        time_window_hours=time_window_hours,
    )


# ---------------------------------------------------------------------------
# FastAPI dependency factory
# ---------------------------------------------------------------------------


def get_deduplication_service() -> DeduplicationService:
    """FastAPI dependency factory for ``DeduplicationService``.

    Returns:
        A new ``DeduplicationService`` instance.
    """
    return DeduplicationService()
