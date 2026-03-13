# UX Evaluation: Comments Collection Module

**Date:** 2026-03-12
**Evaluator role:** UX Tester (Danish discourse researcher perspective)
**Status:** Design-phase evaluation (pre-implementation)

---

## Executive Summary

The proposed Comments Collection Module addresses a genuine gap in the platform. A researcher studying Danish media discourse does not merely care about posts -- they care about the *responses* those posts provoke. Comments are where public opinion crystallizes, where counter-narratives emerge, and where actor networks become visible. The feature is well-motivated.

However, the three-mode targeting design (search terms, actors, post URLs) introduces significant UX complexity that risks confusing researchers if not carefully placed and explained. This evaluation identifies the optimal location for the configuration, maps the researcher's mental model, flags concrete pitfalls, and provides text-level UI recommendations.

The core finding is: **comments configuration should live at the project level (alongside the existing Source Lists and Arena Settings sections on the project detail page), not in the query design editor or collection launcher.** This matches the existing architectural pattern where source-specific configuration is project-scoped, and it keeps the already-complex query design editor from becoming overwhelming.

---

## 1. Workflow Assessment

### The Three-Mode Targeting Design

The proposal offers three targeting modes per platform:

| Mode | Description | Researcher question it answers |
|------|-------------|-------------------------------|
| **Search terms** | Collect comments on posts matching selected terms | "What are people saying in response to posts about *gron omstilling*?" |
| **Source list actors** | Collect comments on posts published by selected actors | "What responses do Mette Frederiksen's posts receive?" |
| **Post URLs** | Collect comments on specific posts by URL | "I found this viral TikTok about the energy crisis -- get me the comments." |

**Assessment:** The three modes are conceptually sound and map to real research needs. However, they create a combinatorial challenge:

- A researcher may want mode A for Facebook, mode B for YouTube, and mode C for TikTok -- all within the same project.
- The modes are not mutually exclusive: a researcher studying actor reception *and* topic reception might want both search terms and actors enabled for the same platform.
- Post URLs are inherently ad-hoc and do not fit neatly alongside the other two modes, which derive their scope from existing query design elements.

### Edge Cases and Confusing Scenarios

1. **"Search terms" mode depends on existing collected posts.** A researcher enables comment collection for YouTube using "search terms." But comments are not *on search results* -- they are on *YouTube videos that match the terms.* This creates a timing dependency: the system must first collect videos matching the terms, then collect comments on those videos. If the researcher has not yet run a collection, there are no posts to collect comments from. This sequence dependency must be made explicit.

2. **Actor-only platforms (Facebook, Instagram) already collect by actors.** The existing launcher UI warns that "Facebook and Instagram collect via actors only." If comments are also scoped by actors, the researcher might wonder: "I already told the system to collect from these pages -- why do I have to say it again for comments?" The answer is that not every post collected from an actor should necessarily have its comments scraped (cost, volume, relevance), but this distinction needs clear explanation.

3. **Post URLs mode is a different interaction pattern.** Search terms and actors are *declarative* (set once, apply to all future runs). Post URLs are *imperative* (the researcher finds a specific post and wants its comments now). Mixing these two interaction styles in the same configuration panel will feel awkward. Post URLs should be a separate "one-off" action, perhaps triggered from the content browser when viewing a specific record.

4. **Cross-platform semantic mismatch.** "Comments" means structurally different things across platforms:
   - **YouTube**: Threaded comments under a video (can be thousands)
   - **Reddit**: Deeply nested comment trees (the comments *are* the content)
   - **Bluesky/X**: Reply threads (not a separate entity -- replies are posts)
   - **Facebook/Instagram**: Comments on posts/reels (require special API access)
   - **TikTok**: Comments under videos (limited API access)

   Reddit is a special case: the existing Reddit collector already collects posts, and the "comments" on a Reddit post are really just more Reddit posts in a tree structure. The researcher needs to understand that "enable comments for Reddit" means "also crawl the comment tree under each collected submission," which is conceptually different from "collect Facebook comments on a page's posts."

5. **Volume explosion risk.** A single viral YouTube video can have 50,000+ comments. A researcher who enables "collect comments on all YouTube videos matching 'klimaforandringer'" might inadvertently trigger collection of hundreds of thousands of comment records. This is the single largest UX risk of this feature.

