"""Test the actual Bright Data Web Scraper API trigger + poll flow.

Simulates what the Facebook and Instagram collectors do:
1. Trigger a small snapshot (1 profile, 5 posts)
2. Poll for delivery status
3. Download results

Run with:
    .venv/bin/python scripts/test_brightdata_flow.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

BD_BASE = "https://api.brightdata.com/datasets/v3"
POLL_INTERVAL = 10  # seconds (shorter than collector's 30s for testing)
MAX_POLLS = 30  # ~5 minutes max


async def test_facebook_flow() -> None:
    """Test Facebook trigger → poll → download flow."""
    token = os.environ.get("BRIGHTDATA_FACEBOOK_API_TOKEN", "")
    if not token:
        print("[facebook] SKIP — no BRIGHTDATA_FACEBOOK_API_TOKEN")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Use a well-known public page for testing
    dataset_id = "gd_lkaxegm826bjpoo9m5"  # Posts scraper
    trigger_url = f"{BD_BASE}/trigger?dataset_id={dataset_id}&include_errors=true"
    payload = [
        {
            "url": "https://www.facebook.com/dr.dk",
            "num_of_posts": 3,
        }
    ]

    print(f"[facebook] Triggering snapshot for dr.dk (3 posts)...")
    print(f"[facebook] POST {trigger_url}")
    print(f"[facebook] Payload: {payload}")

    start = time.monotonic()
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Step 1: Trigger
        try:
            resp = await client.post(trigger_url, json=payload, headers=headers)
            elapsed = time.monotonic() - start
            print(f"[facebook] Trigger response: HTTP {resp.status_code} ({elapsed:.1f}s)")
            print(f"[facebook] Response body: {resp.text[:500]}")

            if resp.status_code not in (200, 201):
                print(f"[facebook] FAILED — trigger returned {resp.status_code}")
                return

            data = resp.json()
            snapshot_id = data.get("snapshot_id") or data.get("id")
            if not snapshot_id:
                print(f"[facebook] FAILED — no snapshot_id in response: {data}")
                return

            print(f"[facebook] Snapshot ID: {snapshot_id}")
        except Exception as exc:
            print(f"[facebook] ERROR triggering: {type(exc).__name__}: {exc}")
            return

        # Step 2: Poll
        progress_url = f"{BD_BASE}/progress/{snapshot_id}"
        snapshot_url = f"{BD_BASE}/snapshot/{snapshot_id}?format=json"

        for attempt in range(1, MAX_POLLS + 1):
            await asyncio.sleep(POLL_INTERVAL)
            elapsed = time.monotonic() - start
            try:
                prog_resp = await client.get(progress_url, headers=headers)
                prog_data = prog_resp.json()
                status = prog_data.get("status", "unknown")
                print(
                    f"[facebook] Poll {attempt}/{MAX_POLLS}: status={status} "
                    f"({elapsed:.0f}s elapsed) — full response: {prog_data}"
                )

                if status == "ready":
                    break
                if status in ("failed", "error"):
                    print(f"[facebook] FAILED — snapshot failed: {prog_data}")
                    return
            except Exception as exc:
                print(f"[facebook] Poll error: {type(exc).__name__}: {exc}")
        else:
            print(f"[facebook] TIMEOUT — snapshot not ready after {MAX_POLLS * POLL_INTERVAL}s")
            return

        # Step 3: Download
        try:
            dl_resp = await client.get(snapshot_url, headers=headers)
            elapsed = time.monotonic() - start
            print(f"[facebook] Download: HTTP {dl_resp.status_code} ({elapsed:.1f}s)")

            if dl_resp.status_code == 200:
                items = dl_resp.json()
                if isinstance(items, list):
                    print(f"[facebook] SUCCESS — {len(items)} posts downloaded")
                    for i, item in enumerate(items[:2]):
                        print(f"[facebook]   Post {i+1}: {item.get('url', 'no url')[:80]}")
                else:
                    print(f"[facebook] Response format: {type(items).__name__} — {str(items)[:200]}")
            else:
                print(f"[facebook] Download failed: {dl_resp.text[:200]}")
        except Exception as exc:
            print(f"[facebook] Download error: {type(exc).__name__}: {exc}")


async def test_instagram_flow() -> None:
    """Test Instagram trigger → poll → download flow."""
    token = os.environ.get("BRIGHTDATA_INSTAGRAM_API_TOKEN", "")
    if not token:
        print("[instagram] SKIP — no BRIGHTDATA_INSTAGRAM_API_TOKEN")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Posts scraper in discovery mode
    dataset_id = "gd_lk5ns7kz21pck8jpis"
    trigger_url = (
        f"{BD_BASE}/trigger?dataset_id={dataset_id}"
        "&include_errors=true&type=discover_new&discover_by=url"
    )
    payload = [
        {
            "url": "https://www.instagram.com/dr.dk/",
            "num_of_posts": 3,
        }
    ]

    print(f"\n[instagram] Triggering snapshot for dr.dk (3 posts)...")
    print(f"[instagram] POST {trigger_url}")
    print(f"[instagram] Payload: {payload}")

    start = time.monotonic()
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Step 1: Trigger
        try:
            resp = await client.post(trigger_url, json=payload, headers=headers)
            elapsed = time.monotonic() - start
            print(f"[instagram] Trigger response: HTTP {resp.status_code} ({elapsed:.1f}s)")
            print(f"[instagram] Response body: {resp.text[:500]}")

            if resp.status_code not in (200, 201):
                print(f"[instagram] FAILED — trigger returned {resp.status_code}")
                return

            data = resp.json()
            snapshot_id = data.get("snapshot_id") or data.get("id")
            if not snapshot_id:
                print(f"[instagram] FAILED — no snapshot_id in response: {data}")
                return

            print(f"[instagram] Snapshot ID: {snapshot_id}")
        except Exception as exc:
            print(f"[instagram] ERROR triggering: {type(exc).__name__}: {exc}")
            return

        # Step 2: Poll
        progress_url = f"{BD_BASE}/progress/{snapshot_id}"
        snapshot_url = f"{BD_BASE}/snapshot/{snapshot_id}?format=json"

        for attempt in range(1, MAX_POLLS + 1):
            await asyncio.sleep(POLL_INTERVAL)
            elapsed = time.monotonic() - start
            try:
                prog_resp = await client.get(progress_url, headers=headers)
                prog_data = prog_resp.json()
                status = prog_data.get("status", "unknown")
                print(
                    f"[instagram] Poll {attempt}/{MAX_POLLS}: status={status} "
                    f"({elapsed:.0f}s elapsed) — full response: {prog_data}"
                )

                if status == "ready":
                    break
                if status in ("failed", "error"):
                    print(f"[instagram] FAILED — snapshot failed: {prog_data}")
                    return
            except Exception as exc:
                print(f"[instagram] Poll error: {type(exc).__name__}: {exc}")
        else:
            print(f"[instagram] TIMEOUT — snapshot not ready after {MAX_POLLS * POLL_INTERVAL}s")
            return

        # Step 3: Download
        try:
            dl_resp = await client.get(snapshot_url, headers=headers)
            elapsed = time.monotonic() - start
            print(f"[instagram] Download: HTTP {dl_resp.status_code} ({elapsed:.1f}s)")

            if dl_resp.status_code == 200:
                items = dl_resp.json()
                if isinstance(items, list):
                    print(f"[instagram] SUCCESS — {len(items)} posts downloaded")
                    for i, item in enumerate(items[:2]):
                        print(f"[instagram]   Post {i+1}: {item.get('url', 'no url')[:80]}")
                else:
                    print(f"[instagram] Response format: {type(items).__name__} — {str(items)[:200]}")
            else:
                print(f"[instagram] Download failed: {dl_resp.text[:200]}")
        except Exception as exc:
            print(f"[instagram] Download error: {type(exc).__name__}: {exc}")


async def main() -> None:
    print("=" * 70)
    print("Bright Data Web Scraper API — End-to-End Flow Test")
    print("=" * 70)
    total_start = time.monotonic()

    # Run both in parallel
    await asyncio.gather(
        test_facebook_flow(),
        test_instagram_flow(),
    )

    total_elapsed = time.monotonic() - total_start
    print(f"\nTotal elapsed: {total_elapsed:.0f}s")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
