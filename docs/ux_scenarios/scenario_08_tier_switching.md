# Scenario 08 — Tier Switching and Credential Management

**Created:** 2026-02-17

## Research question
A researcher wants to understand what "medium tier" adds for Google Search and then switch an existing query design from free to medium tier. Can they do this without reading technical documentation?

## Expected workflow
1. Open the query design editor.
2. Look at the Arena Configuration grid — see three tier radio buttons (free / medium / premium).
3. Try to understand what "medium" provides for Google Search specifically.
4. Navigate to Admin > Credentials to add a Serper.dev API key.
5. Return to the query design and switch Google Search to medium tier.
6. Launch a collection and verify the credit estimate changes.

## Success criteria
- The tier radio buttons communicate what each tier provides, not just label it "medium".
- The credential add form guides the researcher on what fields to enter for Serper.dev specifically.
- After adding the Serper.dev credential, the researcher can return to the query design and enable medium tier without further instructions.
- The credit estimate updates to reflect the cost of medium-tier Google Search.

## Known edge cases
- The arena grid shows all three tier options (free, medium, premium) for every arena, including arenas where some tiers don't exist (e.g., Bluesky has no medium tier) — selecting medium on Bluesky silently falls back to free.
- The credential form shows a generic "API Key" field for most platforms but does not specify whether Serper uses "api_key" or a different field name, and does not link to the Serper.dev dashboard.
- There is no "what does this cost?" link from the tier selector to the pricing documentation.
