"""Test Facebook collection with chunking (25 URLs per trigger).

Sends 30 actor IDs to verify that the chunking logic works:
- Chunk 1: 25 URLs
- Chunk 2: 5 URLs

Run with:
    uv run python scripts/test_fb_chunking.py
"""
from __future__ import annotations

import logging
import sys
import uuid

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
for lib in ("httpx", "httpcore", "hpack", "urllib3", "asyncio"):
    logging.getLogger(lib).setLevel(logging.WARNING)

logger = logging.getLogger("test_fb_chunking")


def main() -> None:
    """Test chunked Facebook collection with 30 actors."""
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

    # 30 Danish political party Facebook pages (production-like set)
    actor_ids = [
        "socialdemokratiet",
        "Konservative",
        "venstre.dk",
        "LiberalAlliance",
        "DanskFolkeparti",
        "radikalevenstre",
        "sfpolitik",
        "NyBorgerlige",
        "alternativet.dk",
        "moderaterne",
        "enaborgen",
        "drnyheder",
        "tv2nyhederne",
        "LokomotivFonden",
        "LandbogSkov",
        "LarsLokkeRasmussen",
        "MetteFrederiksen.LikeHerPage",
        "PiaOlsenDyhr",
        "PerClausen.EL",
        "SorenPape",
        "JakobEllemann",
        "AlexVanopslagh",
        "PernilleVermund",
        "FranciskaStoettrup",
        "danmarksfrihedsbevagelse",
        "LeFolketing",
        "PolitikenDK",
        "beraborsen",
        "NyhedsavionenDK",
        "jabordet",
    ]

    print(f"Testing with {len(actor_ids)} actors (should produce 2 chunks of 25+5)")

    # Create test run
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

    print(f"Run: {run_id[:8]}...")

    pool = CredentialPool()
    collector = FacebookCollector(credential_pool=pool)
    sink = make_batch_sink(run_id, qd_id)
    collector.configure_batch_persistence(sink=sink, batch_size=100, collection_run_id=run_id)

    try:
        remaining, used_tier = run_with_tier_fallback(
            collector=collector,
            collect_method="collect_by_actors",
            kwargs={
                "actor_ids": actor_ids,
                "tier": Tier("premium"),
                "date_from": "2026-02-27T23:00:00+00:00",
                "date_to": "2026-03-04T23:00:00+00:00",
                "max_results": None,
            },
            requested_tier_str="premium",
            platform="facebook",
            task_logger=logger,
        )
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return

    print(f"\nUsed tier: {used_tier}")
    print(f"batch_stats: {collector.batch_stats}")
    print(f"Remaining in buffer: {len(remaining)}")

    fallback_inserted, fallback_skipped = 0, 0
    if remaining:
        fallback_inserted, fallback_skipped = persist_collected_records(remaining, run_id, qd_id)

    inserted = collector.batch_stats["inserted"] + fallback_inserted
    skipped = collector.batch_stats["skipped"] + fallback_skipped

    print(f"\nFINAL: inserted={inserted}, skipped={skipped}")

    # Verify DB
    with get_sync_session() as db:
        count = db.execute(
            text("SELECT COUNT(*) FROM content_records WHERE collection_run_id = CAST(:id AS uuid)"),
            {"id": run_id},
        ).scalar()
        print(f"DB content_records: {count}")

    if inserted > 0:
        print(f"\nSUCCESS: {inserted} records collected from {len(actor_ids)} actors with chunking")
    else:
        print("\nFAILED: 0 records collected — chunking didn't help")


if __name__ == "__main__":
    main()