---

## 2. Where Should This Configuration Live?

### Option A: Project Detail Page (Recommended)

**Location:** A new section on `/projects/{id}` between "Arena Settings" and "Source Lists."

**Pros:**
- Follows the established pattern: Arena Settings and Source Lists are already project-level configuration. Comments configuration is the same type of "how should collection behave" setting.
- Source lists (custom feeds, custom channels, custom accounts) are already platform-specific and project-scoped. Comments configuration is similarly platform-specific.
- Keeps the query design editor focused on *what to search for* (terms, actors, arenas, tiers), while the project page handles *how to collect* (source lists, arena toggles, comments).
- The project page already has the collapsible-panel UI pattern (`source_panel` macro) that works well for per-platform configuration.
- Does not add complexity to the collection launcher, which is already dense with controls.

**Cons:**
- Adds more content to an already-long project detail page.
- The connection between "comments are enabled here" and "the collection run actually collects them" requires clear labeling.

### Option B: Query Design Editor

**Location:** A new panel inside `/query-designs/{id}/edit`.

**Pros:**
- Comments configuration could reference search terms and actors from the same design directly, making the "which terms trigger comment collection" selection feel natural.

**Cons:**
- The query design editor is already the most complex page in the application (metadata form, search terms with groups/overrides/arena-scoping/translations, arena config grid with tiers, language selector, and a source-list redirect note). Adding another panel risks cognitive overload.
- Source lists were *moved out* of the query design editor to the project level for exactly this reason. Moving comments config here reverses that design decision.
- Multiple query designs in a project would each need independent comment settings, creating duplication.

### Option C: Collection Launcher

**Location:** An expandable section in `/collections/new`.

**Pros:**
- The researcher sees comment options at the moment they launch, so there is no surprise cost.

**Cons:**
- The launcher is already a complex form (project selector, mode toggle, date range, tier selector, arena exclusion, credit estimate, pre-flight summary). Adding per-platform comment configuration would make it overwhelming.
- Settings configured at launch time are ephemeral -- they do not persist for live tracking runs or future batch runs.
- A researcher using live tracking mode would have to remember to enable comments every time they modify the collection, or the system would need to persist these settings somewhere else anyway.

### Option D: Dedicated "Comments" Tab or Page

**Location:** A new sidebar entry (e.g., between "Content" and "Actors") or a tab within the project detail page.

**Pros:**
- Maximum discoverability -- researchers can find it in the navigation.
- Dedicated space means no cramming into an existing page.

**Cons:**
- Adding another top-level navigation item increases cognitive load for all users, including those who never need comments.
- Separating comment configuration from the project where it applies creates a navigation disconnect: "I configured my project, now I have to go somewhere else to configure comments?"

### Recommendation

**Option A (project detail page)** is the strongest choice. The implementation should be a new collapsible section titled "Comment Collection" placed between "Arena Settings" and "Source Lists." This mirrors the existing `source_panel` macro pattern and keeps all project-level collection configuration in one place.

---

## 3. Researcher Mental Model

### How Researchers Think About Comments

A Danish communications researcher studying "gron omstilling" (green transition) across platforms does not think in terms of API endpoints or data models. They think:

> "I want to see what people are *saying back* when politicians post about green transition. Not just the posts themselves -- the reactions, the pushback, the agreement."

This mental model has two natural entry points:

1. **Topic-driven**: "Show me comments on posts *about* green transition." This maps to the "search terms" targeting mode.
2. **Actor-driven**: "Show me comments on posts *by* the climate minister." This maps to the "actors" targeting mode.

The third mode (post URLs) maps to a different scenario:

3. **Artifact-driven**: "I found this specific post that went viral. Get me everything underneath it." This is typically a one-off action during analysis, not a configuration setting.

### Does the Proposed Design Match?

Mostly yes, but with friction:

- **Topic-driven** works well *if* the researcher understands the two-step process: first the system collects posts matching terms, then it collects comments on those posts. If the UI presents this as "select terms for comment collection," the researcher might expect the system to search *comments* for those terms -- which is a fundamentally different operation (searching within comment text vs. collecting comments from matched posts).

- **Actor-driven** works naturally: "collect comments on posts by these actors" is unambiguous.

- **Post URLs** does not fit the configuration paradigm. It should be a contextual action available in the content browser ("Collect comments for this post") rather than a pre-configured setting.

