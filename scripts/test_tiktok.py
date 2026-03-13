"""Standalone TikTok Research API diagnostic script.

Tests OAuth token acquisition and video query with a few search terms.
Does NOT persist any records. Reads credentials directly from the DB
without importing the full app settings.

Usage:
    .venv/bin/python scripts/test_tiktok.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

# Load .env manually (no pydantic-settings dependency)
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if not os.environ.get(key):
            os.environ[key] = val

# TikTok API endpoints / constants
TIKTOK_OAUTH_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_VIDEO_QUERY_URL = "https://open.tiktokapis.com/v2/research/video/query/"
TIKTOK_VIDEO_FIELDS = (
    "id,video_description,create_time,region_code,share_count,"
    "view_count,like_count,comment_count,music_id,hashtag_names,"
    "username,effect_ids,playlist_id,voice_to_text"
)
TIKTOK_DATE_FORMAT = "%Y%m%d"
TIKTOK_REGION_CODE = "DK"


def _get_credentials() -> tuple[str, str]:
    """Read TikTok client_key / client_secret from DB or env."""
    db_url = os.environ.get("DATABASE_URL", "")
    sync_url = db_url.replace("+asyncpg", "+psycopg2").replace("asyncpg://", "psycopg2://")

    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(sync_url)
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, credentials FROM api_credentials "
                    "WHERE platform = 'tiktok' AND is_active = true LIMIT 1"
                )
            ).fetchone()

        if row:
            from cryptography.fernet import Fernet

            enc_key = os.environ.get("CREDENTIAL_ENCRYPTION_KEY", "")
            fernet = Fernet(enc_key.encode())
            creds = json.loads(fernet.decrypt(row[1]).decode())
            ck = creds.get("client_key", "")
            cs = creds.get("client_secret", "")
            print(f"Loaded credentials from DB (client_key={ck[:8]}...)")
            return ck, cs
    except Exception as exc:
        print(f"  DB credential lookup failed: {exc}")

    ck = os.environ.get("TIKTOK_CLIENT_KEY", "")
    cs = os.environ.get("TIKTOK_CLIENT_SECRET", "")
    if ck and cs:
        print(f"Using env var credentials (client_key={ck[:8]}...)")
        return ck, cs

    print("ERROR: No TikTok credentials found in DB or env vars.")
    sys.exit(1)


async def main() -> None:
    client_key, client_secret = _get_credentials()

    # ---- 1. Get OAuth token ----
    print("\n--- Step 1: OAuth token request ---")
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            TIKTOK_OAUTH_URL,
            data={
                "client_key": client_key,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        print(f"  Status: {resp.status_code}")
        token_data = resp.json()
        print(f"  Response keys: {list(token_data.keys())}")

        if resp.status_code != 200:
            print(f"  Full response: {json.dumps(token_data, indent=2)}")
            sys.exit(1)

        token = token_data.get("access_token", "")
        expires_in = token_data.get("expires_in", 0)
        if not token:
            print(f"  ERROR: No access_token in response: {token_data}")
            sys.exit(1)
        print(f"  Token acquired (expires_in={expires_in}s)")

    # ---- 2. Test video queries ----
    # Use a window ending 3 days ago (avoid indexing lag) spanning 7 days
    end_dt = datetime.now(tz=timezone.utc) - timedelta(days=3)
    start_dt = end_dt - timedelta(days=7)

    test_terms = ["grønland", "nato", "trump"]

    print(f"\n--- Step 2: Video queries ---")
    print(f"  Date range: {start_dt.strftime(TIKTOK_DATE_FORMAT)} - {end_dt.strftime(TIKTOK_DATE_FORMAT)}")
    print(f"  Region: {TIKTOK_REGION_CODE}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        for term in test_terms:
            body = {
                "query": {
                    "and": [
                        {
                            "operation": "IN",
                            "field_name": "region_code",
                            "field_values": [TIKTOK_REGION_CODE],
                        },
                        {
                            "operation": "EQ",
                            "field_name": "keyword",
                            "field_values": [term],
                        },
                    ]
                },
                "start_date": start_dt.strftime(TIKTOK_DATE_FORMAT),
                "end_date": end_dt.strftime(TIKTOK_DATE_FORMAT),
                "max_count": 10,
            }
            url = f"{TIKTOK_VIDEO_QUERY_URL}?fields={TIKTOK_VIDEO_FIELDS}"
            print(f"\n  Term: '{term}'")

            resp = await client.post(
                url,
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
            print(f"  HTTP {resp.status_code}")

            if resp.status_code != 200:
                print(f"  Response: {resp.text[:500]}")
                # Try without region filter to isolate the issue
                body_no_region = {
                    "query": {
                        "and": [
                            {
                                "operation": "EQ",
                                "field_name": "keyword",
                                "field_values": [term],
                            },
                        ]
                    },
                    "start_date": start_dt.strftime(TIKTOK_DATE_FORMAT),
                    "end_date": end_dt.strftime(TIKTOK_DATE_FORMAT),
                    "max_count": 5,
                }
                print(f"  Retrying WITHOUT region filter...")
                resp2 = await client.post(
                    url,
                    json=body_no_region,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                print(f"  HTTP {resp2.status_code}")
                if resp2.status_code != 200:
                    print(f"  Response: {resp2.text[:500]}")
                else:
                    data2 = resp2.json()
                    videos2 = data2.get("data", {}).get("videos", [])
                    print(f"  Videos (no region): {len(videos2)}")
                continue

            data = resp.json()
            print(f"  Full response: {json.dumps(data, indent=2)[:600]}")

            videos = data.get("data", {}).get("videos", [])
            has_more = data.get("data", {}).get("has_more", False)

            print(f"  Videos returned: {len(videos)}, has_more: {has_more}")

            for i, v in enumerate(videos[:3]):
                username = v.get("username", "?")
                desc = (v.get("video_description", "") or "")[:80]
                views = v.get("view_count", 0)
                create_time = v.get("create_time", 0)
                dt = datetime.fromtimestamp(create_time, tz=timezone.utc) if create_time else None
                print(f"    [{i+1}] @{username} | {dt} | views={views}")
                print(f"        {desc}")

    # ---- 3. Test the full collector flow (without persistence) ----
    print("\n--- Step 3: Full collector test ---")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
    os.environ.setdefault("ALLOWED_ORIGINS", '["http://localhost:8022"]')
    from issue_observatory.arenas.tiktok.collector import TikTokCollector
    from issue_observatory.core.credential_pool import CredentialPool

    pool = CredentialPool()
    collector = TikTokCollector(credential_pool=pool)

    # Use just 2 terms, small max, recent date window
    test_collect_terms = ["grønland", "trump"]
    print(f"  Collecting with terms={test_collect_terms}, max_results=15")
    print(f"  Date range: {start_dt.isoformat()} — {end_dt.isoformat()}")

    from issue_observatory.arenas.base import Tier
    results = await collector.collect_by_terms(
        terms=test_collect_terms,
        tier=Tier.FREE,
        date_from=start_dt,
        date_to=end_dt,
        max_results=15,
    )

    print(f"  Collector returned {len(results)} records")
    print(f"  Batch stats: {collector.batch_stats}")
    print(f"  Per-input counts: {collector.per_input_counts}")

    for i, r in enumerate(results[:3]):
        print(f"    [{i+1}] platform={r.get('platform')} | {r.get('url', '')[:60]}")
        print(f"        text: {(r.get('text_content') or '')[:80]}")
        print(f"        terms_matched: {r.get('search_terms_matched')}")

    print("\n--- Done ---")


if __name__ == "__main__":
    asyncio.run(main())
