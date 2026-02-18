# UX Test Report -- Issue Mapping of "AI og uddannelse" (AI and Education in Denmark)

Date: 2026-02-18
Scenario: Noortje Marres-style issue mapping of the Danish controversy around AI in education
Arenas examined: google_search, google_autocomplete, bluesky, reddit, youtube, rss_feeds, gdelt, telegram, tiktok, ritzau_via, gab (visible in UI); event_registry, x_twitter, ai_chat_search (implemented but not UI-accessible)
Tiers examined: free, medium
Evaluation method: Code-based static analysis of all templates, source files, configuration, and data flow -- simulating every step a Danish STS/communication researcher would take through the application to produce a Noortje Marres-style issue map

---

## Research Scenario and Methodology

### What is Noortje Marres-Style Issue Mapping?

Noortje Marres' approach to issue mapping -- rooted in Science and Technology Studies (STS) and Actor-Network Theory (ANT) -- treats public issues as objects that are constituted by the actors who engage with them, the associations those actors forge between topics, and the networks that form across platforms and arenas. The methodology is explicitly NOT policy analysis. It does not evaluate whether AI in education is "good" or "bad." Instead, it asks:

- **Who participates in this issue?** Which actors speak, are mentioned, are cited, or are conspicuously absent?
- **What discourse associations are formed?** When actors discuss "AI og uddannelse," what other issues do they connect it to -- eksamen (exams), snyd (cheating), kompetencer (competencies), fremtidens arbejdsmarked (future labor market), digital dannelse (digital literacy), demokrati (democracy)?
- **How do issue networks form?** Do university actors connect AI og uddannelse to research and innovation, while teachers' unions connect it to workload and professional autonomy? Do these networks overlap or remain separate?
- **Where are the controversies?** Who disagrees with whom? Is ChatGPT-in-eksamen a point of consensus or contention? Do institutional actors and grassroots voices align?

The goal is to produce an issue MAP -- a visual and analytical representation of the controversy's contours, participants, and discursive structure.

### Research Question

How is the issue of "AI og uddannelse" (AI and education) constituted in Danish public discourse across digital media arenas in early 2026? Who are the key actors and what discourse associations do they forge around this issue? Where are the points of controversy, and how do issue networks differ across platforms?

### Why This Issue is a Strong Test for Issue Mapping

"AI og uddannelse" differs from the CO2 afgift scenario in several ways that test the application specifically for Marres-style issue mapping:

1. **Rapidly evolving terminology**: Unlike "CO2 afgift" (a stable policy term), AI-in-education discourse uses a shifting vocabulary -- ChatGPT, generativ AI, kunstig intelligens, AI-detektion, maskinlaering -- that requires creative, expansive search term design.
2. **Diverse actor landscape**: The issue involves universities (KU, AU, DTU, CBS), teachers' unions (DLF, GL), ministries (Uddannelses- og Forskningsministeriet, Borneog Undervisningsministeriet), tech companies (OpenAI, Microsoft), students (DSF, Danske Gymnasieelever), school principals, private tutoring companies, and individual educators with public profiles.
3. **Discourse association richness**: The same actor may frame "AI og uddannelse" as a cheating problem, a pedagogical opportunity, a labor market issue, a digital literacy imperative, or a democratic concern. The researcher needs to track these shifting associations.
4. **Cross-platform variation**: A university rector's formal press release via Ritzau will use different framing than the same university's communications office on Bluesky, which will differ again from student discussions on Reddit.
5. **Actor discovery imperative**: Unlike CO2 afgift where key actors are well-known political figures, AI-in-education involves many actors who may not be known in advance -- individual teachers who went viral, edtech startups, international commentators. Snowball sampling is genuinely needed.
6. **Network analysis centrality**: Marres-style mapping fundamentally requires network visualization. The term co-occurrence network reveals discourse associations; the actor co-occurrence network reveals issue alliances; the bipartite network reveals which actors are associated with which discursive frames. All three GEXF network types are essential.

---

## Query Design Specification: "AI og uddannelse DK 2026"

### Search Term Strategy

For Marres-style issue mapping, search terms must be designed not just to capture "the topic" but to capture the controversy in all its dimensions. The terms below are organized by function in the issue mapping workflow.

#### Primary Issue Terms (what the issue IS called)

| Term | Type | Rationale |
|------|------|-----------|
| "AI og uddannelse" | Phrase | The canonical Danish framing of the issue |
| "AI i undervisningen" | Phrase | Alternative phrasing used by practitioners |
| kunstig intelligens uddannelse | Keyword | Formal/institutional language variant |
| ChatGPT skole | Keyword | Colloquial association -- ChatGPT as synecdoche for all AI |
| generativ AI undervisning | Keyword | Technical terminology used in policy documents |

#### Actor Discovery Terms (who speaks about the issue)

| Term | Type | Rationale |
|------|------|-----------|
| "digital dannelse" | Phrase | Key discourse frame used by educational institutions and the ministry |
| "AI-kompetencer" | Phrase | Industry-adjacent framing -- links education to labor market |
| #LaeringOgAI | Hashtag | Social media-specific; tests whether practitioners use Danish hashtags |
| #AIiskolen | Hashtag | Colloquial hashtag variant |

#### Discourse Association Terms (what other issues get connected)

| Term | Type | Rationale |
|------|------|-----------|
| "AI eksamen snyd" | Phrase | The cheating controversy -- a key contested point |
| AI detektion plagiat | Keyword | Counter-frame: technological detection as solution |
| "fremtidens kompetencer" | Phrase | Labor market discourse association |
| AI laererens rolle | Keyword | Professional identity discourse -- how AI changes the teacher |

#### English Variants (international coverage)

| Term | Type | Rationale |
|------|------|-----------|
| "AI in education" Denmark | Phrase | Captures English-language reporting on Danish context |
| ChatGPT university cheating | Keyword | International controversy frame |

**Total: 15 search terms.** This is significantly more than the 7 used in the CO2 afgift scenario, reflecting the explorative nature of issue mapping. The researcher needs a wide net to discover the contours of the controversy.

### Actor List for Query Design

For Marres-style issue mapping, the initial actor list should include actors from diverse institutional positions -- not just politicians. The actor type taxonomy (Person, Organisation, Media outlet, Account) needs to capture:

| Actor | Type | Rationale |
|-------|------|-----------|
| Christina Krzyrosiak Hansen | Person | Minister for Education (uddannelsesministeren) as of early 2026 |
| Uddannelses- og Forskningsministeriet | Organisation | Ministry responsible for higher education and AI strategy |
| Danmarks Laererforening (DLF) | Organisation | Teachers' union -- primary institutional voice on AI in schools |
| Gymnasieskolernes Laererforening (GL) | Organisation | Upper secondary teachers' union -- affected by AI eksamen |
| Danske Universiteter | Organisation | University rectors' conference -- institutional higher education voice |
| Danske Gymnasieelevers Sammenslutning | Organisation | Student organization -- youth perspective |
| IT-Universitetet i Kobenhavn | Organisation | ITU -- has published AI education policy documents |
| Microsoft Danmark | Organisation | Major AI provider to Danish education sector (Microsoft 365, Copilot) |

**8 actors across 4 institutional positions**: government, unions, educational institutions, and industry. This gives the snowball sampler meaningful seed actors from diverse network positions.

---

## Step-by-Step Walkthrough

### Step 1: First Contact -- Dashboard Orientation

**Researcher action:** A researcher who studies Danish digital publics and has read Marres' "Digital Sociology" opens the Issue Observatory for the first time, lands on the dashboard.

**What the researcher sees:** The dashboard shows "Welcome, [name]" with three summary cards (Credits, Active Collections, Records Collected) and a Quick Actions panel with links to Create new query design, Start new collection, Browse content, Analyse data. An "About this platform" box reads: "Issue Observatory collects and analyses public discourse across digital media arenas with a focus on the Danish context." Below that: "Phase 0 -- Google Search arena active."

