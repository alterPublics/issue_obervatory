# UX Test Report -- CO2 Afgift Discourse Mapping

Date: 2026-02-17
Scenario: Mapping the Danish policy discourse around "CO2 afgift" (CO2 tax/levy)
Arenas examined: google_search, google_autocomplete, bluesky, reddit, youtube, rss_feeds, gdelt, telegram, tiktok, ritzau_via, gab
Tiers examined: free, medium, premium (as configured in the query design editor and collection launcher)
Evaluation method: Code-based static analysis of all templates, source files, and configuration -- simulating every step a Danish policy researcher would take through the application

---

## Research Scenario

### Research Question

How is the CO2 afgift (carbon tax/levy) framed in Danish public discourse across digital media platforms in early 2026? Who are the key actors, what terms co-occur with "CO2 afgift," and does the framing differ between legacy news media (RSS), social platforms (Bluesky, Reddit), and news aggregation services (GDELT)?

### Why This Scenario Tests the Application Thoroughly

The CO2 afgift topic is ideal for stress-testing the Issue Observatory because:

1. **Bilingual terminology**: The issue uses both Danish ("CO2 afgift," "klimaafgift," "gron omstilling") and English ("carbon tax," "CO2 reduction") terms. A researcher needs to search in both languages and verify that Danish locale filtering works.
2. **Cross-platform presence**: The topic is discussed in parliament (Ritzau press releases), in newspapers (RSS feeds), on social media (Bluesky, Reddit), in YouTube debates, and in international news coverage (GDELT).
3. **Named actors**: Known politicians (Mette Frederiksen, Dan Jorgensen, Lars Lokke Rasmussen), organizations (Dansk Industri, Klimaraadet, Landbrug & Fodevarer), and media outlets all participate in this discourse.
4. **Term co-occurrence relevance**: "CO2 afgift" frequently co-occurs with "landbruget" (agriculture), "gron omstilling" (green transition), "klimaneutral," and "2030." A term co-occurrence network is methodologically meaningful for this topic.
5. **Temporal dynamics**: The topic has recurring peaks around budget negotiations (November-December) and EU regulation milestones, making batch vs. live collection both relevant.

---

## Step-by-Step Walkthrough

### Step 1: First Contact with the Application

**Researcher action:** Open the browser and navigate to the application.

**What the researcher sees:** The root URL (`/`) redirects to `/dashboard`. The dashboard presents:
- A header reading "Dashboard" with "Welcome, [user name]"
- Three summary cards: Credits, Active Collections, Records Collected
- A "Recent Collections" section (empty for a new user)
- Quick Actions panel with links to: Create new query design, Start new collection, Browse content, Analyse data
- An "About this platform" box that reads: "Issue Observatory collects and analyses public discourse across digital media arenas with a focus on the Danish context."

**Assessment:**

The landing experience is clean and well-structured. The "About this platform" text correctly signals the Danish focus, which immediately tells the researcher they are in the right place. However, the footer text reads "Phase 0 -- Google Search arena active," which contradicts the 11 arenas visible elsewhere in the application. A researcher encountering this will question whether the platform is actually usable for multi-arena collection. This is a stale label that should be updated.

The left sidebar navigation is clear: Dashboard, Query Designs, Collections, Content, Actors, Analysis. These six items map well to research workflow stages. The admin section (Users, Credits, API Keys, System Status) is contextually separated and labelled "Administration" -- appropriate.

**Finding FP-01:** The "Phase 0 -- Google Search arena active" text on the dashboard (file: `src/issue_observatory/api/templates/dashboard/index.html`, line 161) is outdated. The system has 11 arenas in the arena configuration grid. This creates a trust issue: the researcher questions whether the application is actually ready for multi-arena work. [frontend]

**Finding FP-02:** The System Status page (file: `src/issue_observatory/api/templates/admin/health.html`, lines 83-95) also states "Version: 0.1.0 (Phase 0)" and "Active Arenas: Google Search." This hardcoded information is incorrect relative to the actual feature set. [frontend]

---

### Step 2: Creating the Query Design -- "CO2 Afgift DK 2026"

**Researcher action:** Click "Create new query design" from the Quick Actions panel.

**What the researcher sees:** The Query Design Editor page with a form containing:
- Name (required) -- placeholder: "e.g. Climate debate DK 2024"
- Description -- placeholder: "Brief description of the purpose and scope..."
- Visibility dropdown: Private, Team, Public
- Default Collection Tier: Free, Medium, Premium
- Language dropdown: Danish (da), English (en), German (de)

**Researcher input:**
- Name: "CO2 Afgift DK 2026"
- Description: "Mapping Danish discourse on carbon taxation (CO2 afgift) across platforms, including framing analysis and actor identification for the period January-February 2026."
- Visibility: Private
- Default Tier: Free
- Language: Danish (da)

**Assessment:**

The placeholder "Climate debate DK 2024" is a good contextual example that signals this is a research tool for exactly this type of topic. The language dropdown defaulting to Danish is correct for the stated purpose.

However, the "Default Collection Tier" dropdown descriptions are minimal:
- "Free -- free data sources only"
- "Medium -- low-cost paid services"
- "Premium -- best available"

These descriptions do not tell the researcher which arenas are affected by each tier, what the credit cost difference is, or what data quality improvements they gain. The researcher is making a tier decision in the dark.

**Finding FP-03:** The Default Collection Tier selector descriptions are insufficient. A researcher choosing between free, medium, and premium cannot determine the practical difference without reading source code. The tier selector in the launcher is slightly better (it says "0 credits for most arenas" for free, "Costs credits" for medium, "Highest credit usage" for premium), but still lacks per-arena specifics. [frontend]

**Step 2a -- saving the query design:** The researcher clicks "Create Query Design." This submits a POST to `/query-designs/`. On success, the server responds with a redirect (via `HX-Redirect-To` header) to the newly created query design's editor page. The researcher is now on the edit page.

**Assessment:** This two-step flow (create a shell, then return to the editor to add terms and actors) is reasonable. The editor page is immediately loaded with the Search Terms panel, Actor List panel, and Arena Configuration grid visible. The researcher does not need to navigate elsewhere.

---

### Step 3: Adding Search Terms for CO2 Afgift

**Researcher action:** In the Search Terms panel, add the following terms:

1. "CO2 afgift" (Phrase) -- the primary Danish term
2. "klimaafgift" (Keyword) -- common Danish synonym
3. "carbon tax" (Phrase) -- English equivalent, for international discourse
4. "gron omstilling" (Keyword) -- "green transition," frequently co-occurring
5. "#CO2afgift" (Hashtag) -- social media hashtag variant
6. "CO2-reduktion" (Keyword) -- related reduction discourse
7. "klimaneutral" (Keyword) -- climate neutrality framing

**What the researcher sees:** A form with a dropdown (Keyword, Phrase, Hashtag, URL pattern) and a text input. Each added term appears as a row in the terms list.

**Assessment:**

The add-term interaction is smooth: the form is inline, the dropdown is next to the input, and the HTMX POST appends the new term to the list without a full page reload. The cursor refocuses on the input after each addition, allowing rapid entry. This is a well-designed interaction.

However, several issues arise:

