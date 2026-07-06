"""Synchronous DB helpers for enrichment Celery tasks.

Separated from ``workers/_task_helpers.py`` to keep each file under 400 lines
and to make the individual helpers unit-testable without importing the Celery
application.

All functions use the synchronous ``get_sync_session()`` context manager
(psycopg2 driver) rather than ``AsyncSessionLocal`` (asyncpg driver).  This
avoids the "Future attached to a different loop" error that occurs when Celery
workers call ``asyncio.run()`` for the collector then attempt to re-use
asyncpg connections on a second ``asyncio.run()`` call.

Public helpers
--------------
- :func:`fetch_content_records_for_run` — paginated fetch for a specific run.
- :func:`fetch_unenriched_content_records` — paginated fetch of records whose
  ``raw_metadata.enrichments.{enricher_name}`` key is absent.
- :func:`write_enrichment` — merge a single enrichment result into JSONB.
- :func:`fetch_unenriched_for_url_extraction` — specialized paginated fetch
  for URL extraction that returns extra columns and includes YouTube/TikTok
  records regardless of text length.
- :func:`write_extracted_urls` — bulk-insert extracted URLs into the
  ``extracted_urls`` relational table.
- :func:`fetch_unenriched_for_engagement` — paginated fetch for records
  in engagement-capable platforms missing the ``engagement_score``
  enrichment.
- :func:`fetch_fitted_engagement_scalers` — load fitted per-platform
  Yeo-Johnson + MinMaxScaler parameters from the ``engagement_scalers``
  table.
- :func:`update_engagement_score_column` — batch-update the
  ``engagement_score`` column on ``content_records``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

if TYPE_CHECKING:
    import uuid

from issue_observatory.core.database import get_sync_session

# Batch size for fetching content records per DB round-trip.
_BATCH_SIZE = 500


def fetch_content_records_for_run(
    run_id: str,
    offset: int,
    limit: int = _BATCH_SIZE,
) -> list[dict[str, Any]]:
    """Fetch a batch of content records for a collection run.

    Args:
        run_id: UUID string of the CollectionRun.
        offset: Row offset for pagination.
        limit: Maximum number of rows to return (default: 100).

    Returns:
        List of dicts with at minimum the keys ``id``, ``text_content``,
        ``language``, and ``raw_metadata``.
    """
    with get_sync_session() as db:
        stmt = text(
            """
            SELECT id, text_content, language, raw_metadata
            FROM content_records
            WHERE collection_run_id = CAST(:run_id AS uuid)
            ORDER BY id
            LIMIT :limit OFFSET :offset
            """
        )
        result = db.execute(
            stmt,
            {"run_id": run_id, "limit": limit, "offset": offset},
        )
        rows = result.mappings().all()
        return [dict(row) for row in rows]


def fetch_unenriched_content_records(
    enricher_name: str,
    offset: int,
    limit: int = _BATCH_SIZE,
) -> list[dict[str, Any]]:
    """Fetch content records that are missing a specific enrichment key.

    A record is considered *unenriched* when
    ``raw_metadata->'enrichments'-><enricher_name>`` is NULL — that is, either
    ``raw_metadata`` itself is NULL, the top-level ``enrichments`` sub-object
    is absent, or the enricher-specific key inside it has never been written.

    Only records with non-null ``text_content`` longer than 50 characters are
    returned, matching the minimum viability threshold used by all enrichers.

    Args:
        enricher_name: The ``ContentEnricher.enricher_name`` value, e.g.
            ``"language_detection"`` or ``"actor_roles"``.  Used as a
            PostgreSQL JSON path key — must not contain special characters.
        offset: Row offset for pagination.
        limit: Maximum number of rows to return (default: 100).

    Returns:
        List of dicts with at minimum the keys ``id``, ``text_content``,
        ``language``, and ``raw_metadata``.
    """
    with get_sync_session() as db:
        stmt = text(
            """
            SELECT id, text_content, language, raw_metadata
            FROM content_records
            WHERE text_content IS NOT NULL
              AND LENGTH(text_content) > 50
              AND (
                  raw_metadata IS NULL
                  OR raw_metadata->'enrichments' IS NULL
                  OR raw_metadata->'enrichments'->:enricher_name IS NULL
              )
            ORDER BY id
            LIMIT :limit OFFSET :offset
            """
        )
        result = db.execute(
            stmt,
            {"enricher_name": enricher_name, "limit": limit, "offset": offset},
        )
        rows = result.mappings().all()
        return [dict(row) for row in rows]


def write_enrichment(
    record_id: uuid.UUID | str,
    enricher_name: str,
    enrichment_data: dict[str, Any],
) -> None:
    """Merge a single enrichment result into raw_metadata.enrichments.{name}.

    Uses PostgreSQL ``jsonb_set`` with ``create_missing=true`` so the
    ``enrichments`` key is created if absent.

    Args:
        record_id: UUID of the content_records row.
        enricher_name: Key under ``raw_metadata.enrichments`` to write.
        enrichment_data: The enrichment result dict to store.
    """
    write_enrichment_batch(enricher_name, [(record_id, enrichment_data)])


def write_enrichment_batch(
    enricher_name: str,
    items: list[tuple[uuid.UUID | str, dict[str, Any]]],
) -> None:
    """Merge multiple enrichment results in a single transaction.

    Each item is a ``(record_id, enrichment_data)`` tuple. All updates are
    executed within one DB session and committed together, which is
    dramatically faster than one-commit-per-record.

    Args:
        enricher_name: Key under ``raw_metadata.enrichments`` to write.
        items: List of ``(record_id, enrichment_data)`` tuples.
    """
    if not items:
        return

    stmt = text(
        f"""
        UPDATE content_records
        SET raw_metadata = jsonb_set(
                jsonb_set(
                    COALESCE(raw_metadata, '{{}}'::jsonb),
                    '{{enrichments}}',
                    COALESCE(raw_metadata->'enrichments', '{{}}'::jsonb),
                    true
                ),
                '{{enrichments,{enricher_name}}}',
                CAST(:data AS jsonb),
                true
            )
        WHERE id = CAST(:record_id AS uuid)
        """
    )

    with get_sync_session() as db:
        for record_id, enrichment_data in items:
            db.execute(
                stmt,
                {
                    "data": json.dumps(enrichment_data),
                    "record_id": str(record_id),
                },
            )
        db.commit()


def fetch_unenriched_for_url_extraction(
    offset: int,
    limit: int = _BATCH_SIZE,
) -> list[dict[str, Any]]:
    """Fetch content records missing URL extraction enrichment.

    Unlike :func:`fetch_unenriched_content_records`, this helper:

    * Joins through ``collection_runs`` and ``query_designs`` to return the
      extra columns ``url``, ``platform``, ``query_design_id``, and
      ``project_id`` that :class:`~issue_observatory.analysis.enrichments.url_extractor.UrlExtractor`
      requires.
    * Includes YouTube/TikTok records even when ``text_content`` is short or
      absent, because those platforms use the record's own URL as a
      self-reference link.

    Args:
        offset: Row offset for pagination.
        limit: Maximum number of rows to return (default: 100).

    Returns:
        List of dicts with keys ``id``, ``published_at``, ``text_content``,
        ``url``, ``platform``, ``raw_metadata``, ``query_design_id``, and
        ``project_id``.
    """
    with get_sync_session() as db:
        stmt = text(
            """
            SELECT cr.id, cr.published_at, cr.text_content, cr.url,
                   cr.platform, cr.raw_metadata,
                   crun.query_design_id,
                   qd.project_id
            FROM content_records cr
            LEFT JOIN collection_runs crun ON cr.collection_run_id = crun.id
            LEFT JOIN query_designs qd ON crun.query_design_id = qd.id
            WHERE (
                cr.raw_metadata IS NULL
                OR cr.raw_metadata->'enrichments' IS NULL
                OR cr.raw_metadata->'enrichments'->'url_extraction' IS NULL
            )
            AND (
                (cr.text_content IS NOT NULL AND LENGTH(cr.text_content) > 10)
                OR cr.platform IN ('youtube', 'tiktok')
            )
            ORDER BY cr.id
            LIMIT :limit OFFSET :offset
            """
        )
        result = db.execute(stmt, {"limit": limit, "offset": offset})
        rows = result.mappings().all()
        return [dict(row) for row in rows]


def write_extracted_urls(
    record_id: str,
    published_at: Any,
    urls: list[dict[str, Any]],
    platform: str,
    query_design_id: str | None,
    project_id: str | None,
    search_terms_matched: list[str],
) -> None:
    """Bulk-insert extracted URLs into the ``extracted_urls`` table.

    Uses ``INSERT … ON CONFLICT DO NOTHING`` for idempotency — safe to
    call multiple times for the same record.

    Args:
        record_id: UUID string of the source content record.
        published_at: Publication timestamp of the source record.
        urls: List of url detail dicts from
            :meth:`~issue_observatory.analysis.enrichments.url_extractor.UrlExtractor.enrich`.
            Each dict must contain the keys ``cleaned``, ``raw``, ``domain``,
            and ``type``.
        platform: Platform name of the source record (e.g. ``"youtube"``).
        query_design_id: UUID string of the associated query design, or
            ``None``.
        project_id: UUID string of the associated project, or ``None``.
        search_terms_matched: List of search terms that matched this record.
            Stored as a PostgreSQL ``TEXT[]`` array.
    """
    if not urls:
        return

    with get_sync_session() as db:
        for url_data in urls:
            cleaned = url_data.get("cleaned")
            if not cleaned:
                continue
            stmt = text(
                """
                INSERT INTO extracted_urls (
                    content_record_id, content_record_published_at,
                    url_raw, url_cleaned, url_domain, url_type,
                    platform, query_design_id, project_id,
                    search_terms_matched
                ) VALUES (
                    CAST(:record_id AS uuid),
                    :published_at,
                    :url_raw,
                    :url_cleaned,
                    :url_domain,
                    :url_type,
                    :platform,
                    CAST(:query_design_id AS uuid),
                    CAST(:project_id AS uuid),
                    :search_terms
                )
                ON CONFLICT (content_record_id, content_record_published_at, url_cleaned)
                DO NOTHING
                """
            )
            db.execute(
                stmt,
                {
                    "record_id": record_id,
                    "published_at": published_at,
                    "url_raw": url_data.get("raw", ""),
                    "url_cleaned": cleaned,
                    "url_domain": url_data.get("domain", ""),
                    "url_type": url_data.get("type", "text_extracted"),
                    "platform": platform,
                    "query_design_id": query_design_id,
                    "project_id": project_id,
                    "search_terms": search_terms_matched if search_terms_matched else None,
                },
            )
        db.commit()


# ---------------------------------------------------------------------------
# Engagement score enrichment helpers
# ---------------------------------------------------------------------------

#: Platforms with real engagement metrics suitable for data-driven scoring.
#: Must stay in sync with ``_ENGAGEMENT_PLATFORMS`` in ``engagement_scorer.py``.
_ENGAGEMENT_PLATFORM_LIST: tuple[str, ...] = (
    "youtube", "reddit", "bluesky", "x_twitter", "tiktok",
    "instagram", "facebook", "threads", "discord",
)


def fetch_unenriched_for_engagement(
    offset: int,
    limit: int = _BATCH_SIZE,
) -> list[dict[str, Any]]:
    """Fetch content records in engagement-capable platforms missing the enrichment.

    Unlike :func:`fetch_unenriched_content_records`, this helper:

    * Filters by platforms in ``_ENGAGEMENT_PLATFORM_LIST``.
    * Returns engagement metric columns instead of ``text_content``.
    * Does not require ``text_content`` (engagement is metrics-based).
    * Requires at least one engagement metric to be non-null and > 0.

    Args:
        offset: Row offset for pagination.
        limit: Maximum number of rows to return (default: 500).

    Returns:
        List of dicts with keys ``id``, ``platform``, ``views_count``,
        ``likes_count``, ``shares_count``, ``comments_count``,
        ``raw_metadata``, ``engagement_score``.
    """
    with get_sync_session() as db:
        stmt = text(
            """
            SELECT id, platform, views_count, likes_count,
                   shares_count, comments_count,
                   raw_metadata, engagement_score
            FROM content_records
            WHERE platform = ANY(:platforms)
              AND (
                  raw_metadata IS NULL
                  OR raw_metadata->'enrichments' IS NULL
                  OR raw_metadata->'enrichments'->'engagement_score' IS NULL
              )
              AND (
                  (views_count IS NOT NULL AND views_count > 0)
                  OR (likes_count IS NOT NULL AND likes_count > 0)
                  OR (shares_count IS NOT NULL AND shares_count > 0)
                  OR (comments_count IS NOT NULL AND comments_count > 0)
              )
            ORDER BY id
            LIMIT :limit OFFSET :offset
            """
        )
        result = db.execute(
            stmt,
            {
                "platforms": list(_ENGAGEMENT_PLATFORM_LIST),
                "limit": limit,
                "offset": offset,
            },
        )
        rows = result.mappings().all()
        return [dict(row) for row in rows]


def fetch_fitted_engagement_scalers() -> dict[str, dict[str, Any]]:
    """Load fitted per-platform engagement scaler parameters from the DB.

    Returns:
        Dict keyed by platform name, each value containing
        ``transformer_params``, ``scaler_params``, and ``fitted_at``.
        Empty dict if the table does not exist or has no rows.
    """
    with get_sync_session() as db:
        try:
            stmt = text(
                """
                SELECT platform, transformer_params, scaler_params, fitted_at
                FROM engagement_scalers
                """
            )
            rows = db.execute(stmt).mappings().all()
        except Exception:
            # Table may not exist yet (migration not applied).
            return {}

    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        result[row["platform"]] = {
            "transformer_params": row["transformer_params"],
            "scaler_params": row["scaler_params"],
            "fitted_at": str(row["fitted_at"]) if row["fitted_at"] else "",
        }
    return result


def update_engagement_score_column(
    items: list[tuple[str, float]],
) -> None:
    """Batch-update the ``engagement_score`` column on content_records.

    Args:
        items: List of ``(record_id, score)`` tuples.
    """
    if not items:
        return

    stmt = text(
        """
        UPDATE content_records
        SET engagement_score = :score
        WHERE id = CAST(:record_id AS uuid)
        """
    )

    with get_sync_session() as db:
        for record_id, score in items:
            db.execute(stmt, {"record_id": record_id, "score": score})
        db.commit()
