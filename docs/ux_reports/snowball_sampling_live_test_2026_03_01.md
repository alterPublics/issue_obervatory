# UX Test Report -- Snowball Sampling End-to-End Live Test

Date: 2026-03-01
Arenas evaluated: bluesky, reddit, youtube, telegram, tiktok, gab, x_twitter, facebook, instagram, threads
Tiers evaluated: free (all snowball-related platforms)
Scenarios run: Snowball sampling actor discovery, actor auto-creation, bulk list add

---

## Test Summary

This report documents a live end-to-end test of the snowball sampling workflow using
the running Issue Observatory application at `http://localhost:8000`. The test covered
authentication, actor discovery via the Actor Directory, snowball sampling execution
across all 10 supported platforms, and the addition of discovered actors to an actor
list -- all via the API (simulating what the frontend JavaScript would do).

### Environment

- 32 pre-existing actors in the database, of which 26 had real Bluesky DID platform
  presences, 2 had YouTube channel IDs, 2 had Facebook page IDs, 1 had a Reddit
  username, 1 had a Telegram username, and 1 had an X/Twitter username.
- One query design ("Iran Discourse") with a "Default" actor list containing the
  project's seed actors.
- No API credentials configured for Reddit, YouTube, TikTok, Gab, X/Twitter,
  Facebook, Instagram, or Threads -- only Bluesky (which uses unauthenticated
  public API) was able to return results.

### Key Findings

- **Bluesky snowball discovery works well**: 20 new actors discovered from 3 Danish
  politician seeds via `bluesky_follows` and `bluesky_followers` methods.
- **All other platforms returned zero results**: Expected given the lack of configured
  credentials, but the researcher receives no indication of WHY each platform found
  nothing (missing credentials vs. no connections vs. API failure).
- **Critical bug: `auto_create_actors` is completely broken**: Despite
  `auto_create_actors: true`, discovered actors are NOT persisted to the database.
  All discovered actors have empty `actor_id` fields in the response.
- **Critical bug: combining `auto_create_actors` + `add_to_actor_list_id` causes a
  500 Internal Server Error**: The `auto_create_actor_records` method poisons the
  SQLAlchemy async session by calling `db.rollback()` mid-transaction, and the
  subsequent `_bulk_add_to_list` call fails with
  `InFailedSQLTransactionError`.
- **Critical bug: raw Python traceback exposed to the user**: The 500 error returns
  a full SQLAlchemy/asyncpg traceback as the HTTP response body. This leaks internal
  implementation details (table names, SQL queries, column types, library versions).
- **ActorResponse serialization bug**: The `presences` field always returns `[]` in
  the JSON API because the Pydantic model maps `presences` but the ORM model uses
  `platform_presences`. This means the researcher can never see which platform
  presences an actor has via the list API.

---

## Passed

1. **Authentication via bearer token** works correctly. Login endpoint returns a JWT
   token that is accepted by all authenticated endpoints.

