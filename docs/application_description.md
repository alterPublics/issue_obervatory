# The Issue Observatory

## A Multi-Platform Media Data Collection and Analysis Application for Communications Research

**Last updated:** 2026-02-20

---

## What Is The Issue Observatory?

The Issue Observatory is a web-based research application designed for media and communications scholars who study how public issues are constituted, debated, and propagated across digital media platforms. It enables researchers to systematically collect, normalize, analyze, and export mediated content from more than twenty different digital platforms -- from national news media and search engines to social networks and fringe discussion forums -- through a single, integrated interface.

The application was built to answer a practical question that confronts any researcher working on contemporary public discourse: how can one track a specific issue across the fragmented landscape of digital media without cobbling together a dozen separate tools, APIs, and data formats? The Issue Observatory addresses this by providing a unified architecture where content from RSS feeds, Google Search results, Reddit threads, Bluesky posts, YouTube videos, Telegram channels, TikTok content, and many other sources is collected, normalized into a common data format, and made available for cross-platform analysis and export.

While the application is designed with the Danish media context as its primary focus -- with Danish-language defaults, curated Danish news feeds, and compliance with EU and Danish data protection regulations -- its architecture is intentionally modular and extensible. New platforms, languages, and geographic contexts can be added without restructuring the core system.

The target audience is academic researchers in media studies, political communication, journalism studies, science and technology studies, and adjacent fields. The application is also relevant to research-oriented organizations studying public discourse, misinformation, or media ecosystems. It is not a commercial social listening platform; it is a research instrument built around scholarly workflows, methodological transparency, and ethical data handling.

---

## Core Capabilities

### Multi-Platform Data Collection

The application currently supports data collection from 21 functional platform collectors, organized into logical groupings:

**Search engines and autocomplete:**
Google Search captures the search result pages that ordinary users encounter when searching for issue-related terms, revealing which sources dominate public information access. Google Autocomplete captures the suggested search completions that shape how users formulate their queries. An AI Chat Search arena simulates how users interact with AI chatbots (such as ChatGPT) to seek information about a topic, using OpenRouter to access multiple language models, expanding queries into natural-language phrasings, and extracting the sources cited in responses.

**Social media platforms:**
Bluesky, Reddit, YouTube, TikTok, Gab, and Threads are all supported with platform-specific collectors. X/Twitter is accessible through third-party API services at modest cost. Facebook and Instagram are available through either the Meta Content Library (for approved academic researchers) or through Bright Data as a commercial alternative. Telegram uses the MTProto protocol to collect from public channels with full message history, forwarding chain data, and view counts. Discord requires bot invitation to specific servers but can then monitor designated channels.

**News media and wire services:**
Over 28 curated Danish RSS feeds cover all major national news outlets -- DR (with 17 separate feeds), TV2, Politiken, Berlingske, Ekstra Bladet, Information, Jyllands-Posten, Borsen, Kristeligt Dagblad, Altinget (including section feeds), and educational media. Via Ritzau provides access to Danish press releases through a free JSON API. GDELT monitors hundreds of thousands of global news sources with Danish-language filtering. Event Registry offers full-text Danish news articles with native-language NLP processing, event clustering, and entity extraction.

**Web archives and link analysis:**
Common Crawl provides access to petabyte-scale monthly web crawls for historical web content discovery. The Wayback Machine enables researchers to track how specific pages change over time and to recover deleted content. A URL Scraper allows researchers to provide their own lists of URLs for systematic content retrieval using either standard HTTP fetching or JavaScript-rendered page capture. Majestic provides backlink index data for mapping how web content is referenced and connected. Wikipedia monitoring tracks revision activity and pageview patterns for researcher-specified articles.

### A Universal Content Record

All collected data -- regardless of its source platform -- is normalized into a universal content record format before storage. This normalization step is fundamental to the application's value: it means a researcher can query, filter, compare, and export content from Reddit, Danish news RSS feeds, and Telegram channels using the same fields and the same analytical functions.

Each content record includes the platform of origin, content type, title, full text, URL, publication timestamp, author information (pseudonymized by default for GDPR compliance), language, engagement metrics (views, likes, shares, comments), a normalized engagement score, and the search terms that matched the content during collection. Platform-specific data that does not fit the universal schema is preserved in a flexible metadata field, ensuring no information is lost during normalization.

