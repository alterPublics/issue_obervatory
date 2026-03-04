"""Test Bright Data Web Scraper API keyword discovery for Facebook and Instagram.

Quick test to determine which dataset IDs support `type=discover_new&discover_by=keyword`.
Uses the synchronous /scrape endpoint with small limits to minimize cost.

Usage:
    python scripts/test_brightdata_discovery.py
"""

from __future__ import annotations

import json
import os
import sys
import time

import requests

API_TOKEN = os.environ.get("BRIGHTDATA_FACEBOOK_API_TOKEN", "")
BASE_URL = "https://api.brightdata.com/datasets/v3"

HEADERS = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json",
}

# Dataset IDs to test keyword discovery on
DATASETS_TO_TEST = {
    "facebook_posts": "gd_lkaxegm826bjpoo9m5",
    "facebook_reels": "gd_lyclm3ey2q6rww027t",
    "facebook_groups": "gd_lz11l67o2cb3r0lkj3",
    "instagram_posts": "gd_lk5ns7kz21pck8jpis",
    "instagram_reels": "gd_lyclm20il4r5helnj",
}

KEYWORD = "grønland"


def test_sync_discovery(name: str, dataset_id: str) -> None:
    """Test synchronous keyword discovery on a single dataset."""
    print(f"\n{'='*60}")
    print(f"Testing: {name} (dataset_id={dataset_id})")
    print(f"Keyword: {KEYWORD}")
    print(f"{'='*60}")

    url = (
        f"{BASE_URL}/scrape"
        f"?dataset_id={dataset_id}"
        f"&notify=false"
        f"&include_errors=true"
        f"&type=discover_new"
        f"&discover_by=keyword"
        f"&limit_multiple_results=3"
    )

    payload = json.dumps([{"keyword": KEYWORD}])

    print(f"POST {url}")
    print(f"Payload: {payload}")
    print()

    try:
        response = requests.post(url, headers=HEADERS, data=payload, timeout=120)
        print(f"Status: {response.status_code}")
        print(f"Headers: content-type={response.headers.get('content-type')}")

        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                print(f"SUCCESS: Got {len(data)} record(s)")
                if data:
                    print(f"First record keys: {list(data[0].keys())}")
                    # Print a summary of the first record
                    first = data[0]
                    print(f"  url: {first.get('url', 'N/A')}")
                    print(f"  content: {(first.get('content') or first.get('description') or 'N/A')[:100]}")
                    print(f"  date_posted: {first.get('date_posted', 'N/A')}")
                    print(f"  num_likes: {first.get('num_likes') or first.get('likes', 'N/A')}")
            elif isinstance(data, dict):
                # Might be a snapshot_id (async fallback) or error
                print(f"Response dict: {json.dumps(data, indent=2)[:500]}")
            else:
                print(f"Unexpected response type: {type(data)}")
        elif response.status_code == 202:
            # Async fallback -- scrape took too long, got snapshot_id
            data = response.json()
            print(f"ASYNC FALLBACK (202): snapshot_id={data.get('snapshot_id')}")
            print("Keyword discovery IS supported, but needs async polling.")
        else:
            print(f"FAILED: {response.status_code}")
            try:
                print(f"Error body: {response.text[:500]}")
            except Exception:
                pass

    except requests.exceptions.Timeout:
        print("TIMEOUT (120s) -- likely needs async trigger instead")
    except Exception as exc:
        print(f"ERROR: {exc}")


def test_async_discovery(name: str, dataset_id: str) -> None:
    """Test async keyword discovery using the trigger endpoint."""
    print(f"\n{'='*60}")
    print(f"Testing ASYNC: {name} (dataset_id={dataset_id})")
    print(f"{'='*60}")

    url = (
        f"{BASE_URL}/trigger"
        f"?dataset_id={dataset_id}"
        f"&notify=false"
        f"&include_errors=true"
        f"&type=discover_new"
        f"&discover_by=keyword"
        f"&limit_multiple_results=3"
    )

    payload = json.dumps([{"keyword": KEYWORD}])

    print(f"POST {url}")
    try:
        response = requests.post(url, headers=HEADERS, data=payload, timeout=30)
        print(f"Status: {response.status_code}")

        if response.status_code in (200, 201):
            data = response.json()
            snapshot_id = data.get("snapshot_id")
            print(f"Trigger OK: snapshot_id={snapshot_id}")

            if snapshot_id:
                # Poll for progress
                for attempt in range(1, 13):  # 12 attempts, 10s apart = 2 min max
                    time.sleep(10)
                    progress_url = f"{BASE_URL}/progress/{snapshot_id}"
                    prog_resp = requests.get(progress_url, headers=HEADERS, timeout=15)
                    prog_data = prog_resp.json()
                    status = prog_data.get("status", "unknown")
                    print(f"  Poll {attempt}: status={status}")

                    if status == "ready":
                        # Download snapshot
                        snap_url = f"{BASE_URL}/snapshot/{snapshot_id}?format=json"
                        snap_resp = requests.get(snap_url, headers=HEADERS, timeout=30)
                        if snap_resp.status_code == 200:
                            records = snap_resp.json()
                            if isinstance(records, list):
                                print(f"SUCCESS: Got {len(records)} record(s)")
                                if records:
                                    print(f"First record keys: {list(records[0].keys())}")
                                    first = records[0]
                                    print(f"  url: {first.get('url', 'N/A')}")
                                    content = first.get("content") or first.get("description") or "N/A"
                                    print(f"  content: {content[:100]}")
                            else:
                                print(f"Snapshot response: {str(records)[:300]}")
                        break

                    if status in ("failed", "error"):
                        print(f"  FAILED: {prog_data}")
                        break
                else:
                    print("  Timed out waiting for results (2 min)")
        else:
            print(f"FAILED: {response.text[:500]}")

    except Exception as exc:
        print(f"ERROR: {exc}")


if __name__ == "__main__":
    print("Bright Data Web Scraper API -- Keyword Discovery Test")
    print(f"Testing keyword: '{KEYWORD}'")
    print(f"Testing {len(DATASETS_TO_TEST)} dataset(s)")

    # Test synchronous first (faster, cheaper for small requests)
    for name, dataset_id in DATASETS_TO_TEST.items():
        test_sync_discovery(name, dataset_id)

    # If any returned 202 (async fallback), we could test async too
    print("\n" + "="*60)
    print("SYNC TESTS COMPLETE")
    print("="*60)

    if "--async" in sys.argv:
        print("\nRunning async tests...")
        for name, dataset_id in DATASETS_TO_TEST.items():
            test_async_discovery(name, dataset_id)
