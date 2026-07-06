# Content Page Filter System - QA Audit Report

> **Update 2026-04-10:** Following this audit, the page was renamed from "Content Browser" to "Recent Content" and the sort semantics (`ORDER BY published_at DESC`) were surfaced in the UI. All "representative sample" language was removed from source code and user-facing copy. This report is a historical record of the pre-rename state.

Date: 2026-04-10
Auditor: QA Guardian
Scope: `/content/` HTML page, `/content/records` HTMX fragment, `/content/export`, filter sidebar form, supporting helpers, indexes, and tests.

## TL;DR

The content page sidebar advertises **13 filter controls**. Of those:

- **5 work end-to-end and compose correctly** (`date_from`, `date_to`, `language`, `project_id`, `scrape_status`).
- **3 work but have correctness or UX defects** (`arenas` multi-select, `run_id`, `search_term`).
- **2 are wired partially and silently break composition** (`q` full-text, `content_types`).
- **1 is critically broken** (`show_all` checkbox — mutated upstream of both `_count_matching` and the base filter, creating count/row divergence and making `show_all` visually behave the opposite of what the user selected when combined with arenas).
- **1 is cosmetic-only** (`mode` — filters results but is not passed to `/content/export`).
- **1 is documented in the UI but has no server-side parser** (none — all declared template fields have a handler, but several are silently dropped by `/content/export`).

In addition:

- The content page and the analysis layer use **two different filter stacks** (`_build_browse_stmt` / `_build_content_stmt` vs. `analysis._filters.build_content_filters`). The analysis stack excludes duplicates (`raw_metadata->>'duplicate_of' IS NULL`); the content page does **not**. Linked-record (content_record_links) cross-design composition is also asymmetric between the two.
- Sampling is not representative — it is strictly `ORDER BY published_at DESC, id DESC` keyset pagination. There is no random seed, no stratification by platform/arena/date, and no shuffle. A user asking for "a representative sample of a large corpus" gets "the 50 most recent records that match", which is a **sampling correctness regression against the stated product goal**.
- The `/content/export` endpoint silently drops at least 6 filters declared in the sidebar form (`arenas` is supported, `mode`, `project_id`, `show_all`, `scrape_status`, `content_types`, `q` are NOT). Since the Export CSV button uses `hx-include="#filter-form"`, users receive an exported dataset that does not match what is rendered in the table. This is a high-severity data correctness bug for researchers.
- The count badge (`#record-count`) disagrees with the rendered rows in three distinct code paths (see Composition Analysis §3).
- JSONB filters on `raw_metadata` (channel, subreddit, etc.) are **not exposed at all** — the only JSONB access is the language fallback via `raw_metadata->enrichments->language_detection->language`. If a researcher needs to filter "Danish subreddits only" or "Telegram channel X only", the code path does not exist.

---

## 1. Filter-by-Filter Status Table

All line numbers refer to `src/issue_observatory/api/routes/content.py` (2498 lines) and `src/issue_observatory/api/templates/content/browser.html` (1010 lines) as of commit `ea9e5f2`.

| # | Filter | Template location | Route handler | SQL clause generated | Status | Severity |
|---|--------|------------------|---------------|---------------------|--------|----------|
| 1 | `q` (full-text) | `browser.html:59-66` `<input name="q">` | `content.py:968,1207` → `_build_browse_stmt:569-575` | `to_tsvector('danish', coalesce(text_content,'') || ' ' || coalesce(title,'')) @@ plainto_tsquery('danish', :q)` | **Partial** — works on page + records fragment; **silently dropped by `/export`** | High |
| 2 | `arenas[]` (multi checkbox) | `browser.html:86-93` (Alpine `arenaFilter` component) | `content.py:969,1208,1701` → routed into `platform_filter` single or `.where(platform.in_(arenas))` post-hoc | `platform = :p` OR `platform IN (...)` | **Partial** — composes OK with other filters; **but the "show all arenas" side-effect on line 1063 and 1324 silently overrides `show_all` semantics** | High |
| 3 | `platform` (singular) | Not in template — URL-only | `content.py:970` (page) / **missing from `/records`** (line 1209 only accepts `arenas`) | `platform = :p` | **Dead code on `/records`** — `platform=` URL param is silently dropped by the fragment endpoint, so any `hx-push-url` with a platform query arg breaks on subsequent HTMX reloads | Medium |
| 4 | `arena` (singular) | Not in template | `content.py:971` (page) / `content.py:1336` sets `arena=None` in `_build_browse_stmt` call | `arena = :a` for page route only; **ignored for `/records`** | **Broken** — the singular `arena` URL param is applied on the initial page load but dropped on HTMX reload, producing a filter that works once and then disappears | Medium |
| 5 | `date_from` | `browser.html:106-111` | `content.py:972,1210` → `_parse_date_param` → `_build_browse_stmt:506-507` | `published_at >= :date_from` | **OK** | — |
| 6 | `date_to` | `browser.html:113-119` | `content.py:973,1211` → `_parse_date_param(..., end_of_day=True)` → `_build_browse_stmt:508-509` | `published_at <= :date_to` | **OK** (end-of-day handling correct at `content.py:409-412`) | — |
| 7 | `language` | `browser.html:125-139` | `content.py:974,1212` → `_build_browse_stmt:510-517` | `split_part(COALESCE(NULLIF(language,''), raw_metadata->'enrichments'->'language_detection'->>'language'), '-', 1) = :language` | **OK** but **not indexed** — the functional expression is not covered by any index; sequential scan on every filter change. See §4. | Medium |
| 8 | `mode` (batch/live) | `browser.html:143-154` | `content.py:977,1215` → `_build_browse_stmt:537-547` | `collection_run_id IN (SELECT id FROM collection_runs WHERE mode = :mode)` | **Partial** — works on page + records; **silently dropped by `/export`** (line 1684 has no `mode` param) | High |
| 9 | `project_id` | `browser.html:158-169` | `content.py:979,1216` → `_build_browse_stmt:550-556` | `collection_run_id IN (SELECT id FROM collection_runs WHERE project_id = :pid)` | **OK** for page + records; **auto-select default from `content.py:1030-1040` silently rewrites the URL** (can surprise users — see §3.4); **silently dropped by `/export`** | High |
| 10 | `run_id` | `browser.html:174-201` | `content.py:976,1214` → `_run_id_filter` at `content.py:62-78` | `(collection_run_id = :rid OR EXISTS (content_record_links with matching run_id))` | **OK** with linked-records; but `run_id` filter in `_build_browse_stmt` uses ownership subquery that **does not include project collaborators** (see §2.2) | Medium |
| 11 | `search_term` | `browser.html:206-220` (lazy-loaded via HTMX from `/content/search-terms`) | `content.py:975,1213` → `_build_browse_stmt:527-534` | `search_terms_matched::text[] @> ARRAY[:term]::text[]` | **OK** for first selection; but `hx-include="[name='search_term']"` at `browser.html:180` causes the current search_term to be POSTed to `/content/search-terms`, which then ignores it while rebuilding the dropdown — so the user's previous selection is silently preserved only in the hidden `<option>` trick at `browser.html:212-214`. Race condition: if the search-terms HTMX call completes after the filter form reload, the dropdown is repopulated without the user's selection. | Medium |
| 12 | `scrape_status` | `browser.html:225-235` | `content.py:981` (alias), `1218` (alias) → `_build_browse_stmt:564-566` | `scrape_status = :ss` | **OK** | — |
| 13 | `show_all` | `browser.html:242-247` `<input type="checkbox" name="show_all" value="true">` | `content.py:980,1217` (coerced to bool); override at `content.py:1063, 1324`; divergent pass to `_count_matching` at `content.py:1157, 1456` | `term_matched = TRUE` when `not show_all` | **BROKEN — critical.** See §2.1. | **Critical** |
| 14 | `content_types[]` | `browser.html:259-273` | `content.py:984,1227` → default `["post"]` at `1067, 1330` → `_build_browse_stmt:562-563` | `content_type IN (...)` | **Partial** — works on page + records; **silently dropped by `/export`**; **default-to-`["post"]`** hides comment-type content even when the user has never opened the filter drawer, which inverts the stated template comment ("unchecked by default") and is essentially a silent hidden filter | High |
| 15 | `sort_by` / `sort_dir` | `browser.html:53-54` (hidden inputs); `<th>` click handlers at `722-745` | `content.py:982,983,1225,1226` → `_build_browse_stmt:579-626` | `ORDER BY {col} {dir}, id {dir}` + `.offset()` for non-default sorts | **OK**, but see §5 — `offset` pagination is used for non-default sorts, which silently caps at 2000 rows **and** triggers the `page_offset` logic that is incompatible with the infinite-scroll sentinel (cursor never encodes the real offset position). | Medium |
| 16 | Infinite-scroll `cursor` + `offset` | `browser.html:515-527`, `content_table_body.html:117-130` | `content.py:1206,1219,1302-1305` → `_decode_cursor` | keyset `(published_at, id)` | **OK** for default sort; **breaks silently on non-default sort** — see §5 | Medium |
| 17 | `format` query param | Not in template; used by programmatic API callers | `content.py:1221-1224` | n/a — controls JSON vs HTML response | **Name collision** with `format` filter on `/export` (route `content.py:1690` also defines `format`); no conflict because they are distinct endpoints, but the shadow of Python's built-in `format()` inside the function body is brittle (see `content.py:1274`, `_prefers_json(request, format)` — `format` is a shadowed parameter name). | Low |