Content records are stored in a PostgreSQL database with monthly range partitioning, enabling efficient time-scoped queries even as datasets grow to hundreds of thousands of records over multi-month studies.

### Three-Tier Pricing Model

Each platform collector operates at one or more of three cost tiers:

- **Free tier:** Uses only free APIs and public data access. Twelve or more arenas operate at zero cost, including RSS feeds, GDELT, Bluesky, Reddit, YouTube (with API key), Via Ritzau, Gab, Common Crawl, and Wayback Machine.
- **Medium tier:** Uses affordable paid services, typically costing between 5 and 120 USD per month per platform. This includes Google Search via Serper.dev, Event Registry, X/Twitter via third-party APIs, and TikTok.
- **Premium tier:** Uses the most comprehensive (and expensive) data access options when budget permits.

Researchers can set a default tier for their entire study and override it on a per-platform basis, allowing precise cost management. A credit system tracks expenditure, and a pre-flight credit estimation tool projects the cost of a planned collection run before it is launched.

---

## Research Workflows

The Issue Observatory is built around a research workflow that proceeds through five stages: design, collect, browse, analyze, and export. Importantly, this workflow is designed to be iterative -- a researcher can cycle through these stages multiple times, refining their query with each pass, as is standard practice in discourse research and issue mapping.

### 1. Designing a Query

A researcher begins by creating a **query design** -- a named, versioned specification of what to collect. A query design contains three elements:

**Search terms** define the vocabulary of the issue under study. Terms can be keywords, exact phrases, hashtags, or URL patterns. Terms can be organized into boolean groups using AND/OR logic, so that a compound query like `"CO2 afgift" AND (landbrug OR industri)` can be expressed and dispatched to platforms that support boolean search. Each term can optionally be scoped to specific platforms -- for instance, English-language terms can be restricted to GDELT and Google Search while Danish terms are sent to Bluesky and Reddit, preventing cross-language contamination. Terms can also be assigned group labels (such as "core terms," "English variants," or "discovered") for organizational clarity.

**Actor lists** define the people, organizations, media outlets, and institutions whose content should be tracked regardless of whether their posts match a search term. Actors are stored as canonical entities with cross-platform presence records -- so "DR Nyheder" can be tracked simultaneously on Twitter, Facebook, YouTube, and Bluesky as a single actor with verified accounts on each platform. Actors can be classified by type (person, organization, media outlet, political party, educational institution, think tank, and others), and public figures can be flagged for exemption from pseudonymization where legally appropriate.

**Arena configuration** specifies which platforms to activate and at which cost tier. Researchers can also provide custom source lists for platforms that require them -- adding specific Telegram channels, Reddit subreddits, RSS feed URLs, Discord channels, or Wikipedia articles to monitor beyond the defaults.

Query designs support cloning, allowing researchers to create modified versions for iterative refinement while preserving the record of earlier configurations.

### 2. Collecting Data

Once a query design is configured, the researcher launches a **collection run** in one of two modes:

- **Batch mode** collects data for a specified date range. This is used for initial exploration, historical backfill, or one-time snapshots. The application provides per-arena guidance on which platforms support historical date ranges and which return only recent content.
- **Live tracking mode** schedules recurring collection at regular intervals (typically daily), capturing new content as it is published. Researchers can suspend and resume live tracking as needed.

During collection, the application dispatches search terms and actor lists to each enabled platform, retrieves results through the appropriate API, normalizes each item into a universal content record, applies deduplication (by URL, content hash, and near-duplicate fingerprinting via SimHash), and stores the results. Collection progress is streamed to the browser in real time via server-sent events, so the researcher can monitor which platforms have completed and how many records have been collected.

After collection, an enrichment pipeline automatically processes the collected content through pluggable analysis modules. Current enrichments include language detection (for platforms that do not provide language metadata), Danish sentiment analysis using the AFINN lexicon, named entity extraction using spaCy, cross-arena propagation detection, and coordinated posting detection.

### 3. Browsing Content

