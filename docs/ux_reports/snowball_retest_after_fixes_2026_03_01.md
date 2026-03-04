# Snowball Sampling Retest After Bug Fixes -- 2026-03-01

Date: 2026-03-01
Arenas evaluated: bluesky, reddit, youtube, telegram, tiktok, gab, x_twitter, facebook, instagram, threads
Tiers evaluated: free (all snowball-related platforms)
Scenarios run: Snowball sampling with auto_create_actors + add_to_actor_list_id (combined flow)
Fixes under test:
  1. Transaction poisoning fix: `snowball.py` `auto_create_actor_records()` now uses `db.begin_nested()` (SAVEPOINT) instead of bare `db.rollback()`
  2. ActorResponse.presences fix: Pydantic schema now has `validation_alias="platform_presences"`

---

## Test Summary

Two fixes were applied and retested via end-to-end API calls against the running application at `http://localhost:8000`. The retest reveals that **one fix works correctly** (the ActorResponse.presences serialization) while the **other fix is ineffective** because the actual root cause is upstream of where the fix was applied.

### Verdict

| Fix | Status | Details |
|-----|--------|---------|
| `ActorResponse.presences` serialization | **PARTIALLY FIXED** | Works on list endpoint; detail endpoint still returns `platform_presences` due to pages.py routing bypass |
| Transaction poisoning in `auto_create_actor_records` | **NOT FIXED** | The `begin_nested()` change is correct in isolation, but the session is already poisoned before `auto_create_actor_records` is ever called |

### Root Cause Discovered

The transaction poisoning does NOT originate in `snowball.py`. It originates in `sampling/network_expander.py` in two methods that use a malformed SQL pattern:

```sql
author_id = :actor_id::uuid
```

SQLAlchemy's asyncpg dialect cannot parse `:actor_id::uuid` correctly. It fails to recognize `:actor_id` as a named bind parameter when followed by `::uuid` (PostgreSQL type cast syntax). The resulting SQL sent to asyncpg has the literal string `:actor_id::uuid` instead of `$N::uuid`, which causes a `PostgresSyntaxError: syntax error at or near ":"`.

This SQL error poisons the PostgreSQL transaction. All subsequent queries on the same session fail with `InFailedSQLTransactionError`, including:
- The presence lookup in `auto_create_actor_records` (line 347 of `snowball.py`)
- The `_bulk_add_to_list` query (line 1270 of `actors.py`)
- Any other DB operation in the route handler

**Affected methods** (3 occurrences in `/src/issue_observatory/sampling/network_expander.py`):
- Line 822: `_expand_via_telegram_forwarding` -- `author_id = :actor_id::uuid`
- Line 826: `_expand_via_telegram_forwarding` -- `author_id = :actor_id::uuid`
- Line 1257: `_expand_via_content_links` -- `author_id = :actor_id::uuid`

**Fix**: Replace all `::uuid` casts with `CAST(:param AS uuid)` syntax, which SQLAlchemy handles correctly:

```python
# BROKEN:
"author_id = :actor_id::uuid"

# FIXED:
"author_id = CAST(:actor_id AS uuid)"
```

Verified: `CAST(:actor_id AS uuid)` syntax works correctly with SQLAlchemy + asyncpg in direct testing.

---

## Test Protocol

### 1. Authentication

- `POST /auth/cookie/login` with `username=admin@example.com&password=change-me-in-production`
- Result: 204 No Content, `access_token` cookie set. **PASS**

### 2. System State Before Testing

- **41 actors** in the database, of which **35 have platform presences**
- Platforms represented: bluesky (27), tiktok (2), youtube (2), x_twitter (2), telegram (2), reddit (2), discord (1), facebook (2), instagram (1)
- **1 actor list** ("Default") linked to query design "Iran Discourse", containing 30 members
- Actor list UUID: `11520185-3449-4047-975f-0bab92c15c78`

### 3. Snowball Test A: Discovery Only (no auto_create, no add_to_list)

**Request:**
```json
{
  "seed_actor_ids": ["7918278f-..."],
  "platforms": ["bluesky"],
  "max_depth": 1,
  "max_actors_per_step": 5,
  "auto_create_actors": false
}
```

**Result:** 6 total actors (1 seed + 5 discovered via `bluesky_follows`). **PASS**

Discovered actors:
- Henrik Bech Seeberg
- Rebecca Jessen
- Froeken
- Iben Sonderup
- hess1976.bsky.social

All discovered actors had empty `actor_id` fields (expected, since auto_create was off).

### 4. Snowball Test B: With auto_create_actors, Without add_to_list

**Request:**
```json
{
  "seed_actor_ids": ["7918278f-..."],
  "platforms": ["bluesky"],
  "max_depth": 1,
  "max_actors_per_step": 3,
  "auto_create_actors": true
}
```

**Result:** HTTP 200, `total_actors: 4`, `newly_created_actors: 0`. **FAIL**

Despite discovering 3 new actors, none were created in the database. The `auto_create_actor_records` method silently fails because the session is already poisoned by `_expand_via_content_links`.

**Why the `begin_nested()` fix is ineffective here:** The `begin_nested()` SAVEPOINT protects individual actor creation failures inside `auto_create_actor_records`. But the session is poisoned BEFORE `auto_create_actor_records` runs -- during the `sampler.run()` call, when `expand_from_actor()` calls `_expand_via_content_links()`, which fails with the SQL syntax error. Even though the Python exception is caught (line 1264 of `network_expander.py`), the PostgreSQL transaction is corrupted. All subsequent queries fail.

### 5. Snowball Test C: With auto_create + add_to_actor_list_id (combined flow)

