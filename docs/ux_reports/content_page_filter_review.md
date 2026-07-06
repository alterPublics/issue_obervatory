# UX Review — Content Page Filter Review

> **Update 2026-04-10:** Following this review, the page was renamed from "Content Browser" to "Recent Content" and the sort semantics were documented. All "representative sample" language was removed from the UI. This report is a historical record of the pre-rename state.

**Date:** 2026-04-10
**Role:** UX evaluator (researcher perspective)
**Evaluated:** `src/issue_observatory/api/routes/content.py` and `src/issue_observatory/api/templates/content/browser.html`
**Test data:** 4.15M content records across 17 platforms, 100 collection runs. Primary evaluation against the admin user's "remigration" project (10 platforms, 75k records, 1,852 term-matched).

---

## Executive Summary

- **The Content page silently hides the majority of collected data behind two invisible default filters** (`content_types=["post"]` and auto-applied `language`), so a researcher opening the page on the "remigration" project sees **33 records out of ~75,000**. There is nothing in the sidebar that tells them those defaults are active.
- **Filtering by an arena whose content type is not "post" returns zero results** — Google Search, YouTube, Wikipedia, RSS, GDELT, Ritzau, TikTok, Twitter, Gab are all silently empty-stated even when the project has thousands of matching records. Toggling "Show non-matching content" does NOT fix this.
- **The record-count badge disagrees with the rendered table** whenever any arena checkbox is selected: for `arenas=facebook`, the page shows "11 records" in the header but renders ~50 rows in the table, because the count uses `show_all=False` while the row query uses `effective_show_all=True`. Researchers have no way to trust either number.
- **The initial page load and subsequent HTMX filter changes use different code paths with different defaults**, so the record count jumps as soon as the researcher touches any filter (e.g. 33 → 48 for the same data). This breaks researcher trust in "what am I actually looking at?".
- **Several advertised filter dimensions are missing entirely from the UI** — there is no actor/author filter, no query-design filter, no content-type filter for real types like `video`, `search_result`, `article`, `tweet`, `press_release`, etc. (only binary "Posts / Comments"). A researcher cannot answer "show me Google search results" without editing the URL by hand.
- **Representative sampling is broken**: the table is always ordered by `published_at DESC`, so the default sample is whatever was most recently published in the newest platform. In one test, 200 rows were all Facebook comments with identical timestamps — no cross-platform variety, no time spread.

---

## Filter Inventory (as shown in the sidebar)