---

## 2. Root Cause Analysis

### 2.1 CRITICAL: `show_all` is mutated upstream of the query, breaking both rendering and the count badge (file: `src/issue_observatory/api/routes/content.py`)

**Observed behavior.** A researcher opens `/content`, selects two arenas (e.g., `bluesky` and `reddit`) via the arena checkboxes, then toggles "Show non-matching content". The table shows either (a) the same results as before, (b) results from Facebook/Instagram they did not ask for, or (c) the count badge says "1,247 records" while the table displays 2,000 rows — depending on the order of operations.

**Root cause.** There are three distinct `show_all` variables in play and they are mixed incorrectly:

```python
# content.py:1063 (browser page)
effective_show_all = show_all or len(arenas_list) > 0

# content.py:1084
stmt = _build_browse_stmt(..., show_all=effective_show_all, ...)

# content.py:1157 — passes the RAW show_all, not effective_show_all
total_count = await _count_matching(..., show_all=show_all, ...)
```

And the same pattern in the `/records` endpoint:

```python
# content.py:1324
effective_show_all = show_all or len(arenas_list) > 0

# content.py:1347
stmt = _build_browse_stmt(..., show_all=effective_show_all, ...)

# content.py:1456 — passes the RAW show_all, not effective_show_all
total_count = await _count_matching(..., show_all=show_all, ...)
```

Consequences:

1. **Count/row divergence.** When the user has one or more arena checkboxes ticked, `effective_show_all = True` so the table shows records with `term_matched = FALSE`, **but** the count badge uses `show_all = False` so it counts only `term_matched = TRUE` rows. Badge undercounts and misleads the user about pagination progress.
2. **The `show_all` checkbox has NO visible effect when any arena checkbox is ticked.** Because `effective_show_all` is `True` as soon as `len(arenas_list) > 0`, the user's explicit `show_all=False` is ignored. The only way to see "only term-matched content from arena X" is to type the arena name into the URL manually — impossible through the UI. This also means the default (no arenas selected) and "all arenas selected" produce different row sets for what the user perceives as equivalent filters.
3. **Order-of-operations bug.** If the user first selects arenas, then unchecks `show_all`, the checkbox state reads "unchecked" but the backend behaves as if it were checked. No client-side code reconciles this.

**Intended logic** (based on the comment at lines 1059-1062) is to exempt actor-only arenas (Facebook/Instagram) from the `term_matched = TRUE` default so that Facebook posts are visible when their arena is selected. The correct fix is to apply the exemption **per arena**, not globally — i.e., when the arena is in `{"facebook", "instagram"}` OR a centrally-maintained `ACTOR_ONLY_ARENAS` set. See §8 for the fix plan.

---

### 2.2 HIGH: `/content/export` silently drops most sidebar filters — exported file ≠ rendered table

**Observed behavior.** A researcher filters the table to `project_id=X, scrape_status=scraped, mode=live, q="klima", content_types=[comment]`, sees 120 records, clicks "Export CSV" in the sidebar, and gets a CSV with 47,000 rows that does not match what they just saw.

**Root cause.** `export_content_sync` at `content.py:1686` accepts only:

```
format, network_type, arenas, platform, arena, query_design_id,
date_from, date_to, language, run_id, search_term, limit, include_metadata
```

Notably **missing**: `q`, `mode`, `project_id`, `show_all`, `scrape_status`, `content_types`.

But the sidebar Export button at `browser.html:292-304` is:

```html
<button hx-get="/content/export" hx-include="#filter-form" ...>
```

HTMX serializes the entire form and appends every field as a query parameter. FastAPI then silently drops every query param that isn't declared on the route (no `extra="forbid"` on `Query()`), so the missing filters vanish with zero feedback. The exporter uses `_build_content_stmt` at line 1789 (a different helper from `_build_browse_stmt`!) which does not know about these filters at all.

Additionally, `_build_content_stmt` at `content.py:164-282` has its own subtle defects:

- **L275**: `show_all` defaults to `False` here too, but there is no "arenas override" hack, so Facebook/Instagram records will never export.
- **L201-204**: Admin ownership path is different from `_build_browse_stmt` — admins see every record regardless of ownership, which matches browse behavior.
- **L215-223**: Non-admin path **includes project collaborators** via `ProjectCollaborator` join, whereas `_build_browse_stmt:488-499` does NOT (it only checks `CollectionRun.initiated_by == current_user.id`). **A project collaborator will see rows in the table that do not appear in their CSV export, and vice versa.** This is a data-visibility inconsistency that should trigger an immediate check.

### 2.3 HIGH: `/content/records` fragment never applies the `arena` singular param; never applies the `platform` singular param either when `arenas` is absent from query string

**Observed behavior.** A user clicks a link (or constructs a URL) containing `?platform=youtube` and expects subsequent HTMX reloads of the records fragment to retain the filter. They do not.

**Root cause.** The sidebar form has **no** `<input name="platform">` and **no** `<input name="arena">`. On every HTMX reload, `hx-get="/content/records"` serializes the filter form, which only contains `arenas[]` (the checkbox group). The singular `platform` and `arena` URL parameters are not in the form, so they get dropped from subsequent requests.

The content_browser_page route reads both `platform` and `arena` at `content.py:970-971` and honors them on the initial HTML render, but `content_records_fragment` at `content.py:1209` only accepts `arenas` — so after the first filter change the singular params are silently discarded.

Furthermore, at `content.py:1336` the fragment hardcodes `arena=None` when calling `_build_browse_stmt` ("arena grouping handled via arenas_list below"), but nothing in the fragment reads the singular `arena` parameter. This is dead code.

### 2.4 HIGH: `content_types` defaults to `["post"]` server-side, so "Comments" is a silent hidden filter on first visit

**Observed behavior.** A researcher runs a Reddit collection that includes top-level posts and their comment threads. They go to the content page and wonder why only 1/10 of their records are visible. The sidebar shows `Posts ✓  Comments ☐` and `(1,247 records)` — but `raw_metadata` has 12,000+ comments.

**Root cause.** `content.py:1067`:

```python
effective_content_types = content_types if content_types else ["post"]
```

When the query string omits `content_types` entirely (first visit, reset URL, etc.), the backend substitutes `["post"]` — silently filtering out every `content_type != "post"` record. The template at `browser.html:258-273` displays the checkboxes with `Posts` checked and `Comments` unchecked, which looks like a UI default but is actually enforced server-side regardless of whether the user even knows the filter exists. There is no `<option value="">All types</option>` fallback.

**Composition effect.** If you tick `Comments`, the form sends `content_types=post&content_types=comment` (because `Posts` remains checked by default). If you tick `Comments` and uncheck `Posts`, the form sends only `content_types=comment`. If you uncheck both, the form sends no `content_types` at all — and the server substitutes `["post"]`. There is no way to "match all content types" through the UI.

### 2.5 MEDIUM: Duplicate records (`raw_metadata->>'duplicate_of'`) are excluded in analysis but included in the content browser

**Observed behavior.** A researcher runs `POST /content/deduplicate`, which flags ~8,000 near-duplicates by setting `raw_metadata.duplicate_of`. The analysis dashboard now shows 100k unique records. The content page still shows 108k.

**Root cause.** `analysis/_filters.py:181` always appends:

```python
clauses.append(f"({prefix}raw_metadata->>'duplicate_of') IS NULL")
```

But `_build_browse_stmt` and `_build_content_stmt` in `content.py` **do not include this predicate**. The content browser shows duplicates; the analysis page does not. This is a cross-page consistency bug.

### 2.6 MEDIUM: Ownership scoping is inconsistent across browse, records, export, and count

Four different ownership predicates are used:

| Location | Who can see what? |
|---|---|
| `content.py:201-229` (`_build_content_stmt`) — used by `/export` | User's own runs **OR** runs where user is a `ProjectCollaborator` |
| `content.py:482-499` (`_build_browse_stmt`) — used by `/`, `/records` | User's own runs only (no collaborators) |
| `content.py:2274-2293` (`get_content_record_html`) — used by `/{record_id}` | User's own runs only (no collaborators) |
| `content.py:912-922` (`content_record_count`) — used by dashboard widget | **scoped via `query_design_id`** (ignores collaborator runs entirely), which is `join(CollectionRun on query_design_id)` filtered by `CollectionRun.initiated_by == current_user.id` |

Consequences:

- A project collaborator sees data in exports but **cannot view individual records' detail panels** (404) — the detail route blocks them.
- A collaborator's dashboard widget reports `matched: 0, total: 0` even though they can see records in the `/export` output.
- If the `run_id` the collaborator selects is not owned by them, the subquery at `_build_browse_stmt:490` returns nothing, and the table shows zero rows — but the count badge **also** reports zero, so the collaborator assumes there is no data.

This is a **data-visibility correctness** issue per GDPR/collaboration semantics — the researcher's stated mental model ("I'm a collaborator on this project") is inconsistent with what they see across the four views.

### 2.7 MEDIUM: `search_term` dropdown population races against filter-form submission

At `browser.html:173-201`, the Collection Run selector has:

```html
<select name="run_id"
        hx-get="/content/search-terms"
        hx-trigger="change"
        hx-target="#search-term-filter"
        hx-swap="innerHTML"
        hx-include="[name='search_term']" ...>
```

When the user changes the run, HTMX fires two requests **in parallel**:

1. The `hx-trigger="change"` on the `run_id` select fires a GET to `/content/search-terms?run_id=…&search_term=…`.
2. The parent form `#filter-form` has `hx-trigger="change, keyup changed delay:400ms"` on `hx-get="/content/records"` — the same `change` event also fires a GET to `/content/records`.

Both complete independently. If the search-terms fragment resolves first, the dropdown is rebuilt and the user's previous `search_term` selection is lost (because the HTMX handler at `content.py:1541-1550` writes only `<option value="">All terms</option>` followed by the DB-derived options — the previously selected term is not re-selected). If the records fragment resolves first, the table shows filtered rows by the old `search_term`, then the dropdown repopulates and the table is out of sync with the dropdown.

`hx-include="[name='search_term']"` on the run selector is a misread of the HTMX API — it sends the previous term value to the search-terms endpoint, but the search-terms handler ignores it.

### 2.8 LOW: `format=json` parameter shadows Python's `format` builtin inside the function body

`content.py:1221` declares a parameter literally named `format`. This shadows `format()` inside the function, which is bad practice and has already generated one bug during refactor (see the commented-out `@limiter.limit` at line 1685 — the refactor comment says "slowapi corrupts FastAPI param parsing"; this is because slowapi wraps the handler with a decorator that introspects parameter names, and `format` is reserved in several decorators). The safe pattern is `format_: str | None = Query(None, alias="format")`.

