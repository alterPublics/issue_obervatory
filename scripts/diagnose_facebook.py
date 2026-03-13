"""Diagnose why the Facebook collector completes with 0 records despite API calls.

Tests the full pipeline step by step:
1. Credential acquisition
2. Single-page Bright Data API call (1 page, limit 5 posts)
3. Raw response inspection
4. Normalization + field validation
5. Database persistence (individual records)
6. Full pipeline with batch sink (mimics Celery task)

Run with:
    uv run python scripts/diagnose_facebook.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("diagnose_facebook")

for lib in ("httpx", "httpcore", "hpack", "urllib3"):
    logging.getLogger(lib).setLevel(logging.WARNING)


def separator(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}\n")


async def step1_check_credentials() -> dict | None:
    """Check if Bright Data Facebook credentials exist."""
    separator("Step 1: Credential Check")

    env_token = os.environ.get("BRIGHTDATA_FACEBOOK_API_TOKEN", "")
    if env_token:
        print(f"  ENV: BRIGHTDATA_FACEBOOK_API_TOKEN = {env_token[:12]}...{env_token[-4:]}")
    else:
        print("  ENV: BRIGHTDATA_FACEBOOK_API_TOKEN = NOT SET")

    from issue_observatory.core.credential_pool import CredentialPool

    pool = CredentialPool()
    try:
        cred = await pool.acquire(platform="brightdata_facebook", tier="medium")
        if cred is None:
            print("  POOL: acquire returned None — no credential available")
            return None
        api_token = cred.get("api_token") or cred.get("api_key", "")
        cred_id = cred.get("id", "unknown")
        print(f"  POOL: Got credential id={cred_id}")
        print(
            f"  POOL: api_token = {api_token[:12]}...{api_token[-4:]}"
            if api_token
            else "  POOL: api_token = EMPTY"
        )
        await pool.release(credential_id=cred_id)
        return cred
    except Exception as exc:
        print(f"  ERROR: {type(exc).__name__}: {exc}")
        return None


async def step2_collect_raw(api_token: str) -> list[dict]:
    """Collect raw items from a single public Facebook page via Bright Data."""
    separator("Step 2: Bright Data API — Single Page Collection")

    import httpx

    from issue_observatory.arenas.facebook.collector import FacebookCollector
    from issue_observatory.arenas.facebook.config import (
        FACEBOOK_DATASET_ID_POSTS,
        build_trigger_url,
    )

    test_url = "https://www.facebook.com/drnyheder"
    print(f"  URL: {test_url}")
    print(f"  Posts requested: 5")

    collector = FacebookCollector(credential_pool=None)
    trigger_url = build_trigger_url(FACEBOOK_DATASET_ID_POSTS)
    payload = [{"url": test_url, "num_of_posts": 5}]
    print(f"  Trigger URL: {trigger_url}")

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            snapshot_id = await collector._trigger_dataset(
                client, api_token, trigger_url, payload
            )
            print(f"  Snapshot ID: {snapshot_id}")
        except Exception as exc:
            print(f"  TRIGGER ERROR: {type(exc).__name__}: {exc}")
            return []

        print("  Polling for results (may take 1-3 minutes)...")
        try:
            raw_items = await collector._poll_and_download(client, api_token, snapshot_id)
            print(f"  Downloaded {len(raw_items)} raw items")
        except Exception as exc:
            print(f"  POLL/DOWNLOAD ERROR: {type(exc).__name__}: {exc}")
            return []

    # Inspect raw items
    error_items = [i for i in raw_items if i.get("error_code")]
    valid_items = [i for i in raw_items if not i.get("error_code")]
    print(f"  Valid items: {len(valid_items)}, Error items: {len(error_items)}")

    for i, item in enumerate(error_items[:3]):
        print(
            f"  Error [{i+1}]: code={item.get('error_code')}, "
            f"url={item.get('input', {}).get('url', '?')}"
        )

    if valid_items:
        item = valid_items[0]
        print(f"\n  First valid item keys: {sorted(item.keys())}")
        print(f"    post_id: {item.get('post_id', 'MISSING')}")
        print(f"    content: {str(item.get('content', ''))[:100]}")
        print(f"    url: {item.get('url', 'MISSING')}")
        print(f"    date_posted: {item.get('date_posted', 'MISSING')}")
        print(f"    page_name: {item.get('page_name', 'MISSING')}")
        print(f"    num_likes: {item.get('num_likes', 'MISSING')}")

    return valid_items


def step3_normalize(raw_items: list[dict]) -> list[dict]:
    """Normalize raw items and validate all required DB fields."""
    separator("Step 3: Normalization + Field Validation")

    if not raw_items:
        print("  SKIP — no raw items")
        return []

    from issue_observatory.arenas.facebook.collector import FacebookCollector

    collector = FacebookCollector(credential_pool=None)
    records = []

    # Required NOT NULL columns in content_records
    required_fields = {
        "platform": "VARCHAR(50) NOT NULL",
        "arena": "VARCHAR(50) NOT NULL",
        "content_type": "VARCHAR(50) NOT NULL",
        "collection_tier": "VARCHAR(10) NOT NULL",
        "published_at": "TIMESTAMPTZ NOT NULL (partition key)",
    }

    for i, item in enumerate(raw_items):
        try:
            record = collector.normalize(item, source="brightdata")
            records.append(record)

            # Validate required fields
            issues = []
            for field, desc in required_fields.items():
                val = record.get(field)
                if val is None or val == "":
                    issues.append(f"{field} is {val!r} ({desc})")

            # Check content_hash for dedup
            if not record.get("content_hash"):
                issues.append("content_hash is None (dedup won't work)")

            status = "FAIL" if issues else "OK"
            print(f"  [{i+1}] {status}")
            print(f"       platform_id={str(record.get('platform_id', 'NONE'))[:30]}")
            print(f"       content_type={record.get('content_type')}")
            print(f"       collection_tier={record.get('collection_tier')}")
            print(f"       published_at={record.get('published_at')}")
            print(f"       content_hash={str(record.get('content_hash', 'NONE'))[:20]}...")
            print(f"       text len={len(record.get('text_content') or '')}")
            if issues:
                for issue in issues:
                    print(f"       >>> {issue}")
        except Exception as exc:
            print(f"  [{i+1}] NORMALIZATION ERROR: {type(exc).__name__}: {exc}")
            import traceback

            traceback.print_exc()

    print(f"\n  Normalized {len(records)}/{len(raw_items)} records")
    return records


def step4_persist_individual(records: list[dict]) -> tuple[str, int, int]:
    """Persist records individually to the DB and report per-record outcomes."""
    separator("Step 4: Database Persistence (Individual Records)")

    if not records:
        print("  SKIP — no records")
        return "", 0, 0

    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session

    # Get a query design ID
    with get_sync_session() as db:
        qd_row = db.execute(
            text("SELECT id FROM query_designs WHERE is_active = true LIMIT 1")
        ).fetchone()
        if not qd_row:
            print("  ERROR: No active query design!")
            return "", 0, 0
        qd_id = str(qd_row[0])

        # Create test collection run
        run_id = str(uuid.uuid4())
        db.execute(
            text("""
                INSERT INTO collection_runs (id, query_design_id, status, tier, mode, started_at)
                VALUES (CAST(:id AS uuid), CAST(:qd_id AS uuid), 'running', 'medium', 'batch', NOW())
            """),
            {"id": run_id, "qd_id": qd_id},
        )
        db.commit()
        print(f"  Test run: {run_id}")

    from issue_observatory.workers._task_helpers import persist_collected_records

    print(f"  Persisting {len(records)} records...")
    try:
        inserted, skipped = persist_collected_records(records, run_id, qd_id)
        print(f"  Result: inserted={inserted}, skipped={skipped}")
    except Exception as exc:
        print(f"  PERSIST ERROR: {type(exc).__name__}: {exc}")
        import traceback

        traceback.print_exc()
        return run_id, 0, 0

    # Verify
    with get_sync_session() as db:
        count = db.execute(
            text(
                "SELECT COUNT(*) FROM content_records "
                "WHERE collection_run_id = CAST(:id AS uuid)"
            ),
            {"id": run_id},
        ).scalar()
        print(f"  Verified in DB: {count} records")

        if count and count > 0:
            samples = db.execute(
                text("""
                    SELECT platform_id, content_type, platform, arena,
                           collection_tier, published_at, content_hash
                    FROM content_records
                    WHERE collection_run_id = CAST(:id AS uuid)
                    LIMIT 3
                """),
                {"id": run_id},
            ).fetchall()
            for s in samples:
                print(
                    f"    pid={str(s[0])[:15]}.. type={s[1]} "
                    f"plat={s[2]} arena={s[3]} tier={s[4]} "
                    f"pub={s[5]} hash={str(s[6])[:15]}.."
                )

    return run_id, inserted, skipped


async def step5_full_pipeline(api_token: str) -> None:
    """Full pipeline with batch sink — mimics the Celery task exactly."""
    separator("Step 5: Full Pipeline with Batch Sink")

    from sqlalchemy import text

    from issue_observatory.arenas.base import Tier
    from issue_observatory.arenas.facebook.collector import FacebookCollector
    from issue_observatory.core.credential_pool import CredentialPool
    from issue_observatory.core.database import get_sync_session
    from issue_observatory.workers._task_helpers import (
        make_batch_sink,
        persist_collected_records,
    )

    # Create test collection run
    with get_sync_session() as db:
        qd_row = db.execute(
            text("SELECT id FROM query_designs WHERE is_active = true LIMIT 1")
        ).fetchone()
        qd_id = str(qd_row[0])
        run_id = str(uuid.uuid4())
        db.execute(
            text("""
                INSERT INTO collection_runs (id, query_design_id, status, tier, mode, started_at)
                VALUES (CAST(:id AS uuid), CAST(:qd_id AS uuid), 'running', 'medium', 'batch', NOW())
            """),
            {"id": run_id, "qd_id": qd_id},
        )
        db.commit()
        print(f"  Test run: {run_id}")

    pool = CredentialPool()
    collector = FacebookCollector(credential_pool=pool)

    sink = make_batch_sink(run_id, qd_id)
    collector.configure_batch_persistence(sink=sink, batch_size=100, collection_run_id=run_id)

    test_url = "https://www.facebook.com/drnyheder"
    print(f"  Collecting from: {test_url}")
    print(f"  Max results: 5, batch_size: 100")

    try:
        remaining = await collector.collect_by_actors(
            actor_ids=[test_url],
            tier=Tier.MEDIUM,
            max_results=5,
        )
    except Exception as exc:
        print(f"  COLLECTION ERROR: {type(exc).__name__}: {exc}")
        import traceback

        traceback.print_exc()
        return

    print(f"\n  Batch stats: {collector.batch_stats}")
    print(f"  Remaining in buffer: {len(remaining)}")

    fallback_inserted, fallback_skipped = 0, 0
    if remaining:
        print(f"  Persisting {len(remaining)} remaining records via fallback...")
        fallback_inserted, fallback_skipped = persist_collected_records(
            remaining, run_id, qd_id
        )
        print(f"  Fallback: inserted={fallback_inserted}, skipped={fallback_skipped}")

    total_inserted = collector.batch_stats["inserted"] + fallback_inserted
    total_skipped = collector.batch_stats["skipped"] + fallback_skipped
    print(f"\n  TOTAL: emitted={collector.batch_stats['emitted']}, "
          f"inserted={total_inserted}, skipped={total_skipped}")

    with get_sync_session() as db:
        count = db.execute(
            text(
                "SELECT COUNT(*) FROM content_records "
                "WHERE collection_run_id = CAST(:id AS uuid)"
            ),
            {"id": run_id},
        ).scalar()
        print(f"  Verified in DB: {count} records for run {run_id}")

    if total_inserted == 0 and collector.batch_stats["emitted"] > 0:
        print("\n  >>> CRITICAL: Records were emitted but none persisted!")
        print("  >>> Check the log output above for INSERT errors.")


async def main() -> None:
    separator("Facebook Arena Diagnostic — Full Pipeline Test")

    # Step 1
    cred = await step1_check_credentials()
    if not cred:
        print("  Cannot proceed without credentials.")
        return
    api_token = cred.get("api_token") or cred.get("api_key", "")
    if not api_token:
        print("  Credential exists but api_token is empty!")
        return

    # Step 2
    raw_items = await step2_collect_raw(api_token)
    if not raw_items:
        separator("BLOCKED — No Data from API")
        print("  Bright Data returned 0 valid items. Check:")
        print("  - Account credits at brightdata.com")
        print("  - Whether the page URL is accessible")
        return

    # Step 3
    records = step3_normalize(raw_items)

    # Step 4
    if records:
        run_id, inserted, skipped = step4_persist_individual(records)
    else:
        print("\n  Skipping persistence — no normalized records.")
        inserted, skipped = 0, 0

    # Step 5 — only run if step 4 worked
    if inserted > 0:
        print(
            "\n  Step 4 succeeded — running full pipeline test (Step 5) "
            "to verify batch sink..."
        )
        await step5_full_pipeline(api_token)
    elif records:
        print(
            "\n  Step 4 inserted 0 records despite having normalized records!"
        )
        print("  Skipping Step 5 — fix Step 4 issues first.")

    separator("Diagnostic Summary")
    if not raw_items:
        print("  ROOT CAUSE: Bright Data API returned 0 valid items")
    elif not records:
        print("  ROOT CAUSE: All records failed normalization")
    elif inserted == 0:
        print("  ROOT CAUSE: All records failed database insertion")
        print("  Check the log output above for SQL errors.")
    else:
        print(f"  Pipeline OK: {len(raw_items)} raw → {len(records)} normalized → {inserted} persisted")


if __name__ == "__main__":
    asyncio.run(main())