### Labeling Implications

The UI must use language that resolves the ambiguity. Instead of:

> "Search terms: select terms for comment collection"

Use:

> "Collect comments on posts that match these terms"

Instead of:

> "Source list actors: select actors for comment collection"

Use:

> "Collect comments on posts published by these actors"

The difference is subtle but critical. The first phrasing could mean "search within comments for these terms." The second phrasing makes the two-step process clear: posts first, then their comments.

---

## 4. Volume and Cost Awareness

### The Core Problem

Comments are a volume multiplier. A collection that returns 500 YouTube videos might generate 250,000 comment records. A Facebook page with 1,000 posts might have 50,000 comments. The researcher who casually toggles on "collect comments for YouTube" may not realize they are increasing their data volume by 100x.

### Required Safeguards

1. **Per-platform comment limits.** The configuration UI must expose a "maximum comments per post" setting for each platform. Sensible defaults: YouTube 100, Facebook 200, Reddit 500 (top-level only), TikTok 100, Bluesky/X unlimited (replies are regular posts). The researcher should see these defaults and be able to adjust them.

2. **Credit estimate integration.** The collection launcher's pre-flight estimate panel must account for comment collection costs. If comments are enabled for YouTube at medium tier, the estimate should show the additional credit impact. The current estimate panel (`/collections/estimate` HTMX endpoint) needs to be extended.

3. **Volume warning at configuration time.** When the researcher enables comment collection for a high-volume platform, show an inline warning:

   > "YouTube comment collection can significantly increase data volume and credit usage. A single popular video may have thousands of comments. Consider setting a per-post comment limit."

4. **Post-collection reporting.** The collection detail page (`/collections/{run_id}`) already shows "Records by Platform." Comment records should be broken out separately (e.g., "YouTube: 500 posts, 12,340 comments") so the researcher can see the multiplier effect.

5. **Progressive disclosure.** Do not show the full per-platform comment configuration by default. Use the same collapsible pattern as the source list panels: collapsed by default, with a badge showing "3 platforms configured" or "Not configured."

### Credit Estimate Panel Mockup

The existing credit estimate panel in the collection launcher shows per-arena costs. With comments enabled, it should add a line:

```
Arena Breakdown
  YouTube (medium)          ......    8 credits
    + comments (~12k est.)  ......   24 credits
  Facebook (medium)         ......   12 credits
    + comments (~5k est.)   ......   10 credits
  ---
  Total                     ......   54 credits
```

The "est." notation is important because comment volume cannot be known precisely before collection.

---

## 5. Discoverability

### Current State

A new researcher arrives at the platform, creates a project, builds a query design, and launches a collection. At no point in this workflow does the system mention comments. There is no breadcrumb, no tooltip, no help text that says "you can also collect comments."

### How a Researcher Would Discover This Feature

The most natural discovery path is:

1. The researcher collects posts from YouTube/Facebook/Reddit.
2. They browse the content in the content browser.
3. They see a YouTube video record and think: "I want the comments on this."
4. They look for a "collect comments" button on the record detail view. (Currently does not exist.)
5. Failing that, they go back to their project settings and look for a comments option.

### Recommendations for Discoverability

1. **Content browser integration.** When viewing a record detail for a platform that supports comments (YouTube, Facebook, Reddit, TikTok, etc.), show a contextual prompt:

   > "Comments for this post have not been collected. [Enable comment collection for YouTube in project settings]"

   This links directly to the project detail page comments section. If comments have already been collected, show a count ("47 comments collected") with a link to filter the content browser to those comment records.

2. **Arena config grid hint.** In the query design editor's arena configuration grid, for platforms that support comments, add a small indicator (similar to the existing "Config" badge for source-list arenas):

   > [Comments: Off]

   Clicking it navigates to the project-level comments configuration.

3. **Collection launcher reminder.** In the collection launcher, below the arena preview badges, add a single line when comment-supporting arenas are enabled but comments are not configured:

   > "Tip: You can also collect comments on posts from YouTube, Facebook, and Reddit. Configure in [Project Settings]."

4. **What Data Is Collected guide update.** Add a "Comments and Replies" section to `docs/guides/what_data_is_collected.md` explaining which platforms support comment collection, what data is captured per comment, and how comments relate to their parent posts.