### 2.9 LOW: `q` full-text search uses hardcoded `'danish'` dictionary

`content.py:571-573`:

```python
"to_tsvector('danish', coalesce(content_records.text_content, '')"
" || ' ' || coalesce(content_records.title, ''))"
" @@ plainto_tsquery('danish', :q)"
```

This matches the index declared in `alembic/versions/001_initial_schema.py:381-384`, so it is index-covered for Danish. **However**, the content browser has a `language` filter with options including `en, de, kl, sv, no, ru, fr` — none of which are matched well by the Danish stemmer. A user searching `"climate"` after setting `language=en` will match poorly because `plainto_tsquery('danish', 'climate')` stems `climate` as a Danish word. This is not a bug in the strict sense (it still returns results) but it is a silent correctness degradation for non-Danish queries. See §8 for the suggested dynamic-dictionary pattern.

### 2.10 LOW: `_parse_date_param` accepts `YYYY-MM-DD` only, silently drops malformed input

`content.py:392-414`: On parse failure, returns `None`. The user types `02/15/2024` (US format) into the date input, the parse fails, the filter is silently dropped. No 400 error, no flash message. The date input is `type="date"`, which normally prevents this, but copy-paste or URL manipulation can inject bad values.

---

## 3. Composition Analysis

### 3.1 Baseline AND semantics

`_build_browse_stmt` uses SQLAlchemy `select(...).where(...)` chaining, so each `.where()` becomes an `AND` predicate. **AND composition itself is correct** for the filters that are actually applied.

### 3.2 Count/row divergence points

The `_count_matching` call and the `_build_browse_stmt` call are structurally **not** identical in either the page route or the records route. Divergences (page route):

| Argument | `_build_browse_stmt` receives | `_count_matching` receives |
|---|---|---|
| `platform` | `platform_filter if len(arenas_list) <= 1 else None` | `count_platform = platform_filter if len(arenas_list) <= 1 else None` (consistent) |
| `arena` | `arena` (singular) | `arena` (singular) — **consistent on page, but INCONSISTENT on /records (passes `None`)** |
| `show_all` | `effective_show_all` (mutated) | `show_all` (raw) — **INCONSISTENT** |
| `arenas_list` | applied post-hoc via `.where(platform.in_(arenas_list))` | applied inside `_count_matching` post-hoc too (consistent) |
| `content_types` | `effective_content_types` | `effective_content_types` (consistent) |
| `sort_by` / `sort_dir` | passed | not passed (count does not need ordering — acceptable) |
| `cursor_published_at` / `cursor_id` | passed | passed as `None` — acceptable |
| `limit` | `_BROWSE_LIMIT=50` | `_BROWSE_CAP+1=2001` — acceptable |

Divergences in `/records` fragment:

Same as above **plus**: `arena=None` is hardcoded into `_count_matching` at `content.py:1447`, which is consistent with `_build_browse_stmt:1336` also receiving `arena=None`. So on the records fragment the singular `arena` param is effectively dead code (it is never applied to the base query), whereas on the page route it IS applied. This is an additional inconsistency: `GET /content?arena=news` shows filtered rows; the subsequent `GET /content/records?...` does not, and the count badge on the initial page load (which used `arena=arena`) disagrees with the OOB count update triggered by the next HTMX reload (which uses `arena=None`).

### 3.3 Dashboard `/content/count` endpoint is scoped differently from browse

`content.py:881-952` uses an entirely different strategy: it resolves the set of `query_design_id`s owned by the user, then counts records with `query_design_id IN (...)`. This bypasses `collection_run_id` entirely and cannot express:

- Collaborator runs (not considered).
- `term_matched` toggle (always applies `= TRUE` for `matched`, never exposes `total` via the UI — but `total` is computed for the card).
- Date range, arena, platform, etc. (none supported).

The dashboard Records Collected card will therefore disagree with the content page's count badge whenever the user has non-default filters active elsewhere. Because the dashboard and the content page are different screens with different scopes, this might be acceptable — but the endpoint's docstring at line 890 says "content record counts for the current user's collection runs", which is misleading because the dashboard card is not showing "what's on the content page". The bug in `run_id` + `project_id` combo: if you filter by `run_id` on the content page, the dashboard card does not update because it has a different URL structure.

### 3.4 Auto-select project silently rewrites filter state

`content.py:1030-1040`:

```python
if not project_id_was_explicit and project_id is None:
    latest_project_stmt = (
        select(CollectionRun.project_id)
        ...
    )
    latest_pid = (await db.execute(latest_project_stmt)).scalar_one_or_none()
    if latest_pid:
        project_id = latest_pid
```

If the user visits `/content` (no query string), the backend silently auto-selects the most recently-run project and applies it as a filter. Side effects:

1. The URL still reads `/content` — no `project_id` in the query string — but the server has applied `WHERE project_id = X`. A bookmark of this URL will not reproduce the filter.
2. If the user then types in a search in the sidebar, HTMX fires `GET /content/records` **without** `project_id` (because the Project select is `<option value="">All projects</option>` by default), and the result set changes — suddenly rows from other projects appear. The user did not ask for that.
3. If the user selects `All projects` explicitly, the `project_id_was_explicit` check **should** suppress the auto-select, but only on the initial page load — the `/records` fragment at `content.py:1201` does NOT have the same auto-select logic, so the first HTMX reload after the auto-select will reset the scope.

This is also why `_count_matching` (called from `/records`) uses the passed `project_id` which is `None` (the user-selected default), while the initial page render's count used the auto-selected project. Another count-divergence vector.

### 3.5 Sampling correctness (what the user asked about)

The page docstring at `content.py:1232` says:

> "Implements keyset pagination on `(published_at DESC, id DESC)`."

There is **no sampling logic whatsoever**. The query is:

```sql
ORDER BY published_at DESC NULLS LAST, id DESC
LIMIT 50
```

Paginated via keyset. The 2000-row browse cap at `content.py:960` (`_BROWSE_CAP = 2000`) silently truncates the view. A user whose filter matches 200k records sees the **2000 most recent**, period. There is no:

- Random sampling (`ORDER BY RANDOM()` or `TABLESAMPLE BERNOULLI`).
- Stratified sampling by platform/arena/date/language.
- Deterministic seed.
- Time-window bucketing.
- Warning in the UI that the sample is not representative.

The template comment at `browser.html:363-369` does alert the user with a "2,000 rows max, export CSV for the rest" banner — but the banner only appears after the user has scrolled through 2000 rows, and it does not explain that the visible 2000 are the most-recent slice, not a random sample.