**Assessment for issue mapping:**

The sidebar navigation (Dashboard, Query Designs, Collections, Content, Actors, Analysis) maps loosely to a Marres workflow, but the terminology is oriented toward data collection rather than issue mapping. A researcher trained in Marres' methodology would think in terms of "issue" (not "query design"), "actors" (good -- the terminology aligns), "discourse" (not "content"), and "networks" (not "analysis"). The mapping from research concepts to application concepts requires translation, but the sidebar labels are neutral enough not to be misleading.

**Finding IM-01:** The "Phase 0 -- Google Search arena active" footer text on the dashboard (`src/issue_observatory/api/templates/dashboard/index.html`, line 160) is factually wrong. This finding persists from the CO2 afgift report (FP-01). For an issue mapping researcher who needs multi-platform data, this text creates immediate doubt about whether the tool can support their methodology. [frontend]

**Finding IM-02:** The Quick Actions panel does not mention the Actor Directory or the Analysis/Network features. A Marres researcher arriving at the dashboard would look for "Map an issue" or "Explore actor networks" and instead see generic collection-oriented actions. The Quick Actions are functional but not oriented toward the issue mapping workflow. [frontend]

---

### Step 2: Query Design -- "AI og uddannelse DK 2026"

**Researcher action:** Create a new query design with name "AI og uddannelse DK 2026", description "Noortje Marres-style issue mapping of the AI-in-education controversy in Danish public discourse, January-February 2026. Tracking actors, discourse associations, and issue networks across platforms.", visibility Private, default tier Free, language Danish (da).

**Assessment for issue mapping:**

The query design editor is clean and the fields make sense. However, two issue-mapping-specific concerns arise.

**Finding IM-03:** The description field is a free-text area with no structure for research methodology documentation. A Marres researcher would want to record their methodological approach (issue mapping vs. content analysis vs. framing analysis) as structured metadata, not just free text. When the researcher later exports data or shares the query design with a collaborator, there is no way to see at a glance that this design follows a Marres methodology. This is a design problem, not a bug -- the field works but does not serve the research documentation need. [research]

**Finding IM-04:** The language dropdown offers only Danish (da), English (en), and German (de). For issue mapping, the researcher may want to track the same issue in both Danish and English simultaneously -- for example, to compare how Danish universities frame AI-in-education in their Danish press releases versus their English-language international communications. The current design forces a single language choice that applies to all arenas, with no option for "Danish + English" or "multilingual." This limits the cross-language dimension of issue mapping. [frontend], [core]

---

### Step 3: Adding Search Terms -- The Issue Mapping Vocabulary

**Researcher action:** Add the 15 search terms specified in the query design above.

**Assessment for issue mapping:**

The term-adding interaction works smoothly. After each addition, the cursor refocuses on the input field, allowing rapid entry of many terms. For the 15-term set needed for issue mapping, this is noticeably better than a form that requires a full page reload per term.

However, several issue-mapping-specific problems arise:

**Finding IM-05 (extends CO2 report FP-04):** The term type dropdown (Keyword, Phrase, Hashtag, URL pattern) offers no explanation. This is more consequential for issue mapping than for policy tracking because the researcher's term strategy is more nuanced. For example: should "AI eksamen snyd" be entered as a Keyword (matching any of the three words) or a Phrase (matching the exact sequence)? For issue mapping, the researcher typically wants the phrase match -- they are tracking a specific discourse association, not isolated keywords. But nothing in the UI tells them which behavior to expect. A researcher who enters "AI eksamen snyd" as Keyword when they meant Phrase will get a much broader (and noisier) result set, diluting the discourse association signal. [frontend]

**Finding IM-06:** There is no way to group or categorize search terms within a query design. The 15 terms for the AI-og-uddannelse issue mapping serve four distinct functions: primary issue terms, actor discovery terms, discourse association terms, and English variants. In the query design editor, they appear as a flat list with no visual grouping. In the analysis dashboard, the "Top terms" chart and the term co-occurrence network treat all 15 terms equally. A researcher doing Marres-style mapping would want to distinguish "which terms define the issue core" from "which terms capture discourse associations." The current flat list loses this structure. [frontend], [research]

**Finding IM-07:** The term count label shows "15 termer" -- using the Danish plural suffix in an otherwise English interface. This inconsistency persists from the CO2 afgift report (FP-05). For an international STS researcher who reads Danish but works in English-language academia, the mixed language is mildly confusing. [frontend]

---

### Step 4: Adding Actors -- Building the Initial Issue Map Seed

**Researcher action:** Add the 8 actors specified above, using the actor type categories Person and Organisation.

**Assessment for issue mapping:**

The actor list panel functions well for data entry. The type badges (Person in blue, Org in purple) provide immediate visual distinction, which is valuable for issue mapping where the researcher needs to see at a glance whether their actor list covers diverse institutional positions.

**Finding IM-08 (confirms CO2 report FP-07):** The query design actor list captures only a name and a type, with no connection to platform-specific identifiers. This is a critical gap for issue mapping because Marres' method requires tracking the SAME actor across DIFFERENT platforms. The researcher adds "Danmarks Laererforening (DLF)" as an Organisation, but the system has no way to know that DLF is @LFdk on Bluesky, u/DLFdk on Reddit, or has a specific YouTube channel. Without platform identifiers, the actor list is a research notebook entry, not a functional cross-platform tracking configuration. [frontend], [core]

**Finding IM-09:** The actor type taxonomy (Person, Organisation, Media outlet, Account) is adequate but missing categories that matter for issue mapping. Marres distinguishes between "spokespersons" (who represent institutions), "concerned groups" (grassroots actors), and "experts" (who provide legitimacy). The current four-type taxonomy conflates these. A university rector speaking on behalf of Danske Universiteter is an "Organisation" in the current system but a "spokesperson" in Marres' framework. This is a minor taxonomic limitation, not a blocker -- the researcher can use the description field on the actor detail page to record the Marres category. [research]

---

### Step 5: Arena Configuration for Issue Mapping

**Researcher action:** Enable arenas strategically for issue mapping at free and medium tiers.

For Marres-style issue mapping, arena selection is a methodological choice -- each arena captures a different facet of the issue public:

| Arena | Tier | Issue Mapping Function |
|-------|------|----------------------|
| Google Search | Free | Public salience -- what appears when people search for the issue |
| Google Autocomplete | Free | Public associations -- what search suggestions cluster around the issue |
| Bluesky | Free | Elite discourse -- Danish educators, politicians, and journalists |
| Reddit | Free | Vernacular discourse -- anonymous discussion, student perspectives |
| YouTube | Free | Media discourse -- educational content, debates, commentary |
| RSS Feeds | Free | Legacy media framing -- newspaper coverage of AI-in-education |
| GDELT | Free | International media -- how the Danish AI education issue is covered abroad |
| Ritzau Infostream | Free | Institutional voice -- press releases from universities, unions, ministry |

Disable: Telegram (minimal Danish education discourse), TikTok (limited text-based content for discourse analysis), Gab (negligible Danish presence).

**Assessment for issue mapping:**

**Finding IM-10 (confirms CO2 report FP-09):** All 11 visible arenas display free/medium/premium tier radio buttons regardless of actual support. Bluesky, RSS Feeds, GDELT, Reddit, Ritzau, Gab, and TikTok only support the free tier. The researcher selecting "medium" for Bluesky sees no warning. For issue mapping, this is a methodological transparency problem: the researcher will document their tier selections in their methods section, and if they write "Bluesky data was collected at medium tier" when in fact the system silently fell back to free, their published methodology is inaccurate. [frontend]