| # | Filter name (UI label) | Control | Backend param(s) | Expected | Observed | Status |
|---|---|---|---|---|---|---|
| 1 | Search (full-text) | text input | `q` | Danish tsvector search across title + text | Works. Danish characters (æ, ø, å) are preserved and match correctly. | PASS |
| 2 | Arena | Alpine-rendered checkbox group (loads `/api/arenas/`) | `arenas` (multi) | Multi-select OR filter by platform_name | Works in isolation but interacts destructively with hidden default `content_types=["post"]`: selecting Google Search, YouTube, TikTok, Wikipedia, RSS, etc. returns zero results | BROKEN (Blocker #1) |
| 3 | Date range — From | `<input type=date>` | `date_from` | Lower bound on `published_at` | Parses YYYY-MM-DD correctly. Invalid dates silently ignored (returns full dataset). | PASS (minor: silent on bad input) |
| 4 | Date range — To | `<input type=date>` | `date_to` | Upper bound on `published_at`, end-of-day | Works. | PASS |
| 5 | Language | `<select>` (da/en/de/kl/sv/no/ru/fr) | `language` | Filter by effective language (raw col + enrichment fallback) | Filter itself works. But: (a) `da` is shown selected as the default even when the project's query design is `en`; (b) empty string `""` is treated as "auto-apply project default" not "all languages" — "All languages" option silently reverts to Danish | BROKEN (Blocker #2) |
| 6 | Collection Mode | `<select>` All / Batch / Live | `mode` | Filter by run mode | Works. Selecting Live with no live runs shows empty state with no explanation. | PASS (minor friction) |
| 7 | Project | `<select>` | `project_id` | Scope to a single project | Works, but "All projects" on initial load silently auto-selects the researcher's most recent project. | BROKEN (Blocker #3) |
| 8 | Collection Run | `<select>` grouped by query design | `run_id` | Restrict to one run's records (incl. linked) | Works. Grouped by query design. But only last 20 runs shown — older runs unreachable except via URL. | PASS (minor: 20-run cap invisible) |
| 9 | Search Term | `<select>` populated via HTMX when run is chosen | `search_term` | Filter by exact match on `search_terms_matched` array | Dropdown populates but includes terms only present via `content_record_links`. Selecting those returns zero because main query doesn't resolve links. | BROKEN (Major #4) |
| 10 | Scrape Status | `<select>` pending/scraped/failed | `scrape_status` | Filter by scrape lifecycle | Works. But `scraped` returns 83 records and `failed` returns zero — dropdown options are mostly useless. | PASS (minor: misleading options) |
| 11 | Matching (checkbox) | "Show non-matching content" | `show_all` | Include actor-tracked records without term match | Works when it applies, but: (a) initial load badge ignores this flag (count/row mismatch); (b) does NOT override `content_types=["post"]` default | BROKEN (Blocker #1) |
| 12 | Content Type | checkbox pair "Posts"/"Comments" | `content_types` (multi) | Filter by content_type column | Fundamentally incomplete. UI offers two values, DB has 14: `comment, post, search_result, video, reply, autocomplete_suggestion, ai_chat_citation, tweet, wiki_pageview, reel, article, scraped_web_page, ai_chat_response, press_release`. "Posts" only matches literal `'post'` string. | BROKEN (Blocker #1) |
| 13 | Reset filters | `<a href="/content">` | none | Clear all filters | Does NOT truly reset — re-triggers auto-project-selection and auto-language-default logic. | BROKEN (Major #5) |
| — | Sort columns | clickable `<th>` | `sort_by`, `sort_dir` | Change ordering, repaginate | Works. Non-default sort switches silently to offset pagination. | PASS |
| — | Actor / Author | missing | — | Filter by author name or actor entity | Not implemented in UI, not accepted as backend param. | MISSING (Blocker #4) |
| — | Query Design | missing | `query_design_id` accepted by route signature but never applied to browse query | Filter to one query design | Not implemented. | MISSING (Major #6) |

---

## Detailed Findings

### BLOCKER #1 — Invisible default filters silently hide 95% of collected data

**Evidence.** Open `/content/` as admin. The backend:
1. Auto-selects the researcher's most recent project (`remigration`).
2. Auto-sets `content_types = ["post"]` because the form provides no value.
3. Auto-sets `language = 'da'` from the project's query design.
4. Auto-sets `term_matched = True` unless `show_all` is checked.

Result: remigration project has 1,852 term-matched records across 10 platforms, but the page renders "33 records":

```
DB:                                                    75,259 records in remigration
+ term_matched=true                                     1,852
+ content_type='post'                                      48
+ effective_language='da'                                  33   ← what the page displays
```

**Impact per arena** (remigration project with all content types selected):

| Arena | DB count | Default filter shows |
|---|---|---|
| facebook | 51,885 | 0 (no posts with content_type='post') |
| youtube | 18,707 | 0 |
| telegram | 2,756 | ~2 |
| google_search | 660 | 0 |
| wikipedia | 500 | 0 |
| tiktok | 276 | 0 |
| x_twitter | 180 | 0 |
| google_autocomplete | 40 | 0 |
| reddit | 33 | ~18 |
| bluesky | 27 | ~17 |

**User experience.** The researcher assumes 33 records is what was collected. They have no way to know that 75,000 records exist unless they:
1. Change Language to "All languages" (which doesn't work — see Blocker #2)
2. Check the "Comments" box — but this doesn't include `video`, `search_result`, `article`, `tweet`, etc.
3. Toggle "Show non-matching content" — but this doesn't override `content_types` either.

There is no path in the UI that will show them the 51,885 Facebook records.

**Reproduction — arena filter silently empty:**
```
GET /content/?project_id=a79298e3-...&arenas=google_search
→ "No content matches your filters" empty state
→ But project has 660 google_search records (all content_type='search_result')
```

**Hypothesis.** The default `content_types if content_types else ["post"]` assumes the column holds social-media-style values. It never considered Google Search, YouTube, RSS, GDELT. The "Posts / Comments" checkbox pair is a model mismatch — the UI exposes a binary choice over a 14-valued column.

**Tagged:** `[core]` (auto-default at `content.py:1067`), `[frontend]` (Posts/Comments checkboxes at `browser.html:254-278`).

---

### BLOCKER #2 — Language filter default lies about itself

**Evidence.** Request `/content/` with no query params. The `<select name="language">` dropdown shows `"Danish (da)"` with `selected` attribute — the researcher never chose Danish. The backend silently looked up `QueryDesign.language` and applied it, even though the dropdown contains `"All languages"` (value="").

If the researcher clicks "All languages" and submits, the form sends `language=""`. The backend code `if not language and project_id:` treats empty string as missing and re-applies the project default.

```
GET /content/?project_id=a79298e3-... &language=        →  "22 records"
GET /content/?project_id=a79298e3-... &language=da      →  "22 records"
GET /content/?project_id=a79298e3-... (no language)     →  "22 records"
```

All three return the same count. The researcher cannot deselect the language filter from the UI.

**Hypothesis.** Auto-default logic at `content.py:1043-1051` uses `if not language` which matches both `None` and `""`. Should distinguish "never sent" vs "explicitly cleared".

**Tagged:** `[core]`.

---

### BLOCKER #3 — Row count and record count disagree by design

**Evidence.** Request `/content/?project_id=...&arenas=facebook` (any single arena trigger).

- Sidebar checks one arena → `effective_show_all = True` in the row query (`content.py:1063`).
- Count badge uses `show_all=show_all` (raw) instead of `show_all=effective_show_all` (`content.py:1157` and `:1456`).
- Consequence: browse query pulls non-term-matched records, count query excludes them.

```
GET /content/?project_id=a79298e3-...&arenas=facebook
→ record-count badge:   "11 records"
→ rendered table rows:  ~50 (with "Load more" sentinel, can scroll to 2000)

GET /content/?project_id=a79298e3-...&platform=facebook   (no effective_show_all path)
→ record-count badge:   "11 records"
→ rendered table rows:  11  ← consistent
```

**User impact.** Researcher checks "Facebook" and sees 50 rows. Header says "11 records". They have no idea which is correct. If they export, they get far more than 11. If they cite "11 records" in a paper, they are lying to their readers.

**Hypothesis.** Bug: `show_all=show_all` in two `_count_matching` call sites should be `show_all=effective_show_all`. Easy fix, severe user-visible confusion until done.

**Tagged:** `[core]`.

---

### BLOCKER #4 — No actor / author filter in the UI

**Evidence.** Task brief specifies filtering by actor. Content browser has no `actor_id`, `author_id`, or author name filter. Backend silently accepts and ignores `author_id=xyz`. An actor profile page can link to content, but the content browser itself offers no way to narrow to a specific actor.

**User impact.** "Show me every post by Pia Kjærsgaard on any platform" is a basic researcher question. The Content page cannot answer it.

**Tagged:** `[core]` (route), `[frontend]` (no UI).

---

### MAJOR #5 — Reset filters does not reset

**Evidence.** Sidebar "Reset filters" is `<a href="/content">`. Clicking navigates to `/content/` with no query params. Backend auto-selects latest project and auto-applies project's language. "Reset" cycles back to the same invisible-default state, not a blank slate.

**Tagged:** `[core]`, `[frontend]`.

---

### MAJOR #6 — search_term dropdown shows terms that produce zero results

**Evidence.** `/content/search-terms?run_id=afaecb02-...` returns options including `grønland`, `nato`, `putin`, `trump`, `arktis`. All come from records linked via `content_record_links` to that run. When the researcher picks `grønland`, the main browse query uses `search_terms_matched @> ['grønland']` **without** the link-resolution clause (`_run_id_filter`):

```
GET /content/records?project_id=...&run_id=afaecb02&search_term=grønland
→ "No content matches your filters"
```

Dropdown uses link-aware query; main browse query does not. Creates a dead-end.

**Tagged:** `[core]`.

---

### MAJOR #7 — No query_design filter from the UI

**Evidence.** `content_browser_page` signature accepts `query_design_id` but only uses it to populate the quick-add modal. Filter never applied to the browse query. Sidebar has no query-design selector.

**Tagged:** `[core]`, `[frontend]`.

---

### MAJOR #8 — Initial-load and HTMX-refresh paths disagree

**Evidence.** `/content/` auto-applies project + language defaults. `/content/records` (HTMX refresh) only applies project when given but does not auto-select, and does not apply project language default.

```
Initial load (GET /content/?project_id=a79298e3-...&search_term=remigration)
→ HTML header:     "33 records"
→ HTMX refresh (GET /content/records?project_id=...&search_term=remigration)
→ OOB count swap:  "48 records"
```

Same filters, same project, count jumps from 33 to 48. Researcher will assume "my last action found 15 more records" — but nothing changed.

**Tagged:** `[core]`.

---

### MAJOR #9 — Representative sampling is not representative

**Evidence.** The page's core purpose is to show a "small representative sample of content collected from any platform". In practice:

- Default sort is `published_at DESC NULLS LAST`. Top 50 rows are whatever is newest.
- With `show_all=true` and all content types, first 200 rows in remigration were 200 Facebook comments all sharing one timestamp (`2026-04-02 16:33:48`). No variation across platforms, authors, or time.
- No "sample across platforms" mode, no random sampling, no stratified sampling.
- Sample size not controllable from UI (backend defaults to 50 per page, hard cap 2000).

**User impact.** A researcher who wants to "spot-check what this collection actually looks like" gets a biased view that always reflects the largest most-recent batch.

**Tagged:** `[core]`, `[frontend]`, `[research]` (needs product decision).

---

### MINOR #10 — Platform vs arena terminology collision

**Evidence.** Sidebar labels the checkbox group "Arena", but checkboxes send `platform_name` values (`reddit`, `bluesky`, `google_search`) and backend filters on the `platform` column. The `arena` column in the DB holds grouping labels (`social_media`, `news_media`, `search`) and cannot be filtered from the UI. Two different filters use "Arena" for different concepts.

**Tagged:** `[frontend]`, `[research]`.

---

### MINOR #11 — Scrape status filter exposes useless options

**Evidence.** DB distribution:

```
scrape_status | count
--------------+--------
(empty)       | 4,044,025
pending       |   110,249
scraped       |        83
(no failed)
```

"Scraped" returns 83 records across entire DB; "Failed" returns nothing.

**Tagged:** `[core]` (remove filter or rethink values).

---

### MINOR #12 — Invalid filter values silently return empty instead of error

**Evidence.** `language=xx`, `mode=fake`, `scrape_status=invalid`, future date ranges all return empty state without explanation. Empty-state copy reads "Try broadening the filters" but the real fix is "you gave an unknown value".

**Tagged:** `[frontend]`.

---

### MINOR #13 — Project dropdown says "All projects" but behaviour is "latest project"

**Evidence.** On initial load, project select shows auto-selected project as selected. Researcher who wants "everything" will click "All projects" and be confused by counts (still gets default content_types and language filters).

**Tagged:** `[frontend]`.

---

## Filter Combination Matrix

Tested on remigration project as admin. "Default" means all hidden defaults active.

| Filter combination | Expected | Observed | Status |
|---|---|---|---|
| (none) | Show reasonable sample of all content | 33 of 75,259 records (1 platform dominates) | FAIL |
| arenas=reddit | Reddit content | ~18 rows, count matches | PASS (by accident) |
| arenas=google_search | 660 Google Search results | Empty state | FAIL |
| arenas=youtube | 18,707 YouTube videos | Empty state | FAIL |
| arenas=facebook | 51k Facebook records | "11 records" badge but ~50 rows | FAIL (count/row mismatch) |
| arenas=reddit + language=en | English reddit posts | 1 row | PASS |
| arenas=reddit + date_from + mode=batch | 3-filter AND | Narrows correctly | PASS |
| arenas=reddit + date + mode + language + q | 5-filter AND | Works | PASS |
| run_id=X + search_term=grønland (dropdown) | Records for that term in that run | Zero (linked-only terms) | FAIL |
| search_term=remigration (no run_id) | All records with that term | 48 records | PASS |
| arenas=reddit + arenas=bluesky (multi) | Both platforms | 60 records | PASS |
| arenas=reddit & platform=bluesky | Ambiguous which wins | arenas wins, platform silently ignored | PARTIAL |
| show_all=true + arenas=google_search | Show all google_search | Empty (content_types=post still applies) | FAIL |
| content_types=post,comment + arenas=youtube | Include videos? | Empty (videos aren't post/comment) | FAIL by design |
| sort_by=engagement_score desc | Sort by engagement | Works (offset pagination) | PASS |
| reset filters | Clean slate | Re-applies defaults | FAIL |
| date_from=2099-01-01 | Future date | Empty state, no warning | PARTIAL |
| language=xx | Unknown lang | Empty, no warning | PARTIAL |

**Summary.** Pure social-media (Reddit/Bluesky/Telegram/Facebook) + date/mode/language compose correctly. Anything involving a non-social arena is broken at the content_type default. Anything with search_term dropdown on a selected run is broken at link resolution. Anything with multiple arenas disagrees between count and row data.

---

## Representative-Sampling Assessment

The rendered table is a strict reverse-chronological slice of whatever passes the filter chain. Observed bias:

- **Platform bias.** Single-platform dominance is the norm because the newest batch is always on top. 200 rows all from one Facebook batch with identical timestamps.
- **Time bias.** 50-row default window, `published_at DESC NULLS LAST` ordering, no date stratification.
- **Type bias.** Only `content_type='post'` by default. Every other type invisible.
- **No control.** No page-size selector, no "random sample" toggle, no stratified-sampling option.

This is not a representative sample — it is "the newest post-typed batch". A researcher spot-checking will form a completely wrong impression of what was collected.

---

## Cross-Platform Coverage Evidence

Same remigration project, show_all=true, all content types manually enumerated in URL:

| Arena | Data in project | Default view | Explicit + all types |
|---|---|---|---|
| Reddit | yes | yes | yes |
| Bluesky | yes | yes | yes |
| YouTube | yes | **no** | yes |
| TikTok | yes | **no** | yes |
| Telegram | yes | ~2 | yes |
| X/Twitter | yes | **no** | yes |
| Facebook | yes | ~11 (but 50 rows) | yes |
| Google Search | yes | **no** | yes |
| Google Autocomplete | yes | **no** | yes |
| Wikipedia | yes | **no** | yes |

**7 of 10 available arenas are invisible in the default view.**

---

## Recommended Fixes (prioritized by researcher impact)

1. **[core] Remove the silent `content_types=["post"]` default.** Replace the Posts/Comments checkbox pair with a multi-select covering the 14 values in the column. Until this lands, researchers cannot see Google Search, YouTube, Wikipedia, or RSS data via the Content page.
2. **[core] Fix `show_all=show_all` → `show_all=effective_show_all`** at `content.py:1157` and `:1456` so count matches rendered rows.
3. **[core] Document or remove auto-selected project + auto-applied language.** Either land with no project selected (empty state prompts selection), or show visible pills. Distinguish `language=""` from `language=None`.
4. **[core] Fix search_term filter's dead-end on link-resolved runs.** Either dropdown excludes terms with no primary-record matches, or main browse query uses `_run_id_filter` to resolve links.
5. **[core] Make `/content/` and `/content/records` apply identical defaults** so count doesn't jump on first interaction.
6. **[frontend] Add actor / author filter.** Basic research primitive currently missing.
7. **[frontend] Make "Reset filters" actually reset.**
8. **[core] [research] Rethink "representative sample".** Either rename to "Recent Content" and document the sort, or implement proper sampling (random or stratified).
9. **[frontend] Expose query-design filter.** Close the existing route-level gap.
10. **[frontend] Rename "Arena" checkbox group to "Platform"** to remove collision with `arena` DB column.
11. **[frontend] Show filter validation feedback.** Warn on unknown values instead of empty state.
12. **[frontend] Surface 20-run cap** in Collection Run dropdown.
13. **[frontend] Add page-size control** and potentially a "sample" button.
14. **[qa] Add regression tests for filter combinations.**

---

## Files Relevant to This Review

- `src/issue_observatory/api/routes/content.py`
  - Lines 1030-1051: auto-select project + auto-apply language
  - Lines 1063-1067: `effective_show_all` / `effective_content_types` defaults
  - Lines 1157, 1456: `show_all=show_all` count mismatch bug
  - Lines 510-517: language filter with enrichment fallback
  - Line 1094: multi-arena IN clause
- `src/issue_observatory/api/templates/content/browser.html`
  - Lines 68-98: Alpine arena checkbox group
  - Lines 123-139: hardcoded language dropdown
  - Lines 254-278: Posts/Comments checkbox pair (incomplete)
  - Line 282-286: "Reset filters" link
  - Line 43-50: HTMX form with `hx-trigger="change"`
- `src/issue_observatory/api/templates/content/record_detail.html` — detail panel
