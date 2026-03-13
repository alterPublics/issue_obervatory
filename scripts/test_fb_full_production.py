"""Simulate the EXACT production Facebook Celery task flow.

Uses the same code path as facebook_collect_actors:
1. Configure collector + batch sink
2. Coverage check (with dates)
3. run_with_tier_fallback (tier=premium → fallback to medium)
4. Report batch_stats

Run with:
    uv run python scripts/test_fb_full_production.py
"""
from __future__ import annotations

import logging
import sys
import time
import uuid

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
for lib in ("httpx", "httpcore", "hpack", "urllib3", "asyncio"):
    logging.getLogger(lib).setLevel(logging.WARNING)

logger = logging.getLogger("test_fb_full_prod")


def main() -> None:
    """Reproduce the exact facebook_collect_actors task body."""
    from datetime import datetime as _dt

    from sqlalchemy import text

    from issue_observatory.arenas.base import Tier
    from issue_observatory.arenas.facebook.collector import FacebookCollector
    from issue_observatory.config.settings import get_settings
    from issue_observatory.core.credential_pool import CredentialPool
    from issue_observatory.core.database import get_sync_session
    from issue_observatory.workers._task_helpers import (
        make_batch_sink,
        persist_collected_records,
        run_with_tier_fallback,
    )

    _settings = get_settings()

    # -- Create test run (same as production) --
    with get_sync_session() as db:
        qd_row = db.execute(
            text("SELECT id FROM query_designs WHERE is_active = true LIMIT 1")
        ).fetchone()
        qd_id = str(qd_row[0])
        user_row = db.execute(text("SELECT id FROM users LIMIT 1")).fetchone()
        user_id = str(user_row[0])
        run_id = str(uuid.uuid4())
        db.execute(
            text("""
                INSERT INTO collection_runs (id, query_design_id, status, tier, mode, started_at, initiated_by)
                VALUES (CAST(:id AS uuid), CAST(:qd_id AS uuid), 'running', 'premium', 'batch', NOW(), CAST(:uid AS uuid))
            """),
            {"id": run_id, "qd_id": qd_id, "uid": user_id},
        )
        db.commit()

    collection_run_id = run_id
    query_design_id = qd_id
    actor_ids = [
        "socialdemokratiet",
        "Konservative",
        "venstre.dk",
    ]
    tier = "premium"
    date_from = "2026-02-27T23:00:00+00:00"
    date_to = "2026-03-04T23:00:00+00:00"
    max_results = None

    print(f"Run: {run_id}")
    print(f"Tier: {tier}")
    print(f"Actors: {actor_ids}")
    print(f"Dates: {date_from} to {date_to}")

    # -- Reproduce the task body --
    tier_enum = Tier(tier)

    credential_pool = CredentialPool()
    collector = FacebookCollector(credential_pool=credential_pool)
    sink = make_batch_sink(collection_run_id, query_design_id)
    collector.configure_batch_persistence(sink=sink, batch_size=100, collection_run_id=collection_run_id)

    # Coverage check (same as production)
    force_recollect = False
    effective_date_from = date_from
    effective_date_to = date_to

    if not force_recollect and date_from and date_to:
        from issue_observatory.core.coverage_checker import check_existing_coverage

        print("\n--- Coverage Check ---")
        gaps = check_existing_coverage(
            platform="facebook",
            date_from=_dt.fromisoformat(date_from),
            date_to=_dt.fromisoformat(date_to),
            actor_ids=actor_ids,
        )
        print(f"  Gaps: {gaps}")
        if not gaps:
            print("  COVERAGE SKIP — would skip API call!")
            # In production, this returns early with records_collected=0
            # This is the root cause if this path is taken!
            return
        effective_date_from = gaps[0][0].isoformat()
        effective_date_to = gaps[-1][1].isoformat()
        print(f"  Effective dates: {effective_date_from} to {effective_date_to}")

    # run_with_tier_fallback (same as production)
    print("\n--- run_with_tier_fallback ---")
    try:
        remaining, used_tier = run_with_tier_fallback(
            collector=collector,
            collect_method="collect_by_actors",
            kwargs={
                "actor_ids": actor_ids,
                "tier": tier_enum,
                "date_from": effective_date_from,
                "date_to": effective_date_to,
                "max_results": max_results,
            },
            requested_tier_str=tier,
            platform="facebook",
            task_logger=logger,
        )
        print(f"  Used tier: {used_tier}")
        print(f"  Remaining: {len(remaining)}")
    except Exception as exc:
        print(f"  ERROR: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return

    # Report (same as production)
    print("\n--- Batch Stats ---")
    print(f"  batch_stats: {collector.batch_stats}")
    print(f"  _batch_errors: {collector._batch_errors}")

    fallback_inserted, fallback_skipped = 0, 0
    if remaining:
        fallback_inserted, fallback_skipped = persist_collected_records(
            remaining, collection_run_id, query_design_id
        )
        print(f"  Fallback: inserted={fallback_inserted}, skipped={fallback_skipped}")

    inserted = collector.batch_stats["inserted"] + fallback_inserted
    skipped = collector.batch_stats["skipped"] + fallback_skipped

    print(f"\n  FINAL: inserted={inserted}, skipped={skipped}")
    print(f"  This is what collection_tasks.records_collected would be set to.")

    # Verify DB
    with get_sync_session() as db:
        count = db.execute(
            text("SELECT COUNT(*) FROM content_records WHERE collection_run_id = CAST(:id AS uuid)"),
            {"id": run_id},
        ).scalar()
        run_records = db.execute(
            text("SELECT records_collected FROM collection_runs WHERE id = CAST(:id AS uuid)"),
            {"id": run_id},
        ).scalar()
        print(f"  DB content_records: {count}")
        print(f"  DB collection_runs.records_collected: {run_records}")

    if inserted == 0 and count > 0:
        print("\n  >>> BUG: Records in DB but inserted count is 0!")
    elif inserted == 0 and count == 0:
        print("\n  >>> Both 0 — either coverage skip or API returned 0 valid items")
    else:
        print(f"\n  OK: {inserted} records properly tracked")


if __name__ == "__main__":
    main()