**Request:**
```json
{
  "seed_actor_ids": ["7918278f-...", "80836d16-..."],
  "platforms": ["bluesky"],
  "max_depth": 1,
  "max_actors_per_step": 10,
  "auto_create_actors": true,
  "add_to_actor_list_id": "11520185-..."
}
```

**Result:** HTTP 500 with full Python traceback. **FAIL**

Error: `InFailedSQLTransactionError: current transaction is aborted, commands ignored until end of transaction block` at `_bulk_add_to_list` (line 1270 of `actors.py`).

### 6. Snowball Test D: Full 35-seed, 10-platform discovery

**Request:**
```json
{
  "seed_actor_ids": [<all 35 actors with presences>],
  "platforms": ["bluesky", "reddit", "youtube", "telegram", "tiktok", "gab", "x_twitter", "facebook", "instagram", "threads"],
  "max_depth": 1,
  "max_actors_per_step": 50,
  "auto_create_actors": false
}
```

**Result:** `total_actors: 41`, `wave_log: [{wave: 0, count: 41, methods: ["seed"]}, {wave: 1, count: 0, methods: []}]`. **FAIL**

Zero actors discovered at depth 1. The session gets poisoned during the first actor's expansion (when `_expand_via_content_links` runs), and ALL subsequent expansion calls for all 35 seeds across all platforms fail. The system silently returns an empty wave 1 with no error indication to the researcher.

### 7. Direct Function Test: auto_create_actor_records in isolation

Tested `auto_create_actor_records` directly with a fresh `AsyncSession` and a synthetic actor dict.

**Result:** Successfully created 1 Actor + 1 ActorPlatformPresence, returned correct UUID. **PASS**

This confirms the `begin_nested()` fix in `auto_create_actor_records` is correct. The problem is that the session is poisoned before this function runs.

---

## ActorResponse.presences Fix Verification

### Actor List Endpoint (`GET /actors/?page_size=50`)

Response uses `presences` field (not `platform_presences`). All 35 actors with presences correctly show their platform data. **PASS**

Example:
```json
{
  "id": "3aaf6ff5-...",
  "canonical_name": "Rasmus Prehn",
  "presences": [
    {
      "id": "689e1f6c-...",
      "platform": "bluesky",
      "platform_username": "rasmusprehn.bsky.social",
      "platform_user_id": "did:plc:rasmus-prehn"
    }
  ]
}
```

### Actor Detail Endpoint (`GET /actors/{id}`)

Response uses `platform_presences` field (not `presences`) and includes `metadata_` field. **PARTIAL FAIL**

The detail endpoint is intercepted by `pages.py:priority_router` (line 1143), which calls `get_actor()` from `actors.py` but does NOT pass through the `response_model=ActorResponse` serialization pipeline. The raw ORM object is serialized directly, producing `platform_presences` instead of `presences`.

Example:
```json
{
  "id": "7918278f-...",
  "canonical_name": "Jens Joel",
  "platform_presences": [...],
  "metadata_": {"notes": "Auto-created by snowball sampling"}
}
```

This means:
- The list endpoint returns `presences` (correct, via ActorResponse)
- The detail endpoint returns `platform_presences` (incorrect, bypasses ActorResponse)
- Frontend JavaScript that expects a consistent field name will break on one or the other endpoint

---

## Cascading Impact Analysis

The `_expand_via_content_links` SQL bug has a cascading impact far beyond the content links feature itself:

1. **Snowball discovery across all platforms returns zero results** when there are any content_records in the database, because the method runs for every expansion call and poisons the session on the first failure.

2. **auto_create_actors is completely non-functional** because the session is poisoned before it runs.

3. **add_to_actor_list_id crashes with 500** because the session is poisoned before the list-add query runs.

4. **The researcher sees no error** -- they get either `newly_created_actors: 0` (misleading success) or a raw Python traceback (security concern).

5. **Multi-depth snowball is impossible** -- even if depth-1 expansion works (e.g., via bluesky HTTP API before the content_links DB query), the `_resolve_uuids` call at line 244 of `snowball.py` will fail on the poisoned session, preventing any depth-2 expansion.

---

## Recommendations

### Immediate Fix Required (1 line change, 3 locations)

**[core]** Replace `::uuid` with `CAST(:param AS uuid)` in all 3 occurrences in `/src/issue_observatory/sampling/network_expander.py`:

| Line | Current | Fixed |
|------|---------|-------|
| 822 | `author_id = :actor_id::uuid` | `author_id = CAST(:actor_id AS uuid)` |
| 826 | `author_id = :actor_id::uuid` | `author_id = CAST(:actor_id AS uuid)` |
| 1257 | `author_id = :actor_id::uuid` | `author_id = CAST(:actor_id AS uuid)` |

### Additional Fixes

1. **[core]** Add session health protection before `_bulk_add_to_list`: wrap the DB calls in `_expand_via_content_links` and `_expand_via_telegram_forwarding` in SAVEPOINTs so that SQL errors do not poison the parent transaction. This prevents future similar issues.

2. **[frontend]** Fix the actor detail endpoint to serialize through `ActorResponse`: in `pages.py` line 1166, convert the ORM result to `ActorResponse.model_validate(actor, from_attributes=True)` before returning as JSON.

3. **[core]** Install a global exception handler that returns structured JSON errors instead of raw tracebacks. The current behavior is a security concern.

---

## Artifacts

- Full test was conducted via `curl` against `http://localhost:8000`
- Server was running via `uvicorn --reload`
- Celery worker was running concurrently
- Database had 41 actors, 12,724 content_records, 1 query design, 1 actor list with 30 members