The **content browser** provides a filterable, searchable interface for exploring collected data. Researchers can filter by platform, date range, language, content type, search term matched, and collection mode (batch or live). Each content record can be expanded to view full text, engagement metrics, platform-specific metadata, matched search terms displayed as visual badges, and enrichment results.

From the content browser, researchers can perform several key actions: add an author directly to their actor directory, annotate a record with qualitative codes, and follow links to discover new sources. A **discovered sources panel** surfaces URLs extracted from collected content that point to platforms the researcher may want to add to their monitoring -- such as Telegram channels mentioned in news articles, or YouTube channels referenced in Reddit posts. Discovered sources can be added to the query design's configuration with a single click.

### 4. Analyzing Data

The **analysis dashboard** provides both descriptive statistics and network analysis for collected data. Analysis can be scoped to a single collection run or aggregated across all runs for a query design, supporting the iterative workflow where a researcher runs multiple collection rounds with evolving search terms.

**Descriptive analytics** include volume over time (with configurable granularity from hourly to monthly), volume broken down by platform, top actors ranked by post count and engagement, top matched search terms, engagement score distributions, temporal volume comparisons (week-over-week or month-over-month with delta calculations), and arena-comparative analysis showing per-platform metrics side by side. A political calendar overlay can annotate the volume timeline with known events.

**Suggested terms** use TF-IDF extraction on collected text content to surface vocabulary that appears frequently in the corpus but was not part of the researcher's original search terms. This is a key discovery mechanism: the application identifies emerging discourse associations that the researcher did not anticipate. Suggested terms can be added to the query design with a single click, feeding directly back into the next collection iteration.

**Network analysis** produces three types of networks: actor co-occurrence networks (which actors share discourse space around the same search terms), term co-occurrence networks (which search terms appear together in the same content), and bipartite actor-term networks (connecting actors to the discourse topics they engage with). Networks can be computed for specific time windows, and temporal network snapshots show how the discourse network evolves over time. An in-browser network visualization (using Sigma.js) allows researchers to explore force-directed graph layouts directly in the application without exporting to external software.

**Cross-run comparison** enables researchers to compare two collection runs side by side, showing volume deltas, newly appearing actors, newly matched terms, and content overlap percentages -- directly supporting the iterative refinement cycle.

**Enrichment results** are displayed in a dedicated dashboard tab, showing language distribution, top named entities extracted from text, propagation patterns across platforms, and coordination signals.

### 5. Exporting Data

The application supports export in seven formats, chosen to serve different downstream analytical workflows:

- **CSV** with UTF-8 BOM encoding for compatibility with Excel and Danish character sets
- **XLSX** with formatted headers, auto-sized columns, and frozen panes
- **NDJSON** (newline-delimited JSON) for streaming ingestion into computational pipelines
- **Apache Parquet** with typed schemas for efficient analysis in Python/pandas or R/arrow
- **GEXF** (Graph Exchange XML Format) for network visualization in Gephi, available in static, per-arena, and dynamic temporal variants
- **RIS and BibTeX** for importing collected articles into reference managers for academic citation

Exports can be filtered by the same criteria available in the content browser and analysis dashboard. Column headers use human-readable labels rather than internal identifiers, and exports include provenance metadata (collection run ID, query design ID, arena, platform) so researchers can trace every record to its source. Synchronous export handles datasets up to 10,000 records; asynchronous export with progress tracking handles larger datasets.

---

## The Researcher Experience

Beyond the workflow stages described above, the following highlights describe what working with the application feels like in practice.

### Query Design as Research Instrument

The query design workflow serves as the researcher's primary "instrument" for defining what to study. Search terms support four types (keyword, phrase, hashtag, URL pattern) with optional group labels that organize terms into thematic categories -- useful when a study involves 15-23 terms serving different analytical functions, as in issue mapping and geopolitical monitoring scenarios. Per-arena term scoping allows researchers to direct English-language terms to international arenas (GDELT, Event Registry) without contaminating Danish-only platforms (Bluesky, Reddit). Boolean term groups support AND/OR query structures for researchers who need nuanced matching logic. Query design cloning with parent-design lineage supports the iterative refinement cycle that discourse research demands, allowing researchers to version their methodology as their understanding of the discourse landscape develops.

