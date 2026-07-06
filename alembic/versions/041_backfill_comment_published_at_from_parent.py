"""Back-fill comment published_at from parent post.

Bright Data's Facebook and Instagram comment scrapers return the scrape
timestamp in the ``date_posted`` field instead of the actual comment creation
date.  Since the real comment date is unavailable, we inherit the parent
post's ``published_at`` so that comments appear in the same time period as
the post they belong to.

This migration:
1. Updates ``content_records.published_at`` for FB/IG comments to match
   the parent post's ``published_at`` (looked up via
   ``raw_metadata->>'parent_post_id'`` = parent post ``url``).
2. Updates the corresponding ``content_record_links.content_record_published_at``
   to keep the link table in sync (no FK, but used in JOIN filters).

Performance:
- Materialises small indexed temp tables for comments and posts so the
  join between them uses hash/index lookups instead of a cross-partition
  nested loop scan of ``content_records``.
- Disables parallel query to avoid DSM allocation that can exhaust Docker's
  default 64 MB ``/dev/shm``.

Revision ID: 041
Revises: 040
"""

from __future__ import annotations

from alembic import op

revision: str = "041"
down_revision: str = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Disable parallel query for this migration.  A JOIN between partitioned
    # content_records tables would otherwise allocate a dynamic shared memory
    # segment that can exceed the container's /dev/shm (default 64 MB in
    # Docker).
    op.execute("SET max_parallel_workers_per_gather = 0")
    op.execute("SET work_mem = '256MB'")

    # ------------------------------------------------------------------
    # Step 1: Materialise small indexed lookup tables.
    # ------------------------------------------------------------------
    # 1a. Comments we want to retarget — single scan of content_records
    # filtered to FB/IG comments, with both raw and query-param-stripped
    # variants of the parent URL precomputed so the later join can use
    # equality lookups instead of an OR clause.
    op.execute(
        """
        CREATE TEMP TABLE tmp_comments AS
        SELECT
            id AS comment_id,
            platform,
            platform_id,
            content_hash,
            collected_at,
            published_at AS current_published_at,
            raw_metadata->>'parent_post_id' AS parent_url,
            SPLIT_PART(raw_metadata->>'parent_post_id', '?', 1) AS parent_url_clean
        FROM content_records
        WHERE platform IN ('facebook', 'instagram')
          AND content_type = 'comment'
          AND raw_metadata->>'parent_post_id' IS NOT NULL
        """
    )
    op.execute("CREATE INDEX ON tmp_comments (platform, parent_url)")
    op.execute("CREATE INDEX ON tmp_comments (platform, parent_url_clean)")
    op.execute("ANALYZE tmp_comments")

    # 1b. Candidate parent posts — single scan of content_records filtered
    # to FB/IG non-comment rows with a URL and a published_at.  If the
    # same URL appears multiple times we keep the earliest published_at.
    op.execute(
        """
        CREATE TEMP TABLE tmp_posts AS
        SELECT
            platform,
            url,
            SPLIT_PART(url, '?', 1) AS url_clean,
            MIN(published_at) AS published_at
        FROM content_records
        WHERE platform IN ('facebook', 'instagram')
          AND content_type != 'comment'
          AND url IS NOT NULL
          AND published_at IS NOT NULL
        GROUP BY platform, url
        """
    )
    op.execute("CREATE INDEX ON tmp_posts (platform, url)")
    op.execute("CREATE INDEX ON tmp_posts (platform, url_clean)")
    op.execute("ANALYZE tmp_posts")

    # ------------------------------------------------------------------
    # Step 2: Compute target date per comment via indexed lookups.
    # Prefer an exact URL match; fall back to query-param-stripped match.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TEMP TABLE comment_target_dates AS
        SELECT
            c.comment_id,
            c.platform,
            c.platform_id,
            c.content_hash,
            c.collected_at,
            COALESCE(pe.published_at, pc.published_at) AS target_published_at
        FROM tmp_comments c
        LEFT JOIN tmp_posts pe
            ON pe.platform = c.platform
           AND pe.url = c.parent_url
        LEFT JOIN tmp_posts pc
            ON pc.platform = c.platform
           AND pc.url_clean = c.parent_url_clean
        WHERE COALESCE(pe.published_at, pc.published_at) IS NOT NULL
        """
    )
    op.execute("CREATE INDEX ON comment_target_dates (comment_id)")
    op.execute(
        "CREATE INDEX ON comment_target_dates "
        "(platform, platform_id, target_published_at)"
    )
    op.execute(
        "CREATE INDEX ON comment_target_dates (content_hash, target_published_at)"
    )
    op.execute("ANALYZE comment_target_dates")

    # ------------------------------------------------------------------
    # Step 3: Identify comments that would violate either unique
    # constraint after the update:
    #   - uq_content_platform_id_published (platform, platform_id, published_at)
    #   - idx_content_hash_unique          (content_hash, published_at)
    # Within each collision group, keep the earliest-collected row and
    # mark the rest for deletion.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TEMP TABLE comments_to_delete AS
        SELECT comment_id
        FROM (
            SELECT
                comment_id,
                ROW_NUMBER() OVER (
                    PARTITION BY platform, platform_id, target_published_at
                    ORDER BY collected_at ASC, comment_id ASC
                ) AS rn_pi,
                CASE
                    WHEN content_hash IS NULL THEN 1
                    ELSE ROW_NUMBER() OVER (
                        PARTITION BY content_hash, target_published_at
                        ORDER BY collected_at ASC, comment_id ASC
                    )
                END AS rn_ch
            FROM comment_target_dates
        ) ranked
        WHERE rn_pi > 1 OR rn_ch > 1
        """
    )
    op.execute("CREATE INDEX ON comments_to_delete (comment_id)")
    op.execute("ANALYZE comments_to_delete")

    # ------------------------------------------------------------------
    # Step 4: Delete colliding rows.  Links first (no FK, but composite
    # join key), then content_records.
    # ------------------------------------------------------------------
    op.execute(
        """
        DELETE FROM content_record_links
        WHERE content_record_id IN (SELECT comment_id FROM comments_to_delete)
        """
    )
    op.execute(
        """
        DELETE FROM content_records
        WHERE id IN (SELECT comment_id FROM comments_to_delete)
        """
    )

    # ------------------------------------------------------------------
    # Step 5: Update remaining comments' published_at.
    # ------------------------------------------------------------------
    op.execute(
        """
        UPDATE content_records AS c
        SET published_at = ctd.target_published_at
        FROM comment_target_dates ctd
        WHERE c.id = ctd.comment_id
          AND NOT EXISTS (
              SELECT 1 FROM comments_to_delete d
              WHERE d.comment_id = ctd.comment_id
          )
          AND c.published_at IS DISTINCT FROM ctd.target_published_at
        """
    )

    # ------------------------------------------------------------------
    # Step 6: Sync content_record_links.content_record_published_at.
    # ------------------------------------------------------------------
    op.execute(
        """
        UPDATE content_record_links AS crl
        SET content_record_published_at = cr.published_at
        FROM content_records AS cr
        WHERE crl.content_record_id = cr.id
          AND cr.platform IN ('facebook', 'instagram')
          AND cr.content_type = 'comment'
          AND crl.content_record_published_at
              IS DISTINCT FROM cr.published_at
        """
    )

    # Cleanup temp tables (they would be dropped at session end anyway).
    op.execute("DROP TABLE IF EXISTS comments_to_delete")
    op.execute("DROP TABLE IF EXISTS comment_target_dates")
    op.execute("DROP TABLE IF EXISTS tmp_posts")
    op.execute("DROP TABLE IF EXISTS tmp_comments")


def downgrade() -> None:
    # Non-reversible: the original scrape timestamps are lost from
    # published_at (they remain in raw_metadata.date_posted).
    pass
