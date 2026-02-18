# Scenario 01 — First-Time Setup

**Created:** 2026-02-17

## Research question
A Danish media researcher at a Danish university wants to install The Issue Observatory and begin collecting data. Can they reach a working, verified installation within 30 minutes without developer assistance?

## Expected workflow
1. Clone the repository or receive a zip from a colleague.
2. Read `docs/guides/env_setup.md` from top to bottom.
3. Copy the .env template from Part 7 and fill in all four required secrets.
4. Generate SECRET_KEY using the provided openssl command.
5. Generate CREDENTIAL_ENCRYPTION_KEY using the provided Python command.
6. Generate PSEUDONYMIZATION_SALT using the provided openssl command.
7. Start Docker Compose and verify all containers are running.
8. Hit the health endpoint to confirm the system is live.
9. Log in to the admin UI with bootstrap credentials.
10. Navigate to Admin > Credentials to understand which arenas need keys.

## Success criteria
- Researcher can complete all steps without consulting a developer.
- All four required variables are generated with the correct format.
- The health endpoint returns `{"status": "ok"}`.
- The researcher understands which arenas work out of the box vs. require paid credentials.
- The PSEUDONYMIZATION_SALT warning about project-lifetime stability is understood.

## Known edge cases
- Researcher may not have Python available to generate the Fernet key; the guide provides a one-liner but does not suggest fallback alternatives.
- Docker may not be installed; guide does not address Docker installation prerequisites.
- The Jyllands-Posten RSS URL is flagged as uncertain in source code but not in documentation.
- The verification step (Step 2) requires a Python virtual environment that may not yet be set up.
