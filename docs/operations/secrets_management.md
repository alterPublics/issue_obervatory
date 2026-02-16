# Secrets Management

## Critical Secrets

The system has two secrets that, if lost or compromised, have irreversible consequences:

| Secret | Setting | Consequence if lost |
|--------|---------|---------------------|
| `SECRET_KEY` | `settings.secret_key` | All existing JWT tokens become invalid. Users must log in again. New tokens work immediately after rotation. |
| `CREDENTIAL_ENCRYPTION_KEY` | `settings.credential_encryption_key` | All `api_credentials` rows become unrecoverable ciphertext. Every API credential must be manually re-entered. No automated recovery is possible. |

---

## Key Generation

### Fernet key (CREDENTIAL_ENCRYPTION_KEY)

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Output is a 44-character base64-encoded string, e.g.:
`h3ZpQ8k2...=`

### JWT secret (SECRET_KEY)

```bash
openssl rand -hex 32
```

Output is a 64-character hex string, e.g.:
`a3f1c2e9...`

---

## Storing Secrets

### Docker Secrets (recommended for production)

Docker Secrets store values on disk encrypted by the Docker swarm or as
tmpfs-mounted files at `/run/secrets/` in the container.

**Step 1 — Create the secrets:**

```bash
# From files (safer — avoids shell history)
echo -n "your-fernet-key" | docker secret create credential_encryption_key -
echo -n "your-jwt-secret" | docker secret create secret_key -
```

**Step 2 — Reference in docker-compose.yml:**

```yaml
secrets:
  secret_key:
    external: true
  credential_encryption_key:
    external: true

services:
  app:
    secrets:
      - secret_key
      - credential_encryption_key
    environment:
      # Point Pydantic Settings to the mounted secret files
      SECRET_KEY_FILE: /run/secrets/secret_key
      CREDENTIAL_ENCRYPTION_KEY_FILE: /run/secrets/credential_encryption_key
```

**Step 3 — Application reads from file path:**

Pydantic Settings supports the `_FILE` suffix convention via a custom
`model_validator` or by overriding `settings_customise_sources()`. If not yet
implemented, read the file in the `Settings` validator:

```python
# In config/settings.py, add a model_validator if needed:
@model_validator(mode="before")
@classmethod
def _read_secret_files(cls, values: dict) -> dict:
    for key in ("secret_key", "credential_encryption_key"):
        file_var = f"{key.upper()}_FILE"
        if file_path := values.get(file_var) or os.environ.get(file_var):
            values[key] = Path(file_path).read_text().strip()
    return values
```

### .env file (development only)

Never commit `.env` to version control. Add it to `.gitignore`.

```
SECRET_KEY=a3f1c2e9...
CREDENTIAL_ENCRYPTION_KEY=h3ZpQ8k2...=
```

---

## Backup Procedure

### Where to store backups

- Store an encrypted copy of both secrets **offline** (e.g., printed QR code in
  a physically secured location, or a hardware security key).
- Do not store both secrets in the same backup location.
- Use a password manager with encrypted vault export as a secondary backup.

### Backup format

Create a single encrypted archive:

```bash
# Encrypt the secrets file with a passphrase
gpg --symmetric --cipher-algo AES256 secrets.txt
# Store secrets.txt.gpg offline; delete plaintext immediately
shred -u secrets.txt
```

---

## Rotation Procedures

### Rotating SECRET_KEY (JWT secret)

JWT rotation can be done with a brief overlap period to avoid logging out
active users:

1. Generate a new secret: `openssl rand -hex 32`
2. Update `SECRET_KEY` in your secret store.
3. Restart the app service: `docker compose restart app`
4. Active sessions using old tokens expire naturally within
   `ACCESS_TOKEN_EXPIRE_MINUTES` (default: 30 minutes).
5. After all old tokens have expired, remove the old secret from any overlap
   configuration.

Note: If your `user_manager.py` is extended to support multiple valid signing
keys simultaneously, the overlap period can be zero-downtime. The current
implementation uses a single key.

### Rotating CREDENTIAL_ENCRYPTION_KEY (Fernet)

This procedure re-encrypts all stored API credentials with the new key.
Schedule a maintenance window; arena collection will be unavailable during
rotation.

1. Generate a new Fernet key.
2. Run the re-encryption script (implement if not present):
   ```bash
   docker compose exec app python scripts/rotate_credential_key.py \
     --old-key "$OLD_CREDENTIAL_ENCRYPTION_KEY" \
     --new-key "$NEW_CREDENTIAL_ENCRYPTION_KEY"
   ```
   The script must:
   - Fetch all `api_credentials` rows.
   - Decrypt each `encrypted_value` with the old key.
   - Re-encrypt with the new key.
   - Write back atomically (transaction with rollback on any failure).
3. Update `CREDENTIAL_ENCRYPTION_KEY` in your secret store.
4. Restart app and worker: `docker compose restart app worker`
5. Verify arena health: `curl http://localhost:8000/api/arenas/health`

---

## What Happens if CREDENTIAL_ENCRYPTION_KEY Is Lost

If the `CREDENTIAL_ENCRYPTION_KEY` is permanently lost:

- Every row in the `api_credentials` table contains ciphertext that is
  **mathematically unrecoverable** without the key.
- The application will raise `cryptography.fernet.InvalidToken` on every
  attempt to use a stored credential.
- Arena collection will fail for all paid-tier arenas.

**Recovery procedure:**

1. Set a new `CREDENTIAL_ENCRYPTION_KEY` (generate fresh).
2. Truncate `api_credentials`: `TRUNCATE api_credentials;`
3. Re-enter all API credentials via the admin UI (`/admin/credentials`) or
   via `scripts/bootstrap_admin.py`.
4. Re-enable affected arenas in each query design's arena configuration.

There is no automated recovery. Back up this key with the same care as a
production database encryption master key.
