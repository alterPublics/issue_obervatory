# Security Configuration Fixes — 2026-02-21

## Summary

Fixed three beta-blocking security configuration issues identified in the pre-production secrets audit. All fixes enforce security requirements at application startup rather than allowing silent degradation.

## Fixed Issues

### BB-01: PSEUDONYMIZATION_SALT Silent Degradation (GDPR Risk) — CRITICAL

**Location:** `src/issue_observatory/core/normalizer.py`

**Problem:** When PSEUDONYMIZATION_SALT was missing or empty, the normalizer only logged a WARNING and continued to produce records with `pseudonymized_author_id = None`, violating GDPR data minimization requirements. Data collection proceeded without pseudonymization.

**Fix:** The normalizer now raises `NormalizationError` at construction time when the salt is empty or missing. Collection cannot proceed without a valid pseudonymization salt — this is a GDPR hard requirement.

**Impact:**
- Application will refuse to start if PSEUDONYMIZATION_SALT is not configured
- Test environments must provide a valid salt (test suite updated)
- No silent GDPR violations can occur

**Code Changes:**
```python
# Before: Silent degradation
if not self._salt:
    logger.warning("PSEUDONYMIZATION_SALT is empty...")

# After: Hard failure
if not self._salt:
    logger.critical("PSEUDONYMIZATION_SALT is empty or missing...")
    raise NormalizationError(
        "PSEUDONYMIZATION_SALT is required for GDPR-compliant data collection."
    )
```

---

### BB-02: SECRET_KEY Accepts Known-Weak Placeholder Values — HIGH

**Location:** `src/issue_observatory/config/settings.py`

**Problem:** No runtime validation rejected placeholder values like `"change-me-in-production"` from `.env.example`. If an operator copied the file without changing secrets, JWT tokens would be signed with a publicly-known key.

**Fix:** Added Pydantic `@field_validator` that rejects known weak values at application startup.

**Rejected values:**
- `"change-me-in-production"`
- `"changeme"`
- `"secret"`
- `"password"`
- `"insecure"`
- Empty string

**Additional validation:**
- Warns if SECRET_KEY is shorter than 32 characters

**Impact:**
- Application will refuse to start with known-weak SECRET_KEY values
- Operators must generate proper secrets: `openssl rand -hex 32`
- `.env.example` updated with clear warnings

**Code Changes:**
```python
@field_validator("secret_key")
@classmethod
def validate_secret_key(cls, v: str) -> str:
    weak_values = {"change-me-in-production", "changeme", "secret", ...}
    if v.lower() in weak_values:
        raise ValueError(
            f"SECRET_KEY cannot be '{v}'. "
            "Generate a strong secret with: openssl rand -hex 32"
        )
    return v
```

---

### BB-03: CREDENTIAL_ENCRYPTION_KEY Not Validated at Startup — HIGH

**Location:** `src/issue_observatory/config/settings.py`

**Problem:** Invalid Fernet keys were only caught at runtime when the first credential decryption was attempted (mid-operation), not at application startup. This could cause collection runs to fail unexpectedly.

**Fix:** Added Pydantic `@field_validator` that verifies the key is a valid Fernet key at startup by attempting to instantiate a Fernet cipher.

**Validation logic:**
- Empty key: Logs WARNING but allows (development mode with no credentials)
- Invalid Fernet key: Raises `ValueError` with clear generation instructions
- Valid key: Accepts and proceeds

**Impact:**
- Application will refuse to start with invalid CREDENTIAL_ENCRYPTION_KEY
- Operators must generate proper Fernet keys
- Clear error messages with copy-paste generation commands

**Code Changes:**
```python
@field_validator("credential_encryption_key")
@classmethod
def validate_credential_encryption_key(cls, v: str) -> str:
    if not v:
        logger.warning("CREDENTIAL_ENCRYPTION_KEY is empty...")
        return v
    try:
        Fernet(v.encode("utf-8"))
    except Exception as e:
        raise ValueError(
            f"CREDENTIAL_ENCRYPTION_KEY is not a valid Fernet key: {e}. "
            "Generate a valid key with: python -c '...'"
        ) from e
    return v
```

---

## Updated Files

### Core Code
1. `src/issue_observatory/core/normalizer.py` — BB-01 fix, updated docstring
2. `src/issue_observatory/config/settings.py` — BB-02 and BB-03 validators

### Tests
3. `tests/conftest.py` — Updated test environment defaults:
   - Valid Fernet key for CREDENTIAL_ENCRYPTION_KEY
   - Extended SECRET_KEY to meet 32-character recommendation
4. `tests/unit/test_normalizer.py` — Updated test to expect `NormalizationError` instead of silent degradation

### Documentation
5. `.env.example` — Added security warnings with specific generation commands for all three secrets

---

## Migration Guide

### For Development Environments

If your `.env` file has placeholder values, update them:

```bash
# Generate new secrets
export NEW_SECRET_KEY=$(openssl rand -hex 32)
export NEW_FERNET_KEY=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')
export NEW_SALT=$(openssl rand -hex 32)

# Update .env file
sed -i.bak "s/SECRET_KEY=.*/SECRET_KEY=$NEW_SECRET_KEY/" .env
sed -i.bak "s/CREDENTIAL_ENCRYPTION_KEY=.*/CREDENTIAL_ENCRYPTION_KEY=$NEW_FERNET_KEY/" .env
sed -i.bak "s/PSEUDONYMIZATION_SALT=.*/PSEUDONYMIZATION_SALT=$NEW_SALT/" .env
```

### For Production Deployments

**CRITICAL:** If you already have production data:
- **DO NOT change PSEUDONYMIZATION_SALT** — changing it will break all pseudonymized actor references
- **DO NOT change CREDENTIAL_ENCRYPTION_KEY** — changing it will make all stored credentials unrecoverable
- **DO change SECRET_KEY** if it's currently weak — this will invalidate all active JWT sessions (users must re-login)

If deploying fresh (no existing data):
1. Generate all three secrets with strong random values
2. Store them securely (Docker Secrets, Vault, or equivalent)
3. Back up CREDENTIAL_ENCRYPTION_KEY and PSEUDONYMIZATION_SALT in a secure location
4. Document the salt generation date for GDPR audit trail

---

## Test Results

All fixes verified:
- ✅ Empty PSEUDONYMIZATION_SALT raises `NormalizationError`
- ✅ Weak SECRET_KEY values rejected at startup
- ✅ Invalid CREDENTIAL_ENCRYPTION_KEY rejected at startup
- ✅ Empty CREDENTIAL_ENCRYPTION_KEY allowed with warning (dev mode)
- ✅ Valid configuration accepted
- ✅ All 677 unit tests pass

---

## Security Impact Assessment

| Issue | Severity | Exploitability | Impact if Exploited | Status |
|-------|----------|----------------|---------------------|--------|
| BB-01 | **CRITICAL** | N/A (config error) | GDPR violation, data breach | **FIXED** |
| BB-02 | **HIGH** | High (if placeholder used) | JWT token forgery, account takeover | **FIXED** |
| BB-03 | **HIGH** | Low (requires misconfiguration) | Collection run failures, data loss | **FIXED** |

All issues now fail-fast at application startup rather than allowing silent security degradation.

---

## References

- Pre-production checklist: `/docs/pre_production_checklist_p0_5_secrets.md`
- Normalizer module: `/src/issue_observatory/core/normalizer.py`
- Settings module: `/src/issue_observatory/config/settings.py`
- Test configuration: `/tests/conftest.py`