### Live Collection Monitoring

When a collection runs, the researcher sees real-time progress via server-sent events. Each arena appears as a row in a task table that updates its status (pending, running, completed, failed), record count, credit cost, and duration without requiring page refreshes. Error messages from individual arenas (invalid credentials, rate limits, platform downtime) surface in a Notes column, allowing the researcher to understand failures without developer intervention. For live tracking runs, a schedule panel shows the next scheduled execution time, supports suspend and resume operations, and clearly distinguishes pausing from permanent cancellation.

### Content Browser as Qualitative Workspace

The content browser is the researcher's primary workspace for qualitative exploration. A sidebar provides arena checkboxes, date range selectors, language filters, and matched-term filters. Clicking a record opens a slide-in detail panel showing the full text, source URL (with a "View original" link for verification), matched search term badges, and expandable raw metadata. The matched search term badges are particularly valuable for discourse analysis: a researcher scanning for framing patterns can immediately see which of their terms co-occur in each record. Full-text search uses PostgreSQL's Danish text configuration, meaning searches for "ytringsfrihedens" (genitive) correctly match records containing "ytringsfrihed."

### Analysis Dashboard

The analysis dashboard provides four summary cards (total records, arenas covered, date range, credits spent), temporal volume charts, top actors and terms rankings, and four network analysis tabs (actor co-occurrence, term co-occurrence, bipartite actor-term, cross-platform actors). Per-arena filtering on all endpoints allows researchers to compare network structures across platforms. Temporal network snapshots track how discourse networks evolve over time. Emergent term extraction (TF-IDF) identifies vocabulary that is statistically distinctive to the collected corpus, helping researchers discover terms they did not anticipate. Cross-run analysis aggregates data from multiple collection cycles for a unified view of a research project's full dataset.

### Actor Management and Discovery

The actor directory serves as a cross-platform identity registry. Actors added to a query design are automatically synchronized to the directory. Each actor can have multiple platform presences (Bluesky handle, Reddit username, YouTube channel), enabling cross-platform tracking of the same individual or organization. Snowball sampling discovers additional actors by traversing social graphs from seed actors on Bluesky, Reddit, and YouTube. The discovered-links pipeline mines URLs from collected content, classifies them by platform, and presents them for bulk addition to the actor directory. Entity resolution detects candidate duplicates across platforms using trigram similarity, and merge/split operations maintain a clean actor directory as the research evolves.

---

## Key Differentiating Features

### Designed for Danish Public Discourse Research

The application embeds Danish-specific configuration at every level. All platform collectors apply Danish locale defaults: Google uses `gl=dk` and `hl=da`, YouTube uses `relevanceLanguage=da` and `regionCode=DK`, Bluesky appends `lang:da` to search queries, GDELT filters by `sourcelang:danish` and `sourcecountry:DA`, and Event Registry uses the ISO 639-3 code `dan`. The PostgreSQL full-text search index uses the Danish snowball stemmer for efficient content search across Danish-language text.

The curated RSS feed list covers all major Danish national news outlets and can be extended by researchers through the interface. The default Reddit subreddit list includes r/Denmark, r/danish, r/copenhagen, r/aarhus, and r/dkpolitik. Danish sentiment analysis is available through the AFINN lexicon, which includes Danish-language word lists.

At the same time, the application is not limited to Danish. Researchers can configure multi-language query designs (for instance, Danish and English simultaneously), and all locale settings can be overridden for studies focused on other contexts.

### Iterative Discovery, Not Just Collection

Unlike tools designed for one-shot data collection or ongoing monitoring of known sources, The Issue Observatory is built to support the iterative cycle of discovery that defines much communications research. The suggested-terms feature surfaces unexpected vocabulary from collected text. The discovered-sources panel identifies new platforms and channels referenced within collected content. RSS feed autodiscovery and Reddit subreddit suggestion provide automated assistance for finding relevant sources. One-click actions allow researchers to feed discoveries directly back into their query designs without leaving the analysis interface.

This discovery-oriented design is directly informed by the methodological requirements of issue mapping in the tradition of Noortje Marres, where the research question is not "how much coverage does this issue receive?" but "what actors, discourse associations, and controversies constitute this issue, and how do they evolve?"