**Finding FP-04:** The term type dropdown offers no explanation of what each type means. When the researcher selects "Phrase" for "CO2 afgift," they do not know whether the system will automatically wrap it in quotes when querying Google Search (it should, but this is not communicated). When they select "Hashtag" for "#CO2afgift," they do not know whether they should include the # sign or if the system prepends it. The placeholder says "Add search term..." but gives no guidance on formatting. [frontend]

**Finding FP-05:** The term count label (file: `src/issue_observatory/api/templates/query_designs/editor.html`, line 160) reads "X termer" -- using the Danish plural suffix "-er." This is a nice touch for Danish-context software, but it creates an inconsistency: the rest of the interface is in English. A Danish researcher expecting a fully Danish UI will be surprised to see only this one Danish word. An English-speaking collaborator will be confused by "termer." The label should be consistently in one language. [frontend]

**Finding FP-06:** There is no way to reorder search terms. The order of terms affects how they appear in the query design detail view and potentially in how results are matched. A researcher who wants "CO2 afgift" as the primary term has no way to ensure it appears first. This is minor but noted. [frontend]

**Special character handling for Danish terms:** The terms "gron omstilling" and "CO2-reduktion" contain the Danish characters that would normally include oe (as in "gron" which should be "gron" -- the researcher might type "gron omstilling" or "gron omstilling"). The system correctly handles UTF-8 input through the HTML form, and the PostgreSQL full-text search configuration uses the "danish" stemmer (confirmed in `danish_defaults.py`, line 218). The researcher should be able to enter "gron omstilling" with the proper ae/oe/aa characters without issue.

---

### Step 4: Adding Actors to the Query Design

**Researcher action:** In the Actor List panel, add key discourse actors:

1. Mette Frederiksen (Person) -- Prime Minister
2. Dan Jorgensen (Person) -- former Climate Minister
3. Lars Lokke Rasmussen (Person) -- Moderaterne leader
4. Dansk Industri (Organisation) -- industry lobby
5. Klimaraadet (Organisation) -- Climate Council
6. Landbrug & Fodevarer (Organisation) -- agriculture lobby

**What the researcher sees:** A dropdown (Person, Organisation, Media outlet, Account) and a text input with placeholder "Actor name or handle..."

**Assessment:**

The actor type categories are well-chosen for research purposes: Person, Organisation, Media outlet, and Account cover the standard categories used in Danish political communication research.

However, the Actor List panel in the query design editor only captures a name and a type. There is no field for platform-specific identifiers (e.g., Bluesky handle, Reddit username, YouTube channel ID). The researcher adds "Mette Frederiksen" as a Person, but the system has no way to know that this is @mfrederiksen.bsky.social on Bluesky, u/MFrederiksen on Reddit, or a specific YouTube channel.