**Finding IM-11 (confirms CO2 report FP-11):** The AI Chat Search arena -- which is explicitly designed for studying how AI mediates information about Danish issues -- is implemented in the codebase but invisible in the arena configuration grid. For an issue mapping study of "AI og uddannelse," this arena would be uniquely valuable: it would reveal how AI chatbots themselves frame and source information about AI in education, creating a meta-level of analysis. The arena is absent from the hardcoded JavaScript arena list (`src/issue_observatory/api/templates/query_designs/editor.html`, lines 474-486). Similarly, Event Registry and X/Twitter are implemented but inaccessible. [frontend], [core]

**Finding IM-12:** The AI Chat Search arena only operates at medium and premium tiers (no free tier). This means the researcher cannot include AI chatbot framing analysis without switching to at least medium tier for that arena. The tier constraint of this test (free and medium only) makes medium tier the minimum viable option for AI Chat Search. However, since the arena is not visible in the UI (IM-11), this is moot until the arena grid is dynamically populated. [research]

**Finding IM-13 (confirms CO2 report FP-13):** No arena descriptions are provided. A Marres researcher who is not familiar with GDELT needs to know that it captures international news coverage, not domestic Danish media. A researcher unfamiliar with Ritzau needs to know it captures press releases (organizational voice), not journalism (media voice). This distinction is methodologically critical for issue mapping: press releases reveal how organizations choose to frame the issue, while journalism reveals how media re-frame it. Without arena descriptions, the researcher cannot make informed methodological choices. [frontend]

**Finding IM-14:** Google Autocomplete is potentially one of the most valuable arenas for Marres-style issue mapping because it reveals the "suggested publics" -- what the search engine associates with the issue. When a user types "AI og uddannelse," Google Autocomplete suggests completions that reflect aggregate search behavior, which Marres interprets as a form of "issue indexing." However, the arena grid provides no indication that Google Autocomplete captures fundamentally different data (search suggestions) than Google Search (search results). A researcher might assume they are redundant and disable one, losing a crucial data source. [frontend], [research]

---

### Step 6: Launching and Monitoring the Collection

**Researcher action:** Save the arena configuration, navigate to the query design detail page, click "Run collection," select Batch mode with date range 2026-01-01 to 2026-02-18, tier Free.

**Assessment for issue mapping:**

The collection launcher works as expected. The credit estimate panel on the right provides useful pre-flight information. However:

**Finding IM-15 (confirms CO2 report FP-15):** The query design detail page does not display the arena configuration. Before launching a collection, the researcher cannot see a complete "methods section" view -- search terms, actors, AND arenas -- on a single page. They must click Edit and scroll to the arena grid. For Marres-style research, the complete configuration is the "research instrument" and should be reviewable at a glance, equivalent to a survey instrument in quantitative research. [frontend]

**Finding IM-16 (confirms CO2 report FP-17):** No guidance on practical date range limits per arena. RSS feeds have no historical archive; GDELT goes back years. For issue mapping, the researcher needs to know that their "January-February 2026" date range will yield very different coverage across arenas. RSS will capture only what was in the feed at the moment of collection (recent articles only), while GDELT will capture the full two-month window. This creates a temporal comparability issue that the researcher should be warned about. [frontend], [research]

**Finding IM-17 (confirms CO2 report FP-16):** The Live mode description reads "Start ongoing daily collection (Celery Beat)." "Celery Beat" is developer jargon. For an issue mapping researcher who might want to track the issue over weeks or months (standard practice in Marres-style longitudinal issue mapping), the live mode description should communicate the research value: "Start ongoing daily collection. New content is collected automatically every day at midnight Copenhagen time, building a longitudinal dataset of the issue's evolution." [frontend]

---

### Step 7: Browsing Collected Content for Issue Mapping

**Researcher action:** After collection completes, navigate to the Content Browser to begin qualitative exploration of the issue.

**Assessment for issue mapping:**

The content browser is the primary workspace for qualitative issue mapping. The researcher will spend significant time here, scanning records to identify actors, note discourse associations, and spot controversy patterns. The split-view layout (table on left, detail panel on right) is well-suited to this workflow.

**Finding IM-18 (confirms CO2 report FP-21):** The Arena column is hidden below the xl breakpoint (1280px). For issue mapping, knowing which arena a record came from is not supplementary information -- it is a primary analytical dimension. A Marres researcher reads content differently depending on whether it is a Ritzau press release (organizational framing), a Bluesky post (elite discourse), or a Reddit comment (vernacular discourse). Hiding this column on standard laptop screens forces the researcher to click into every record's detail panel to see the arena, severely slowing the qualitative scanning workflow. [frontend]

**Finding IM-19:** The content browser's sidebar filters include arena checkboxes, which is excellent for issue mapping. The researcher can quickly filter to "RSS Feeds only" to scan how legacy media frames the issue, then switch to "Bluesky only" to scan elite discourse. However, the arena checkboxes are hardcoded in the template (11 arenas, lines 61-73 of `browser.html`), so newly implemented arenas will not appear as filter options. [frontend]

**Finding IM-20:** The "Search Term" filter in the content browser sidebar is labeled "Matched term..." with a note "Filter by matched search term." This is actually one of the most powerful features for issue mapping: the researcher can filter to records matching only "AI eksamen snyd" (the cheating frame) and see which actors appear in that subset, then filter to "fremtidens kompetencer" (the labor market frame) and compare actor overlap. However, the filter is a free-text input rather than a dropdown populated from the query design's actual terms. The researcher must remember and type their exact terms. A dropdown would make this filtering workflow much faster. [frontend]

**Finding IM-21 (confirms CO2 report FP-22):** The engagement score is unexplained and not comparable across platforms. For issue mapping, engagement comparability matters less than for policy analysis -- Marres is interested in who speaks, not how popular their speech is. However, the engagement column still takes up screen space and may mislead the researcher into drawing quantitative conclusions about "salience" that the data does not support. A tooltip explaining "Engagement: composite score not comparable across platforms -- use for within-platform ranking only" would prevent methodological errors. [frontend], [research]

---

### Step 8: Record Detail Panel -- Reading for Issue Mapping

**Researcher action:** Click on individual records to read the full text and identify actors, discourse associations, and controversy signals.

**Assessment for issue mapping:**

The record detail panel is well-designed for close reading. The "Matched search terms" badges are displayed prominently, allowing the researcher to immediately see which of their 15 search terms this record triggered. For issue mapping, this is the key analytical signal: a record matching both "AI og uddannelse" (primary issue term) and "AI eksamen snyd" (discourse association term) reveals that this actor connects the issue to the cheating frame.

**Passed -- IM-P01:** The matched search terms display in the record detail panel is exactly what a Marres researcher needs. The styled badges make discourse associations immediately visible during qualitative reading. The researcher can see at a glance: "This record connects AI-in-education to cheating AND to digital literacy" -- a discourse association pattern.

**Passed -- IM-P02:** The "View original" link to the source URL enables verification against the original text, which is essential for any publication-quality qualitative research. The researcher can confirm that the Issue Observatory's extracted text accurately represents the original content.

**Passed -- IM-P03:** The "Find actor" link pre-fills the actor search with the author's name, bridging the content browser to the actor directory. This supports the Marres workflow of moving from "I found an interesting statement" to "Who is this actor and where else do they appear?"

**Finding IM-22 (confirms CO2 report FP-25):** Timestamps are displayed in ISO 8601 format without timezone information. For issue mapping across platforms, the researcher needs to know whether events are sequenced correctly. A Ritzau press release timestamped 14:00 and a Bluesky post timestamped 14:30 -- are they in the same timezone? This matters for controversy mapping where the researcher needs to reconstruct the sequence of claims and counter-claims. [frontend]

**Finding IM-23:** The record detail panel does not display which other search terms co-occurred with this record in the broader dataset. It shows which terms THIS record matched, but not which other records share the same term matches. For Marres-style mapping, the researcher would benefit from a "Related records" section that shows: "23 other records also matched 'AI eksamen snyd' + 'digital dannelse' -- view them." This would surface discourse association clusters without requiring the researcher to manually cross-filter. [frontend], [research]

---

