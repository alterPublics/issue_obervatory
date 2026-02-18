# Scenario 03 — Actor Discovery via Snowball Sampling

**Created:** 2026-02-17

## Research question
A researcher has identified three Danish politicians on Bluesky and Reddit. Can they use the actor discovery feature to find additional Danish discourse actors connected to these seed actors?

## Expected workflow
1. Navigate to the Actor Directory.
2. Add three Danish politicians as actors with their platform handles.
3. Open an actor's detail page.
4. Find and use the snowball sampling / actor discovery function.
5. Review discovered actors and decide which ones to add to the research corpus.
6. Add selected discovered actors to the query design's actor list.

## Success criteria
- A visible and labelled path from actor list to "discover more like them" exists.
- After a snowball run, the researcher sees a list of discovered actors with plausible metadata (platform, username, discovery depth).
- The researcher can understand whether a discovered actor is on Bluesky, Reddit, or another platform.
- Discovered actors can be added to a query design from the results view.

## Known edge cases
- Actors discovered via snowball who are not yet in the database cannot be expanded in subsequent waves — this is an implementation limitation the researcher must understand.
- Actor discovery on Reddit may surface English-language users who post in r/Denmark, not necessarily Danish-speaking actors.
- The UI distinction between "actor in the system" and "actor discovered via API" may be unclear.
