# Scenario 02 — Danish Issue Tracking

**Created:** 2026-02-17

## Research question
A researcher wants to track the Danish term "grøn omstilling" across Google Search, Danish news RSS feeds, and Bluesky. Do the collected records represent actual Danish-language content?

## Expected workflow
1. Create a new query design with the term "grøn omstilling".
2. Enable arenas: Google Search (medium tier), RSS Feeds (free), Bluesky (free).
3. Set language to Danish (da).
4. Save the query design and launch a batch collection.
5. Browse results and verify: Google results scoped to dk/da, RSS articles from Danish outlets, Bluesky posts in Danish.

## Success criteria
- Google Search results include `gl=dk&hl=da` parameters.
- RSS results come from outlets listed in DANISH_RSS_FEEDS (DR, Politiken, Berlingske, etc.).
- Bluesky results are filtered with `lang=da`.
- The language column in collected records shows "da" for all three arenas.
- The query design editor communicates the language setting clearly.

## Known edge cases
- "grøn omstilling" contains the Danish character ø — must survive encoding through all API calls.
- Google Search has no free tier; the researcher must configure Serper.dev credentials first.
- Actor-based Bluesky collection does not apply a language filter — only term-based collection does.
- The query editor does not display per-arena Danish locale settings, so the researcher cannot verify that locale is applied.
