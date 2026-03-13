"""Test Facebook collection with actual production actor IDs (bare usernames).

Tests 3 bare usernames from the Udenrigspolitik og forsvar query design
to see if Bright Data returns valid data or error records.

Run with:
    uv run python scripts/test_fb_production_actors.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

for lib in ("httpx", "httpcore", "hpack", "urllib3"):
    logging.getLogger(lib).setLevel(logging.WARNING)

logger = logging.getLogger("test_fb_actors")


async def main() -> None:
    import httpx

    from issue_observatory.arenas.facebook.collector import (
        FacebookCollector,
        _normalize_facebook_url,
    )
    from issue_observatory.arenas.facebook.config import (
        FACEBOOK_DATASET_ID_POSTS,
        build_trigger_url,
    )
    from issue_observatory.core.credential_pool import CredentialPool

    pool = CredentialPool()
    collector = FacebookCollector(credential_pool=pool)

    cred = await pool.acquire(platform="brightdata_facebook", tier="medium")
    if not cred:
        print("ERROR: No credential available")
        return
    api_token = cred.get("api_token") or cred.get("api_key", "")
    cred_id = cred["id"]

    # Test with actual production bare usernames
    test_actors = [
        "socialdemokratiet",        # Danish Social Democrats
        "Konservative",             # Danish Conservative party
        "venstre.dk",               # Danish Liberal party
    ]

    print("=" * 70)
    print("  Testing bare usernames from production")
    print("=" * 70)

    # Normalize URLs (same as production code)
    normalized = []
    for actor in test_actors:
        url = _normalize_facebook_url(actor)
        print(f"  {actor} → {url}")
        if url:
            normalized.append(url)

    # Build payload
    payload = [{"url": url, "num_of_posts": 5} for url in normalized]
    trigger_url = build_trigger_url(FACEBOOK_DATASET_ID_POSTS)

    print(f"\n  Trigger URL: {trigger_url}")
    print(f"  Payload: {json.dumps(payload, indent=2)}")

    async with httpx.AsyncClient(timeout=120.0) as client:
        # Trigger
        print("\n  Triggering Bright Data API...")
        try:
            snapshot_id = await collector._trigger_dataset(
                client, api_token, trigger_url, payload
            )
            print(f"  Snapshot ID: {snapshot_id}")
        except Exception as exc:
            print(f"  TRIGGER ERROR: {type(exc).__name__}: {exc}")
            # Try to see the actual response body
            if hasattr(exc, '__cause__') and hasattr(exc.__cause__, 'response'):
                resp = exc.__cause__.response
                print(f"  Response body: {resp.text[:500]}")
            await pool.release(credential_id=cred_id)
            return

        # Poll and download
        print("  Polling for results...")
        try:
            raw_items = await collector._poll_and_download(client, api_token, snapshot_id)
            print(f"\n  Downloaded {len(raw_items)} raw items")
        except Exception as exc:
            print(f"  POLL ERROR: {type(exc).__name__}: {exc}")
            await pool.release(credential_id=cred_id)
            return

    await pool.release(credential_id=cred_id)

    # Analyze results
    error_items = [i for i in raw_items if i.get("error_code")]
    valid_items = [i for i in raw_items if not i.get("error_code")]

    print(f"\n  Valid items: {len(valid_items)}")
    print(f"  Error items: {len(error_items)}")

    for i, item in enumerate(error_items[:5]):
        input_url = (item.get("input") or {}).get("url", "?")
        print(f"\n  Error [{i+1}]:")
        print(f"    input_url: {input_url}")
        print(f"    error_code: {item.get('error_code')}")
        print(f"    error: {item.get('error', '')[:200]}")

    for i, item in enumerate(valid_items[:3]):
        print(f"\n  Valid [{i+1}]:")
        print(f"    post_id: {item.get('post_id', 'MISSING')}")
        print(f"    page_name: {item.get('page_name', 'MISSING')}")
        print(f"    url: {item.get('url', 'MISSING')}")
        print(f"    content: {str(item.get('content', ''))[:100]}")
        print(f"    date_posted: {item.get('date_posted', 'MISSING')}")

    if error_items and not valid_items:
        print("\n" + "=" * 70)
        print("  ROOT CAUSE: ALL items are error records!")
        print("  Bright Data cannot scrape these Facebook pages.")
        print("  Common causes:")
        print("    - Pages require login (privacy settings)")
        print("    - Pages don't exist or were renamed")
        print("    - Bright Data scraper blocked by Facebook")
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