### Step 9: Actor Directory and Snowball Sampling for Issue Discovery

**Researcher action:** Navigate to the Actor Directory. The 8 actors added in the query design should appear here (if they are linked to the actor directory). Add platform presences for key actors. Run snowball sampling to discover additional actors in the AI-og-uddannelse network.

**Assessment for issue mapping:**

The Actor Directory page is functional but its relationship to the query design's actor list is unclear.

**Finding IM-24 (confirms CO2 report FP-07):** The actors added in the query design editor (Step 4) are stored as query-design-level actor list members. They are NOT automatically created as entries in the Actor Directory. The researcher who added "Danmarks Laererforening (DLF)" to the query design actor list, then navigates to the Actor Directory, expects to see DLF there. If the directory is empty, the researcher experiences a discontinuity: "I already added my actors -- where are they?" The query design actor list and the Actor Directory are conceptually separate databases with no automatic synchronization. This is a significant workflow gap for issue mapping, where actors are the central analytical unit. [frontend], [core]

**Finding IM-25 (confirms CO2 report FP-27):** The Snowball Sampling panel is collapsed by default at the bottom of the Actor Directory page. For issue mapping, snowball sampling is not an optional advanced feature -- it is a core part of the methodology. Marres explicitly advocates for "following the actors" to discover the issue network. The sampling panel should be more prominent, ideally with a navigation link in the sidebar or a mention in the Actor Directory's page-level description. [frontend]

**Finding IM-26 (confirms CO2 report FP-28):** The Snowball Sampling panel requires seed actors to already exist in the Actor Directory. If the researcher has not manually created actors in the directory (only in the query design), the panel shows "No actors in this list yet. Add actors above first." This creates a three-step detour: (1) realize the query design actors are not in the directory, (2) manually re-add them in the directory via the Add Actor modal, (3) then add platform presences, (4) then use snowball sampling. For issue mapping, this is a workflow blocker that transforms a natural research action ("discover who else is talking about this") into an administrative chore. [frontend]

**Finding IM-27:** The Snowball Sampling panel's platform selection checkboxes load from `/actors/sampling/snowball/platforms`. The available platforms for sampling are limited to the platforms that support actor network traversal (likely Bluesky, Reddit, YouTube). For issue mapping, the researcher might want to discover actors across ALL arenas -- for example, finding which organizations file press releases about AI-in-education via Ritzau, or which news outlets cover the topic via RSS. The sampling is limited to social platforms with follow/reply network structures, missing institutional and media actors. [research]

**Finding IM-28:** The snowball sampling results table shows Name, Platforms, and Discovery depth (wave). For issue mapping, the researcher also needs to see WHY an actor was discovered -- what is the connection to the seed actor? "Discovered at depth 1 from Danmarks Laererforening" is more useful than just "depth 1." The current table does not expose the discovery path or the relationship type (replied to, was mentioned by, follows, is followed by). [frontend], [research]

---

### Step 10: Analysis Dashboard -- From Data to Issue Map

**Researcher action:** Navigate to the Analysis dashboard for the completed collection run. Examine charts, network tabs, and export options.

**Assessment for issue mapping:**

The Analysis dashboard has four chart panels (Volume over time, Top actors, Top terms, Engagement distribution) and four network tabs (Actor network, Term network, Bipartite, Cross-platform actors). For Marres-style issue mapping, the network tabs are the most important feature -- they directly produce the issue map.

**Passed -- IM-P04:** The Analysis dashboard provides all three network types that a Marres researcher needs: actor co-occurrence (who speaks about the same terms), term co-occurrence (which discourse frames cluster together), and bipartite actor-term (which actors are associated with which frames). The tab interface makes switching between these views straightforward.

**Passed -- IM-P05:** The bipartite network description text is excellent for issue mapping: "Bipartite actor-term graph -- links each pseudonymised author to the search terms their posts matched. Edge weight is the record count per pair." This is exactly the data structure that Marres' methodology requires: connecting actors to their discourse frames.

**Finding IM-29 (confirms CO2 report FP-30):** Charts have no axis labels. For issue mapping publications, the "Volume over time" chart would show how the issue's public presence fluctuates -- but without axis labels, the researcher cannot produce a publication-ready figure. The "Top actors" chart would show who dominates the discourse, but without labels it is an exploratory tool only. [frontend]

**Finding IM-30 (confirms CO2 report FP-31):** The filter bar uses free-text inputs for Platform and Arena instead of dropdown selectors. For issue mapping, the researcher would frequently filter to specific arenas to compare framing across platforms. Typing "bluesky" vs "Bluesky" vs "bsky" with no autocomplete creates unnecessary friction. [frontend]

**Finding IM-31 (confirms CO2 report FP-32):** No in-browser network visualization. The three network tabs each contain only a description and a GEXF download button. The researcher must download the file, open Gephi, and import it before they can see any network structure. For exploratory issue mapping -- where the researcher iterates between "look at the network, refine the query, look again" -- this export-then-visualize cycle is too slow. Even a simple force-directed graph preview (using a JavaScript library like d3-force or sigma.js) would dramatically accelerate the issue mapping workflow. [frontend]

**Finding IM-32:** The analysis dashboard's "Top actors" chart shows author_display_name for some bars and pseudonymized_author_id hashes for others. For issue mapping, the mix of readable names and hex hashes makes the chart difficult to interpret. The researcher sees "DR Nyheder" next to "a7b3f2e1" with no way to know who the hashed actor is. This is an inherent tension between GDPR compliance (pseudonymization) and research utility. The actor directory should provide a way to resolve these hashes for actors the researcher has manually identified, displaying the canonical name from the actor directory instead of the hash. [frontend], [core]

---

### Step 11: Network Analysis Deep Dive -- The Heart of Issue Mapping

**Researcher action:** Download all three GEXF network files to examine them as potential issue maps.

#### Actor Co-occurrence Network

The actor co-occurrence GEXF (`_build_actor_gexf` in `export.py`, lines 411-491) links two authors when they both have records matching at least one common search term. Edge weight is the number of distinct shared terms. The `shared_terms` edge attribute contains the pipe-separated list of overlapping terms.

**Assessment for issue mapping:** This network structure is methodologically appropriate for Marres-style issue mapping. It reveals issue alliances: if the university rector and the teachers' union both discuss "AI kompetencer" and "fremtidens kompetencer," they are connected by shared discourse. If a tech company and a student organization share no terms, they occupy separate issue spaces.

**Passed -- IM-P06:** The `shared_terms` edge attribute in the actor co-occurrence GEXF is invaluable for issue mapping. In Gephi, the researcher can color edges by shared terms to visualize which discourse associations connect different actors. This directly supports the Marres method of tracing "how actors forge associations between issues."

**Finding IM-33:** The actor co-occurrence network uses `pseudonymized_author_id` as node IDs. While `author_display_name` is used as the node label (which Gephi displays), the node ID in the GEXF XML is a hash. Some Gephi operations (filtering, layout algorithms, modularity detection) may surface the node ID rather than the label. The researcher may encounter hash strings in their Gephi workflow. Additionally, if two records have the same display name but different pseudonymized IDs (e.g., two different "Henrik" accounts on different platforms), they appear as separate nodes -- which is technically correct but may confuse the researcher who expects entity resolution. [data], [research]

#### Term Co-occurrence Network

The term co-occurrence GEXF (`_build_term_gexf` in `export.py`, lines 497-567) links two search terms when they appear together in the `search_terms_matched` array of the same content record. Edge weight is the number of records where both terms co-occur. Node attribute `frequency` is the total records containing that term.

**Assessment for issue mapping:** This is the discourse association map. For the 15-term AI-og-uddannelse query, this network would reveal which discourse frames cluster together. If "AI eksamen snyd" and "AI detektion plagiat" always co-occur (high edge weight), they form a coherent "cheating controversy" cluster. If "digital dannelse" and "fremtidens kompetencer" never co-occur, they are competing frames that different actors use to define the issue differently.