---

## 6. Potential UX Pitfalls

### Pitfall 1: "I Enabled Comments but Nothing Was Collected"

**Scenario:** The researcher enables comment collection for Bluesky using "search terms" mode, but they run a batch collection for a date range where no Bluesky posts matched their terms. Result: zero comments collected, and the researcher does not understand why.

**Mitigation:** The collection detail page should show the dependency chain. For comment collection tasks, display: "0 comments collected (0 parent posts found matching your terms on Bluesky)." This makes the two-step relationship visible.

### Pitfall 2: "Comments Drowned My Real Data"

**Scenario:** The researcher enables comment collection for YouTube without a per-post limit. Their content browser, which previously showed 800 manageable records, now shows 45,000 records -- almost all comments. The signal-to-noise ratio collapses.

**Mitigation:** Two measures:

1. The content browser's filter sidebar should include a `content_type` filter that distinguishes "post" from "comment." This lets the researcher toggle between viewing posts-only and comments-included.
2. Comment records should be visually distinct in the content browser table -- perhaps indented with a reply icon, or with a lighter background, or with a "comment" badge in the content-type column.

### Pitfall 3: "Which Post Does This Comment Belong To?"

**Scenario:** The researcher exports 10,000 comment records as XLSX. In the spreadsheet, each comment is a row, but there is no obvious way to group comments by their parent post. The `parent_id` or `in_reply_to` field exists but uses platform-internal IDs that mean nothing to the researcher.

**Mitigation:** Comment records must include a human-readable reference to their parent: the parent post's title or first 100 characters of text, the parent post's URL, and the parent post's `platform_id`. In the export, add a column "Parent Post URL" and "Parent Post Title" that researchers can use as grouping keys in their analysis tools.

### Pitfall 4: "Reddit Comments -- Aren't They Already Posts?"

**Scenario:** The researcher has Reddit enabled and is confused about what "enable comments for Reddit" means, since Reddit submissions and comments are structurally similar. They wonder if enabling comments means they will get duplicate data.

**Mitigation:** The Reddit-specific help text should explain: "Reddit comments are the threaded replies below each submission. By default, the system collects submissions (posts) only. Enabling comment collection also retrieves the reply threads beneath each submission, up to the configured depth limit. Comments appear as separate records linked to their parent submission."

### Pitfall 5: "I Changed My Comment Settings But the Live Tracker Did Not Pick It Up"

**Scenario:** The researcher has a live tracking run active. They go to project settings and enable comment collection for a new platform. The next daily run at midnight does not include comments because the live run was configured at launch time and does not dynamically reload project settings.

**Mitigation:** Either: (a) live tracking runs should re-read project-level comment configuration before each daily batch (preferable), or (b) the UI must explicitly warn: "Changes to comment collection settings will apply to new collection runs only. Your active live tracking run will not be affected. Consider suspending and relaunching it."

### Pitfall 6: Bluesky and X/Twitter Replies Are Already Posts

**Scenario:** On Bluesky and X/Twitter, replies are structurally identical to posts. The existing collectors may already capture some replies if they match search terms. Enabling "comment collection" for these platforms risks creating duplicate records -- the same reply captured once as a search-matching post and once as a comment on a parent post.

**Mitigation:** The deduplication layer (`content_hash` + URL normalisation) should catch these duplicates. But the UI should explain: "On Bluesky and X/Twitter, replies are posts. The system automatically deduplicates replies that were already collected via search terms."

---

## 7. Concrete UI Recommendations

### 7.1 Project Detail Page: New "Comment Collection" Section

Placement: Between "Arena Settings" and "Source Lists."

```
+----------------------------------------------------------------------+
| Comment Collection                                            [?] Help|
| Configure which platforms should have post comments collected.        |
| Comments are collected as a second pass after posts are gathered.     |
+----------------------------------------------------------------------+
|                                                                      |
|  No platforms configured for comment collection.                     |
|  [+ Add Platform]                                                    |
|                                                                      |
+----------------------------------------------------------------------+
```

After the researcher clicks "+ Add Platform":

