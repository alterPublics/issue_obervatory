"""Standalone Bright Data credit measurement script.

Measures exact API call count and posts collected for a single Facebook account
using the same Bright Data Web Scraper API flow as the application's
FacebookCollector.

Usage:
    python scripts/test_brightdata_credits.py

Requires BRIGHTDATA_FACEBOOK_API_TOKEN in .env (or environment).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load .env from project root
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

API_TOKEN = os.environ.get("BRIGHTDATA_FACEBOOK_API_TOKEN", "")
if not API_TOKEN:
    print("ERROR: BRIGHTDATA_FACEBOOK_API_TOKEN not set in .env or environment")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants — mirrored from arenas/facebook/config.py
# ---------------------------------------------------------------------------
BRIGHTDATA_API_BASE = "https://api.brightdata.com/datasets/v3"
FACEBOOK_DATASET_ID_POSTS = "gd_lkaxegm826bjpoo9m5"

POLL_INTERVAL = 30  # seconds between progress checks
MAX_POLL_ATTEMPTS = 40  # 40 * 30s = 20 minutes max

# ---------------------------------------------------------------------------
# Test parameters
# ---------------------------------------------------------------------------
TARGET_URL = "https://www.facebook.com/stemhalsboe"
DATE_FROM = "02-28-2026"  # MM-DD-YYYY (Bright Data format)
DATE_TO = "03-10-2026"    # MM-DD-YYYY
NUM_POSTS = 100           # matches _DEFAULT_NUM_POSTS in collector

# ---------------------------------------------------------------------------
# Tracking counters
# ---------------------------------------------------------------------------
api_calls: list[dict] = []  # log of every HTTP request made


def log_call(method: str, url: str, status: int, detail: str = "") -> None:
    """Record an API call for the final report."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "method": method,
        "url": url,
        "status": status,
        "detail": detail,
    }
    api_calls.append(entry)
    print(f"  [{len(api_calls):>3}] {method} {url.split('?')[0]}... → {status}  {detail}")


# ---------------------------------------------------------------------------
# Core flow — mirrors FacebookCollector._trigger_dataset + _poll_and_download
# ---------------------------------------------------------------------------