### Cross-Platform Normalization and Comparison

The universal content record schema makes it possible to ask questions that span platforms: Which actors are active on both Twitter and in news media? Does the same story appear first on social media or in traditional news? How does the engagement pattern for a given issue differ between YouTube and Reddit? The arena-comparative analysis function produces side-by-side metrics for all active platforms, and the propagation detection enrichment identifies when the same content or closely related content appears across platforms over time, revealing narrative flow patterns.

### Researcher-Configurable Source Lists

Platforms that depend on curated source lists -- Telegram channels, Reddit subreddits, RSS feeds, Discord servers, Wikipedia articles -- are fully configurable through the query design interface. Researchers can add, remove, and modify their monitored sources without any code changes or technical assistance. This is essential because different research topics require different sources, and no default list can anticipate every study.

### Qualitative Coding and Annotation

The application includes a content annotation system that allows researchers to assign qualitative codes to individual content records -- including stance labels (positive, negative, neutral, contested, irrelevant), free-text notes, and custom codes defined through a codebook management interface. Codebooks can be scoped to specific query designs or shared globally. This enables mixed-methods research workflows where computational collection and analysis are combined with interpretive human judgment.

### Actor Sampling and Network Expansion

The actor directory supports multiple methods for building and expanding the list of actors being tracked. Snowball sampling starts from seed actors and discovers connected actors through platform-specific social graph traversal (follows and followers on Bluesky, featured channels on YouTube, comment mentions on Reddit, forwarding chains on Telegram). Content similarity analysis identifies actors who produce similar content even when they are not socially connected. These sampling methods are tracked with provenance metadata, supporting methodological transparency about how the actor list was constructed.

---

## Analysis and Enrichment Capabilities

Beyond the descriptive and network analysis functions described above, the application includes a pluggable enrichment pipeline that processes collected content through a series of automated analysis steps:

- **Language detection** identifies the language of content from platforms that do not provide language metadata, using the langdetect library with a heuristic fallback for Danish character frequency patterns.
- **Danish sentiment analysis** scores content on a scale from negative to positive using the AFINN lexicon, storing a normalized score, a raw score, and a categorical label (positive, negative, or neutral) for each record.
- **Named entity extraction** identifies people, organizations, and geographic entities mentioned in text content using spaCy's Danish language model, with role classification (mentioned, speaker, quoted source).
- **Propagation detection** identifies when the same or closely related content appears across multiple platforms over time, constructing cross-arena propagation chains with timestamps and arena sequences.
- **Coordination detection** identifies patterns of synchronized posting across accounts, flagging potential coordinated behavior based on temporal clustering.
- **Near-duplicate detection** uses SimHash fingerprinting to identify content that is substantially similar but not identical -- such as wire service articles that have been lightly edited by different news outlets -- preventing inflated volume counts and distorted engagement aggregations.

The enrichment pipeline is designed to be extensible: new enrichment modules can be added by implementing a standard interface, without requiring changes to the data schema or the analysis layer.

---

## Ethical and Legal Considerations

### GDPR Compliance

The application is designed with GDPR compliance integrated into its architecture rather than added as an afterthought.

**Pseudonymization** is applied by default to all author identifiers. The normalizer computes SHA-256 hashes of author platform IDs using a configurable salt (stored as an environment variable, never in the codebase), producing pseudonymized identifiers that prevent casual identification while preserving the ability to track the same author across multiple content records. For public figures -- politicians, organizational spokespersons, journalists, and other individuals whose public discourse activities are part of their public role -- pseudonymization can be bypassed on a per-actor basis, with an audit trail recorded in the content metadata. This approach aligns with GDPR Article 89(1) provisions for research and the recognition that public figures have a reduced expectation of privacy in their public communications.

**Data subject deletion** is supported through a retention service that can remove all content records associated with a specific author, implementing the data subject's right to erasure.

**Purpose limitation** is enforced structurally: all content records are linked to the query design that motivated their collection, making it possible to verify that data is used for its stated research purpose.

**Data minimization** is supported through configurable retention policies and the ability to delete content that is no longer needed for the research.

### Danish Data Protection Law