**Passed -- IM-P07:** The term co-occurrence network implementation is correct and well-suited to Marres-style discourse association analysis. The sorted pair enumeration and per-record deduplication ensure accurate co-occurrence counts. The `frequency` node attribute allows the researcher to distinguish between terms that are frequent overall and terms that are frequently paired.

**Finding IM-34:** The term co-occurrence network only includes terms from the query design's `search_terms_matched` array -- it does not discover NEW terms from the collected content. For issue mapping, the researcher would also want to see which WORDS (not just search terms) co-occur in the collected text. For example, the word "etik" (ethics) might frequently appear alongside "AI og uddannelse" in the collected content, even though "etik" was not one of the 15 search terms. A content-based term co-occurrence network (using NLP extraction from text_content, not just search_terms_matched) would be a powerful addition for issue mapping. This is a feature gap, not a bug. [research]

#### Bipartite Actor-Term Network

The bipartite GEXF (`_build_bipartite_gexf` in `export.py`, lines 573-647) links each author to each search term their posts matched. Edge weight is the record count per pair. Node attribute `type` is "actor" or "term" for Gephi partitioning.

**Assessment for issue mapping:** This is the most directly useful network for Marres-style mapping. It answers the question: "Which actors are associated with which discourse frames?" If the university rector is connected to "AI kompetencer" and "digital dannelse" but NOT to "AI eksamen snyd," while the students' union is connected to "AI eksamen snyd" and "fremtidens kompetencer," the bipartite network reveals how different actors frame the issue differently.

**Passed -- IM-P08:** The bipartite network uses a `term:` prefix for term node IDs to avoid collision with actor IDs. The `type` node attribute ("actor" or "term") enables Gephi's partition module to color nodes by type, creating a visual distinction between actors and discourse frames. This is exactly the visualization structure needed for Marres-style issue mapping.

**Finding IM-35:** The bipartite network does not include arena/platform information on actor nodes. In Gephi, the researcher cannot distinguish between actors who appear on Bluesky and actors who appear in RSS feeds without additional manual annotation. For cross-platform issue mapping, the platform attribute should be included on actor nodes (it is present in the actor co-occurrence network's node attributes but absent in the bipartite network's node attributes). [data]

---

### Step 12: Cross-Platform Actors -- Entity Resolution for Issue Mapping

**Researcher action:** Click on the "Cross-platform actors" tab in the Network Analysis section.

**Assessment for issue mapping:**

The cross-platform actors table shows actors resolved across multiple platforms via entity resolution. This is critical for issue mapping because the same institution (e.g., DR Nyheder) may be present as an RSS feed source, a Bluesky account, a YouTube channel, and a GDELT news source. The cross-platform view reveals which actors are active across the most arenas, indicating their centrality in the issue network.

**Finding IM-36:** The cross-platform actors table requires that `author_id` is non-null, meaning entity resolution must have been performed. The note reads: "No cross-platform actors found. Entity resolution may not have been performed for this collection run." For a first-time issue mapping researcher, this message is confusing. It implies that some additional step (entity resolution) is needed, but the application provides no UI for triggering or managing entity resolution. The researcher does not know whether entity resolution runs automatically, must be manually triggered, or requires developer intervention. This is a significant gap for cross-platform issue mapping. [frontend], [core]

---

### Step 13: Export for External Analysis

**Researcher action:** Export collected data for use in qualitative coding (NVivo/Atlas.ti), network visualization (Gephi), and quantitative analysis (R/Python).

**Assessment for issue mapping:**

The export panel offers five formats: CSV, XLSX, JSON (NDJSON), Parquet, and GEXF with network type selector. For issue mapping, the researcher needs:

1. **GEXF for Gephi** -- the primary output for network visualization. Covered by the three network types.
2. **CSV/XLSX for qualitative coding** -- to import into NVivo or Atlas.ti for close reading and coding of discourse frames.
3. **CSV for statistical analysis** -- to compute network metrics in R (igraph) or Python (networkx).

**Finding IM-37 (confirms CO2 report FP-33):** Export column headers use internal snake_case names: `text_content`, `views_count`, `search_terms_matched`, `pseudonymized_author_id`. A Marres researcher importing this CSV into NVivo will need to manually rename columns before sharing results with collaborators or including in publications. The headers should be human-readable: "Text Content," "View Count," "Matched Search Terms," "Author ID (Pseudonymized)." [data]

**Finding IM-38:** The CSV/XLSX export does not include a column for the query design name or the collection date. When the researcher has multiple collection runs for the same issue, the exported files contain no metadata to distinguish which run produced which records. The `collection_tier` column is included but `collection_run_id` is not in the `_FLAT_COLUMNS` list (confirmed in `export.py`, lines 42-58). Adding `collection_run_id` (or better, the query design name and run date) would help the researcher organize their exported data. [data]

**Finding IM-39:** The GEXF export includes all records from the collection run. There is no way to export a GEXF network for a SUBSET of the data (e.g., only Bluesky records, or only records matching a specific search term). For issue mapping, the researcher may want to compare the actor co-occurrence network on Bluesky versus on Reddit to see if the issue network structure differs across platforms. This requires per-arena GEXF export, which is not currently available. The researcher would need to export CSV, filter in R/Python, and rebuild the network manually. [research]

---

### Step 14: Assessment of the Full Issue Mapping Workflow

Having walked through the complete workflow -- query design, term entry, actor definition, arena configuration, collection, content browsing, analysis, network export -- I now assess whether the application can produce a Noortje Marres-style issue map at free/medium tiers.

#### What Works Well for Issue Mapping

1. **The three GEXF network types** directly correspond to the three network structures Marres' methodology requires: actor co-occurrence (issue alliances), term co-occurrence (discourse associations), and bipartite actor-term (who frames the issue how).
2. **The Danish locale configuration** (`danish_defaults.py`) is thorough and correctly implemented. For a study of "AI og uddannelse" in the Danish context, the Google `gl=dk`/`hl=da` parameters, the Bluesky `lang:da` filter, the curated Danish RSS feeds, and the GDELT `sourcelang=danish` filter all ensure Danish-language content.
3. **The content browser's filter system** supports the qualitative scanning workflow essential to issue mapping. Filtering by arena checkboxes and by matched search term allows the researcher to systematically explore discourse associations.
4. **The record detail panel** with matched search term badges makes discourse association patterns immediately visible during close reading.
5. **The snowball sampling panel** provides the actor discovery mechanism that Marres' "follow the actors" methodology requires.
6. **The bipartite GEXF export** with proper `type` node attributes enables direct Gephi visualization of actor-discourse-frame mappings.
7. **Multiple export formats** (CSV for qualitative coding, GEXF for network visualization, Parquet for large-scale analysis) cover the diverse tool chain of STS researchers.

#### What Does Not Work for Issue Mapping

1. **No in-browser network preview**: The researcher must download GEXF and open Gephi before they can see any network structure. This interrupts the explorative iteration cycle central to issue mapping.
2. **No entity resolution UI**: Cross-platform actor tracking requires entity resolution, but there is no visible way to trigger or manage it.
3. **Query design actors are disconnected from the Actor Directory**: The researcher must duplicate work to use both systems.
4. **Search terms are an unstructured flat list**: No grouping by function (primary issue terms vs. discourse association terms).
5. **The arena grid is missing key arenas**: AI Chat Search, Event Registry, and X/Twitter are inaccessible despite being implemented.
6. **No per-arena GEXF export**: The researcher cannot compare network structures across platforms without manual data processing.
7. **No content-based term discovery**: The application only tracks co-occurrence of pre-defined search terms, not emergent terms from the collected text.

---

## Passed

### IM-P01: Matched search terms displayed as badges in record detail
The record detail panel prominently shows which search terms each record matched, using styled badges. This enables the researcher to visually identify discourse association patterns during qualitative reading.

