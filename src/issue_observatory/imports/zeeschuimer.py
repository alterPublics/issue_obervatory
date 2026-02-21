"""Zeeschuimer NDJSON processor — streaming parser and platform dispatcher.

This module handles the core logic for processing Zeeschuimer NDJSON files:

1. Stream the file line by line (never load entire file into memory)
2. Strip NUL bytes from each line before JSON parsing
3. Restructure each item: extract ``data`` as content, collect envelope as metadata
4. Dispatch to platform-specific normalizer based on ``source_platform``
5. Apply GDPR pseudonymization via the universal normalizer
6. Compute content_hash and simhash for deduplication
7. Bulk-insert into content_records table

The processor is called by the router after streaming the request body to a
temporary file.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.core.deduplication import compute_simhash
from issue_observatory.core.normalizer import Normalizer
from issue_observatory.imports.normalizers.instagram import InstagramNormalizer
from issue_observatory.imports.normalizers.linkedin import LinkedInNormalizer
from issue_observatory.imports.normalizers.threads import ThreadsNormalizer
from issue_observatory.imports.normalizers.tiktok import TikTokNormalizer
from issue_observatory.imports.normalizers.twitter import TwitterNormalizer

logger = structlog.get_logger(__name__)


class ZeeschuimerProcessor:
    """Processes Zeeschuimer NDJSON files and imports records into IO.

    The processor is stateless except for the database session. A new instance
    should be created for each import operation.

    Args:
        db: Async database session for bulk insert operations.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._normalizer = Normalizer()
        self._platform_normalizers: dict[str, Any] = {
            "linkedin.com": LinkedInNormalizer(),
            "twitter.com": TwitterNormalizer(),
            "instagram.com": InstagramNormalizer(),
            "tiktok.com": TikTokNormalizer(),
            "tiktok-comments": TikTokNormalizer(),  # Same normalizer, different context
            "threads.net": ThreadsNormalizer(),
        }

    async def process_file(
        self,
        file_path: Path,
        zeeschuimer_platform: str,
        io_platform: str,
        zeeschuimer_import_id: UUID,
        user_id: UUID,
    ) -> dict[str, Any]:
        """Process a Zeeschuimer NDJSON file and import records.

        Streams the file line by line, normalizes each item via the platform-specific
        normalizer, and bulk-inserts into the content_records table.

        Args:
            file_path: Path to the temporary NDJSON file.
            zeeschuimer_platform: Zeeschuimer module_id (e.g., "linkedin.com").
            io_platform: IO platform name (e.g., "linkedin").
            zeeschuimer_import_id: UUID of the ZeeschuimerImport tracking this import.
            user_id: UUID of the user who initiated the import.

        Returns:
            Dict with import statistics:
            ``{"imported": int, "skipped": int, "errors": list[dict]}``

        Raises:
            FileNotFoundError: If file_path does not exist.
            ValueError: If zeeschuimer_platform is not supported.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"NDJSON file not found: {file_path}")

        if zeeschuimer_platform not in self._platform_normalizers:
            raise ValueError(
                f"Unsupported Zeeschuimer platform: {zeeschuimer_platform}. "
                f"Supported: {list(self._platform_normalizers.keys())}"
            )

        platform_normalizer = self._platform_normalizers[zeeschuimer_platform]
        records_to_insert: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        total_lines = 0

        logger.info(
            "zeeschuimer.process_file.started",
            file_path=str(file_path),
            platform=io_platform,
            zeeschuimer_import_id=str(zeeschuimer_import_id),
        )

        # Stream file line by line
        with file_path.open("r", encoding="utf-8", errors="replace") as f:
            for line_num, line in enumerate(f, start=1):
                # Strip NUL bytes (Section 3.2 of spec)
                line = line.replace("\x00", "").strip()
                if not line:
                    continue

                total_lines += 1

                try:
                    # Parse JSON
                    zeeschuimer_item = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append({
                        "line": line_num,
                        "error": f"JSON parse error: {exc}",
                        "raw_line": line[:200],
                    })
                    continue

                try:
                    # Restructure: extract data as top-level, envelope as metadata
                    # (Section 3.2 of spec)
                    platform_data = zeeschuimer_item.get("data", {})
                    envelope = {
                        k: v for k, v in zeeschuimer_item.items() if k != "data"
                    }

                    # Convert timestamp_collected from milliseconds to datetime
                    timestamp_collected = None
                    if "timestamp_collected" in envelope:
                        try:
                            # Zeeschuimer timestamps are in milliseconds (Section 7.5)
                            ts_ms = int(envelope["timestamp_collected"])
                            timestamp_collected = datetime.fromtimestamp(
                                ts_ms / 1000, tz=timezone.utc
                            )
                        except (ValueError, TypeError) as exc:
                            logger.warning(
                                "zeeschuimer.invalid_timestamp",
                                line=line_num,
                                timestamp_collected=envelope.get("timestamp_collected"),
                                error=str(exc),
                            )

                    # Normalize via platform-specific normalizer
                    normalized_data = platform_normalizer.normalize(
                        raw_data=platform_data,
                        envelope=envelope,
                    )

                    # Skip filtered records (e.g., Instagram ads)
                    if normalized_data.get("instagram_ad_filtered"):
                        logger.debug("zeeschuimer.ad_filtered", line=line_num)
                        continue

                    # Apply universal normalization
                    record = self._normalizer.normalize(
                        raw_item=normalized_data,
                        platform=io_platform,
                        arena="social_media",
                        collection_tier="manual",
                        collection_run_id=None,  # No collection run for Zeeschuimer imports
                        search_terms_matched=[],  # Manual imports have no term matching
                    )

                    # Override collected_at with Zeeschuimer's timestamp if available (WARNING-6)
                    if timestamp_collected:
                        record["collected_at"] = timestamp_collected.isoformat()

                    # BLOCKER-4: Fall back to collected_at if published_at is None
                    if not record.get("published_at"):
                        fallback_timestamp = timestamp_collected or datetime.now(tz=timezone.utc)
                        record["published_at"] = fallback_timestamp.isoformat()
                        if "raw_metadata" not in record or record["raw_metadata"] is None:
                            record["raw_metadata"] = {}
                        record["raw_metadata"]["published_at_source"] = "collected_at_fallback"

                    # Tag with import source
                    if "raw_metadata" not in record or record["raw_metadata"] is None:
                        record["raw_metadata"] = {}
                    record["raw_metadata"]["import_source"] = "zeeschuimer"
                    record["raw_metadata"]["zeeschuimer_import_id"] = str(zeeschuimer_import_id)
                    record["raw_metadata"]["zeeschuimer"] = envelope

                    # Compute simhash for near-duplicate detection
                    if record.get("text_content"):
                        record["simhash"] = compute_simhash(record["text_content"])

                    records_to_insert.append(record)

                except Exception as exc:
                    logger.warning(
                        "zeeschuimer.normalization_error",
                        line=line_num,
                        platform=io_platform,
                        error=str(exc),
                        exc_info=exc,
                    )
                    errors.append({
                        "line": line_num,
                        "error": f"Normalization error: {exc}",
                        "platform": io_platform,
                    })

        # Bulk insert
        inserted, skipped = await self._bulk_insert(records_to_insert)

        logger.info(
            "zeeschuimer.process_file.complete",
            platform=io_platform,
            total_lines=total_lines,
            inserted=inserted,
            skipped=skipped,
            errors=len(errors),
        )

        return {
            "imported": inserted,
            "skipped": skipped,
            "errors": errors,
        }

    async def _bulk_insert(
        self,
        records: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """Bulk-insert content records, skipping duplicates by content_hash.

        Uses ``INSERT ... ON CONFLICT DO NOTHING`` against the
        ``content_records`` table keyed on ``content_hash``. The conflict target
        must match the partial unique index: ``WHERE content_hash IS NOT NULL``.

        Args:
            records: List of normalized content record dicts.

        Returns:
            Tuple of ``(inserted_count, skipped_count)``.
        """
        if not records:
            return 0, 0

        inserted = 0
        skipped = 0

        for record in records:
            # Build dynamic INSERT statement
            columns = [k for k, v in record.items() if v is not None]
            if not columns:
                skipped += 1
                continue

            placeholders = ", ".join(f":{col}" for col in columns)
            col_list = ", ".join(columns)

            # BLOCKER-1: Use ON CONFLICT with WHERE clause to match partial unique index
            stmt = text(
                f"INSERT INTO content_records ({col_list}) "  # noqa: S608
                f"VALUES ({placeholders}) "
                f"ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL DO NOTHING"
            )

            try:
                result = await self._db.execute(
                    stmt,
                    {col: record[col] for col in columns},
                )
                if result.rowcount == 1:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.warning(
                    "zeeschuimer.insert_error",
                    error=str(exc),
                    platform_id=record.get("platform_id"),
                )
                skipped += 1

        # WARNING-8: Let the caller manage the commit boundary
        return inserted, skipped
