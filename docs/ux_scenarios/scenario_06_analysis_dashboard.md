# Scenario 06 — Analysis Dashboard End-to-End

**Created:** 2026-02-17

## Research question
A researcher has completed a collection run on "sundhedsreform" across four arenas. Can they explore the results in the analysis dashboard, understand what the charts show, and download a GEXF file for Gephi?

## Expected workflow
1. Navigate from the completed collection run to the Analysis Dashboard.
2. Review the four summary cards (total records, arenas, date range, credits spent).
3. Read the Volume over Time chart — understand x-axis (dates), y-axis (record count), and per-arena series.
4. Read the Top Actors chart — understand what "actor" means (pseudonymized vs. named).
5. Read the Engagement Distribution chart — understand what is being shown.
6. Navigate to the Network Analysis section, select "Actor network" tab.
7. Download the actor co-occurrence GEXF file.
8. Open the GEXF file in Gephi and verify it loads with useful node/edge attributes.

## Success criteria
- Charts have titles and the researcher can infer what they show from the labels alone.
- Top actors panel communicates whether names shown are real display names or pseudonymized IDs.
- GEXF download link is visible and clearly labelled.
- The GEXF file opens in Gephi with nodes labelled by display_name and edges weighted by co-occurrence.

## Known edge cases
- The "Top actors" chart shows `author_display_name` if available, but falls back to `pseudonymized_author_id` — these may appear interleaved with no visual distinction.
- Charts have no axis labels — "Volume over time" does not label the y-axis as "Number of records" or x-axis as "Date".
- The engagement distribution chart shows aggregate statistics but does not explain which metric (likes, views, shares) is displayed per platform.
- All three GEXF export buttons (actor, term, bipartite tabs) link to the same endpoint URL — a researcher cannot distinguish which type of network they are downloading.
