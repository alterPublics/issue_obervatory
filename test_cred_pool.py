#!/usr/bin/env python
"""Quick diagnostic script to test credential pool env var fallback."""

import asyncio
import os

# Set test env vars
os.environ["SERPER_API_KEY"] = "test-serper-key"
os.environ["TIKTOK_CLIENT_KEY"] = "test-tiktok-key"
os.environ["TIKTOK_CLIENT_SECRET"] = "test-tiktok-secret"
os.environ["GAB_ACCESS_TOKEN"] = "test-gab-token"

from issue_observatory.core.credential_pool import CredentialPool


async def main():
    pool = CredentialPool(env=dict(os.environ))

    print("Testing credential pool env var fallback...\n")

    # Test 1: Google Search (Serper, MEDIUM tier)
    print("1. Testing serper/medium:")
    cred = await pool.acquire(platform="serper", tier="medium")
    if cred:
        print(f"   ✓ Got credential: id={cred['id']}, api_key={cred.get('api_key', 'MISSING')}")
    else:
        print("   ✗ No credential returned")

    # Test 2: TikTok (FREE tier)
    print("\n2. Testing tiktok/free:")
    cred = await pool.acquire(platform="tiktok", tier="free")
    if cred:
        print(f"   ✓ Got credential: id={cred['id']}")
        print(f"     client_key={cred.get('client_key', 'MISSING')}")
        print(f"     client_secret={cred.get('client_secret', 'MISSING')}")
    else:
        print("   ✗ No credential returned")

    # Test 3: Gab (FREE tier)
    print("\n3. Testing gab/free:")
    cred = await pool.acquire(platform="gab", tier="free")
    if cred:
        print(f"   ✓ Got credential: id={cred['id']}")
        print(f"     access_token={cred.get('access_token', 'MISSING')}")
    else:
        print("   ✗ No credential returned")

    print("\n✓ Test complete")


if __name__ == "__main__":
    asyncio.run(main())
