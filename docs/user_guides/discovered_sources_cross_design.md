# User Guide: Discovered Sources Across Multiple Query Designs

**Feature:** Cross-Design Discovered Sources View (YF-13)

**Location:** `/content/discovered-links`

---

## Overview

The Discovered Sources page mines outbound links from your collected content to identify accounts and channels that were mentioned but not explicitly collected. This helps you discover new relevant sources to add to your collection.

By default, the page can show links from **a single query design** or **all your query designs combined**.

---

## Viewing Discovered Sources

### Access the Page

1. Navigate to **Content** in the main menu
2. Click **Discovered Sources** in the secondary navigation

   *Or directly visit: `/content/discovered-links`*

---

## Scope Selection

### View All Your Query Designs (Cross-Design Mode)

This is the recommended starting point for exploratory research.

1. In the **Query design** dropdown at the top of the page, select **"All designs"**
2. The page will reload and show discovered links from **all your query designs combined**
3. Links that appear in multiple designs will show an aggregated source count

**When to use this:**
- You want to see which sources are mentioned across multiple projects
- You're looking for sources with high cross-project relevance
- You're starting exploratory research and want a broad view

**Example:**
If you have 3 query designs about climate, energy, and sustainability, selecting "All designs" will show you channels mentioned in any or all of those collections. A Telegram channel mentioned in all 3 designs will show `source_count: 3`.

---

### View a Single Query Design

For focused analysis on one specific project.

1. In the **Query design** dropdown, select a specific query design by name
2. The page will reload and show **only** links discovered in that design's content
3. Source counts reflect mentions within that design only

**When to use this:**
- You want to stay focused on one research question
- You're reviewing a specific collection run
- You want to see design-specific discovery patterns

---

## Filtering Options

Both modes support the same filters:

- **Platform:** Telegram, Reddit, YouTube, Bluesky, Discord, Gab, Web (generic)
- **Minimum mentions:** Slider from 1 to 50+ (filters out low-signal links)

**Tip:** Set minimum mentions to 2-3 when in "All designs" mode to surface high-confidence sources.

---

## Understanding Source Counts

### In Single-Design Mode

`source_count` = number of distinct content records in **this design** that link to the target

**Example:**
- Design: "Climate Policy Denmark"
- Telegram channel `@climateDK` mentioned in 5 posts
- Source count: **5**

### In Cross-Design Mode (All Designs)

`source_count` = number of distinct content records across **all your designs** that link to the target

**Example:**
- Design A: "Climate Policy" — `@climateDK` mentioned in 5 posts
- Design B: "Energy Transition" — `@climateDK` mentioned in 3 posts
- Design C: "Sustainability" — `@climateDK` mentioned in 2 posts
- **Total source count: 10**

This aggregation helps you identify sources with **cross-cutting relevance**.

---

## Adding Sources to Your Collection

### Quick-Add (Single Source)

1. Click the **"Add"** button next to any discovered source
2. A modal opens with pre-filled platform and identifier
3. Edit the **Display name** if needed
4. Select an **Actor type** (Individual, Organization, Bot)
5. Optionally assign to an **Actor list**
6. Click **"Add to Collection"**

The source is now in your Actor Directory and can be included in future collections.

---

### Bulk Import (Multiple Sources)

1. Check the boxes next to multiple discovered sources
2. Click **"Import Selected"** at the top
3. All selected sources are added to your Actor Directory
4. A summary banner shows how many were added vs. already existed

**Note:** Bulk import uses default values (Actor type: Individual, no actor list assignment). You can edit details afterward in the Actor Directory.

---

## Tips for Cross-Design Research

### Finding High-Signal Sources

1. Select **"All designs"**
2. Set **Minimum mentions** to 3 or higher
3. Sort mentally by platform (results are grouped by platform)
4. Look for sources that appear in multiple designs' contexts

### Identifying Platform-Specific Patterns

Use the **Platform** filter to see which platforms are most referenced:
- Telegram: often used for activist/organizing channels
- Reddit: community discussions and subreddits
- YouTube: video creators and channels
- Discord: private communities and servers

### Following the Network

1. Start with high-count sources in "All designs" mode
2. Add them to an actor list
3. Run a new collection with `collect_by_actors` to gather their content
4. Return to Discovered Sources to find **their** mentioned sources
5. Repeat (snowball sampling via link mining)

---

## Limitations & Known Behavior

### Link Extraction

- Only URLs in `text_content` are mined (not `title` or `author` fields)
- Requires `https://` or `http://` scheme
- Malformed URLs may not be detected

### Platform Classification

- Most social media platforms are detected automatically
- Unrecognized URLs fall into "Web" category with domain as identifier
- Some short URLs (t.co, bit.ly) are classified as "Web" rather than target platform

### Deduplication

- Same URL appearing multiple times in one content record = 1 source count
- Same URL in different records = multiple source counts (desired behavior)
- Cross-design aggregation merges identical targets by platform + identifier

---

## Privacy & Compliance

- **GDPR:** Discovered sources are not pseudonymized — they are public account identifiers extracted from public content
- **Retention:** Discovered links persist as long as the source content records exist
- **User Isolation:** You only see links from your own query designs (except admins)

---

## Questions?

- **Why don't I see any links?** Run at least one collection first. Links are mined from collected content.
- **Can I export discovered sources?** Not directly, but you can bulk-import them to your Actor Directory and export from there.
- **Do links update in real-time?** No, they're computed on-demand when you load the page. New collections will be reflected next time you visit.

---

## Related Features

- **Actor Directory:** Manage all your collected sources in one place
- **Actor Snowball Sampling:** Expand your network based on actor relationships
- **Content Browser Quick-Add:** Add actors while browsing content records (GR-17)

---

**Last updated:** 2026-02-19 (YF-13 verification)
