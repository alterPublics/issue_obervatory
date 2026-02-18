# Scenario 09 — Credential Failure Recovery

**Created:** 2026-02-17

## Research question
A researcher's Serper.dev API key has expired mid-collection. What do they see on the collection detail page, and can they understand what went wrong and recover without developer assistance?

## Expected workflow
1. A collection run is in progress (Google Search arena is running).
2. The Serper.dev key is invalid — the arena task fails.
3. Researcher watches the live detail page.
4. The Google Search task row shows a "failed" status.
5. Researcher reads the error message in the Notes column.
6. Researcher navigates to Admin > Credentials, identifies the bad key, removes and replaces it.
7. Researcher re-launches the collection run.

## Success criteria
- The task row's Notes column shows a human-readable error message, not a raw exception class name.
- The error message says something actionable: "API key invalid" or "check your Serper.dev credential".
- The error count on the credential in Admin > Credentials is visible and nonzero.
- The researcher can identify which credential caused the failure.
- The "Run again" button on the completed (failed) run page works.

## Known edge cases
- The error message stored in collection_tasks comes from the ArenaCollectionError message, which reads "google_search: no credential available for tier=medium" — this is technically accurate but not researcher-friendly.
- The credential's error_count field increments but the credential may still show as "Active" if it has not hit the circuit-breaker threshold.
- There is no link from the failed task row directly to the Admin > Credentials page.
- Rate-limit errors trigger auto-retry silently — the researcher sees "running" for up to 15 minutes before the task resolves, with no progress indicator.
