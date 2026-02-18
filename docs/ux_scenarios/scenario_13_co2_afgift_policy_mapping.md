# Scenario 13 -- CO2 Afgift Policy Discourse Mapping

**Created:** 2026-02-17

## Research question

How is the CO2 afgift (carbon tax/levy) framed in Danish public discourse across digital media platforms in early 2026? Who are the key actors, what terms co-occur with "CO2 afgift," and does the framing differ between legacy news media (RSS), social platforms (Bluesky, Reddit), and news aggregation services (GDELT)?

## Why this scenario is a strong stress test

This scenario exercises nearly every feature of the application because:

1. **Bilingual terminology**: Both Danish ("CO2 afgift," "klimaafgift," "gron omstilling") and English ("carbon tax," "CO2 reduction") terms are required. Tests UTF-8 handling and cross-language search behavior.
2. **Cross-platform presence**: The topic spans parliament (Ritzau), newspapers (RSS), social media (Bluesky, Reddit), video (YouTube), and international aggregators (GDELT, Event Registry).
3. **Named actors**: Politicians (Mette Frederiksen, Dan Jorgensen, Lars Lokke Rasmussen), organizations (Dansk Industri, Klimaraadet, Landbrug & Fodevarer), media outlets.
4. **Term co-occurrence**: "CO2 afgift" frequently co-occurs with "landbruget," "gron omstilling," "klimaneutral," "2030" -- making network analysis methodologically meaningful.
5. **Temporal dynamics**: Peaks around budget negotiations and EU regulation milestones.

## Expected workflow

1. Create a query design named "CO2 Afgift DK 2026" with language set to Danish (da).
2. Add 7 search terms:
   - "CO2 afgift" (phrase)
   - "klimaafgift" (keyword)
   - "carbon tax" (phrase)
   - "gron omstilling" (keyword)
   - "#CO2afgift" (hashtag)
   - "CO2-reduktion" (keyword)
   - "klimaneutral" (keyword)
3. Add 6 actors: Mette Frederiksen, Dan Jorgensen, Lars Lokke Rasmussen, Dansk Industri, Klimaraadet, Landbrug & Fodevarer.
4. Enable arenas: Google Search, Google Autocomplete, Bluesky, Reddit, YouTube, RSS Feeds, GDELT, Ritzau Infostream.
5. Disable: Telegram, TikTok, Gab (minimal Danish policy discourse).
6. Launch a batch collection with date range 2026-01-01 to 2026-02-17.
7. Monitor collection via SSE until completion.
8. Browse content filtered by arena to examine per-platform coverage.
9. Filter by language "Danish (da)" to verify locale filtering.
10. Navigate to the Analysis dashboard, examine volume-over-time chart.
11. Download the term co-occurrence GEXF file.
12. Open the GEXF file in Gephi and verify node/edge attributes.
13. Use the Actor Directory to add platform presences for the 6 actors.
14. Run snowball sampling from the Actor Directory with 2 seed actors.
15. Export all results as CSV and verify column headers.

## Success criteria

- All 8 selected arenas appear in the arena configuration grid and can be enabled.
- The term type dropdown explains what "phrase" vs "keyword" means.
- The arena configuration saves and shows confirmation.
- The query design detail page shows arena configuration alongside terms and actors.
- The collection runs all 8 arenas and shows per-arena status.
- Content browser records are predominantly Danish-language (da).
- The analysis dashboard charts have readable axis labels.
- The term co-occurrence GEXF file opens in Gephi with correct node labels (the 7 search terms) and weighted edges.
- The CSV export has human-readable column headers.
- Snowball sampling discovers plausible additional actors in the climate policy space.

## Known edge cases

- Danish characters (ae, oe, aa) in search terms must survive UTF-8 encoding through all API calls.
- "CO2 afgift" vs "CO2-afgift" (with hyphen) are different terms -- the system should ideally match both.
- Jyllands-Posten RSS feed may return 404 (noted in danish_defaults.py comments).
- GDELT dual-query deduplication (sourcelang=danish + sourcecountry=DA) must not inflate record counts.
- Reddit r/dkfinance is not in the default subreddit list but contains relevant economic discussions.
- The arena grid currently only shows 11 of 19 implemented arenas -- Event Registry and X/Twitter are invisible.
- Tier selection for arenas that only support "free" is misleading (no warning when selecting "medium" or "premium").
- Engagement scores are not comparable across platforms.

## Related reports

- `/docs/ux_reports/co2_afgift_mapping_report.md` -- Full evaluation report from the initial run of this scenario (2026-02-17).
