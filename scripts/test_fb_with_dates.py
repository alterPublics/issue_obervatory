"""Quick test: do dates cause Bright Data to return 0 results?"""
from __future__ import annotations

import asyncio
import json
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
for lib in ("httpx", "httpcore", "hpack", "urllib3"):
    logging.getLogger(lib).setLevel(logging.WARNING)


async def main() -> None:
    import httpx

    from issue_observatory.arenas.facebook.collector import FacebookCollector
    from issue_observatory.arenas.facebook.config import FACEBOOK_DATASET_ID_POSTS, build_trigger_url
    from issue_observatory.core.credential_pool import CredentialPool

    pool = CredentialPool()
    cred = await pool.acquire(platform="brightdata_facebook", tier="medium")
    api_token = cred.get("api_token") or cred.get("api_key", "")
    cred_id = cred["id"]
    collector = FacebookCollector(credential_pool=pool)

    # Exact production parameters
    payload = [
        {"url": "https://www.facebook.com/socialdemokratiet", "num_of_posts": 5,
         "start_date": "02-27-2026", "end_date": "03-04-2026"},
        {"url": "https://www.facebook.com/Konservative", "num_of_posts": 5,
         "start_date": "02-27-2026", "end_date": "03-04-2026"},
    ]

    trigger_url = build_trigger_url(FACEBOOK_DATASET_ID_POSTS)
    print(f"Payload: {json.dumps(payload, indent=2)}")

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            snapshot_id = await collector._trigger_dataset(client, api_token, trigger_url, payload)
            print(f"Snapshot: {snapshot_id}")
        except Exception as exc:
            print(f"TRIGGER ERROR: {type(exc).__name__}: {exc}")
            await pool.release(credential_id=cred_id)
            return

        raw_items = await collector._poll_and_download(client, api_token, snapshot_id)
        print(f"Downloaded: {len(raw_items)} items")

    await pool.release(credential_id=cred_id)

    errors = [i for i in raw_items if i.get("error_code")]
    valid = [i for i in raw_items if not i.get("error_code")]
    print(f"Valid: {len(valid)}, Errors: {len(errors)}")

    for item in errors[:3]:
        print(f"  Error: {item.get('error_code')} — {item.get('error', '')[:100]}")
    for item in valid[:3]:
        print(f"  Valid: {item.get('page_name')} | {item.get('date_posted')} | {str(item.get('content',''))[:80]}")


if __name__ == "__main__":
    asyncio.run(main())
