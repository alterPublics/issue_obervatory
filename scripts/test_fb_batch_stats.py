"""Test whether batch_stats reports correctly through run_with_tier_fallback.

Reproduces the exact production flow to find why collection_tasks.records_collected = 0
when records ARE being persisted.

Run with:
    uv run python scripts/test_fb_batch_stats.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
import uuid

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("test_fb_batch_stats")

for lib in ("httpx", "httpcore", "hpack", "urllib3"):
    logging.getLogger(lib).setLevel(logging.WARNING)


def main() -> None:
    from sqlalchemy import text

    from issue_observatory.arenas.base import Tier
    from issue_observatory.arenas.facebook.collector import FacebookCollector
    from issue_observatory.core.credential_pool import CredentialPool
    from issue_observatory.core.database import get_sync_session
    from issue_observatory.workers._task_helpers import (
        make_batch_sink,
        persist_collected_records,
        run_with_tier_fallback,
    )

    # -- Setup: create test run --
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
    print(f"Test run: {run_id}")

    # -- Create collector with batch sink (same as production) --
    pool = CredentialPool()
    collector = FacebookCollector(credential_pool=pool)
    sink = make_batch_sink(run_id, qd_id)
    collector.configure_batch_persistence(sink=sink, batch_size=100, collection_run_id=run_id)

    test_url = "https://www.facebook.com/drnyheder"

    # =====================================================
    # Test A: Direct await (like diagnostic step 5)
    # =====================================================
    print("\n=== TEST A: Direct await ===")
    remaining_a = asyncio.run(
        collector.collect_by_actors(
            actor_ids=[test_url],
            tier=Tier.MEDIUM,
            max_results=3,
        )
    )
    print(f"  batch_stats: {collector.batch_stats}")
    print(f"  remaining: {len(remaining_a)}")
    print(f"  _total_inserted: {collector._total_inserted}")
    print(f"  _total_emitted: {collector._total_emitted}")
    print(f"  _record_sink is None: {collector._record_sink is None}")
    print(f"  _batch_errors: {collector._batch_errors}")

    # Fallback persist for remaining
    fb_ins_a, fb_skip_a = 0, 0
    if remaining_a:
        fb_ins_a, fb_skip_a = persist_collected_records(remaining_a, run_id, qd_id)
    total_a = collector.batch_stats["inserted"] + fb_ins_a
    print(f"  TOTAL inserted (batch + fallback): {total_a}")

    # =====================================================
    # Test B: Through run_with_tier_fallback with tier=premium
    # (This is the EXACT production path)
    # =====================================================
    print("\n=== TEST B: run_with_tier_fallback (tier=premium) ===")

    # Create a fresh run for test B
    run_id_b = str(uuid.uuid4())
    with get_sync_session() as db:
        db.execute(
            text("""
                INSERT INTO collection_runs (id, query_design_id, status, tier, mode, started_at, initiated_by)
                VALUES (CAST(:id AS uuid), CAST(:qd_id AS uuid), 'running', 'premium', 'batch', NOW(), CAST(:uid AS uuid))
            """),
            {"id": run_id_b, "qd_id": qd_id, "uid": user_id},
        )
        db.commit()
    print(f"  Test run B: {run_id_b}")

    # Re-create collector with fresh batch sink for run B
    collector_b = FacebookCollector(credential_pool=pool)
    sink_b = make_batch_sink(run_id_b, qd_id)
    collector_b.configure_batch_persistence(sink=sink_b, batch_size=100, collection_run_id=run_id_b)

    try:
        remaining_b, used_tier = run_with_tier_fallback(
            collector=collector_b,
            collect_method="collect_by_actors",
            kwargs={
                "actor_ids": [test_url],
                "tier": Tier("premium"),
                "max_results": 3,
            },
            requested_tier_str="premium",
            platform="facebook",
            task_logger=logger,
        )
    except Exception as exc:
        print(f"  ERROR: {type(exc).__name__}: {exc}")
        remaining_b = []

    print(f"  batch_stats: {collector_b.batch_stats}")
    print(f"  remaining: {len(remaining_b)}")
    print(f"  _total_inserted: {collector_b._total_inserted}")
    print(f"  _total_emitted: {collector_b._total_emitted}")
    print(f"  _record_sink is None: {collector_b._record_sink is None}")
    print(f"  _batch_errors: {collector_b._batch_errors}")

    # Fallback persist for remaining
    fb_ins_b, fb_skip_b = 0, 0
    if remaining_b:
        fb_ins_b, fb_skip_b = persist_collected_records(remaining_b, run_id_b, qd_id)
    total_b = collector_b.batch_stats["inserted"] + fb_ins_b
    print(f"  TOTAL inserted (batch + fallback): {total_b}")

    # =====================================================
    # Verify DB counts
    # =====================================================
    print("\n=== DB Verification ===")
    with get_sync_session() as db:
        for label, rid in [("A", run_id), ("B", run_id_b)]:
            count = db.execute(
                text("SELECT COUNT(*) FROM content_records WHERE collection_run_id = CAST(:id AS uuid)"),
                {"id": rid},
            ).scalar()
            run_count = db.execute(
                text("SELECT records_collected FROM collection_runs WHERE id = CAST(:id AS uuid)"),
                {"id": rid},
            ).scalar()
            print(f"  Run {label} ({rid[:8]}): DB records={count}, run.records_collected={run_count}")

    print("\n=== DIAGNOSIS ===")
    if total_a > 0 and total_b == 0:
        print("  BUG CONFIRMED: run_with_tier_fallback causes batch_stats to report 0")
        print("  Records are persisted but the count is not tracked correctly.")
    elif total_a > 0 and total_b > 0:
        print("  Both paths work — issue may be intermittent or environment-specific.")
    else:
        print(f"  Test A total={total_a}, Test B total={total_b}")


if __name__ == "__main__":
    main()