```
+----------------------------------------------------------------------+
| Comment Collection                                    2 configured   |
+----------------------------------------------------------------------+
|                                                                      |
|  [v] YouTube                                             [Collapse]  |
|  +----------------------------------------------------------------+  |
|  |  Collect comments on:                                          |  |
|  |    (*) Posts matching search terms from query designs          |  |
|  |    ( ) Posts published by source list actors                   |  |
|  |    (*) Both terms and actors                                   |  |
|  |                                                                |  |
|  |  Maximum comments per post:  [  200  ]                         |  |
|  |                                                                |  |
|  |  [!] YouTube videos can have thousands of comments.            |  |
|  |      Consider keeping the limit at 200 or below for           |  |
|  |      manageable data volumes.                                  |  |
|  |                                                     [Saved]    |  |
|  +----------------------------------------------------------------+  |
|                                                                      |
|  [>] Reddit                                              [Collapse]  |
|  +----------------------------------------------------------------+  |
|  |  Collect comments on:                                          |  |
|  |    (*) Posts matching search terms from query designs          |  |
|  |    ( ) Posts published by source list actors                   |  |
|  |    (*) Both terms and actors                                   |  |
|  |                                                                |  |
|  |  Maximum comment depth:  [  3  ]   (top-level + 2 reply       |  |
|  |                                      levels)                   |  |
|  |  Maximum comments per post:  [  500  ]                         |  |
|  |                                                     [Saved]    |  |
|  +----------------------------------------------------------------+  |
|                                                                      |
|  [+ Add Platform]                                                    |
|  Available: Facebook, Instagram, TikTok, Bluesky, X/Twitter         |
|                                                                      |
+----------------------------------------------------------------------+
```

### 7.2 Implementation Pattern: Reuse the `source_panel` Macro

The existing `source_panel` Jinja macro on the project detail page provides collapsible per-platform configuration panels with auto-save. The comment collection panels should follow the same pattern:

- Collapsed by default with a badge ("configured" / "not configured")
- Click to expand
- Changes auto-save via `PATCH /projects/{id}/comments-config/{arena_name}`
- Persisted in `project.source_config` (or a new `comments_config` JSONB column if separation is preferred)

### 7.3 Content Browser: Comment-Aware Filtering

Add a "Content Type" filter in the left sidebar filter form:

```
CONTENT TYPE
  [x] Posts
  [x] Comments
  [ ] Search results
  [ ] Autocomplete suggestions
```

When "Comments" is selected, add a visual indicator on each comment row:

```
  [reply icon] Comment on: "Ny klimaaftale splitter..."   |  YouTube  |  2h ago
    "Det er helt urealistisk at tro vi kan na det..."
```

### 7.4 Content Browser: Contextual "Collect Comments" Action

On the record detail panel (when clicking a post), add a contextual action for platforms that support comments:

```
+----------------------------------------------+
|  Record Detail                          [X]  |
+----------------------------------------------+
|  YouTube | Video                             |
|  "Klimaminister fremlaegger ny plan"          |
|  Published: 2026-03-10 14:22                 |
|  Views: 12,400  |  Likes: 890               |
|  Comments: not collected                     |
|                                              |
|  [Collect Comments for This Post]            |
|  [Enable Comment Collection for YouTube]     |
|  (takes you to project settings)             |
+----------------------------------------------+
```

If comments have already been collected:

```
|  Comments: 147 collected                     |
|  [View Comments] (filters browser to         |
|   comments on this post)                     |
```

### 7.5 Collection Launcher: Comment Collection Summary

In the pre-flight collection summary panel (the blue box that says "Collection scope: 8 arenas, 12 search terms, 3 actors"), add a comment line:

```
  Collection scope: 8 arenas, 12 search terms, 3 actors
  Comment collection: YouTube (limit 200/post), Reddit (depth 3, limit 500/post)
```

### 7.6 Collection Detail Page: Comment Breakdown

In the "Records by Platform" table on the collection run page, add a column or sub-row for comments:

```
  Platform       | Posts | Comments | Total | Status
  ---------------+-------+----------+-------+---------
  YouTube        |   45  |   3,210  | 3,255 | Complete
  Reddit         |  120  |   8,450  | 8,570 | Complete
  Bluesky        |  310  |       0  |   310 | Complete (no comments configured)
  RSS Feeds      |   85  |     n/a  |    85 | Complete
```

The "n/a" for RSS Feeds makes it clear that some platforms do not support comment collection at all.

### 7.7 Post URLs: Content Browser Action, Not Configuration

