# Scenario 05 — Live Tracking Lifecycle

**Created:** 2026-02-17

## Research question
A researcher wants to track "folkeskole" daily across RSS Feeds and Bluesky for 30 days. Can they set up live tracking, monitor it over time, and understand when it ran and what it collected?

## Expected workflow
1. Open the collection launcher.
2. Select the query design for "folkeskole".
3. Select "Live (ongoing)" mode.
4. Launch the collection.
5. Observe the collection detail page to understand the live schedule.
6. Return the next day to see what was collected overnight.
7. After one week, review accumulated data.
8. If needed, suspend or cancel the live tracking run.

## Success criteria
- The launcher clearly labels the difference between Batch and Live modes.
- After launching in Live mode, the researcher understands when the next run fires (midnight Copenhagen time).
- The collection detail page indicates this is a live/recurring run, not a one-off.
- The researcher can cancel a live run from the UI.
- Day-over-day collection is visible in the content browser filtered by date range.

## Known edge cases
- The beat schedule fires at 00:00 Copenhagen time but this is not communicated in the launcher UI.
- RSS feeds are also collected every 15 minutes by a separate beat task independent of the manual live run — this overlap is invisible to the researcher.
- A cancelled live run cannot be resumed; a new run must be created.
- The detail page does not distinguish between a manually-launched live run and a beat-scheduled collection.