**Assessment:** The content page delivers a "recency-ordered window" and calls it a "browser". It does not deliver a representative sample under any reasonable definition. If the product requirement is representative sampling, this needs a new query path.

---

## 4. Indexing and Performance Notes

### 4.1 Indexes that exist on `content_records` (migrations 001, 021, 022, 040, others)

| Index | Columns | Notes |
|---|---|---|
| `idx_content_platform` | `platform` | Used by filter 2 |
| `idx_content_arena` | `arena` | Used by singular arena filter 4 |
| `idx_content_published` | `published_at` | Used by filter 5/6; also partition key |
| `idx_content_query` | `query_design_id` | Used by dashboard count endpoint |
| `idx_content_hash` | `content_hash` | Dedup |
| `idx_content_author` | `author_id` | LEFT JOIN to actors |
| `idx_content_terms` (GIN) | `search_terms_matched` | Used by filter 11 |
| `idx_content_metadata` (GIN) | `raw_metadata` | General JSONB — expensive, rarely used |
| `idx_content_fulltext` (GIN) | `to_tsvector('danish', ...)` | Used by filter 1 |
| `idx_content_language` (mig 040) | `language` | Partial coverage of filter 7 |
| `idx_content_collected_at` (mig 040) | `collected_at` | ORDER BY fallback |
| `idx_content_scrape_status` (mig 021) | `scrape_status WHERE IS NOT NULL` | Used by filter 12 |
| `idx_content_term_matched` (mig 022) | `term_matched WHERE = false` | Used by the inverted default filter |

### 4.2 Index gaps

1. **Language fallback** (filter 7): The `_effective_lang` expression at `content.py:242-245` evaluates `COALESCE(NULLIF(language,''), raw_metadata->'enrichments'->'language_detection'->>'language')` and wraps it in `split_part(...)`. Neither the `split_part` nor the `COALESCE` is index-covered. The partial `idx_content_language` covers only rows where `language` is populated; for rows where the fallback applies, a seq-scan is required. **Fix:** Add an expression index `CREATE INDEX idx_content_effective_lang ON content_records ((split_part(COALESCE(NULLIF(language, ''), raw_metadata->'enrichments'->'language_detection'->>'language'), '-', 1)))`. Or (better) backfill `language` from the enrichment at collection time so the fallback is no longer needed.

2. **`content_type` filter** (filter 14): No index. With `content_types=["post"]` as the silent default, every query adds `WHERE content_type IN ('post')` which is a seq-scan if not also narrowed by date. **Fix:** Add `CREATE INDEX idx_content_type ON content_records (content_type)` or a composite `(content_type, published_at DESC)` to match the ORDER BY. Check cardinality first — if 99% of rows are `post`, a partial index `WHERE content_type != 'post'` is more useful.

3. **`collection_run_id` not indexed on the parent table.** I do not see an explicit index on `collection_run_id` in migration 001 or 040. The table uses `collection_run_id` in nearly every filter path (ownership subquery, run_id filter, mode filter, project_id filter), and without an index this is a potentially very expensive join/subquery. **Verification required — run `\d content_records` and report.** If missing, add it ASAP.

4. **No index on the EXISTS-subquery side of `_run_id_filter`**. The subquery joins `content_record_links` on `(collection_run_id, content_record_id, content_record_published_at)`. Migration 025 created `idx_content_record_links_run` — verify it covers this composite. If the subquery falls back to `(collection_run_id)` alone, the EXISTS evaluation runs N times per row. This is already called out in `analysis/_filters.py:105-115` as "uses EXISTS with an indexed lookup", but the content page uses a different helper and it is not obvious the same index coverage applies.

5. **Cross-date filtering penalty from partition.** `content_records` is `PARTITION BY RANGE (published_at)`. Queries that do not include `published_at >= X` or `published_at <= Y` hit **every partition**. Specifically, the default content page query (no date filter) scans every partition. With 20+ monthly partitions this can be painful. The sort `ORDER BY published_at DESC NULLS LAST, id DESC` is partition-aware for keyset pagination but still needs to walk every partition to find the LIMIT-50 top.

### 4.3 Full-text search concerns

The GIN index on `to_tsvector('danish', ...)` is 100% tied to the Danish dictionary. Any call to `plainto_tsquery` with a different dictionary is NOT index-covered — PostgreSQL will fall back to a sequential scan. This is relevant if we ever want to support non-Danish search correctly (§2.9).

### 4.4 Sequential scan on JSONB language fallback

The analysis `_filters.py:142-155` emits the exact same expression, but the analysis code calls it from `descriptive.py` functions that almost always also apply a `published_at` or `run_id` predicate. The content browser does not — so a user who sets `language=en` with no other filters triggers a full-table scan on every partition. With millions of rows this is a real latency hit.

### 4.5 N+1 risk

I did not find obvious N+1 query patterns in `_build_browse_stmt` — it eagerly joins `actors` and `collection_runs` via LEFT JOIN. Good.

However, `_fetch_recent_runs` at `content.py:629-697` does two queries: one for runs (with `selectinload(query_design)`), then one grouped count on `content_records`. Acceptable but adds 2x latency to every initial content page load. Could be collapsed into a single CTE, but not urgent.

---

## 5. Sampling Correctness Assessment

As described in §3.5, the page is **not a sampler** in any statistical sense. If the user's intent was "show me a representative slice of my corpus so I can spot-check quality", the current implementation misleads them. Specific risks:

1. **Platform skew.** Bluesky and X push high-volume feeds; a recency-ordered view will be dominated by whichever platform had the most recent batch run. The user concludes "my corpus is 90% Bluesky" when in fact Bluesky is 12% of the total corpus and merely ran more recently.
2. **Date skew.** A live-tracking run writing 100 records/hour vs. a batch run from last week: the recency view will show ~100% live-tracking records at the top.
3. **Language skew.** Enrichment pipelines that set `language` lag behind the recency cursor; rows near the top of the view are disproportionately `language IS NULL` (because the language-detection enricher hasn't caught up yet). This interacts poorly with the language filter.
4. **No seed/reproducibility.** The user cannot return to "the same 50 records I was looking at yesterday" — a new record inserted overnight shifts the cursor window.

### 5.1 Sampling options to propose

- **Deterministic random sample via bucket**: `WHERE ABS(hashtextextended(id::text, 0)) % 100 < :sample_pct`. Stable across reloads, seedable, and indexable if we add an expression index.
- **Stratified bucket per platform**: `WINDOW w AS (PARTITION BY platform ORDER BY …) SELECT * WHERE row_number() OVER w <= :k`. Guarantees each platform contributes at most `k` rows.
- **TABLESAMPLE SYSTEM_ROWS(n)**: Postgres extension — may not be available in all deployments. Good approximation when the user tolerates sampling error.
- **Reservoir sampling server-side** via a Celery task — most expensive, most accurate.

**Recommended minimum fix**: Add a `sample=random|recent` query parameter (default `recent` to preserve current behavior) and a `sample_size` parameter. Document the sampling semantics in the UI banner that currently only says "2,000 rows max".

---

## 6. Test Coverage Gaps

The only content-page-related tests I found:

1. `tests/unit/test_content_json_api.py` — tests **only** the JSON-vs-HTML content negotiation for `/records`. 10 tests. **Zero** tests of actual filter application. All DB calls are mocked to return empty lists, so filter correctness is never exercised.
2. `tests/unit/test_content_route_search_terms.py` — tests `/search-terms` HTML fragment formatting, XSS escaping, Danish character preservation. 10 tests. Does not exercise the main browse query.

**No tests exist for:**

- `_build_browse_stmt` — not a single test exercises the filter-building SQL.
- `_build_content_stmt` — not a single test.
- `_count_matching` — not a single test.
- `/content/` full page render (any filter combination).
- `/content/records` with any filter applied (every test calls it with default params).
- `/content/export` end-to-end with filters.
- Cursor encoding/decoding (`_encode_cursor` / `_decode_cursor`).
- `_run_id_filter` EXISTS logic (no test verifies linked-record inclusion).
- Multi-arena IN filter behavior.
- `show_all` toggle semantics (the critical bug in §2.1 has zero coverage).
- `content_types` default behavior (the hidden-default bug in §2.4 has zero coverage).
- Duplicate-exclusion parity between content browser and analysis (§2.5).
- Language fallback via `raw_metadata->enrichments->language_detection->language`.
- Danish character preservation through the full filter → SQL → render pipeline.
- Ownership scoping consistency between `/`, `/records`, `/export`, `/{id}`, `/count` (§2.6).
- Project auto-select side effects (§3.4).

**Minimum acceptable test suite** (my recommendation, to be written as part of the fix plan):

```
tests/unit/api/content/
    test_build_browse_stmt.py        # 30+ parametric tests, one per filter and composition
    test_build_content_stmt.py       # parity with _build_browse_stmt
    test_count_matching.py           # verifies count == len(rows) for every filter combo
    test_cursor_pagination.py        # encode/decode roundtrip + invalid cursor handling
    test_ownership_scoping.py        # owner, collaborator, admin, foreign user x 4 routes
    test_show_all_semantics.py       # the critical bug regression test
    test_content_types_defaults.py   # the hidden-default bug
    test_sampling_representativeness.py  # stratification, seed, platform balance
tests/integration/api/content/
    test_filter_composition_e2e.py   # real DB, real HTTP, every filter AND combo
    test_danish_text_preserved.py    # æ/ø/å through filter → SQL → response → template
    test_export_filter_parity.py     # rows in /records must equal rows in /export
    test_duplicate_exclusion.py      # after deduplicate, both pages agree
```

---

## 7. Cross-Page Divergence Summary

This table makes the content-page-vs-analysis-page disagreement explicit.

| Concern | Content page (`content.py`) | Analysis layer (`analysis/_filters.py`) |
|---|---|---|
| Filter helper | Inline in `_build_browse_stmt` / `_build_content_stmt` | Centralized in `build_content_filters` / `build_content_where` |
| SQL dialect | SQLAlchemy `select().where()` | Raw SQL strings via f-string + bind params |
| Duplicate exclusion (`raw_metadata->>'duplicate_of' IS NULL`) | **NOT APPLIED** | Always applied (line 181) |
| Linked records via `content_record_links` | Applied only for `run_id` filter | Applied for BOTH `run_id` AND `query_design_id(s)` |
| `term_matched = TRUE` default | Applied unless `show_all`; with the `effective_show_all` mutation (§2.1) | Applied unless `include_linked` overrides via EXISTS on `content_record_links` |
| Ownership scoping | User's runs only (page/records); user + collaborator runs (export) | No ownership scoping — analysis functions trust the caller to pass the already-scoped run_ids |
| Language fallback | Yes, via the same JSONB path | Yes, same expression |
| Arena / platform list support | Singular only in helpers; multi-value via post-hoc `.where(col.in_(...))` | Native list support via `IN (:p_1, :p_2, …)` bindparams |
| Search term filter | Single term via `search_terms_matched @> ARRAY[:t]` | List of terms via `search_terms_matched && ARRAY[:st_1, …]::text[]` (overlap) |

**Action item:** Converge these two code paths. Either (a) content page calls `build_content_filters` and translates its output to SQLAlchemy `text()` clauses, or (b) promote `_build_browse_stmt`'s SQLAlchemy-native logic into a shared helper that analysis also uses. Either way, stop maintaining two filter dialects.

---

## 8. Prioritized Fix Plan

### P0 — Critical (data correctness / user trust)

1. **Fix `show_all` mutation** — `src/issue_observatory/api/routes/content.py:1063, 1157, 1324, 1456`.
   - Define a centralized `ACTOR_ONLY_PLATFORMS = {"facebook", "instagram"}` set in `config/danish_defaults.py` or similar.
   - In `_build_browse_stmt`, instead of `if not show_all: .where(term_matched.is_(True))`, use a conditional predicate: `where((term_matched.is_(True)) | platform.in_(ACTOR_ONLY_PLATFORMS))` when `show_all` is False AND arenas_list overlaps with ACTOR_ONLY_PLATFORMS.
   - Remove the `effective_show_all = show_all or len(arenas_list) > 0` mutation entirely.
   - Pass `show_all` unchanged to both `_build_browse_stmt` and `_count_matching`.
   - Write a regression test: `test_show_all_semantics.py::test_show_all_false_with_actor_only_arena_still_shows_records`.

2. **Fix `/content/export` filter drop** — `src/issue_observatory/api/routes/content.py:1686-1808`.
   - Add query parameters: `q, mode, project_id, show_all, scrape_status_filter (alias scrape_status), content_types`.
   - Replace the call to `_build_content_stmt` at line 1789 with a call to `_build_browse_stmt` (adding `cursor_published_at=None, cursor_id=None, limit=limit`).
   - Delete `_build_content_stmt` entirely (it duplicates the browse helper).
   - Update `_record_to_dict` to be callable from either source mapping (ORM instance OR `(ORM, mode, resolved_name)` row).
   - Regression test: `test_export_filter_parity.py::test_exported_rows_match_rendered_rows_for_all_filter_combinations`.

3. **Fix count/row divergence** — `src/issue_observatory/api/routes/content.py:1157, 1447, 1456`.
   - Ensure `_count_matching` is called with **identical** arguments to `_build_browse_stmt`. Extract a `_browse_filter_kwargs` dict in each endpoint and `**`-splat it to both.
   - Regression test: `test_count_matching.py::test_count_equals_row_count_for_every_filter_combo`.

### P1 — High

4. **Add duplicate exclusion to content browser** — `src/issue_observatory/api/routes/content.py:273-281` (inside `_build_content_stmt`), and add at ~560 inside `_build_browse_stmt`.
   - Add: `stmt = stmt.where(UniversalContentRecord.raw_metadata["duplicate_of"].astext.is_(None))`.
   - Or better: converge on the analysis layer's `build_content_filters` (see action 9 below).

5. **Fix `content_types` hidden-default bug** — `src/issue_observatory/api/routes/content.py:1067, 1330`.
   - Option A (safe): Make the template explicit — add a third checkbox "All types" and default to it; pass `None` (don't apply filter) when nothing is ticked OR when "All types" is ticked.
   - Option B (minimum change): Change the default from `["post"]` to `None` and let the user explicitly tick what they want.
   - Document the change in a release note — existing bookmarks will now see comments.

6. **Fix singular `platform` / `arena` fragment dropout** — `src/issue_observatory/api/routes/content.py:1209`.
   - Add `platform: str | None = Query(default=None)` and `arena: str | None = Query(default=None)` to `content_records_fragment`.
   - Add hidden `<input name="platform">` and `<input name="arena">` to the sidebar form to preserve URL-injected filters across HTMX reloads.
   - Delete the `arena=None` hardcode at `content.py:1336`.

7. **Fix ownership consistency** — `src/issue_observatory/api/routes/content.py:488-499, 912-945, 2280-2293`.
   - Extract a shared `_owned_run_subquery(current_user)` helper that returns the user's own runs + collaborator runs.
   - Use it in **all four** paths: `_build_browse_stmt` (non-admin branch), `_build_content_stmt` (already close — uses collaborator), `content_record_count` (completely rewrite to use `collection_run_id` IN subquery so it honors collaborators), `get_content_record_html`.
   - Regression test: `test_ownership_scoping.py` with matrix `{owner, collaborator, admin, stranger} × {/, /records, /export, /{id}, /count}`.

8. **Fix `/content/search-terms` race condition** — `src/issue_observatory/api/templates/content/browser.html:173-220`.
   - Remove `hx-trigger="change"` from the run_id select and instead let the parent form handle the reload. After the form submits, trigger a separate HTMX GET to `/content/search-terms` via `hx-trigger="htmx:afterRequest from:#filter-form"`.
   - Or: move the search-terms dropdown rebuild into the same HTMX response as the filter update (OOB swap).
   - Either way, preserve the previously-selected term by passing it to the handler and re-selecting if still valid.

### P2 — Medium

9. **Converge content page and analysis filter helpers** — `src/issue_observatory/analysis/_filters.py` + `src/issue_observatory/api/routes/content.py`.
   - Create `src/issue_observatory/core/filters.py` with a single `build_content_where(...)` function that returns **both** a SQLAlchemy select filter list (for content routes) and a raw-SQL string (for analysis routes).
   - Move `duplicate_of` exclusion, language fallback, linked-record EXISTS, `term_matched` default, and scope predicates into this single helper.
   - Update `_build_browse_stmt` to delegate.
   - Update `analysis/_filters.py` to delegate (or keep as a thin wrapper).
   - Add a contract test `test_filter_parity.py::test_analysis_and_content_produce_same_row_set`.

10. **Add language functional index** — new Alembic migration.
    - `CREATE INDEX idx_content_effective_lang ON content_records ((split_part(COALESCE(NULLIF(language, ''), raw_metadata->'enrichments'->'language_detection'->>'language'), '-', 1)))`.
    - Or backfill `language` from enrichment at write time and drop the fallback.

11. **Verify `collection_run_id` is indexed** — investigate `\d content_records` against a live database and, if `idx_content_collection_run_id` is absent, add a migration.

12. **Fix sort + keyset pagination interaction** — `src/issue_observatory/api/routes/content.py:589-626`.
    - When `sort_by != 'published_at'`, the code switches to offset pagination — but the `cursor` returned to the client is hardcoded to the literal string `"offset"` (line 1384), which means the next HTMX reload sends `cursor=offset` and the decoder fails silently, leaving pagination broken for non-default sorts.
    - Fix: Encode the offset in the cursor itself (`offset:{integer}`) or switch all sorts to keyset with composite tie-breakers.

13. **Auto-select project**: either don't auto-select, or push the selection into the URL via `hx-push-url` so subsequent reloads preserve the filter. Current behavior at `content.py:1030-1040` is a silent server-side rewrite that the UI doesn't reflect.

### P3 — Low / nice-to-have

14. **Document sampling semantics** — `browser.html:328-334` (record count badge) should say "(ordered by recency)" or similar so users understand this is not a random sample. Add a tooltip.

15. **Introduce proper sampling** — see §5.1 above. Propose `sample=random&sample_size=200` as a query parameter with explicit UI controls.

16. **Fix `format` parameter shadow** — rename to `format_` with `alias="format"` at `content.py:1221, 1690`.

17. **Dynamic tsvector language**: `plainto_tsquery(COALESCE(:lang_conf, 'danish'), :q)` where the text-search config is derived from the `language` filter. Requires additional expression indexes for each supported language (`english`, `german`, etc.) OR drop the FTS index requirement and accept seq-scan for non-Danish.

18. **Strict date parsing**: if `_parse_date_param` fails, return 400 instead of silently dropping. Or at least log a warning and display a banner.

19. **Raw JSONB filter exposure** — if researchers need to filter by `raw_metadata.subreddit`, `raw_metadata.channel`, etc., add an expression index per platform and expose corresponding sidebar controls. This is a net-new feature, not a fix, but it is implied by the user's description of "many different filters".

20. **Content-count endpoint coherence** — the dashboard `/content/count` endpoint uses a fundamentally different scoping strategy than the content browser. Either make it accept the same filters (complicated) or rename it to make its scope explicit (`/content/count/by-query-design`).

---

## 9. Concrete Punch List (line-level)

Engineers should read this section as a to-do list tied to the file references. Each item maps to one of the fixes above.

| # | File | Line | Action |
|---|---|---|---|
| 1 | `src/issue_observatory/api/routes/content.py` | 1063 | Remove `effective_show_all = show_all or len(arenas_list) > 0`. |
| 2 | `src/issue_observatory/api/routes/content.py` | 1084 | Change `show_all=effective_show_all` to `show_all=show_all`. |
| 3 | `src/issue_observatory/api/routes/content.py` | 1157 | Already uses raw `show_all` — keep, but remove the resulting inconsistency by fixing item 2. |
| 4 | `src/issue_observatory/api/routes/content.py` | 1324 | Same as item 1. |
| 5 | `src/issue_observatory/api/routes/content.py` | 1347 | Same as item 2. |
| 6 | `src/issue_observatory/api/routes/content.py` | 273-275 | Replace `if not show_all: stmt.where(term_matched.is_(True))` with actor-only arena exemption pattern. |
| 7 | `src/issue_observatory/api/routes/content.py` | 559-560 | Same replacement in `_build_browse_stmt`. |
| 8 | `src/issue_observatory/api/routes/content.py` | 1067, 1330 | Change default from `["post"]` to `None` (filter off when absent). |
| 9 | `src/issue_observatory/api/routes/content.py` | 1209 | Add `platform: str | None = Query(None)` and `arena: str | None = Query(None)` parameters. |
| 10 | `src/issue_observatory/api/routes/content.py` | 1336 | Remove `arena=None` hardcode; pass the new `arena` parameter. |
| 11 | `src/issue_observatory/api/routes/content.py` | 1447 | Same — pass actual `arena`, not `None`. |
| 12 | `src/issue_observatory/api/routes/content.py` | 1686-1808 | Add missing parameters `q, mode, project_id, show_all, scrape_status, content_types`; replace `_build_content_stmt` call with `_build_browse_stmt`. |
| 13 | `src/issue_observatory/api/routes/content.py` | 164-282 | Delete `_build_content_stmt` after item 12 is complete. |
| 14 | `src/issue_observatory/api/routes/content.py` | 488-499 | Extract and use `_owned_run_subquery(current_user)` shared helper that includes collaborators. |
| 15 | `src/issue_observatory/api/routes/content.py` | 916-945 | Rewrite `content_record_count` to use `collection_run_id` subquery (consistent with browse) or rename endpoint. |
| 16 | `src/issue_observatory/api/routes/content.py` | ~560 and 273-281 | Add `.where(raw_metadata["duplicate_of"].astext.is_(None))` to exclude duplicates in both `_build_browse_stmt` and `_build_content_stmt` (if not deleted per item 13). |
| 17 | `src/issue_observatory/api/routes/content.py` | 1221, 1690 | Rename parameter `format` → `format_` with `alias="format"`. |
| 18 | `src/issue_observatory/api/templates/content/browser.html` | 173-181 | Remove `hx-trigger="change"` from the run_id select; wire search-terms reload to `htmx:afterRequest` on the main form instead. Remove the `hx-include="[name='search_term']"` which is a misread. |
| 19 | `src/issue_observatory/api/templates/content/browser.html` | 260-273 | Change the default for "Posts" checked state from always-checked to "checked only if `filter.content_types` explicitly contains it". Add an "All types" checkbox that maps to no-filter. |
| 20 | `src/issue_observatory/api/routes/content.py` | 1384 | The literal `"offset"` cursor is invalid. Either encode the numeric offset (`"offset:{n}"`) and decode at line 1302, or drop non-keyset sort support entirely. |
| 21 | `alembic/versions/` | (new) | Add migration `042_add_content_effective_language_index.py` with the language functional index described in §4.2. |
| 22 | `alembic/versions/` | (new) | Add migration `043_add_content_run_id_index.py` if `\d content_records` confirms the index is missing. |
| 23 | `tests/unit/api/content/` | (new) | Create the test files listed in §6. P0 tests first: `test_show_all_semantics.py`, `test_content_types_defaults.py`, `test_export_filter_parity.py`, `test_count_matching.py`. |
| 24 | `tests/integration/api/content/` | (new) | Create `test_filter_composition_e2e.py` with a full filter matrix against a real PostgreSQL fixture. |
| 25 | `src/issue_observatory/api/routes/content.py` | 1030-1040 | Either delete auto-select or push the selected `project_id` into `hx-push-url` so the URL and the applied filter stay in sync. |

---

## 10. Verdict (QA Guardian's Position)

**The content page filter system is not production-quality.** Of the 16 filter-like controls I audited, one is critically broken (`show_all`), five are high-severity partial (filter drops on export, hidden content_type default, fragment singular-platform dropout, search-term race, cross-page duplicate-exclusion divergence), four are medium (ownership inconsistency, language seq-scan, sort+pagination interaction, auto-select rewriting state), and only five work correctly end-to-end. There is no meaningful test coverage exercising any filter in a real query context. The sampling claim ("representative sample") is unsupported by the implementation.

**Blocking status:** If the content page were submitted to me as a new arena for the Definition of Done review, I would block it. Specifically:

- P0 items 1-3 (`show_all`, export filter drop, count divergence) must be fixed before any further UI work on this page.
- The test matrix in §6 must be written before fixes are merged — otherwise the same bugs will recur during the next refactor.
- The duplicate-exclusion asymmetry (§2.5) must be resolved before users are told "run deduplicate and see fewer records".

**Do not attempt a point-fix.** The root architectural issue is the divergence between `_build_browse_stmt`, `_build_content_stmt`, `analysis._filters`, and `content_record_count` — four filter stacks that must behave identically but do not. Fix item 9 (converge the helpers) is the correct structural intervention; the rest of the punch list becomes much smaller once the helpers are unified.

---

## Appendix A — Files Touched by This Audit

- `src/issue_observatory/api/routes/content.py` (2498 lines)
- `src/issue_observatory/api/templates/content/browser.html` (1010 lines)
- `src/issue_observatory/api/templates/_fragments/content_table_body.html` (131 lines)
- `src/issue_observatory/analysis/_filters.py` (260 lines)
- `src/issue_observatory/api/routes/analysis.py` (filter usage cross-check, lines 38-200)
- `src/issue_observatory/core/models/content.py` (337 lines)
- `src/issue_observatory/api/static/js/app.js` (scanned — no filter-related code)
- `src/issue_observatory/api/static/js/charts.js`, `network_preview.js` (not content-filter related)
- `alembic/versions/001_initial_schema.py` (index inventory)
- `alembic/versions/021_add_scrape_status.py`
- `alembic/versions/022_add_term_matched.py`
- `alembic/versions/040_add_dashboard_performance_indexes.py`
- `tests/unit/test_content_json_api.py` (376 lines)
- `tests/unit/test_content_route_search_terms.py` (210 lines)

## Appendix B — Files NOT Audited (out of scope for this pass)

- `/content/discovered-links`, `/content/{id}`, `/content/{id}/fetch-content`, `/content/duplicates`, `/content/deduplicate`, `/content/export/async`, `/content/export/{job_id}/*` — these are not user-facing filter controls and were only checked for parameter handoff bugs (none found beyond those noted above).
- `browse.html` (does not exist — `browser.html` is the correct path).
- `record_detail.html` — detail panel rendering, not filter logic.
- Arena-specific filter customization via `raw_metadata.subreddit`, `raw_metadata.channel_id`, etc. — these are not implemented; see fix item 19.
