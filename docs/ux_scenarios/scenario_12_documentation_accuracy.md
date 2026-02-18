# Scenario 12 — Documentation Accuracy

**Created:** 2026-02-17

## Research question
A researcher reads `docs/guides/what_data_is_collected.md` to understand what they are collecting and what is excluded. Is the documentation accurate relative to the actual collector implementations?

## Expected workflow
1. Read the Bluesky section of the documentation.
2. Cross-check with the BlueskyCollector source code.
3. Read the RSS Feeds section.
4. Cross-check with DANISH_RSS_FEEDS in danish_defaults.py.
5. Read the YouTube section.
6. Cross-check with the YouTubeCollector source code.
7. Note any discrepancies between documentation claims and actual implementation.

## Success criteria
- Documentation accurately describes what is and is not collected.
- Danish targeting methods described match the actual API parameters used.
- The "NOT collected" lists are accurate and complete.
- No claims in the documentation contradict the source code behaviour.

## Known edge cases
- Bluesky firehose streaming is described as available but requires the `websockets` package which is not installed by default — the documentation does not mention this prerequisite.
- The documentation says Bluesky actor-based collection uses `getAuthorFeed` — this is accurate.
- The documentation lists 27+ RSS feeds but the actual DANISH_RSS_FEEDS dict contains 27 entries — this matches.
- YouTube is listed in the documentation's summary table but the documentation body does not have a standalone YouTube section — it is implicitly covered under "Social Media Platforms" which only covers social platforms, leaving YouTube coverage ambiguous.