The application's design accounts for the specific requirements of the Danish Data Protection Act (Databeskyttelsesloven). Section 10 imposes a heightened threshold of "significant societal importance" for research involving special category data (such as political opinions or health information that may be revealed in social media posts). The pseudonymization-by-default approach, combined with purpose limitation and the availability of data subject deletion, supports compliance with these requirements. Researchers using the application should still conduct a Data Protection Impact Assessment for their specific project, as is practically mandatory for large-scale social media collection under Datatilsynet's DPIA blacklist criteria.

### DSA Researcher Access

The EU Digital Services Act (Article 40) creates enforceable rights to platform data for researchers studying systemic risks. This is particularly relevant for platforms like Facebook, Instagram, and X/Twitter, where official API access has become restrictive or expensive. The DSA framework -- now backed by significant enforcement actions including a 120 million euro fine against X -- establishes that platforms cannot charge researchers for public data access or punish them for scraping public data for systemic risk research. The application's architecture is designed to work with both official API access and third-party data access services, positioning researchers to take advantage of whichever access pathway is most practical for each platform.

---

## Flexibility and Extensibility

### Modular Arena Architecture

Each platform collector is a self-contained module that implements a standard interface (the ArenaCollector base class). Adding support for a new platform means creating a new module that implements term-based search, actor-based collection, and data normalization -- without modifying any core infrastructure. This modular design has enabled the application to grow from its initial Google Search implementation to 21 functional platform collectors.

### Multi-Language Support

While Danish is the default, the application supports multi-language query designs where researchers can specify multiple target languages. Search terms can be scoped to specific platforms, allowing Danish and English terms to be dispatched only to the platforms where each language is relevant. Language configuration is per-query-design, not per-installation, so the same application instance can support studies in different linguistic contexts.

### Self-Hosted and Self-Contained

The application runs on standard open-source infrastructure: Python 3.12+, PostgreSQL 16+, Redis 7+, and Celery for task processing. It can be deployed on a single server or in a containerized environment using Docker Compose. There are no proprietary dependencies or mandatory cloud services -- all data remains under the researcher's control.

---

## Evaluated Research Scenarios

The Issue Observatory has been evaluated through structured end-to-end testing against six distinct research scenarios, each representing a different methodological approach and substantive domain. Each evaluation followed a realistic Danish media research question from query design through collection, analysis, and export.

### 1. CO2 Afgift (Carbon Tax) -- Danish Policy Discourse Mapping

**Research question.** How is the CO2 afgift framed in Danish public discourse across digital media platforms in early 2026? Who are the key actors, what terms co-occur with "CO2 afgift," and does the framing differ between legacy news media, social platforms, and news aggregation services?

**Relevant arenas.** Google Search, Google Autocomplete, Bluesky, Reddit, YouTube, RSS Feeds (28+ Danish outlets), GDELT, Via Ritzau, Gab.

**Researcher workflow.** The researcher creates a query design with seven search terms spanning Danish and English variants ("CO2 afgift," "klimaafgift," "carbon tax," "gron omstilling"), adds six named actors (politicians, industry organizations, the Climate Council), configures nine arenas at the free tier, and launches a batch collection covering January--February 2026. After collection, the researcher browses results in the content browser with arena-specific filtering, examines term co-occurrence patterns through the analysis dashboard, and exports GEXF network files for Gephi visualization.

**Capabilities exercised.** Danish locale defaults across all arenas; multi-arena batch collection with SSE live monitoring; content browser with full-text Danish search and arena filtering; term co-occurrence and actor co-occurrence GEXF export; five-format data export.

**Outputs.** Term co-occurrence network revealing which policy framings cluster together; actor co-occurrence network showing which actors address the same sub-topics; bipartite actor-term network mapping which actors employ which framings; CSV/XLSX exports suitable for external quantitative analysis.

### 2. AI og Uddannelse (AI and Education) -- Issue Mapping

**Research question.** How is the issue of "AI og uddannelse" constituted in Danish public discourse? Who are the key actors and what discourse associations do they forge around this issue? Where are the points of controversy, and how do issue networks differ across platforms?

**Relevant arenas.** Google Search, Google Autocomplete, Bluesky, Reddit, YouTube, RSS Feeds, GDELT, Via Ritzau. Additionally, Event Registry, X/Twitter, and AI Chat Search were identified as highly relevant.

