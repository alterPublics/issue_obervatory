"""Test that credential pool can acquire SERPER credentials from env."""
from __future__ import annotations

import asyncio
import os


def test_env_map() -> None:
    """Verify the platform env map has the serper mapping."""
    from issue_observatory.core.credential_pool import _PLATFORM_ENV_MAP

    key = ("serper", "medium")
    assert key in _PLATFORM_ENV_MAP, f"Missing {key} in _PLATFORM_ENV_MAP"
    mapping = _PLATFORM_ENV_MAP[key]
    assert mapping == {"api_key": "SERPER_API_KEY"}, f"Wrong mapping: {mapping}"
    print(f"✅ _PLATFORM_ENV_MAP has correct entry for {key}")


async def test_acquire() -> None:
    """Test that acquire works with SERPER_API_KEY from env."""
    from issue_observatory.core.credential_pool import CredentialPool

    # Create pool with SERPER_API_KEY in env
    test_env = {"SERPER_API_KEY": "test-key-12345"}
    pool = CredentialPool(env=test_env)

    # Try to acquire
    cred = await pool.acquire(platform="serper", tier="medium")

    if cred is None:
        print("❌ FAILED: acquire returned None")
        return False

    assert cred["platform"] == "serper", f"Wrong platform: {cred['platform']}"
    assert cred["tier"] == "medium", f"Wrong tier: {cred['tier']}"
    assert cred["api_key"] == "test-key-12345", f"Wrong api_key: {cred['api_key']}"
    print(f"✅ Successfully acquired credential: {cred}")
    return True


async def test_acquire_from_real_env() -> None:
    """Test acquire with actual os.environ."""
    from issue_observatory.core.credential_pool import CredentialPool

    key = os.environ.get("SERPER_API_KEY")
    print(f"\nSERPER_API_KEY in os.environ: {'YES' if key else 'NO'}")
    if key:
        print(f"  Value: {key[:10]}...")

    pool = CredentialPool()  # Uses os.environ
    cred = await pool.acquire(platform="serper", tier="medium")

    if cred is None:
        print("❌ FAILED: acquire returned None from real env")
        return False

    print(f"✅ Successfully acquired from real env: platform={cred['platform']} tier={cred['tier']}")
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("Testing credential pool SERPER env fallback")
    print("=" * 60)

    # Test 1: Verify mapping exists
    test_env_map()

    # Test 2: Acquire with test env
    print("\n" + "=" * 60)
    print("Test 2: Acquire with test env dict")
    print("=" * 60)
    success = asyncio.run(test_acquire())

    # Test 3: Acquire from real os.environ
    print("\n" + "=" * 60)
    print("Test 3: Acquire from real os.environ")
    print("=" * 60)
    success2 = asyncio.run(test_acquire_from_real_env())

    if success and success2:
        print("\n✅ ALL TESTS PASSED")
    else:
        print("\n❌ SOME TESTS FAILED")