### IM-P02: "View original" link for source verification
Each record's detail panel includes a link to the source URL, opening in a new tab. This supports publication-quality verification.

### IM-P03: "Find actor" bridge from content to actor directory
The record detail panel's "Find actor" link pre-fills the actor search, supporting the Marres workflow of moving from content reading to actor investigation.

### IM-P04: All three Marres-relevant network types available
The Analysis dashboard provides Actor co-occurrence, Term co-occurrence, and Bipartite actor-term networks with GEXF export. This directly supports Marres-style issue mapping.

### IM-P05: Bipartite network description is research-appropriate
The bipartite tab's description text uses appropriate language for STS researchers and correctly describes the network structure.

### IM-P06: shared_terms edge attribute in actor GEXF
The actor co-occurrence GEXF includes a `shared_terms` edge attribute containing the pipe-separated list of overlapping search terms. This enables discourse-association-level analysis in Gephi.

### IM-P07: Term co-occurrence network is methodologically sound
The implementation correctly computes sorted, deduplicated term pairs per record, with accurate co-occurrence counts and per-term frequency as a node attribute.

### IM-P08: Bipartite GEXF uses type attribute for Gephi partitioning
The bipartite network's `type` node attribute ("actor" or "term") enables Gephi's partition module, which is essential for visual distinction in the issue map.

### IM-P09: Danish locale parameters correctly configured
All arena-specific Danish filters (Google gl/hl, Bluesky lang:da, Reddit Danish subreddits, GDELT sourcelang/sourcecountry, YouTube relevanceLanguage/regionCode, Ritzau language=da) are correctly defined in `danish_defaults.py`.

### IM-P10: Content browser arena filter checkboxes support platform comparison
The sidebar's arena checkboxes allow the researcher to quickly switch between single-arena views, supporting the cross-platform comparison workflow central to issue mapping.

---

## Friction Points

### IM-01: Dashboard "Phase 0" text creates doubt about multi-arena capability
File: `src/issue_observatory/api/templates/dashboard/index.html`, line 160. Identical to CO2 report FP-01. [frontend]

### IM-02: Quick Actions panel does not orient toward issue mapping workflow
File: `src/issue_observatory/api/templates/dashboard/index.html`, lines 118-151. No mention of Actor Directory or Network Analysis in quick links. [frontend]

### IM-03: No structured methodology documentation in query design
File: `src/issue_observatory/api/templates/query_designs/editor.html`, lines 70-78. Description is free text only, no methodology category field. [research]

### IM-04: Language selector forces single language, no multilingual option
File: `src/issue_observatory/api/templates/query_designs/editor.html`, lines 115-121. Cannot select "Danish + English" for bilingual issue tracking. [frontend], [core]

### IM-05: No explanation of what term types (Keyword, Phrase, Hashtag) mean
File: `src/issue_observatory/api/templates/query_designs/editor.html`, lines 169-175. Identical to CO2 report FP-04 but more consequential for issue mapping's nuanced term strategy. [frontend]

### IM-06: No way to group or categorize search terms within a query design
File: `src/issue_observatory/api/templates/query_designs/editor.html`, lines 157-206. All 15 terms appear as a flat list with no visual or functional grouping. [frontend], [research]

### IM-07: Mixed language "termer" in otherwise English UI
File: `src/issue_observatory/api/templates/query_designs/editor.html`, line 160. Identical to CO2 report FP-05. [frontend]

### IM-08: Query design actors lack platform identifiers
File: `src/issue_observatory/api/templates/query_designs/editor.html`, lines 208-295. Identical to CO2 report FP-07. Critical for cross-platform issue mapping. [frontend], [core]

### IM-10: Misleading tier options for free-only arenas
File: `src/issue_observatory/api/templates/query_designs/editor.html`, lines 391-409. Identical to CO2 report FP-09. Methodological transparency issue for published research. [frontend]

### IM-11: AI Chat Search, Event Registry, X/Twitter invisible in arena grid
File: `src/issue_observatory/api/templates/query_designs/editor.html`, lines 474-486. AI Chat Search would be uniquely valuable for meta-analysis of AI-in-education framing. Identical to CO2 report FP-11 but more significant for this scenario. [frontend], [core]

### IM-13: No arena descriptions in configuration grid
File: `src/issue_observatory/api/templates/query_designs/editor.html`, lines 363-425. Identical to CO2 report FP-13. Methodologically critical for issue mapping arena selection. [frontend]

### IM-15: Query design detail page does not show arena configuration
File: `src/issue_observatory/api/templates/query_designs/detail.html`. Identical to CO2 report FP-15. Cannot view complete "research instrument" on one page. [frontend]

### IM-17: Live mode description uses developer jargon "Celery Beat"
File: `src/issue_observatory/api/templates/collections/launcher.html`, line 112. Identical to CO2 report FP-16. [frontend]

### IM-18: Arena column hidden below xl breakpoint
File: `src/issue_observatory/api/templates/content/browser.html`, line 245. Identical to CO2 report FP-21. Critical for issue mapping qualitative scanning. [frontend]

### IM-20: Search Term filter is free-text instead of dropdown
File: `src/issue_observatory/api/templates/content/browser.html`, lines 124-134. For issue mapping's 15-term design, a dropdown would dramatically accelerate the filtering workflow. [frontend]

### IM-22: Timestamps lack timezone information
File: `src/issue_observatory/api/templates/content/record_detail.html`, lines 107-119. Identical to CO2 report FP-25. Matters for controversy sequence reconstruction. [frontend]

### IM-25: Snowball sampling panel collapsed at page bottom
File: `src/issue_observatory/api/templates/actors/list.html`, lines 245-550. Identical to CO2 report FP-27. For issue mapping, snowball sampling is a core method, not an advanced feature. [frontend]

### IM-29: Analysis dashboard charts lack axis labels
File: `src/issue_observatory/api/templates/analysis/index.html`, lines 207-276. Identical to CO2 report FP-30. [frontend]

### IM-30: Analysis filter bar uses free-text for Platform and Arena
File: `src/issue_observatory/api/templates/analysis/index.html`, lines 133-150. Identical to CO2 report FP-31. [frontend]

### IM-31: No in-browser network preview
File: `src/issue_observatory/api/templates/analysis/index.html`, lines 301-422. Each network tab shows only a description and download button. No visual preview of the network structure. [frontend]

### IM-32: Mixed readable names and hash IDs in Top Actors chart
File: `src/issue_observatory/api/templates/analysis/index.html`, lines 661-691 (actorsChart function). Pseudonymized IDs appear alongside display names with no resolution mechanism visible to the researcher. [frontend], [core]

### IM-33: Actor co-occurrence GEXF uses hash IDs as node IDs
File: `src/issue_observatory/analysis/export.py`, lines 411-491. While display names are used as labels, some Gephi operations may surface hash IDs. [data]

### IM-35: Bipartite GEXF lacks platform attribute on actor nodes
File: `src/issue_observatory/analysis/export.py`, lines 573-647. Actor nodes have a `type` attribute but not a `platform` attribute, preventing cross-platform visual analysis in Gephi. [data]

### IM-37: Export column headers use internal snake_case names
File: `src/issue_observatory/analysis/export.py`, lines 42-58. Identical to CO2 report FP-33. [data]

### IM-38: Export does not include collection run ID or query design name
File: `src/issue_observatory/analysis/export.py`, lines 42-58. Missing metadata columns for organizing multiple exports. [data]

---

## Blockers

### IM-B01: Query design actors are disconnected from Actor Directory

**Observation:** Actors added in the query design editor (Step 4) are stored as query-design-level list members. They are NOT automatically created as entries in the Actor Directory and have no platform presences. The Actor Directory's snowball sampling requires actors to exist IN the directory with platform presences. A researcher who adds 8 actors to the query design, then navigates to the Actor Directory for snowball sampling, finds an empty directory.