async def trigger_dataset(
    client: httpx.AsyncClient,
    dataset_id: str,
    payload: list[dict],
) -> str:
    """POST trigger request. Returns snapshot_id."""
    trigger_url = f"{BRIGHTDATA_API_BASE}/trigger?dataset_id={dataset_id}&include_errors=true"
    response = await client.post(
        trigger_url,
        json=payload,
        headers={
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    log_call("POST", trigger_url, response.status_code, f"payload_size={len(payload)}")
    response.raise_for_status()

    data = response.json()
    snapshot_id = data.get("snapshot_id") or data.get("id")
    if not snapshot_id:
        print(f"ERROR: No snapshot_id in response: {data}")
        sys.exit(1)
    return snapshot_id


async def poll_progress(
    client: httpx.AsyncClient,
    snapshot_id: str,
) -> None:
    """Poll until snapshot is ready. Each poll counts as an API call."""
    progress_url = f"{BRIGHTDATA_API_BASE}/progress/{snapshot_id}"
    headers = {"Authorization": f"Bearer {API_TOKEN}"}

    for attempt in range(1, MAX_POLL_ATTEMPTS + 1):
        response = await client.get(progress_url, headers=headers)
        data = response.json() if response.status_code == 200 else {}
        status = data.get("status", "unknown")
        log_call(
            "GET",
            progress_url,
            response.status_code,
            f"status={status} attempt={attempt}/{MAX_POLL_ATTEMPTS}",
        )

        if status == "ready":
            return
        if status in ("failed", "error"):
            print(f"ERROR: Snapshot {snapshot_id} failed: {data}")
            sys.exit(1)

        if attempt < MAX_POLL_ATTEMPTS:
            await asyncio.sleep(POLL_INTERVAL)

    print(f"ERROR: Snapshot {snapshot_id} timed out after {MAX_POLL_ATTEMPTS * POLL_INTERVAL}s")
    sys.exit(1)


async def download_snapshot(
    client: httpx.AsyncClient,
    snapshot_id: str,
) -> list[dict]:
    """Download completed snapshot. Returns raw items."""
    snapshot_url = f"{BRIGHTDATA_API_BASE}/snapshot/{snapshot_id}?format=json"
    headers = {"Authorization": f"Bearer {API_TOKEN}"}

    response = await client.get(snapshot_url, headers=headers)
    log_call("GET", snapshot_url, response.status_code, f"content_length={len(response.content)}")
    response.raise_for_status()

    raw_items = response.json()
    if not isinstance(raw_items, list):
        raw_items = raw_items.get("data", []) if isinstance(raw_items, dict) else []
    return raw_items


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

def analyze_results(raw_items: list[dict]) -> dict:
    """Analyze the raw results, separating valid posts from errors."""
    valid = []
    errors = []

    for item in raw_items:
        if item.get("error_code"):
            errors.append({
                "url": (item.get("input") or {}).get("url", "unknown"),
                "error_code": item.get("error_code"),
                "error": item.get("error", ""),
            })
        else:
            valid.append(item)

    # Extract date range of collected posts
    dates = []
    for item in valid:
        date_str = item.get("date_posted") or item.get("created_time") or item.get("date")
        if date_str:
            dates.append(date_str)

    return {
        "total_raw_items": len(raw_items),
        "valid_posts": len(valid),
        "error_records": len(errors),
        "errors": errors,
        "date_range": {
            "earliest": min(dates) if dates else None,
            "latest": max(dates) if dates else None,
        },
        "sample_fields": list(valid[0].keys()) if valid else [],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 70)
    print("BRIGHT DATA CREDIT MEASUREMENT TEST")
    print("=" * 70)
    print(f"Target:     {TARGET_URL}")
    print(f"Date range: {DATE_FROM} → {DATE_TO} (MM-DD-YYYY)")
    print(f"num_posts:  {NUM_POSTS}")
    print(f"Dataset ID: {FACEBOOK_DATASET_ID_POSTS}")
    print(f"API token:  {API_TOKEN[:8]}...{API_TOKEN[-4:]}")
    print("=" * 70)

    # Build payload — exactly as the app does in _collect_brightdata_actors
    payload = [
        {
            "url": TARGET_URL,
            "num_of_posts": NUM_POSTS,
            "start_date": DATE_FROM,
            "end_date": DATE_TO,
        }
    ]

    print(f"\nPayload:\n{json.dumps(payload, indent=2)}\n")
    print("--- API Call Log ---")

    start_time = time.monotonic()

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Step 1: Trigger
        snapshot_id = await trigger_dataset(client, FACEBOOK_DATASET_ID_POSTS, payload)
        print(f"\nSnapshot ID: {snapshot_id}\n")

        # Step 2: Poll
        await poll_progress(client, snapshot_id)

        # Step 3: Download
        raw_items = await download_snapshot(client, snapshot_id)

    elapsed = time.monotonic() - start_time

    # Analyze
    analysis = analyze_results(raw_items)

    # ---------------------------------------------------------------------------
    # Report
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"Total API calls made:     {len(api_calls)}")
    print(f"  - Trigger (POST):       {sum(1 for c in api_calls if c['method'] == 'POST')}")
    poll_calls = sum(
        1 for c in api_calls
        if c["method"] == "GET" and "/progress/" in c["url"]
    )
    print(f"  - Progress polls (GET): {poll_calls}")
    dl_calls = sum(
        1 for c in api_calls
        if c["method"] == "GET" and "/snapshot/" in c["url"]
    )
    print(f"  - Download (GET):       {dl_calls}")
    print()
    print(f"Raw items returned:       {analysis['total_raw_items']}")
    print(f"Valid posts:              {analysis['valid_posts']}")
    print(f"Error records:            {analysis['error_records']}")
    print(f"Post date range:          {analysis['date_range']['earliest']} → "
          f"{analysis['date_range']['latest']}")
    print()
    print(f"Elapsed time:             {elapsed:.1f}s")
    print()

    if analysis["errors"]:
        print("Error details:")
        for err in analysis["errors"]:
            print(f"  - {err['error_code']}: {err['error']}")
        print()

    # Cost estimate (from config.py: $0.0015/record)
    cost_per_record = 0.0015
    estimated_cost = analysis["valid_posts"] * cost_per_record
    print(f"Estimated cost:           ${estimated_cost:.4f} "
          f"({analysis['valid_posts']} records × ${cost_per_record}/record)")
    print()

    if analysis["sample_fields"]:
        print(f"Fields in raw records ({len(analysis['sample_fields'])}):")
        for f in sorted(analysis["sample_fields"]):
            print(f"  - {f}")

    # Save raw data for inspection
    output_path = PROJECT_ROOT / "scripts" / "brightdata_credit_test_results.json"
    output_data = {
        "test_params": {
            "target_url": TARGET_URL,
            "date_from": DATE_FROM,
            "date_to": DATE_TO,
            "num_posts": NUM_POSTS,
            "dataset_id": FACEBOOK_DATASET_ID_POSTS,
        },
        "api_calls": api_calls,
        "summary": {
            "total_api_calls": len(api_calls),
            "trigger_calls": sum(1 for c in api_calls if c["method"] == "POST"),
            "poll_calls": poll_calls,
            "download_calls": dl_calls,
            "total_raw_items": analysis["total_raw_items"],
            "valid_posts": analysis["valid_posts"],
            "error_records": analysis["error_records"],
            "elapsed_seconds": round(elapsed, 1),
            "estimated_cost_usd": round(estimated_cost, 4),
        },
        "date_range": analysis["date_range"],
        "raw_items": raw_items,
    }
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2, default=str)
    print(f"\nFull results saved to: {output_path}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