Rather than including "Post URLs" as a third targeting mode in the project configuration, implement it as a contextual action:

1. In the content browser, add a "+ Collect Comments" bulk action that lets the researcher select multiple records and trigger comment collection for all of them.
2. Add a standalone "Collect Comments by URL" tool page (under the "Tools" section in the navigation, alongside "Scraping Jobs" and "Import Data") where a researcher can paste one or more post URLs and trigger ad-hoc comment collection.

This separation keeps the project-level configuration clean (declarative: terms and actors) while still supporting the imperative "get comments on this specific post" workflow.

---

## 8. Data Model Considerations (from a researcher's perspective)

The researcher does not care about the data model. But they will care about:

1. **Can I tell comments apart from posts?** The `content_type` field must distinguish "comment" from "post" / "article" / "search_result" etc.
2. **Can I link a comment to its parent post?** There must be a `parent_content_id` or `in_reply_to_id` field on comment records. In exports, this should resolve to the parent's URL and title, not just an opaque UUID.
3. **Can I see the reply depth?** For threaded platforms (Reddit, YouTube), a `reply_depth` integer (0 = top-level comment, 1 = reply to comment, 2 = reply to reply) helps researchers analyze conversation structure.
4. **Are comment authors pseudonymized?** Yes -- the same `pseudonymized_author_id` logic must apply to comment authors.
5. **Does deduplication work across posts and comments?** A Bluesky reply collected both as a search-matching post and as a comment should be deduplicated to one record.

---

## 9. Documentation Requirements

When this feature is implemented, the following documentation must be updated:

1. **`docs/guides/what_data_is_collected.md`** -- Add a "Comments and Replies" section explaining what comment data looks like, how it relates to parent posts, and which platforms support it.
2. **Project detail page help text** -- The inline help text on the "Comment Collection" section must explain the two-step collection process (posts first, then comments) and the cost implications.
3. **Content browser help** -- Update any content browser documentation to explain the new content_type filter and how comment records appear.
4. **`docs/operations/arena_config.md`** -- Document the `comments_config` structure and its per-platform settings.

---

## 10. Responsible Agent Tags

| Finding | Responsible Agent |
|---------|-------------------|
| Project detail page section implementation | [frontend] |
| Comments config data model (JSONB on Project) | [core] |
| Content browser content_type filter | [frontend] |
| Comment record parent linking in exports | [core] |
| Credit estimate extension for comments | [core] |
| Per-platform comment collectors | [data] |
| Deduplication of replies already collected as posts | [core] |
| Documentation updates | [research] |
| Content browser "Collect Comments" action | [frontend] + [core] |
| Volume warning UI copy | [frontend] |

---

## 11. Priority Ranking

If this feature is implemented incrementally, the recommended priority order is:

1. **Project-level comment configuration UI** (the section on the project detail page) -- this is the foundation.
2. **Comment collection integration in the collection pipeline** -- per-platform comment collectors that run as a second pass after post collection.
3. **Content browser content_type filter** -- without this, comment records drown post records.
4. **Credit estimate extension** -- researchers must see the cost before launching.
5. **Content browser "Collect Comments" contextual action** -- the ad-hoc workflow for specific posts.
6. **Collection detail page comment breakdown** -- visibility into what was collected.
7. **Post URLs tool page** -- the standalone URL-based comment collection tool.

---

## 12. Summary of Key Recommendations

1. **Place comment configuration on the project detail page**, not in the query design editor or collection launcher. Follow the existing `source_panel` pattern.
2. **Use two targeting modes (terms and actors) in project configuration.** Move the post-URL mode to a contextual action in the content browser and a standalone tool page.
3. **Make the two-step collection process explicit** in all UI copy: posts are collected first, then their comments.
4. **Require per-post comment limits** with visible platform-specific defaults and volume warnings.
5. **Extend the credit estimate** to account for comment collection costs.
6. **Add a content_type filter** to the content browser so researchers can separate posts from comments.
7. **Link comments to parents** with human-readable fields (parent URL, parent title) not just internal IDs.
8. **Show comment breakdowns** on the collection detail page, separately from post counts.
9. **Discover this feature** via contextual prompts in the content browser and hints in the arena config grid.
10. **Explain platform differences** clearly: Reddit thread depth, Bluesky/X replies-are-posts deduplication, YouTube volume warnings.