**Research impact:** The issue mapping workflow requires the researcher to duplicate all actor data: enter actors in the query design (for collection matching), then re-enter them in the Actor Directory (for snowball sampling and cross-platform tracking). With 8 seed actors, this is tedious but possible. At scale (after snowball sampling discovers 30+ actors), maintaining two disconnected actor lists becomes unsustainable. [frontend], [core]

### IM-B02: No UI for triggering or managing entity resolution

**Observation:** The Cross-platform actors tab in the Analysis dashboard requires `author_id` to be non-null, meaning entity resolution must have been performed. The application provides no visible mechanism for the researcher to trigger entity resolution or even understand what it is. The message "Entity resolution may not have been performed for this collection run" suggests a step the researcher should take, but there are no instructions or buttons for doing so.

**Research impact:** Cross-platform actor tracking is a fundamental requirement of Marres-style issue mapping. Without entity resolution, the researcher cannot determine which actors appear on multiple platforms, making cross-platform comparison impossible from within the application. The researcher must resort to manual matching of author names across platform exports. [frontend], [core]

### IM-B03: Arena configuration grid missing AI Chat Search and other implemented arenas

**Observation:** Identical to CO2 report B-01. The hardcoded arena list contains 11 arenas; the codebase implements at least 19. For the AI-og-uddannelse scenario, the AI Chat Search arena (`src/issue_observatory/arenas/ai_chat_search/`) is uniquely relevant: it would reveal how AI chatbots frame and source the very topic the researcher is studying. This creates a meta-level of analysis that no other arena provides. Event Registry and X/Twitter are also absent.

**Research impact:** The researcher's issue map is limited to 11 arenas when the system supports many more. The AI Chat Search arena -- which is methodologically novel for studying AI-in-education -- is completely inaccessible through the research workflow. [frontend], [core]

---

## Data Quality Findings

### DQ-01: Term co-occurrence limited to pre-defined search terms

**Observation:** The term co-occurrence network (both in `network.py` and `export.py`) operates exclusively on the `search_terms_matched` array, which contains only the search terms defined in the query design. It does not discover emergent terms from the collected text content.

**Research impact for AI og uddannelse:** The issue mapping researcher defines 15 search terms, but the collected content may reveal additional relevant terms that were not anticipated. For example, "etik" (ethics), "ansvar" (responsibility), "automatisering" (automation), or specific tool names (Copilot, Gemini, Claude) might appear frequently in the discourse but would not show up in the term co-occurrence network because they are not in the query design. This limits the "discovery" dimension of issue mapping.

### DQ-02: RSS feed temporal coverage for issue mapping

**Observation:** RSS feeds are real-time snapshots -- they contain only the most recent articles in the feed at the time of collection. For a batch collection with a date range of January-February 2026, the RSS arena will only capture articles that are in the feed at the moment of collection, not articles published throughout the two-month period.

**Research impact:** If DR published an article about AI-in-education on January 15 and it is no longer in the feed by February 18, the batch collection will miss it. The researcher's RSS coverage is biased toward recent articles, not the full date range. This temporal bias is undocumented in the UI and could affect the researcher's analysis of how media framing evolves over time.

### DQ-03: Reddit subreddit scope for AI-in-education

**Observation:** The default Danish subreddits are r/Denmark, r/danish, r/copenhagen, and r/aarhus (`danish_defaults.py`, lines 140-145). For the AI-og-uddannelse issue, r/dkpolitik and r/studenterraadet (if they exist) would be relevant, as would educational discussion threads in the general r/Denmark subreddit. More importantly, international subreddits like r/education, r/ChatGPT, r/professors, and r/academia may contain Danish user contributions or discussions directly relevant to the Danish context.

**Research impact:** Reddit coverage is limited to 4 Danish subreddits, potentially missing student-led discourse in education-specific or technology-specific subreddits. The researcher cannot add subreddits through the UI.

### DQ-04: Google Autocomplete for discourse association mapping

**Observation (positive):** Google Autocomplete is a particularly valuable data source for Marres-style issue mapping because it reveals "issue associations" -- what the search engine clusters around the issue term. When a user types "AI og uddannelse," the autocomplete suggestions (e.g., "AI og uddannelse eksamen," "AI og uddannelse fordele og ulemper," "AI og uddannelse ministeriet") reveal how the search algorithm indexes public interest clusters. The `google_autocomplete` arena is enabled in the arena grid and operates at the free tier using the Danish locale parameters (`gl=dk`, `hl=da`).

### DQ-05: Bluesky language filtering for Danish AI discourse

**Observation (positive):** The Bluesky collector appends `lang:da` to search queries, ensuring results are filtered to Danish-language posts. For the AI-og-uddannelse issue, this is important because many international AI-in-education discussions happen in English on Bluesky. The Danish filter ensures the researcher captures the specifically Danish discourse, not the global conversation.

### DQ-06: GDELT dual-query deduplication

**Observation:** Identical to CO2 report DQ-03. GDELT uses two queries (`sourcelang=danish` and `sourcecountry=DA`) and deduplicates by URL. For the AI-og-uddannelse issue, international English-language articles about Danish AI education policy would match `sourcecountry=DA` but not `sourcelang=danish`, while Danish-language articles from non-Danish domains would match `sourcelang=danish` but not `sourcecountry=DA`. The deduplication is transparent to the researcher -- no visibility into how many duplicates were removed or how the two query results relate.

### DQ-07: Pseudonymization impact on actor identification

**Observation:** Content records use `pseudonymized_author_id` (a hash) rather than raw platform usernames. While `author_display_name` preserves readable names, the hash-based ID means the researcher cannot directly link a content record's author to a platform profile. For issue mapping where actor identification is central, this creates an extra step: the researcher sees "Henrik Hansen" in the display name but cannot verify which "Henrik Hansen" this is across platforms without checking the raw metadata or the original URL.

**Research impact:** For well-known institutional actors (DR Nyheder, DLF), display names are distinctive enough to identify. For individuals with common names, pseudonymization makes cross-referencing difficult without the entity resolution system working (which has no UI, per IM-B02).

---

## Recommendations

### Priority 1 -- Critical for Issue Mapping Methodology

**R-01** [frontend] [core] -- Dynamically populate the arena configuration grid from the server's arena registry. This unblocks access to AI Chat Search (uniquely valuable for studying AI-in-education), Event Registry, and X/Twitter. This is the single most impactful change for issue mapping capability.

**R-02** [frontend] [core] -- Create automatic synchronization between query design actor lists and the Actor Directory. When a researcher adds "Danmarks Laererforening" to a query design, an actor entry should be created (or linked) in the Actor Directory. This eliminates the duplicate-entry workflow that currently blocks the actor discovery pathway.

**R-03** [frontend] [core] -- Provide a UI mechanism for triggering and monitoring entity resolution. Cross-platform actor tracking is fundamental to Marres-style mapping. The researcher needs to see which actors appear on multiple platforms without resorting to manual CSV matching.

**R-04** [frontend] -- Add a simple in-browser network preview to the network analysis tabs. Even a basic force-directed graph (d3-force, sigma.js, or vis.js) with 50-100 nodes would transform the explorative issue mapping workflow by eliminating the GEXF-download-then-open-Gephi cycle for initial exploration.

### Priority 2 -- High Value for Issue Mapping Workflow

**R-05** [frontend] -- Add arena descriptions to the configuration grid. For issue mapping, the researcher must understand what each arena captures to make methodologically sound inclusion/exclusion decisions. One-line descriptions per arena (e.g., "Ritzau: Danish press releases from organizations and institutions") would suffice.

**R-06** [frontend] -- Disable or grey out tier options not supported by each arena, with a tooltip explaining why. This prevents methodological misreporting in published research.

**R-07** [frontend] -- Replace the "Search Term" filter in the content browser with a dropdown populated from the query design's actual terms. For a 15-term issue mapping design, this would dramatically accelerate the discourse association exploration workflow.