**Finding FP-07:** The actor list in the query design captures only a name and a type, but does not link to platform presences. To actually use actor-based collection (e.g., fetching a specific politician's Bluesky feed), the researcher must separately navigate to the Actor Directory, find or create the actor there, add platform presences, and then hope the system connects the two. The query design actor list and the Actor Directory are conceptually separate, which creates a workflow gap. The query design actor rows do have a "Profile" link if an `actor_id` is present, suggesting the system can link them -- but the creation flow in the query design does not surface this connection. [frontend], [core]

**Finding FP-08:** When the researcher adds "Landbrug & Fodevarer" (containing the ampersand character `&`), the HTMX POST will URL-encode it. The confirm dialog for deletion (line 277) embeds the actor name directly in the `hx-confirm` attribute as `Remove '{{ actor.name | default('') }}' from this actor list?`. If the name contains characters that are meaningful in HTML attribute context (quotes, ampersands), this could cause rendering issues in the confirmation dialog. This is a minor robustness concern. [frontend]

---

### Step 5: Configuring Arenas

**Researcher action:** In the Arena Configuration grid, enable arenas and select tiers.

**What the researcher sees:** A table with 11 arenas, each with:
- Arena name (e.g., "Google Search") and identifier (e.g., `google_search`)
- An enable/disable toggle
- Three tier radio buttons: free, medium, premium
- An estimated credits column

The arenas listed are: Google Search, Google Autocomplete, Bluesky, Reddit, YouTube, RSS Feeds, GDELT, Telegram, TikTok, Ritzau Infostream, Gab.

**Researcher decisions for CO2 Afgift mapping:**

- Google Search: Enable, Free -- to capture search engine presence of the topic
- Google Autocomplete: Enable, Free -- to understand public search behavior
- Bluesky: Enable, Free -- Danish political discourse has moved significantly to Bluesky
- Reddit: Enable, Free -- the r/Denmark subreddit has active policy discussions
- YouTube: Enable, Free -- Danish political commentary is growing on YouTube
- RSS Feeds: Enable, Free -- major Danish newspapers' coverage
- GDELT: Enable, Free -- international news coverage of Danish climate policy
- Ritzau Infostream: Enable, Free -- Danish press releases from politicians and organizations
- Telegram: Disable -- Danish political discourse on Telegram is minimal
- TikTok: Disable -- CO2 tax is not a primary TikTok topic in Denmark
- Gab: Disable -- negligible Danish presence on Gab

**Assessment:**

The arena grid is functional and visually clear. The "Enable all" and "Disable all" buttons are useful shortcuts. The tier radio buttons use appropriate color coding (green for free, yellow for medium, purple for premium).

However, there are significant issues:

**Finding FP-09 (confirms Phase 3 FP-03):** All 11 arenas display free/medium/premium radio buttons, but arenas like Bluesky, RSS Feeds, GDELT, Reddit, Ritzau, Gab, and TikTok only support the free tier. Selecting "medium" or "premium" for Bluesky gives no visual warning. The researcher may believe they are getting enhanced Bluesky data at medium tier when in fact the collector silently falls back to free. This is a data trust issue that directly affects the researcher's ability to describe their methodology accurately. [frontend]

**Finding FP-10:** The arena list is hardcoded in JavaScript (file: `src/issue_observatory/api/templates/query_designs/editor.html`, lines 474-486) rather than fetched from the server. This means:
- New arenas added to the backend will not appear in the UI until the template is updated
- The list does not reflect which arenas have active credentials configured
- The researcher cannot tell which arenas are ready to collect (have credentials) vs. which are merely listed

This is a significant discoverability issue. A researcher who enables "Event Registry" (which is absent from the hardcoded list, despite having a full backend implementation) cannot do so through this interface. [frontend], [core]

**Finding FP-11:** The arena list is missing several implemented arenas. Comparing the hardcoded list (11 arenas) to the arenas directory in the source code reveals implemented but unlisted arenas: Event Registry, X/Twitter, Threads, Common Crawl, Majestic, Wayback Machine, Facebook, Instagram. These arenas have full collector implementations but are invisible in the query design editor. [frontend]

**Finding FP-12:** The credit estimate column shows "..." for enabled arenas but never resolves to actual values during the static analysis. The HTMX trigger fires a GET to `/api/collections/estimate` which must be implemented on the backend. The researcher experience depends on whether this endpoint is functional. If it returns no data or errors, the researcher sees perpetual "..." values, which provides no useful information. [frontend], [core]

**Finding FP-13:** There is no tooltip, help text, or "info" icon on any arena explaining what data it collects or what Danish-specific filtering is applied. The researcher sees "GDELT" but may not know what GDELT is. They see "Ritzau Infostream" but may not know it collects press releases (not news articles). The arena labels are too terse for a researcher who is not already familiar with each platform's API. [frontend]

---

### Step 6: Saving the Arena Configuration

**Researcher action:** Click "Save Arena Config" button.

**What the researcher sees:** The button triggers an HTMX POST to `/query-designs/{design_id}/arena-config` with the arena enable/disable and tier selections. A spinner appears during the request.

**Assessment:**

The save flow is straightforward. However, there is no confirmation message after a successful save -- the spinner disappears and the page returns to its previous state. The researcher does not know whether the save succeeded or failed unless they check the network tab in browser developer tools.

**Finding FP-14:** No success confirmation after saving arena configuration. The HTMX POST uses `hx-swap="none"`, meaning no visible DOM update occurs on success. The researcher clicks "Save Arena Config," the spinner appears briefly, and then... nothing visible happens. A brief flash message or a green checkmark next to the button would confirm the save. [frontend]

---

### Step 7: Reviewing the Query Design

**Researcher action:** Navigate to the query design detail page (`/query-designs/{design_id}`).

**What the researcher sees:** A read-only view showing:
- Basic Information (name, description, visibility, default tier, language, owner, creation date)
- Search Terms displayed as styled badges (type prefix + term text)
- Actor List (if populated)
- Run History (empty for a new design)

The detail page has two buttons in the header: "Edit" and "Run collection."

**Assessment:**

The detail page is clean and well-organized. The search terms are displayed with type indicators: "kw" for keyword, `""` for phrase, "#" for hashtag, "URL" for URL pattern. This is a nice visual distinction.

The term count label again uses "termer" (Danish plural), consistent with the editor page.

The "Run collection" button links to `/collections/new?design_id={id}`, pre-selecting this query design in the launcher. This is a good workflow shortcut -- the researcher does not need to navigate through the collections menu separately.

**Finding FP-15:** The query design detail page shows search terms and actors but does NOT display the arena configuration. The researcher can see what they are searching for (terms, actors) but not where they are searching (which arenas are enabled, at which tier). To see the arena configuration, they must click "Edit" and scroll down to the arena grid. This omission means the researcher cannot get a complete "methods section" view of their research design from a single page. [frontend]

---

### Step 8: Launching a Collection

**Researcher action:** Click "Run collection" from the query design detail page, or navigate to Collections > New Collection.

**What the researcher sees:** The Collection Launcher page with:
- Query Design selector (pre-filled if coming from the detail page)
- Mode toggle: Batch (historical) / Live (ongoing)
- Date range fields (From/To) -- visible only in Batch mode
- Tier selector: Free, Medium, Premium (with brief descriptions)
- A right-side panel showing "Credit Estimate"
- A "Start Collection" button

**Researcher decisions for CO2 Afgift:**
- Query Design: "CO2 Afgift DK 2026" (pre-selected)
- Mode: Batch (historical)
- Date range: 2026-01-01 to 2026-02-17
- Tier: Free

**Assessment:**

The launcher is well-structured. The mode toggle is clear, with contextual descriptions that change based on selection. The credit estimate panel on the right provides pre-flight cost awareness, which is excellent for researchers with limited budgets.

The tier selector cards in the launcher are more descriptive than the one in the query design editor:
- Free: "Free data sources only. 0 credits for most arenas."
- Medium: "Includes low-cost API services. Costs credits."
- Premium: "Best available data quality. Highest credit usage."

These are still vague but better than the editor's dropdown options.

**Finding FP-16 (confirms Phase 3 FP-10):** The Live mode description reads "Start ongoing daily collection (Celery Beat)." "Celery Beat" is a developer-internal technology name that means nothing to a Danish policy researcher. The description should read something like "Start ongoing daily collection. Runs automatically every day at midnight Copenhagen time." [frontend]

**Finding FP-17:** The date range inputs for Batch mode have no guidance on what date ranges are practical or supported. A researcher might enter a date range of two years, not knowing that some arenas (Google Search free tier) have limited historical reach (typically the most recent results only, no historical archive). The date range interacts differently with each arena -- RSS feeds have no historical archive at all, while GDELT can go back years. No guidance is provided. [frontend], [research]

**Finding FP-18:** The launcher's tier selector is at the global level, but the query design editor also has per-arena tier selection. It is unclear which takes precedence. If the researcher set Bluesky to "medium" in the arena config but selects "free" in the launcher, which tier applies? This ambiguity is not resolved anywhere in the UI. [frontend], [core]

---

### Step 9: Monitoring the Collection

**Researcher action:** After clicking "Start Collection," the researcher is redirected to the Collection Detail page.

**What the researcher sees (batch mode):**
- A header showing "Collection Run" with a truncated run ID
- An SSE-connected live status area that shows arena tasks as they execute
- An Arena Tasks table with columns: Arena, Status, Records, Credits, Duration, Notes
- A "Cancel run" button while the run is active
- A "Live" indicator dot

After completion:
- A message: "Collection finished. Explore the collected content below."
- Two buttons: "Browse content" and "Run again"

**Assessment:**

The collection monitoring experience is well-designed. The SSE (Server-Sent Events) connection provides real-time updates without the researcher needing to refresh. Each arena task appears as a row that updates its status from "pending" to "running" to "completed" (or "failed"). This gives the researcher visibility into which arenas succeeded and which had problems.

The "Notes" column in the task table is where error messages appear. If a credential is invalid or a rate limit is hit, the note column shows the error text from the collector. This is appropriate for batch runs.

**Finding FP-19:** For batch mode, the collection detail page does not show which search terms were used or which arenas were configured. The researcher sees the run ID and the task table, but if they return to this page days later, they cannot determine what was collected without navigating back to the query design. The run metadata should include a link to the query design and a summary of the search terms used. [frontend]

**Finding FP-20:** The run ID is displayed as a truncated 8-character UUID hash (e.g., "a1b2c3d4"). This is developer-centric. The researcher would benefit from seeing the query design name prominently in the header instead of just the UUID. The template does include `run.query_design_name` in the page title (line 2), but the visible header only shows "Collection Run" + the UUID fragment. [frontend]

---

### Step 10: Examining the Live Tracking Schedule (for live mode)

**Researcher action (hypothetical):** If the researcher had chosen "Live (ongoing)" mode, the collection detail page would show an additional "Live Tracking Schedule" panel.

**What the researcher sees:**
- A "Live Tracking Schedule" panel with:
  - "Next scheduled run:" with a timestamp formatted in en-GB locale with Copenhagen timezone
  - A status badge: "Active -- collecting daily" (green) or "Suspended -- collection paused" (amber)
  - Three action buttons: "Suspend Tracking," "Resume Tracking," "Cancel & Delete Run"
  - An inline explanation: "Suspend pauses daily collection without deleting your data. Cancel permanently ends the run."

**Assessment:**

This is a substantial improvement over the Phase 3 findings. The Phase 3 report identified B-03 (no UI for viewing or suspending the live tracking schedule) as a blocker. The current implementation addresses this comprehensively:

1. The schedule panel shows the next scheduled run timestamp with timezone context
2. Suspend and Resume operations are available, with clear confirmation dialogs
3. The Cancel operation is distinct from Suspend, with explicit warning text
4. The status badges use appropriate colors (green for active, amber for suspended)
5. The fallback text "Daily at midnight Copenhagen time (00:00 CET/CEST)" appears when the schedule endpoint is unreachable

**Passed:** The live tracking schedule panel addresses the Phase 3 blocker B-03. The researcher can now see when the next run will fire, suspend collection during holidays, and resume it. The terminology is clear and research-friendly.

---

### Step 11: Browsing Collected Content

**Researcher action:** After the collection completes, click "Browse content" to examine results.

**What the researcher sees:** The Content Browser with:
- A left sidebar with filters: Search, Arena (checkboxes for 11 arenas), Date Range, Language (All/Danish/English/German), Search Term, Collection Run
- A main table with columns: Platform, Content (title + text excerpt), Author (hidden below lg breakpoint), Published (hidden below md), Arena (hidden below xl), Engagement (hidden below md)
- An "Export CSV" button at the bottom of the sidebar
- A detail panel that slides in from the right when a row is clicked

**Researcher workflow for CO2 Afgift:**
1. First, check all results (no filters) to see the total volume
2. Filter by arena: check only "RSS Feeds" to examine Danish newspaper coverage
3. Search for "CO2 afgift" in the search box to find exact-match content
4. Filter by language: select "Danish (da)" to confirm locale filtering is working
5. Click individual records to examine content in the detail panel

**Assessment:**

The content browser is the most complex and frequently-used page in the application. Its design is generally sound:
- The sidebar filter form auto-submits on change with a 400ms debounce, which provides responsive filtering without excessive server requests
- The infinite scroll (capped at 2,000 rows with a warning banner) is appropriate for research browsing
- The detail panel slide-in is a good split-view pattern that avoids full-page navigation

However, several issues arise for the CO2 Afgift use case:

**Finding FP-21 (confirms Phase 3 FP-09):** The Arena column is hidden below the xl breakpoint (1280px). On a standard 1366x768 laptop display, the researcher cannot see which arena a record came from. For a multi-arena study like CO2 Afgift, this is critical information. The "Platform" column remains visible but does not distinguish between google_search and google_autocomplete (both show "Google"), or between rss_feeds and ritzau_via. [frontend]

**Finding FP-22 (confirms Phase 3 FP-08):** The "Engagement" column has no explanation of what the score represents. A researcher comparing engagement scores across RSS Feeds (which may have zero engagement metrics) and Reddit (where engagement reflects upvotes) will be confused. For the CO2 Afgift study, comparing how "engaging" the topic is across platforms requires understanding what the metric means per platform. [frontend], [research]

**Finding FP-23:** The content browser search box (labelled "Search") performs full-text search across content, but the sidebar also has a "Search Term" filter that filters by which query design search term was matched. These are different operations with similar names. A researcher typing "CO2 afgift" in the "Search" box searches text content; typing it in the "Search Term" field filters by matched search terms from the query design. The distinction is not explained, and a researcher may use the wrong one. [frontend]

**Finding FP-24:** The Language filter dropdown offers only four options: All, Danish (da), English (en), German (de). The researcher cannot filter for Norwegian or Swedish content, which may be relevant for cross-Scandinavian climate policy discourse. More importantly, there is no "Unknown" or "Undetected" option -- records where language detection failed or was not performed (e.g., some RSS feed entries) are filtered out by any language selection, including Danish. [frontend]

---

### Step 12: Examining the Record Detail Panel

**Researcher action:** Click on a content record row in the browser table.

**What the researcher sees:** A detail panel sliding in from the right with:
- Platform badge and arena identifier
- "View original" link to the source URL
- Title (if present)
- Full text content in a gray box (truncated at 2,000 characters)
- Metadata grid: Author, Published, Collected, Language, Engagement, Collection Run, Record ID
- "Matched search terms" as styled badges
- "Show raw metadata" expandable section with JSON viewer
- Action links: "Find actor," "More from this run," "Full page"

**Assessment:**

The record detail panel is well-designed for research use. Key observations:

1. The "Matched search terms" display is excellent -- the researcher can immediately see which of their search terms triggered this record's inclusion. For the CO2 Afgift study, seeing whether a record matched "CO2 afgift," "klimaafgift," or "gron omstilling" is directly useful for framing analysis.

2. The "View original" link opens the source URL in a new tab, allowing the researcher to verify the content against the original source. This is critical for data trust.

3. The "Show raw metadata" toggle provides access to platform-specific fields without cluttering the default view. A researcher who needs Reddit-specific fields (score, num_comments, subreddit) can expand this section.

4. The "Find actor" link correctly pre-fills the actor search with the author's name, bridging the content browser to the actor directory.

**Finding FP-25:** The "Published" and "Collected" timestamps are displayed in ISO 8601 format (e.g., "2026-02-15T14:30:00") truncated to 19 characters. This format is technically precise but not human-friendly for Danish researchers, who would expect dates in dd/mm/yyyy format or a localized format. No timezone information is visible -- the researcher cannot tell if the timestamp is UTC, CET, or the original platform's timezone. [frontend]

**Finding FP-26:** The "Collection Run" field shows a truncated UUID (8 characters). For a researcher who has run multiple collections with the same query design, this is not sufficient to identify which run a record belongs to. The query design name and the run's start date would be more useful. [frontend]

---

### Step 13: Using the Actor Directory

**Researcher action:** Navigate to the Actors page from the sidebar.

**What the researcher sees:**
- A header: "Actor Directory" with subtitle "Cross-platform identity registry"
- An "Add Actor" button
- A search bar: "Search actors by name..."
- An actors table: Name, Type, Platforms, Content (count), Last seen
- A "Snowball Sampling" collapsible panel at the bottom

**Researcher workflow for CO2 Afgift:**
1. Add key actors (Mette Frederiksen, Dan Jorgensen, etc.)
2. For each actor, add platform presences (Bluesky handle, Reddit username)
3. Use snowball sampling to discover additional actors in the CO2 afgift discourse

**Assessment:**

The Actor Directory is more complete than reported in the Phase 3 review. Critically, the Snowball Sampling panel IS now present on the Actor Directory page -- this was identified as blocker B-01 in the Phase 3 report. The implementation includes:

- Seed actor selection via checkboxes from the current actor list
- Platform selection for which platforms to search
- Depth slider (1-3 hops) with clear labels
- Max actors per step input
- "Automatically add all discovered actors to this list" toggle
- Results table with discovered actors, their platforms, and discovery depth
- Select all/none functionality
- "Add selected actors to this list" button

**Passed:** The Snowball Sampling panel exists on the Actor Directory page, addressing Phase 3 blocker B-01. The UI is well-designed with clear controls and a reviewable results workflow. The researcher can select seed actors, choose platforms, set discovery depth, run the sampler, review results, and add selected actors to their list.

However, there are friction points:

**Finding FP-27:** The Snowball Sampling panel is collapsed by default and appears at the very bottom of the page, below the actors table. A new researcher who visits the Actor Directory for the first time may not scroll down far enough to notice it. There is no mention of snowball sampling anywhere else in the navigation or in the query design editor. The feature is present but not discoverable without scrolling. [frontend]

**Finding FP-28:** The Snowball Sampling panel requires seed actors to already exist in the actor directory. A researcher who is just starting (empty actor directory) sees the message "No actors in this list yet. Add actors above first." This creates a chicken-and-egg problem: the researcher must manually add actors before they can discover more actors. The workflow should allow entering seed actor handles directly (e.g., a Bluesky handle) without first creating actor entries. [frontend]

**Finding FP-29:** The actor detail page's "Platform Presences" section requires the researcher to know the exact platform identifier for each actor. The platform dropdown lists: Bluesky, Reddit, YouTube, Telegram, TikTok, Twitter/X, Facebook, Instagram, Gab, LinkedIn, Other. For a researcher tracking Danish politicians on Bluesky, they need to know the Bluesky handle (e.g., "mfrederiksen.bsky.social"). The form does not provide any lookup or search functionality. [frontend]

---

### Step 14: Analysis Dashboard

**Researcher action:** Navigate to Analysis (from the sidebar) or click "Analyse data" from the collection detail page.

**What the researcher sees:**
- A page header with status badge, tier badge, and mode badge
- Four summary cards: Total records, Arenas, Date range, Credits spent
- A filter bar with: Platform, Arena, From, To, Granularity (hour/day/week/month) + Apply/Reset buttons
- Four chart panels: Volume over time, Top actors, Top terms, Engagement distribution
- A Network Analysis section with four tabs: Actor network, Term network, Bipartite, Cross-platform actors
- An Export section with format selector (CSV, XLSX, JSON, Parquet, GEXF) and download buttons

**Assessment for CO2 Afgift:**

The Analysis Dashboard is comprehensive and well-organized. For the CO2 Afgift study, the researcher would:

1. **Volume over time (day granularity):** See how CO2 afgift coverage fluctuates across arenas over the January-February 2026 period. The multi-arena line chart (if `initMultiArenaVolumeChart` is available) would show separate lines per arena, which is excellent for cross-platform comparison.

2. **Top actors:** Identify who is discussing CO2 afgift most frequently. This chart uses `author_display_name || pseudonymized_author_id || '?'` as labels, which means some bars will show readable names and others will show hex hashes.

3. **Top terms:** See which of the 7 search terms match most content. This is directly useful for understanding which framings dominate.

4. **Engagement distribution:** Compare engagement levels across platforms. However, the engagement metric comparability issue (FP-22) applies here too.

**Finding FP-30 (confirms Phase 3 FP-12):** The chart panels have no axis labels. The researcher cannot produce publication-quality screenshots without external annotation. For the CO2 Afgift study, a chart titled "Volume over time" with unlabelled axes is suitable for exploration but not for inclusion in a conference paper or journal article. [frontend]

**Finding FP-31:** The filter bar uses plain text inputs for "Platform" and "Arena" (placeholders: "e.g. reddit" and "e.g. social"). These should be dropdown selectors or at least autocomplete fields. A researcher who types "bluesky" when the system expects "Bluesky" (or vice versa) will get no results without understanding why. The content browser uses checkboxes for arenas, but the analysis dashboard uses free-text inputs -- this inconsistency is confusing. [frontend]

---

### Step 15: Network Analysis and GEXF Export

**Researcher action:** Click on the "Term network" tab to examine which CO2 afgift search terms co-occur.

**What the researcher sees:**
- A description: "Term co-occurrence graph -- two search terms are linked when they appear together in the `search_terms_matched` array of the same record."
- A "Download Term Co-occurrence Network (GEXF)" button
- The button links to `/content/export?format=gexf&network_type=term&run_id={run_id}`

**Assessment:**

The Phase 3 report identified B-02 as a critical blocker: all three GEXF download buttons pointed to the same endpoint with no `network_type` parameter. The current implementation has been fixed:

1. The actor network button links to `network_type=actor`
2. The term network button links to `network_type=term`
3. The bipartite network button links to `network_type=bipartite`

Furthermore, examining `export.py`, all three network types are now fully implemented:
- `_build_actor_gexf()` (lines 411-491): Actor co-occurrence based on shared search terms
- `_build_term_gexf()` (lines 497-567): Term co-occurrence based on records matching multiple terms
- `_build_bipartite_gexf()` (lines 573-647): Bipartite actor-term network

The `export_gexf()` dispatch method (lines 653-717) correctly routes based on `network_type` and raises a `ValueError` for unknown types.

**Passed:** The GEXF export now supports all three network types (actor, term, bipartite) with distinct implementations. The download buttons in the network tabs correctly pass the `network_type` parameter. This addresses Phase 3 blocker B-02.

**Passed:** The actor co-occurrence edge construction (confirmed by reading `_build_actor_gexf()`) now correctly uses shared search terms rather than shared collection_run_id. Two authors are linked only when they both have records matching at least one common term. Edge weight equals the number of shared terms, and the `shared_terms` edge attribute contains the pipe-separated sorted list of overlapping terms. This addresses Phase 3 data quality finding DQ-02.

The Export section also has a GEXF network type selector (lines 451-473) that appears when GEXF format is selected, offering radio buttons for Actor co-occurrence, Term co-occurrence, and Bipartite actor-term. This is a good duplicate of the tab-level download buttons, providing the same functionality through the general export panel.

**Finding FP-32:** For the CO2 Afgift study, the term co-occurrence network would show which search terms appear together in the same records. For example, if many records match both "CO2 afgift" and "gron omstilling," these terms will have a strong edge. However, the GEXF export produces a file that must be opened in external software (Gephi). The analysis dashboard provides no in-browser visualization of the network. A simple force-directed graph rendering would help the researcher preview the network structure before deciding to export it. [frontend]

---

### Step 16: Data Export for External Analysis

**Researcher action:** Use the Export panel to download collected data.

**What the researcher sees:**
- Format selector: CSV, XLSX, JSON, Parquet, GEXF
- "Export (up to 10 k records)" button
- "Export async (large dataset)" button
- When async export is started: Job ID, status, progress percentage, download link when complete

**Assessment for CO2 Afgift:**

A researcher who wants to analyze CO2 afgift data in R, Python, or NVivo would use CSV or XLSX export. The export flow has two paths:

1. **Synchronous export (up to 10,000 records):** Direct download link. Good for moderate datasets.
2. **Asynchronous export (large datasets):** Celery task with progress tracking and download when complete. Good for datasets exceeding 10,000 records.

**Finding FP-33 (confirms Phase 3 FP-15):** The XLSX/CSV column headers use internal snake_case names: `text_content`, `views_count`, `search_terms_matched`. A researcher opening the file sees technical identifiers rather than human-readable column names. For the CO2 Afgift study, sharing the export with a collaborator requires a separate data dictionary. The headers should be human-readable (e.g., "Text Content," "View Count," "Matched Search Terms"). [data]

**Finding FP-34 (confirms Phase 3 FP-16):** The JSON export format is NDJSON (one JSON object per line), but the UI labels it simply "JSON." A researcher who selects "JSON" and opens the file expecting a standard JSON array will find a malformed-looking file. The label should read "NDJSON (one record per line)" with a tooltip explaining the format. [frontend], [data]

**Finding FP-35:** The Parquet export option is excellent for researchers who work with Python (pandas) or R (arrow). However, the UI provides no explanation of what Parquet is. A researcher unfamiliar with columnar data formats will not know what this option is for. A brief tooltip ("Columnar format for efficient analysis in Python/pandas or R/arrow") would help. [frontend]

---

### Step 17: System Health Check

**Researcher action:** Navigate to Admin > System Status.

**What the researcher sees:**
- Infrastructure status cards for PostgreSQL, Redis, Celery Workers (HTMX-polled every 15s)
- Arena Status section with individual health checks (polled every 60s)
- System Information: Version 0.1.0 (Phase 0), Active Arenas: Google Search

**Assessment:**

The health dashboard is useful for confirming that the infrastructure is operational before starting a collection. For the CO2 Afgift researcher, checking that the RSS feed health checks pass (especially the uncertain Jyllands-Posten feed) would be important.

**Finding FP-36 (reconfirms FP-02):** The System Information section is hardcoded and stale. "Active Arenas: Google Search" does not reflect the actual arena set. "Implementation Phase: Phase 0" does not match the feature maturity. [frontend]

---

## Passed

### P-01: Snowball sampling has a frontend entry point
The Actor Directory page now includes a collapsible "Snowball Sampling" panel with seed actor selection, platform choice, depth controls, and a results review workflow. This addresses Phase 3 blocker B-01.

### P-02: GEXF export supports all three network types
The `export_gexf()` method dispatches to `_build_actor_gexf()`, `_build_term_gexf()`, or `_build_bipartite_gexf()` based on the `network_type` parameter. The UI download buttons correctly pass distinct `network_type` values. This addresses Phase 3 blocker B-02.

### P-03: GEXF actor co-occurrence edge construction is correct
The `_build_actor_gexf()` method builds edges based on shared search terms (not shared collection_run_id). Edge weight equals the number of distinct shared terms. The `shared_terms` attribute contains the intersection, not the union. This addresses Phase 3 data quality finding DQ-02.

### P-04: Live tracking schedule is visible and controllable
The collection detail page for live-mode runs includes a "Live Tracking Schedule" panel with next-run timestamp, suspend/resume controls, and clear status indicators. This addresses Phase 3 blocker B-03.

### P-05: Danish locale parameters are correctly configured
`danish_defaults.py` defines correct locale parameters for all Danish-context arenas: Google (gl=dk, hl=da), Bluesky (lang:da), Reddit (4 Danish subreddits), GDELT (sourcelang=danish, sourcecountry=DA), YouTube (relevanceLanguage=da, regionCode=DK), RSS (27 curated Danish news feeds), Ritzau (language=da). These are well-documented with source references.

### P-06: Content record detail panel is researcher-friendly
The record detail panel shows platform badge, source link, full text content, matched search terms as badges, and expandable raw metadata. The "Find actor" and "More from this run" action links bridge the detail panel to other parts of the application. This is a well-designed research inspection interface.

### P-07: Export panel supports five formats including async export
CSV, XLSX, JSON (NDJSON), Parquet, and GEXF are all available. The async export with job tracking (status, progress percentage, download link) handles large datasets appropriately.

### P-08: Query design editor supports full term and actor management
The editor allows adding/removing search terms with type classification (keyword, phrase, hashtag, URL pattern) and actors with type classification (person, organisation, media outlet, account) via HTMX inline forms. The interaction is responsive and auto-refocuses for rapid entry.

### P-09: Content browser has a functional filter system
The sidebar filters (arena checkboxes, date range, language, search term, collection run) auto-submit with debounce. The infinite scroll with 2,000-row cap and export fallback is appropriate for research browsing.

---

## Friction Points

### FP-01 -- Dashboard says "Phase 0" when the application has 11+ arenas
File: `src/issue_observatory/api/templates/dashboard/index.html`, line 161
The researcher sees "Phase 0 -- Google Search arena active" on the dashboard, creating doubt about the application's capabilities. [frontend]

### FP-02 -- System Status page shows hardcoded stale information
File: `src/issue_observatory/api/templates/admin/health.html`, lines 83-95
"Version: 0.1.0 (Phase 0)" and "Active Arenas: Google Search" are incorrect. [frontend]

### FP-03 -- Tier descriptions are too vague for informed decision-making
File: `src/issue_observatory/api/templates/query_designs/editor.html`, lines 104-107; `collections/launcher.html`, lines 148-166
The researcher cannot determine the practical difference between tiers without reading documentation or source code. [frontend]

### FP-04 -- No explanation of what Keyword, Phrase, Hashtag, URL pattern mean
File: `src/issue_observatory/api/templates/query_designs/editor.html`, lines 169-175
The term type dropdown offers four options with no help text or tooltip explaining how each type is handled by arena collectors. [frontend]

### FP-05 -- Mixed language: "termer" (Danish plural) in otherwise English UI
File: `src/issue_observatory/api/templates/query_designs/editor.html`, line 160; `query_designs/detail.html`, line 120
The term count label uses "termer" (Danish) while all other text is in English. [frontend]

### FP-07 -- Query design actor list does not link to platform presences
File: `src/issue_observatory/api/templates/query_designs/editor.html`, lines 208-295
Adding an actor to the query design captures only a name and type, with no connection to the actor's platform-specific identifiers needed for actor-based collection. [frontend], [core]

### FP-09 -- All arenas show free/medium/premium tiers regardless of support
File: `src/issue_observatory/api/templates/query_designs/editor.html`, lines 392-409
Arenas that only support the free tier (Bluesky, RSS, GDELT, Reddit, Ritzau, Gab, TikTok) display medium and premium radio buttons with no warning. [frontend]

### FP-10 -- Arena list is hardcoded in JavaScript, not fetched from server
File: `src/issue_observatory/api/templates/query_designs/editor.html`, lines 474-486
New arenas, arena credential status, and arena availability are not reflected dynamically. [frontend], [core]

### FP-11 -- Several implemented arenas are missing from the UI arena grid
File: `src/issue_observatory/api/templates/query_designs/editor.html`, lines 474-486
Event Registry, X/Twitter, Threads, Common Crawl, Majestic, Wayback Machine, Facebook, Instagram are implemented but not listed in the arena configuration grid. [frontend]

### FP-13 -- No tooltip or description for each arena in the configuration grid
File: `src/issue_observatory/api/templates/query_designs/editor.html`, lines 363-425
A researcher who does not know what GDELT or Ritzau Infostream is cannot make an informed decision about enabling them. [frontend]

### FP-14 -- No success confirmation after saving arena configuration
File: `src/issue_observatory/api/templates/query_designs/editor.html`, lines 437-452
The save uses `hx-swap="none"` so no visible feedback occurs on success. [frontend]

### FP-15 -- Query design detail page does not show arena configuration
File: `src/issue_observatory/api/templates/query_designs/detail.html`
The researcher cannot see which arenas and tiers are configured without entering the edit view. [frontend]

### FP-16 -- "Celery Beat" mentioned in live mode description
File: `src/issue_observatory/api/templates/collections/launcher.html`, line 112
Developer terminology in a user-facing label. [frontend]

### FP-17 -- No guidance on practical date range limits per arena
File: `src/issue_observatory/api/templates/collections/launcher.html`, lines 117-140
The researcher does not know that some arenas have no historical archive capability. [frontend], [research]

### FP-18 -- Tier precedence between query design and launcher is ambiguous
File: `src/issue_observatory/api/templates/collections/launcher.html` vs `query_designs/editor.html`
Per-arena tier settings in the query design vs. global tier in the launcher -- unclear which wins. [frontend], [core]

### FP-19 -- Collection detail page does not show search terms used
File: `src/issue_observatory/api/templates/collections/detail.html`
The researcher returning later cannot see what was collected without navigating elsewhere. [frontend]

### FP-20 -- Collection detail header shows UUID instead of query design name
File: `src/issue_observatory/api/templates/collections/detail.html`, lines 40-42
The run UUID is developer-facing; the query design name would be more meaningful. [frontend]

### FP-21 -- Arena column hidden below xl breakpoint (1280px)
File: `src/issue_observatory/api/templates/content/browser.html`, line 245
On standard laptop displays, the researcher cannot see which arena a record came from. [frontend]

### FP-22 -- Engagement score is unexplained and not comparable cross-platform
File: `src/issue_observatory/api/templates/content/browser.html`, line 246
No tooltip or explanation of what the composite engagement score represents. [frontend], [research]

### FP-23 -- "Search" and "Search Term" filters have confusingly similar names
File: `src/issue_observatory/api/templates/content/browser.html`, lines 46-55 and 126-134
Full-text search and matched-term filter look similar but do different things. [frontend]

### FP-25 -- Timestamps in record detail are ISO format without timezone context
File: `src/issue_observatory/api/templates/content/record_detail.html`, lines 109-119
No timezone information is visible to the researcher. [frontend]

### FP-27 -- Snowball sampling panel is collapsed and at page bottom -- low discoverability
File: `src/issue_observatory/api/templates/actors/list.html`, lines 245-550
A researcher must scroll past the actor table and notice the collapsed panel. [frontend]

### FP-30 -- Analysis dashboard charts have no axis labels
File: `src/issue_observatory/api/templates/analysis/index.html`, lines 207-276
Charts are unsuitable for publication without external annotation. [frontend]

### FP-31 -- Analysis filter bar uses free-text inputs for platform and arena
File: `src/issue_observatory/api/templates/analysis/index.html`, lines 133-150
Text inputs instead of dropdowns create case-sensitivity and discoverability issues. [frontend]

### FP-33 -- Export column headers use internal snake_case names
File: `src/issue_observatory/analysis/export.py`, lines 42-58
`text_content`, `views_count`, `search_terms_matched` are not human-readable. [data]

### FP-34 -- JSON export is NDJSON but labelled "JSON"
File: `src/issue_observatory/api/templates/analysis/index.html`, line 436
Misleading format label. [frontend], [data]

---

## Blockers

### B-01 -- Arena configuration grid is missing 8 implemented arenas

**Files:** `src/issue_observatory/api/templates/query_designs/editor.html`, lines 474-486; `src/issue_observatory/arenas/` directory

**Observation:** The hardcoded arena list in the editor template contains 11 arenas. The `src/issue_observatory/arenas/` directory contains implementations for at least 19 arenas (google_search, google_autocomplete, bluesky, reddit, youtube, rss_feeds, gdelt, telegram, tiktok, ritzau_via, gab, event_registry, x_twitter, threads, web/common_crawl, and more). A researcher who wants to include Event Registry (a major Danish news source) or X/Twitter in their CO2 Afgift study cannot enable these arenas through the UI.

**Research impact:** The researcher's multi-platform analysis is limited to 11 arenas when the system supports nearly 19. Eight arena implementations are unreachable through the normal research workflow. [frontend], [core]

### B-02 -- Admin credential form still missing platforms

**File:** `src/issue_observatory/api/templates/admin/credentials.html`, lines 74-89

**Observation:** The platform dropdown in the Add Credentials modal lists 11 platforms: YouTube, Telegram, TikTok, Serper.dev, TwitterAPI.io, Bluesky, Reddit, Event Registry, Majestic, GDELT, RSS Feeds. Missing: Gab, Threads, Facebook (Bright Data), Instagram (Bright Data), SerpAPI. While Gab appears in the arena grid (so a researcher would expect to use it), they cannot configure credentials for it through the UI.

**Research impact:** Researchers wanting Gab, Threads, Facebook, or Instagram data cannot set up credentials without CLI access. This persists from Phase 3 (blocker B-04). [frontend]

---

## Data Quality Findings

### DQ-01 -- RSS feed coverage for CO2 Afgift: Jyllands-Posten uncertainty persists

**Source:** `src/issue_observatory/config/danish_defaults.py`, lines 99-103

**Observation:** The code comment notes: "JP's RSS availability is uncertain as of 2026 (shifting to app-first delivery). This URL may return 404." Jyllands-Posten is one of Denmark's three largest broadsheet newspapers and has published extensive coverage of CO2 afgift. If the RSS feed returns 404, the researcher's dataset will silently exclude JP coverage without warning. The documentation has not been updated with this caveat (confirmed in Phase 3 report DQ-05, still open).

**Research impact for CO2 Afgift:** A researcher claiming comprehensive Danish newspaper coverage of CO2 afgift would be missing one of the three major broadsheets. This affects the validity of any content analysis conclusions about media framing.

### DQ-02 -- Danish Google Search locale parameters are correctly applied

**Source:** `src/issue_observatory/config/danish_defaults.py`, lines 157-166

**Observation (positive):** The `gl=dk` and `hl=da` parameters ensure Google Search results reflect the Danish media landscape. For a search like "CO2 afgift," this means the results will prioritize Danish-language pages from Danish domains, which is correct for this research scenario.

### DQ-03 -- GDELT dual-query deduplication remains opaque

**Source:** `src/issue_observatory/config/danish_defaults.py`, lines 172-183

**Observation:** GDELT uses two filters: `sourcelang=danish` and `sourcecountry=DA`. These are run as separate queries and deduplicated by URL. For the CO2 Afgift study, a Danish newspaper article about CO2 afgift would match both queries and should be deduplicated to a single record. However, the researcher has no visibility into whether deduplication is working or how many duplicates were removed.

**Research impact:** If deduplication fails or is incomplete, GDELT record counts for CO2 afgift topics will be inflated relative to other arenas, distorting cross-platform volume comparisons.

### DQ-04 -- Reddit subreddit scope is limited to 4 for CO2 Afgift discourse

**Source:** `src/issue_observatory/config/danish_defaults.py`, lines 140-151

**Observation:** Only r/Denmark, r/danish, r/copenhagen, and r/aarhus are monitored. For CO2 afgift discourse, r/dkfinance (Danish finance) would be relevant because carbon tax discussions frequently involve economic impact arguments. This subreddit is not in the default list. The researcher cannot add subreddits through the UI (the arena configuration grid does not expose subreddit selection).

**Research impact:** Reddit coverage of CO2 afgift will miss economically-focused discussions in r/dkfinance.

### DQ-05 -- Term co-occurrence network for CO2 Afgift would be methodologically sound

**Source:** `src/issue_observatory/analysis/export.py`, lines 497-567

**Observation (positive):** The `_build_term_gexf()` implementation correctly builds term co-occurrence from the `search_terms_matched` array. For the CO2 Afgift study with 7 search terms, the resulting network would show which terms frequently co-appear in the same records. For example, records matching both "CO2 afgift" and "landbruget" would create an edge between these terms. The implementation uses correct pair enumeration (sorted, deduplicated per record) and the edge weight correctly counts distinct records where both terms co-occur.

### DQ-06 -- Bluesky actor-based collection language filter status

**Source:** Phase 3 report confirms client-side `lang:da` filter was added to `collect_by_actors()`.

**Observation:** For the CO2 Afgift study, if the researcher tracks Danish politicians on Bluesky via actor-based collection, posts not tagged as Danish will now be filtered out client-side. Posts with no language tag will be included (conservative behavior). This is acceptable for research purposes as long as the researcher notes this limitation in their methods section.

---

## Recommendations

### Priority 1 -- Critical for the CO2 Afgift use case

**R-01** [frontend] [core] -- Dynamically populate the arena configuration grid from the server's arena registry instead of a hardcoded JavaScript array. This should fetch arena availability, credential status, and supported tiers from a backend endpoint. The 8 missing arenas become immediately accessible.

**R-02** [frontend] -- Add arena descriptions (tooltips or inline help text) to the arena configuration grid. Each arena should have a one-line description: "GDELT: International news coverage from 65+ languages, filtered to Danish sources" or "Ritzau Infostream: Danish press releases from organizations and political parties (free, no credentials needed)."

**R-03** [frontend] -- Disable or visually distinguish tier options that are not supported for each arena. If Bluesky only supports "free," the "medium" and "premium" radio buttons should be greyed out with a tooltip "This arena only supports the Free tier."

**R-04** [frontend] -- Show the arena configuration on the query design detail page (read-only view). The researcher should be able to see their complete "methods section" -- search terms, actors, and arena configuration -- from a single page.

### Priority 2 -- High: improves research workflow

**R-05** [frontend] -- Add help text below the term type dropdown explaining each type: "Keyword: matches any word. Phrase: matches the exact phrase (wrapped in quotes on supported arenas). Hashtag: prepends # automatically. URL pattern: matches content linking to this URL pattern."

**R-06** [frontend] -- Replace the analysis dashboard's free-text "Platform" and "Arena" filter inputs with dropdown selectors populated from the run's actual data. A researcher should select from options that exist rather than guess text values.

**R-07** [frontend] -- Add axis labels to all analysis dashboard charts. At minimum: y-axis = "Number of records" for the volume chart; x-axis = "Record count" for actor and term charts.

**R-08** [frontend] -- Update the dashboard's "About this platform" text and the System Status page's system information to reflect the actual feature maturity and arena count.

**R-09** [frontend] -- Change the live mode description from "Start ongoing daily collection (Celery Beat)" to "Start ongoing daily collection. Runs automatically every day at midnight Copenhagen time."

**R-10** [frontend] -- Add the query design name prominently to the collection detail page header, alongside (not instead of) the run ID.

### Priority 3 -- Medium: general improvements

**R-11** [data] -- Replace snake_case export column headers with human-readable names: `text_content` to "Text Content," `views_count` to "View Count," `search_terms_matched` to "Matched Search Terms."

**R-12** [frontend] -- Relabel "JSON" in the export format selector to "NDJSON (one record per line)."

**R-13** [frontend] -- Add a brief tooltip or inline preview capability to the GEXF network tabs, showing at minimum node count and edge count before the researcher downloads the file.

**R-14** [frontend] -- Improve the snowball sampling panel's discoverability by adding a mention or link to it in the Actor Directory's page-level description text, or by auto-expanding it when the page has actors.

**R-15** [frontend] -- Add Gab, Threads, Facebook (Bright Data), Instagram (Bright Data), and SerpAPI to the admin credentials platform dropdown.

**R-16** [frontend] -- Add a "per-arena date range" guidance tooltip in the collection launcher explaining that some arenas (RSS, Bluesky) are real-time only with no historical archive, while others (GDELT, Event Registry) support historical queries.

**R-17** [frontend] -- Display a success toast/flash message after saving arena configuration.

---

## Overall Assessment

### Can a Danish policy researcher map CO2 afgift discourse using this application?

**Partially, with significant workarounds.**

The core workflow -- design a query, add search terms, enable arenas, launch a collection, browse results, export data -- is functional and well-designed. The Danish locale configuration is thorough and correctly implemented. The content browser and record detail panel provide good research-level inspection capabilities.

The application excels at:
- Danish-specific defaults (RSS feeds, Google locale, Bluesky language filtering)
- Clean, consistent visual design using Tailwind CSS
- HTMX-powered interactions that avoid full page reloads
- Comprehensive export options (5 formats including GEXF for network analysis)
- The collection monitoring experience with SSE live updates
- The recently-added live tracking schedule with suspend/resume controls
- The recently-added snowball sampling UI
- The recently-fixed GEXF network exports (all three types now implemented correctly)

However, the researcher encounters these obstacles:
1. **8 arenas are invisible** in the UI despite being implemented -- including Event Registry and X/Twitter, which are important for Danish policy discourse
2. **Tier selection is misleading** -- arenas that only support free still show medium/premium options
3. **Arena descriptions are absent** -- a researcher unfamiliar with GDELT or Ritzau cannot make informed configuration decisions
4. **Cross-platform engagement comparability is unexplained** -- the researcher cannot meaningfully compare engagement scores across platforms
5. **Export column headers are developer-facing** -- sharing exported data with collaborators requires a separate data dictionary
6. **Analysis chart labels are missing** -- the charts are suitable for exploration but not for publication

### Severity Rating

| Dimension | Rating | Notes |
|-----------|--------|-------|
| Discoverability | Moderate | Core features are findable via the sidebar. Snowball sampling and some arenas require exploration. |
| Comprehensibility | Moderate | Labels are mostly clear but tier descriptions, term types, and engagement metrics lack explanation. |
| Completeness | Fair | The end-to-end workflow works for the 11 visible arenas. 8 additional arenas are blocked. |
| Data Trust | Moderate | Danish locale filtering is correct. Engagement comparability and deduplication transparency are weak points. |
| Recovery | Good | Error messages surface in the collection task table. Credential failure is handled. Live tracking can be suspended/resumed. |

### Comparison to Phase 3 Report

Three of the four Phase 3 blockers have been addressed:
- **B-01 (Snowball sampling no UI):** Fixed -- panel exists on Actor Directory page
- **B-02 (GEXF network types):** Fixed -- all three types implemented and correctly wired
- **B-03 (Live tracking schedule):** Fixed -- schedule panel with suspend/resume controls

One blocker persists from Phase 3:
- **B-04 (Admin credential form missing platforms):** Still open -- Gab, Threads, Facebook, Instagram, SerpAPI missing

New blockers identified in this report:
- **B-01 (Arena grid missing 8 arenas):** A broader issue than the credential form -- the entire arena configuration interface is incomplete

### Readiness for the CO2 Afgift Research Task

The application is **ready for pilot-stage research** on CO2 afgift with the following caveats:

1. The researcher should limit their study to the 11 arenas visible in the UI
2. They should set all arenas to "Free" tier to avoid misleading tier configuration
3. They should note in their methods section that Jyllands-Posten RSS coverage may be absent
4. They should not compare engagement scores across platforms without qualifying the metric
5. They should rename export column headers manually before sharing data
6. They should use the GEXF term co-occurrence export (now correctly implemented) for network analysis

The application is **not yet ready for publication-quality multi-platform discourse analysis** until the arena grid is dynamically populated, tier validation is added, chart labels are implemented, and export headers are human-readable.
