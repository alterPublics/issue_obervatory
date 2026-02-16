"""Data import routes — multipart file upload for CSV and NDJSON content.

Supports two collection pathways that cannot be automated via ArenaCollector:

- **Zeeschuimer** (LinkedIn, TikTok, Instagram): NDJSON exported from the
  Firefox browser extension.
- **4CAT** pipeline exports: CSV or NDJSON files produced by 4CAT analytical
  tooling.
- **Manual CSV**: spreadsheet exports with a known column schema.
- **Manual NDJSON**: line-delimited JSON with a ``platform`` field.

Routes:
    POST /content/import — multipart file upload (NDJSON or CSV)

File size limit: 50 MB.  Per-row errors are collected and returned; if more
than 10% of rows fail the endpoint returns HTTP 422 instead of HTTP 200.

The ``collection_method`` field is injected into each record's ``raw_metadata``
so downstream analysis can distinguish import pathway from API collection.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.core.database import get_db
from issue_observatory.core.models.users import User
from issue_observatory.core.normalizer import Normalizer

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_FILE_BYTES: int = 50 * 1024 * 1024  # 50 MB
_ERROR_THRESHOLD_PCT: float = 0.10  # 10 % of rows

# CSV column → UCR field mapping (all optional except platform).
_CSV_COLUMN_MAP: dict[str, str] = {
    "url": "url",
    "text": "text",
    "title": "title",
    "published_at": "published_at",
    "platform": "platform",
    "author_display_name": "author_display_name",
    "author_id": "author_id",
    "language": "language",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_format(file: UploadFile) -> str:
    """Detect file format from filename extension or content-type header.

    Args:
        file: The uploaded file object.

    Returns:
        ``"ndjson"`` or ``"csv"``.

    Raises:
        HTTPException: HTTP 415 when the format cannot be determined.
    """
    filename = (file.filename or "").lower()
    content_type = (file.content_type or "").lower()

    if filename.endswith(".ndjson") or "x-ndjson" in content_type:
        return "ndjson"
    if filename.endswith(".jsonl"):
        return "ndjson"
    if filename.endswith(".csv") or "text/csv" in content_type:
        return "csv"
    # Last-resort: try content-type substring matching
    if "json" in content_type:
        return "ndjson"
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail=(
            "Cannot determine file format. "
            "Use a .ndjson / .jsonl / .csv extension or set Content-Type to "
            "text/csv or application/x-ndjson."
        ),
    )


def _csv_row_to_raw(row: dict[str, str]) -> dict[str, str | None]:
    """Map a CSV DictReader row to a flat raw-item dict for the normalizer.

    Args:
        row: Single row from ``csv.DictReader``.

    Returns:
        Dict with UCR-compatible keys populated from the CSV columns.
    """
    mapped: dict[str, str | None] = {}
    for csv_col, ucr_field in _CSV_COLUMN_MAP.items():
        value = row.get(csv_col, "").strip() or None
        mapped[ucr_field] = value
    return mapped


def _infer_platform_from_ndjson(obj: dict) -> str | None:
    """Attempt to infer the platform from an NDJSON object.

    Checks the top-level ``platform`` key first; falls back to common
    platform-specific fingerprint keys.

    Args:
        obj: Parsed JSON object from one NDJSON line.

    Returns:
        Platform string or ``None`` when detection fails.
    """
    if "platform" in obj and isinstance(obj["platform"], str):
        return obj["platform"].strip() or None
    # Zeeschuimer LinkedIn fingerprint
    if "post" in obj and "urn:li:" in str(obj.get("post", "")):
        return "linkedin"
    # Zeeschuimer TikTok fingerprint
    if "video_description" in obj or "tiktok" in str(obj).lower()[:200]:
        return "tiktok"
    return None


# ---------------------------------------------------------------------------
# Bulk insert helper
# ---------------------------------------------------------------------------


async def _bulk_insert(
    db: AsyncSession,
    records: list[dict],
) -> tuple[int, int]:
    """Bulk-insert content records, skipping duplicates by content_hash.

    Uses ``INSERT ... ON CONFLICT DO NOTHING`` against the
    ``content_records`` table keyed on ``content_hash``.

    Args:
        db: Active async DB session.
        records: List of normalized content record dicts.

    Returns:
        Tuple of ``(inserted_count, skipped_count)``.
    """
    if not records:
        return 0, 0

    inserted = 0
    skipped = 0

    for record in records:
        # Build the INSERT statement dynamically from the record dict keys.
        # Only include non-None values to avoid overriding DB defaults.
        columns = [k for k, v in record.items() if v is not None]
        if not columns:
            skipped += 1
            continue

        placeholders = ", ".join(f":{col}" for col in columns)
        col_list = ", ".join(columns)

        stmt = text(
            f"INSERT INTO content_records ({col_list}) "  # noqa: S608
            f"VALUES ({placeholders}) "
            f"ON CONFLICT (content_hash) DO NOTHING"
        )
        result = await db.execute(stmt, {col: record[col] for col in columns})
        if result.rowcount == 1:
            inserted += 1
        else:
            skipped += 1

    await db.commit()
    return inserted, skipped


# ---------------------------------------------------------------------------
# Import endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/content/import",
    tags=["imports"],
    summary="Import content records from a CSV or NDJSON file upload.",
    status_code=status.HTTP_200_OK,
)
async def import_content(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    file: Annotated[UploadFile, File(description="CSV or NDJSON file to import.")],
    collection_method: Annotated[
        str,
        Form(
            description=(
                "Collection method tag injected into raw_metadata. "
                "E.g. 'zeeschuimer', '4cat', 'manual_csv', 'manual_ndjson'."
            )
        ),
    ],
    query_design_id: Annotated[
        Optional[UUID],
        Form(description="Optional query design UUID to associate with imported records."),
    ] = None,
) -> dict:
    """Import content records from a multipart CSV or NDJSON file upload.

    Streams the file line-by-line through the normalizer.  Per-row errors are
    collected and returned rather than raising an exception.  If more than 10%
    of rows fail, the endpoint returns HTTP 422 with the full error list.

    File size is capped at 50 MB.  Files larger than this receive HTTP 413.

    Args:
        db: Injected async DB session.
        current_user: Authenticated active user (required).
        file: Uploaded file (``multipart/form-data``).
        collection_method: Tag describing how data was captured.
        query_design_id: Optional query design to associate with records.

    Returns:
        JSON body: ``{"imported": N, "skipped": M, "errors": [...]}``.

    Raises:
        HTTPException: 413 when file exceeds 50 MB size limit.
        HTTPException: 415 when file format cannot be determined.
        HTTPException: 422 when more than 10% of rows contain errors.
    """
    # ---- File size guard ---------------------------------------------------
    raw_bytes = await file.read()
    if len(raw_bytes) > _MAX_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the 50 MB limit ({len(raw_bytes):,} bytes received).",
        )

    file_format = _detect_format(file)

    normalizer = Normalizer()
    normalizer_kwargs: dict = {}
    if query_design_id is not None:
        normalizer_kwargs["query_design_id"] = str(query_design_id)

    records_to_insert: list[dict] = []
    errors: list[dict] = []
    total_rows = 0

    # ---- Parse and normalize -----------------------------------------------

    if file_format == "ndjson":
        text_data = raw_bytes.decode("utf-8", errors="replace")
        for line_num, line in enumerate(text_data.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            total_rows += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append({"row": line_num, "error": f"JSON parse error: {exc}"})
                continue

            platform = _infer_platform_from_ndjson(obj)
            if platform is None:
                errors.append({
                    "row": line_num,
                    "error": "Cannot determine platform. Add a 'platform' field.",
                })
                continue

            try:
                # Inject collection_method into raw data before normalization
                # so it is preserved in raw_metadata.
                enriched = dict(obj)
                enriched["collection_method"] = collection_method
                record = normalizer.normalize(
                    raw_item=enriched,
                    platform=platform,
                    arena=enriched.get("arena", "import"),
                    collection_tier=enriched.get("collection_tier", "manual"),
                    **normalizer_kwargs,
                )
                # Ensure raw_metadata carries collection_method
                if isinstance(record.get("raw_metadata"), dict):
                    record["raw_metadata"]["collection_method"] = collection_method
                records_to_insert.append(record)
            except Exception as exc:  # noqa: BLE001
                errors.append({"row": line_num, "error": str(exc)})

    else:  # csv
        text_data = raw_bytes.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text_data))
        for row_num, row in enumerate(reader, start=2):  # row 1 is header
            total_rows += 1
            platform = (row.get("platform") or "").strip()
            if not platform:
                errors.append({
                    "row": row_num,
                    "error": "Missing required 'platform' column value.",
                })
                continue

            try:
                raw_item = _csv_row_to_raw(row)
                raw_item["collection_method"] = collection_method
                record = normalizer.normalize(
                    raw_item=raw_item,
                    platform=platform,
                    arena="import",
                    collection_tier="manual",
                    **normalizer_kwargs,
                )
                if isinstance(record.get("raw_metadata"), dict):
                    record["raw_metadata"]["collection_method"] = collection_method
                records_to_insert.append(record)
            except Exception as exc:  # noqa: BLE001
                errors.append({"row": row_num, "error": str(exc)})

    # ---- Error threshold check ---------------------------------------------

    if total_rows > 0 and errors:
        error_pct = len(errors) / total_rows
        if error_pct > _ERROR_THRESHOLD_PCT:
            logger.warning(
                "import: error threshold exceeded (%.1f%% errors, %d/%d rows)",
                error_pct * 100,
                len(errors),
                total_rows,
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": (
                        f"Import aborted: {len(errors)}/{total_rows} rows "
                        f"({error_pct:.1%}) had errors, exceeding the 10% threshold."
                    ),
                    "errors": errors,
                },
            )

    # ---- DB insert ---------------------------------------------------------

    try:
        inserted, skipped = await _bulk_insert(db, records_to_insert)
    except Exception as exc:
        logger.exception("import: DB insert failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database insert failed: {exc}",
        ) from exc

    logger.info(
        "import: method=%s format=%s total=%d inserted=%d skipped=%d errors=%d",
        collection_method,
        file_format,
        total_rows,
        inserted,
        skipped,
        len(errors),
    )

    return {
        "imported": inserted,
        "skipped": skipped,
        "errors": errors,
    }