**R-08** [frontend] -- Show the arena configuration on the query design detail page (read-only). The complete "research instrument" -- terms, actors, and arenas -- should be visible on a single page for methodology documentation.

**R-09** [data] -- Add a `platform` attribute to actor nodes in the bipartite GEXF export. This enables cross-platform visual analysis in Gephi without requiring the researcher to manually annotate nodes.

### Priority 3 -- Enhancements for Advanced Issue Mapping

**R-10** [research] -- Add term grouping/categorization within query designs. Allow the researcher to tag terms as "primary issue terms," "discourse association terms," "actor discovery terms," etc. These categories could be visualized in the term co-occurrence network using Gephi color partitions.

**R-11** [research] -- Add a content-based term discovery feature that extracts frequently occurring words/phrases from collected text content (beyond the pre-defined search terms). This would support the "discovery" dimension of issue mapping where the researcher does not know all relevant terms in advance.

**R-12** [frontend] -- Add per-arena GEXF export. Allow the researcher to generate network files filtered by arena, enabling cross-platform network comparison.

**R-13** [data] -- Add `collection_run_id` and `query_design_name` to the flat export columns. This helps the researcher organize multiple exports.

**R-14** [frontend] -- Replace snake_case export column headers with human-readable names.

**R-15** [frontend] -- Add chart axis labels to the analysis dashboard. Y-axis: "Number of records" for volume; X-axis: "Record count" for actor and term charts.

**R-16** [frontend] -- Add multilingual query design support (e.g., "Danish + English") so the researcher can track an issue in both languages simultaneously across arenas.

**R-17** [frontend] -- Make the Snowball Sampling panel more discoverable. Add a link to it from the sidebar navigation or promote it on the Actor Directory page with a prominent call-to-action.

---

## Comparison to the CO2 Afgift Report

### What is the Same

The following issues identified in the CO2 afgift report persist and apply equally to the AI-og-uddannelse scenario:

- Dashboard "Phase 0" stale text (FP-01 / IM-01)
- Tier descriptions too vague (FP-03)
- No term type explanations (FP-04 / IM-05)
- Mixed language "termer" (FP-05 / IM-07)
- Query design actors lack platform identifiers (FP-07 / IM-08)
- Misleading tier options for free-only arenas (FP-09 / IM-10)
- Arena grid missing implemented arenas (FP-11 / IM-11)
- No arena descriptions (FP-13 / IM-13)
- No save confirmation for arena config (FP-14)
- Query design detail missing arena configuration (FP-15 / IM-15)
- "Celery Beat" jargon (FP-16 / IM-17)
- Arena column hidden below xl (FP-21 / IM-18)
- Engagement score unexplained (FP-22 / IM-21)
- Timestamps lack timezone (FP-25 / IM-22)
- Snowball sampling low discoverability (FP-27 / IM-25)
- Charts lack axis labels (FP-30 / IM-29)
- Analysis filter uses free-text (FP-31 / IM-30)
- Export headers snake_case (FP-33 / IM-37)
- No in-browser network preview (FP-32 / IM-31)

### What is Different for Issue Mapping

The AI-og-uddannelse issue mapping scenario reveals problems that the CO2 afgift policy tracking scenario did not surface or surfaced only mildly:

1. **The disconnection between query design actors and the Actor Directory** (IM-B01) was noted in the CO2 report (FP-07) as a friction point. For issue mapping, where actors are the central analytical unit and snowball sampling is a core method, it escalates to a blocker.

2. **The lack of entity resolution UI** (IM-B02) was not identified in the CO2 report because cross-platform actor tracking was tested at the single-record level. Issue mapping requires systematic cross-platform actor comparison, making this a blocker.

3. **The AI Chat Search arena's invisibility** (IM-11) is more significant for AI-og-uddannelse than for CO2 afgift. For CO2 afgift, the AI Chat Search arena would provide supplementary data. For AI-og-uddannelse, it provides META-data: how AI chatbots themselves frame and source the very controversy the researcher is studying. This is a unique analytical dimension that no other arena offers.

4. **Term grouping** (IM-06) is a new finding. The CO2 afgift scenario used 7 terms that were all of similar type (primary issue terms and synonyms). The 15-term issue mapping design uses terms that serve four distinct analytical functions. The flat list representation loses this structure.

5. **Content-based term discovery** (DQ-01) is a new finding specific to issue mapping. Policy tracking uses pre-defined terms to measure coverage of known concepts. Issue mapping uses terms to discover UNKNOWN discourse associations, requiring the system to surface emergent terms from the collected data.

6. **Multilingual query design** (IM-04) is a new finding. CO2 afgift is primarily a Danish policy term; "AI og uddannelse" is an international topic that Danish institutions discuss in both Danish and English.

### Severity Comparison

| Dimension | CO2 Afgift Rating | AI og uddannelse Rating | Notes |
|-----------|-------------------|-------------------------|-------|
| Discoverability | Moderate | Moderate | Same issues: snowball sampling hidden, arena descriptions absent |
| Comprehensibility | Moderate | Moderate-Low | Term types, arena functions, and entity resolution are less transparent for the more complex issue mapping workflow |
| Completeness | Fair | Poor | Three blockers (actor disconnect, no entity resolution UI, missing arenas) interrupt the issue mapping workflow |
| Data Trust | Moderate | Moderate | Same locale correctness strengths; same deduplication opacity |
| Recovery | Good | Good | Error handling unchanged between scenarios |

---

## Overall Assessment

### Can a Danish STS Researcher Produce a Noortje Marres-Style Issue Map Using This Application?

**Partially, with significant workarounds and manual steps outside the application.**

The application provides the foundational data infrastructure for issue mapping: multi-arena collection with Danish locale filtering, three GEXF network types aligned with Marres' methodology, a content browser suitable for qualitative scanning, and a snowball sampling mechanism for actor discovery.

**The application excels at:**
- Danish-specific data collection across multiple arenas
- GEXF network export in all three structures Marres' methodology requires
- Matched search term display for discourse association identification
- Content browsing with arena and term filtering for qualitative exploration
- Actor type taxonomy (Person, Organisation, Media outlet, Account)

**The application falls short for issue mapping in these areas:**
- The actor workflow is fragmented across two disconnected systems (query design list and Actor Directory), blocking the actor-centric methodology that defines Marres' approach
- Cross-platform actor tracking requires entity resolution that has no UI
- The AI Chat Search arena, uniquely relevant for studying AI-in-education, is invisible in the UI
- Term grouping and content-based term discovery are absent, limiting the discourse association analysis
- No in-browser network preview interrupts the explorative iteration cycle

**What the researcher CAN produce at free/medium tier:**
- A term co-occurrence GEXF showing discourse association clusters around "AI og uddannelse" across 8 arenas (Google Search, Autocomplete, Bluesky, Reddit, YouTube, RSS, GDELT, Ritzau)
- A bipartite actor-term GEXF showing which discourse frames different actors employ
- A CSV export suitable for qualitative coding in NVivo
- A temporal volume chart showing issue salience fluctuations

**What the researcher CANNOT produce without workarounds:**
- A cross-platform actor network (requires entity resolution with no UI)
- An issue map that includes AI chatbot framing (AI Chat Search arena inaccessible)
- A network filtered by arena for cross-platform comparison (no per-arena GEXF export)
- Publication-ready charts (no axis labels, no figure export)
- A content-based term discovery analysis (only pre-defined search terms are tracked)

### Readiness Verdict

The application is **ready for pilot-stage explorative issue mapping** at free tier, producing exportable GEXF networks suitable for Gephi visualization. It is **not yet ready for publication-quality Marres-style issue mapping** until the actor workflow is unified, entity resolution is accessible, and the arena grid is dynamically populated.

The most impactful single change would be **R-01 (dynamic arena population)** combined with **R-02 (actor synchronization)**, which together would unblock both the AI Chat Search meta-analysis and the cross-platform actor tracking that Marres' methodology requires.