**Researcher workflow.** Following Noortje Marres' issue mapping methodology, the researcher designs a 15-term query structured into four functional categories: primary issue terms, actor discovery terms, discourse association terms, and English variants. Eight seed actors are added spanning government ministries, teachers' unions, universities, student organizations, and technology companies. After collection, the researcher uses the analysis dashboard's three network types to produce the issue map: the actor co-occurrence network reveals issue alliances, the term co-occurrence network reveals discourse association clusters, and the bipartite actor-term network shows which actors are associated with which framings. Snowball sampling is used to expand the actor corpus beyond the initial seed set.

**Capabilities exercised.** 15-term query design with term type classification; actor management with type taxonomy (person, organization, political party, educational institution, teachers' union, think tank); snowball sampling for actor discovery; all three GEXF network types; matched search term display in the content browser's record detail panel for identifying discourse associations during qualitative reading.

**Outputs.** Three complementary GEXF network files for Gephi: actor alliances around AI-in-education, discourse frame clustering, and actor-frame mappings; CSV exports for qualitative coding in NVivo; temporal volume charts showing issue salience fluctuations.

### 3. Greenland -- Geopolitical Discourse and Fringe Platform Monitoring

**Research question.** How is the issue of "Greenland" constituted in Danish public discourse leading up to the 2026 general election? Who are the key actors? What discourse associations emerge (sovereignty, independence, Arctic security, Trump/US, colonial history)? Where might conspiracy theories or foreign interference narratives form?

**Relevant arenas.** All 24 implemented arena collectors were evaluated, with particular attention to platforms relevant for fringe monitoring: Telegram, Reddit, Discord, Gab, TikTok, and the web archive arenas (Common Crawl, Wayback Machine). Wikipedia was noted as uniquely valuable for tracking editorial contestation around Greenland-related articles.

**Researcher workflow.** The researcher designs a 23-term query spanning six thematic dimensions: core Danish political terms, English geopolitical terms, conspiracy and foreign interference terms, social media hashtags, indigenous self-determination terms, and NATO/defence terms. Eight actors are added from diverse institutional positions across Danish and Greenlandic governance. The study requires configuring source-list arenas (Telegram channels for political discourse, Reddit subreddits for community discussion) and distinguishing mainstream from fringe platform content.

**Capabilities exercised.** Term grouping with named thematic categories; researcher-configurable source lists (custom Telegram channels, custom Reddit subreddits, custom RSS feeds); dynamic arena registry with tier validation and credential status indicators; arena descriptions for informed configuration decisions; actor synchronization between query design and Actor Directory; human-readable export headers with provenance metadata.

**Outputs.** Term co-occurrence network revealing which geopolitical framings cluster together (e.g., whether "Trump Greenland" co-occurs with "arktisk sikkerhed" or with "kolonihistorie"); cross-platform comparison of mainstream versus fringe discourse; exported data with full provenance for methodology documentation.

### 4. Ytringsfrihed (Freedom of Speech) -- Cross-Arena Discovery Workflow

**Research question.** How is "ytringsfrihed" (freedom of speech) constituted as a public issue in Danish discourse? What sub-framings exist (democratic principle, hate speech regulation, platform moderation, cultural sensitivity)? Who are the key actors across mainstream and fringe platforms?

**Relevant arenas.** All 20 mounted arena routers were evaluated across free, medium, and premium tiers. Particular attention was paid to the cross-arena discovery workflow: using results from one arena to seed collection on another.

**Researcher workflow.** The researcher begins with 18 search terms across five thematic groups (core, regulation, legal, tech, cultural, social). The evaluation traces the full iterative discovery cycle: initial free-tier collection across six arenas; using the suggested-terms endpoint (TF-IDF extraction) to discover new vocabulary; using the discovered-links endpoint (cross-platform link mining) to find Telegram channels, YouTube videos, and organizational websites referenced in collected content; using snowball sampling to expand actor networks; cloning the query design for a refined second collection round; and eventually transitioning from batch exploration to live daily tracking.

**Capabilities exercised.** Per-arena search term scoping (allowing English terms for GDELT without contaminating Bluesky results); bulk term and actor import; ad-hoc exploration mode (testing a term on free arenas before committing to a query design); source-list arena configuration through the UI; pre-flight credit estimation; cross-run analysis aggregating data from multiple collection cycles; query design cloning with provenance tracking; seven export formats including RIS and BibTeX for reference managers.

**Outputs.** Iteratively refined multi-platform dataset with full design lineage; GEXF networks filtered by arena for cross-platform comparison; RIS citations for direct import into reference management software; Parquet exports for data science workflows.

### 5. Socialt Bedrageri (Social Benefits Fraud) -- Discovery-Intensive Bootstrapping

**Research question.** How is "socialt bedrageri" (social benefits fraud) constituted as a public issue in Danish discourse? What are the dominant framings -- punitive enforcement versus protection of vulnerable populations? How does the discourse propagate across different arenas?

**Relevant arenas.** All 21 functional arena collectors, with primary focus on free-tier arenas and selective medium-tier additions (Google Search, X/Twitter, TikTok, AI Chat Search).

**Researcher workflow.** This scenario tests the most demanding use case: a researcher with limited prior knowledge who must bootstrap a comprehensive mapping through iterative discovery. Starting with 12 initial terms across four groups, the researcher launches a free-tier exploratory collection, then uses the suggested-terms endpoint to discover domain-specific vocabulary (e.g., "kontrolgruppe," "fejludbetaling," "Ankestyrelsen"), the discovered-links endpoint to find relevant Telegram channels and niche RSS feeds, and quick-add from the content browser to build an actor directory. The design is cloned and refined, a second collection captures expanded coverage, and the researcher transitions to live daily tracking. Boolean term groups support AND/OR query structures for nuanced matching. Annotation with stance labels (positive, negative, neutral, contested, irrelevant) supports qualitative coding alongside quantitative collection.

**Capabilities exercised.** Boolean query groups with AND/OR logic; TF-IDF emergent term extraction; cross-platform link mining and one-click source addition; query design cloning with parent-design lineage; batch-to-live-tracking transition with suspend/resume controls; content annotation with stance vocabulary; cross-arena propagation detection; volume spike alerting; coordination detection; engagement score normalization; SimHash near-duplicate detection for wire-service article variants.

**Outputs.** Iteratively expanded multi-platform dataset built from minimal starting knowledge; temporal network snapshots showing discourse evolution; propagation flow analysis across arenas; annotated content records exportable alongside quantitative data; per-arena GEXF networks for comparing discourse structures across platforms.

### 6. Phase 3 Baseline Evaluation

**Scope.** All 12 core UX scenarios were evaluated across 18 arenas and all three tiers. This baseline evaluation established the initial assessment of the application's five UX dimensions (discoverability, comprehensibility, completeness, data trust, recovery) and identified critical data quality issues including incorrect GEXF edge construction, missing Bluesky language filtering for actor-based collection, and documentation mismatches with actual data coverage. Three critical blockers were identified and subsequently resolved: snowball sampling had no UI entry point; GEXF exports produced identical files regardless of network type; and live tracking had no schedule visibility or suspend/pause capability. Data quality fixes corrected the GEXF co-occurrence algorithm to use shared search terms rather than shared collection runs, and added client-side language filtering to Bluesky actor-based collection.

---

## Current Status and Future Directions

As of February 2026, the application is fully functional with 21 active platform collectors, 12 database migrations defining the complete schema, 6 enrichment modules, comprehensive analysis and export capabilities, and a browser-based interface covering all major research workflows. The application has been iteratively refined through six scenario-based evaluations that identified and resolved more than 150 specific improvement recommendations.

Two capabilities remain on the roadmap for future development: topic modeling using BERTopic (which requires GPU infrastructure and heavy dependencies) and a dedicated collector for Folketinget.dk parliamentary proceedings. Additionally, the application does not currently support automated collection from LinkedIn, which remains the hardest major platform to access legally in Europe; manual capture using the Zeeschuimer browser extension with NDJSON import is the current workaround.

The application is an active research tool under continued development. Its architecture is designed to accommodate new platforms, new analytical methods, and new research contexts as the digital media landscape evolves.
