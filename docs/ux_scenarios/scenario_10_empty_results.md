# Scenario 10 — Empty Results

**Created:** 2026-02-17

## Research question
A researcher searches for "læserbrev" (letters to the editor) on Gab, expecting zero results. Does the application communicate this gracefully, or does it look broken?

## Expected workflow
1. Run a collection for a niche Danish term on Gab and GDELT.
2. After the run completes, open the Content Browser.
3. Filter by the Gab arena.
4. Observe the empty state.
5. Navigate to the Analysis Dashboard for this run.
6. Observe how the charts handle zero records.

## Success criteria
- The Content Browser shows a visible empty state with a helpful message (not a blank white area).
- The empty state message suggests a next action (broaden filters, run a new collection).
- The Analysis Dashboard does not crash or show broken charts when there are zero records for a platform.
- Summary cards show "0" rather than "—" or blank, so the researcher can confirm collection ran but found nothing.

## Known edge cases
- The empty state message "No content matches your filters" may be misleading if the collection genuinely found nothing — the researcher may think their filter is wrong rather than that Gab had no results.
- The Analysis Dashboard charts fetch data asynchronously; if an arena returns zero rows, the chart may render empty without any label indicating this is expected (zero records collected) vs. a load error.
