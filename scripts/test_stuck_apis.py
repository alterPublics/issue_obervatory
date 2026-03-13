"""Standalone API endpoint tests for stuck collectors.

Tests each platform's API with a minimal request to verify the endpoint
responds correctly. Run with:

    python scripts/test_stuck_apis.py

Requires: httpx, python-dotenv
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

TIMEOUT = 30.0  # seconds per request


async def test_youtube() -> dict[str, str]:
    """Test YouTube Data API v3 search.list endpoint."""
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        return {"youtube": "SKIP - no YOUTUBE_API_KEY"}

    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": "test",
        "type": "video",
        "maxResults": 1,
        "relevanceLanguage": "da",
        "regionCode": "DK",
        "key": api_key,
    }
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params=params)
            elapsed = time.monotonic() - start
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                return {
                    "youtube": f"OK - {resp.status_code} - {len(items)} items - {elapsed:.1f}s"
                }
            elif resp.status_code == 403:
                detail = resp.json().get("error", {}).get("errors", [{}])[0].get("reason", "")
                return {"youtube": f"FAIL - 403 ({detail}) - {elapsed:.1f}s"}
            else:
                return {"youtube": f"FAIL - HTTP {resp.status_code} - {elapsed:.1f}s"}
    except Exception as exc:
        elapsed = time.monotonic() - start
        return {"youtube": f"ERROR - {type(exc).__name__}: {exc} - {elapsed:.1f}s"}


async def test_facebook() -> dict[str, str]:
    """Test Bright Data Web Scraper API trigger endpoint (dry run)."""
    api_token = os.environ.get("BRIGHTDATA_FACEBOOK_API_TOKEN", "")
    if not api_token:
        return {"facebook": "SKIP - no BRIGHTDATA_FACEBOOK_API_TOKEN"}

    # Just check if authentication works by querying an invalid snapshot
    url = "https://api.brightdata.com/datasets/v3/progress/test-nonexistent-id"
    headers = {"Authorization": f"Bearer {api_token}"}
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
            elapsed = time.monotonic() - start
            # 404 = auth works, snapshot not found (expected)
            # 401/403 = auth failed
            if resp.status_code in (404, 200):
                return {"facebook": f"OK - auth valid (HTTP {resp.status_code}) - {elapsed:.1f}s"}
            elif resp.status_code in (401, 403):
                return {"facebook": f"FAIL - auth rejected (HTTP {resp.status_code}) - {elapsed:.1f}s"}
            else:
                return {"facebook": f"WARN - unexpected HTTP {resp.status_code} - {elapsed:.1f}s"}
    except Exception as exc:
        elapsed = time.monotonic() - start
        return {"facebook": f"ERROR - {type(exc).__name__}: {exc} - {elapsed:.1f}s"}


async def test_gdelt() -> dict[str, str]:
    """Test GDELT DOC 2.0 API endpoint."""
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {
        "query": "test sourcelang:danish",
        "mode": "artlist",
        "maxrecords": "1",
        "format": "json",
        "sort": "DateDesc",
    }
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(url, params=params)
            elapsed = time.monotonic() - start
            if resp.status_code == 200:
                data = resp.json()
                articles = data.get("articles", [])
                return {
                    "gdelt": f"OK - {resp.status_code} - {len(articles)} articles - {elapsed:.1f}s"
                }
            else:
                body_preview = resp.text[:200]
                return {
                    "gdelt": f"FAIL - HTTP {resp.status_code} - {body_preview} - {elapsed:.1f}s"
                }
    except Exception as exc:
        elapsed = time.monotonic() - start
        return {"gdelt": f"ERROR - {type(exc).__name__}: {exc} - {elapsed:.1f}s"}


async def test_instagram() -> dict[str, str]:
    """Test Bright Data Web Scraper API for Instagram (auth check)."""
    api_token = os.environ.get("BRIGHTDATA_INSTAGRAM_API_TOKEN", "")
    if not api_token:
        return {"instagram": "SKIP - no BRIGHTDATA_INSTAGRAM_API_TOKEN"}

    url = "https://api.brightdata.com/datasets/v3/progress/test-nonexistent-id"
    headers = {"Authorization": f"Bearer {api_token}"}
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
            elapsed = time.monotonic() - start
            if resp.status_code in (404, 200):
                return {"instagram": f"OK - auth valid (HTTP {resp.status_code}) - {elapsed:.1f}s"}
            elif resp.status_code in (401, 403):
                return {"instagram": f"FAIL - auth rejected (HTTP {resp.status_code}) - {elapsed:.1f}s"}
            else:
                return {"instagram": f"WARN - unexpected HTTP {resp.status_code} - {elapsed:.1f}s"}
    except Exception as exc:
        elapsed = time.monotonic() - start
        return {"instagram": f"ERROR - {type(exc).__name__}: {exc} - {elapsed:.1f}s"}


async def test_openrouter() -> dict[str, str]:
    """Test OpenRouter API chat completions endpoint."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        return {"openrouter": "SKIP - no OPENROUTER_API_KEY"}

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://issue-observatory.local",
    }
    body = {
        "model": "google/gemma-3-27b-it:free",
        "messages": [{"role": "user", "content": "Say hello in one word."}],
        "max_tokens": 5,
    }
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=body, headers=headers)
            elapsed = time.monotonic() - start
            if resp.status_code == 200:
                data = resp.json()
                content = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")[:50]
                )
                return {
                    "openrouter": f"OK - {resp.status_code} - response='{content}' - {elapsed:.1f}s"
                }
            elif resp.status_code == 429:
                return {"openrouter": f"RATE LIMITED - HTTP 429 - {elapsed:.1f}s"}
            elif resp.status_code in (401, 403):
                return {"openrouter": f"FAIL - auth rejected (HTTP {resp.status_code}) - {elapsed:.1f}s"}
            else:
                body_preview = resp.text[:200]
                return {
                    "openrouter": f"FAIL - HTTP {resp.status_code} - {body_preview} - {elapsed:.1f}s"
                }
    except Exception as exc:
        elapsed = time.monotonic() - start
        return {"openrouter": f"ERROR - {type(exc).__name__}: {exc} - {elapsed:.1f}s"}