2. **Actor creation via POST /actors/** works correctly, including attaching an
   initial platform presence.

3. **Platform presence creation via POST /actors/{id}/presences** works correctly.

4. **Snowball platform list endpoint** (`GET /actors/sampling/snowball/platforms`)
   correctly returns all 10 supported platforms.

5. **Snowball sampling core logic** works when `auto_create_actors: false` and
   `add_to_actor_list_id` is not provided. The Bluesky expansion discovers
   real Danish-discourse actors from the follow/follower graphs.

6. **Bulk add to list** (`POST /actors/lists/{id}/members/bulk`) works correctly
   as a standalone operation, returning accurate counts of added and
   already-present actors.

7. **Snowball UI template** (`actors/list.html`) has a well-structured two-step
   workflow (Step 1: configure and run, Step 2: review and add to list) with
   clear labels, discovery method descriptions, and filter controls.

8. **Seed deduplication** works: actors expanded via multiple presences are not
   double-counted in the results (though each presence gets its own entry in
   the response's actors array for seeds).

---

## Friction Points

### F-1. Seed actors displayed as separate entries per presence [frontend]

When a seed actor has multiple platform presences (e.g., Pelle Dragsted with both
Bluesky and X/Twitter presences), the response lists them as separate entries:

```
Pelle Dragsted [x_twitter] -- seed
Pelle Dragsted [bluesky] -- seed
```

From a researcher's perspective, this inflates the "total actors" count. The response
reported `total_actors: 8` but only 4 unique actors were seeded. A researcher would
expect the count to reflect unique people, not unique presence records.

**Research impact**: Misleading statistics; the researcher may think they have more
seed coverage than they actually do.

### F-2. No indication of why non-Bluesky platforms found nothing [core]

When snowball sampling runs across 10 platforms but only Bluesky returns results,
the wave log shows `["bluesky_followers"]` as the only method used. There is no
per-platform breakdown explaining:
- "Reddit: no credentials configured"
- "YouTube: no credentials configured"
- "Telegram: no content records found for forwarding analysis"
- "X/Twitter: no credentials configured"

The researcher is left wondering whether these platforms genuinely have no connections
or whether the system could not even attempt the expansion.

**Research impact**: The researcher cannot distinguish between "no connections exist"
and "the platform could not be queried." This fundamentally undermines the
methodological validity of the snowball sample.

### F-3. `max_actors_per_step` is a global budget, not per-platform [research]

The `max_actors_per_step: 20` parameter caps the total number of new actors across
ALL platforms. Since Bluesky is first in the platform list and returns many results,
it can consume the entire budget before other platforms are even tried. The researcher
has no way to set per-platform budgets.

**Research impact**: Platform bias in the snowball sample. The fastest-responding
platform dominates the results.

### F-4. Duplicate presences can be created without warning [core]

When adding a Bluesky presence to an actor who already has one (e.g., Pernille
Rosenkrantz-Theil ended up with two Bluesky presences -- one real DID and one fake),
the system creates both without warning. This leads to confusion about which presence
is the "real" one and can cause duplicate expansion results.

### F-5. No "Select All / Deselect All" visibility in Step 2 when `actor_id` is empty [frontend]

The "Select All" function at line 1193-1195 maps `filteredResults.map(a => a.id)`.
When `actor_id` is empty (because auto_create failed), selecting all actors produces
an array of empty strings. The subsequent "Add to list" call would send these empty
strings, which would fail silently or produce no useful result.

---

## Blockers

### B-1. `auto_create_actors` silently fails -- discovered actors not persisted [core]

**What the researcher does**: Runs snowball sampling with `auto_create_actors: true`
(the default) to discover new actors and automatically add them to the Actor
Directory.

**What happens**: The API returns HTTP 200 with `newly_created_actors: 0`. All
discovered actors have empty `actor_id` fields. The actors are NOT created in the
database.

**Why it blocks research**: The researcher discovers 20 relevant Danish-discourse
actors but cannot do anything with them. They cannot add them to a list, cannot use
them as seeds for deeper snowball waves, and cannot collect content from them. The
only workaround is to manually create each actor one by one via the Actor Directory,
which defeats the purpose of automated discovery.

**Root cause (user-visible)**: The actor creation step completes without error but
produces no visible result. There is no error message, no warning, nothing. The
researcher has no way to know that auto-creation failed.

**Affected endpoint**: `POST /actors/sampling/snowball` with `auto_create_actors: true`

### B-2. 500 traceback when combining `auto_create_actors` + `add_to_actor_list_id` [core]

**What the researcher does**: Runs snowball sampling with both auto-creation enabled
AND a target actor list specified (the default behavior in the UI when opened from
the Actor Directory with a list context).

**What happens**: The API returns HTTP 500 with a raw Python traceback containing
internal details:
```
asyncpg.exceptions.InFailedSQLTransactionError: current transaction is
aborted, commands ignored until end of transaction block
[SQL: SELECT actor_list_members.actor_id ...]
```

In the browser UI, this appears as a red error banner saying
"HTTP 500: Internal Server Error" with no actionable information.

**Why it blocks research**: The researcher's complete workflow (discover actors +
add to list) is impossible. They must use a multi-step manual workaround:
1. Run snowball without list add
2. Note the discovered actor names
3. Manually create each actor in the Actor Directory
4. Manually add each actor to the list

**Root cause (user-visible)**: The system crashes after discovering actors but before
saving them. The researcher has no way to recover the discovery results because they
are lost when the request fails.

**Technical note for `[core]`**: The `auto_create_actor_records` method in
`sampling/snowball.py` calls `await db.rollback()` at line 403 when an individual
actor creation fails, which poisons the shared SQLAlchemy AsyncSession. The
subsequent `_bulk_add_to_list` call in `routes/actors.py` at line 1270 then fails
because PostgreSQL rejects all queries on an aborted transaction. The fix should use
`SAVEPOINT` (nested transactions) or a separate session for auto-creation.

### B-3. Raw traceback exposed in HTTP response [core]

**What the researcher sees**: When the 500 error occurs, the full Python traceback
is returned as the HTTP response body (text/plain). This includes:
- Internal table names (`actor_list_members`, `actor_platform_presences`)
- Internal column types (`UUID`, `JSONB`)
- Database connection strings (via SQLAlchemy error messages)
- Library versions and internal file paths

**Security impact**: Information disclosure. Production deployments must never expose
internal tracebacks to end users.

**User impact**: A researcher seeing "asyncpg.exceptions.InFailedSQLTransactionError"
has no useful information about what went wrong or how to fix it.

---

## Data Quality Findings

### DQ-1. Actor deduplication not enforced across creation methods

Actors created via different methods (manual, snowball auto-create, bulk import)
can duplicate the same real-world person. For example, "Pelle Dragsted" exists as
a manually created actor AND could be re-created by snowball auto-creation if a
different DID is used. There is no cross-referencing by canonical name during
auto-creation.

### DQ-2. Platform presences can be duplicated

An actor can accumulate multiple presences for the same platform (e.g., two Bluesky
presences with different DIDs for Pernille Rosenkrantz-Theil). The unique constraint
is on `(platform, platform_user_id)`, but different DIDs for the same person are not
detected as duplicates.

### DQ-3. Snowball discovery limited to follow/follower graphs

The snowball sampling only discovered actors via `bluesky_follows` and
`bluesky_followers` methods. The co-mention fallback (which would discover actors
mentioned in the same content) requires existing content_records in the database.
Without prior collection runs, the co-mention strategy has no data to work with.

This is a chicken-and-egg problem: the researcher needs actors to run collections,
but needs collections to discover actors via co-mention. The documentation does not
explain this dependency.

---

## Documentation Gaps

### DOC-1. No documentation of auto_create_actors behavior

The snowball sampling UI and API documentation do not explain what `auto_create_actors`
does, what happens when it fails, or what the `actor_id` field means in the response.
A researcher would not know that empty `actor_id` values indicate a failure.

### DOC-2. No documentation of platform credential requirements for snowball

The snowball sampling UI lists all 10 platforms as available but does not indicate
which platforms require configured credentials. A researcher selecting "YouTube" for
expansion has no way to know that a YouTube Data API key must be configured in the
admin credential pool before YouTube expansion will work.

### DOC-3. No documentation of co-mention prerequisite

The co-mention discovery method requires existing content_records for the seed actors.
This prerequisite is not documented in the UI or guides. A researcher who has not
yet run any collections would not understand why co-mention discovery finds nothing.

---

## Recommendations

### Priority 1 -- Blockers (must fix before snowball is usable)

1. **[core] Fix `auto_create_actor_records` transaction handling**: Replace the
   `db.rollback()` error handling with `SAVEPOINT`-based nested transactions
   (SQLAlchemy `begin_nested()`) so that individual actor creation failures do not
   poison the entire session. Alternatively, run auto-creation in a separate
   database session.

2. **[core] Fix combined auto_create + list_add flow**: Ensure that the
   `_bulk_add_to_list` step can execute even if some auto-creations failed. The
   session must be in a valid state for the list-add query.

3. **[core] Add proper error handling for 500 responses**: Install a global exception
   handler that catches unhandled errors and returns a structured JSON response with
   a user-friendly message and a correlation ID, rather than exposing raw tracebacks.

### Priority 2 -- Friction reduction

4. **[core] Add per-platform expansion status to snowball response**: Include a
   `platform_status` field in the response showing each platform's outcome:
   `"expanded"`, `"no_credentials"`, `"no_presences"`, `"no_results"`, `"error"`.

5. **[db] Fix ActorResponse.presences serialization**: Either rename the Pydantic
   field to `platform_presences` to match the ORM, or add a `model_validator` that
   maps `platform_presences` to `presences`.

6. **[core] Deduplicate seed actor entries in snowball response**: Group seed actors
   by UUID so each unique actor appears once, with all their platforms listed in the
   `platforms` array, rather than one entry per presence.

7. **[frontend] Show credential status in snowball platform selector**: Gray out or
   annotate platforms that have no configured credentials, with a message like
   "Requires API key -- configure in Admin > Credentials."

### Priority 3 -- Documentation and polish

8. **[research] Document the snowball sampling workflow in a guide**: Create
   `docs/guides/snowball_sampling.md` explaining the two-step process, platform
   requirements, auto-creation behavior, and the co-mention prerequisite.

9. **[frontend] Add "Discovered actors were not saved" warning**: When
   `newly_created_actors: 0` but discovered actors exist, show a warning explaining
   that the actors need to be manually created or that auto-creation encountered
   an issue.

10. **[core] Prevent duplicate platform presences for the same actor**: Before
    creating a new presence, check whether the actor already has a presence on that
    platform and warn or merge instead of creating a duplicate.
