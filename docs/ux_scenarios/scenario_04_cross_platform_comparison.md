# Scenario 04 — Cross-Platform Comparison

**Created:** 2026-02-17

## Research question
A researcher has collected data on "klimaforandringer" across five arenas: Bluesky, Reddit, RSS Feeds, GDELT, and YouTube. Can they meaningfully compare content and engagement across platforms in the data browser?

## Expected workflow
1. Open the Content Browser after a completed multi-arena collection run.
2. Use arena checkboxes in the sidebar to filter by a single arena.
3. Sort or inspect the Engagement column across different platforms.
4. Open a record from each arena to compare the displayed engagement figures.
5. Try to understand what "Engagement" means for each platform (likes, upvotes, views, etc.).

## Success criteria
- Arena checkbox filter works and correctly scopes results.
- Engagement score is displayed and non-zero for platforms that produce it.
- The researcher can understand what the engagement number represents for a given platform.
- The researcher is not misled into comparing a Bluesky like count directly with a YouTube view count.

## Known edge cases
- "engagement_score" is a synthetic composite — not a raw platform metric. The meaning is not explained in the browser UI.
- GDELT records have no engagement data; the column shows "—" with no explanation.
- Reddit records show an upvote score (upvotes minus downvotes), not a raw view count.
- The Arena column is hidden at resolutions below xl breakpoint, making it invisible on 1366px laptop screens.