async def test_tiktok() -> dict[str, str]:
    """Test TikTok Research API OAuth token endpoint."""
    client_key = os.environ.get("TIKTOK_CLIENT_KEY", "")
    client_secret = os.environ.get("TIKTOK_CLIENT_SECRET", "")
    if not client_key or not client_secret:
        return {"tiktok": "SKIP - no TIKTOK_CLIENT_KEY/SECRET"}

    # Step 1: Get access token
    token_url = "https://open.tiktokapis.com/v2/oauth/token/"
    token_body = {
        "client_key": client_key,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    }
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            token_resp = await client.post(
                token_url,
                data=token_body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            elapsed_token = time.monotonic() - start

            if token_resp.status_code != 200:
                return {
                    "tiktok": f"FAIL - token endpoint HTTP {token_resp.status_code} - "
                    f"{token_resp.text[:200]} - {elapsed_token:.1f}s"
                }

            token_data = token_resp.json()
            access_token = token_data.get("access_token", "")
            if not access_token:
                return {
                    "tiktok": f"FAIL - no access_token in response: {token_data} - {elapsed_token:.1f}s"
                }

            # Step 2: Test video query endpoint
            query_url = "https://open.tiktokapis.com/v2/research/video/query/"
            query_headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            query_body = {
                "query": {
                    "and": [{"field_name": "keyword", "operation": "IN", "field_values": ["test"]}]
                },
                "start_date": "20260301",
                "end_date": "20260305",
                "max_count": 1,
            }
            query_resp = await client.post(
                query_url,
                json=query_body,
                headers=query_headers,
                params={"fields": "id,create_time"},
            )
            elapsed = time.monotonic() - start

            if query_resp.status_code == 200:
                data = query_resp.json()
                videos = data.get("data", {}).get("videos", [])
                return {
                    "tiktok": f"OK - token+query both work - {len(videos)} videos - {elapsed:.1f}s"
                }
            else:
                return {
                    "tiktok": f"WARN - token OK but query HTTP {query_resp.status_code} - "
                    f"{query_resp.text[:200]} - {elapsed:.1f}s"
                }
    except Exception as exc:
        elapsed = time.monotonic() - start
        return {"tiktok": f"ERROR - {type(exc).__name__}: {exc} - {elapsed:.1f}s"}


async def main() -> None:
    """Run all API tests concurrently."""
    print("=" * 60)
    print("Stuck Collector API Endpoint Tests")
    print("=" * 60)
    print()

    results = await asyncio.gather(
        test_youtube(),
        test_facebook(),
        test_gdelt(),
        test_instagram(),
        test_openrouter(),
        test_tiktok(),
    )

    all_results: dict[str, str] = {}
    for r in results:
        all_results.update(r)

    for platform, status in sorted(all_results.items()):
        icon = "✓" if status.startswith("OK") else "✗" if "FAIL" in status or "ERROR" in status else "?"
        print(f"  {icon} {platform:15s} {status}")

    print()
    print("=" * 60)

    # Return exit code based on failures
    failures = sum(1 for s in all_results.values() if "FAIL" in s or "ERROR" in s)
    if failures:
        print(f"{failures} test(s) failed.")
        sys.exit(1)
    else:
        print("All tests passed (or skipped).")


if __name__ == "__main__":
    asyncio.run(main())
