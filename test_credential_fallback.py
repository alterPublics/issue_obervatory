"""Quick test to verify credential pool env fallback works."""
from __future__ import annotations

import asyncio
import os


async def main() -> None:
    """Test credential acquisition from env vars."""
    # Ensure SERPER_API_KEY is set
    serper_key = os.environ.get("SERPER_API_KEY")
    print(f"SERPER_API_KEY env var: {'SET' if serper_key else 'NOT SET'}")
    if serper_key:
        print(f"  Value: {serper_key[:10]}..." if len(serper_key) > 10 else f"  Value: {serper_key}")

    # Import after checking env
    from issue_observatory.core.credential_pool import CredentialPool

    # Create pool (no redis needed for env fallback)
    pool = CredentialPool()

    # Try to acquire
    print("\nAttempting to acquire credential for platform='serper', tier='medium'...")
    cred = await pool.acquire(platform="serper", tier="medium")

    if cred is None:
        print("❌ FAILED: No credential acquired")
    else:
        print("✅ SUCCESS: Credential acquired")
        print(f"  ID: {cred.get('id')}")
        print(f"  Platform: {cred.get('platform')}")
        print(f"  Tier: {cred.get('tier')}")
        api_key = cred.get('api_key', '')
        print(f"  API Key: {api_key[:10]}..." if len(api_key) > 10 else f"  API Key: {api_key}")


if __name__ == "__main__":
    asyncio.run(main())
