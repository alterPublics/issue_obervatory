# Cross-platform media data collection in Denmark: a comprehensive guide

**Denmark offers one of Europe's richest — and most regulated — environments for media data collection.** With **91% of Danes aged 16–74 on social media** (the highest rate in the EU), a digitized press infrastructure centered on Infomedia's national archive, and a rapidly evolving legal framework shaped by the GDPR and the EU Digital Services Act, researchers face both extraordinary opportunity and significant compliance complexity. This guide covers ten essential data sources and frameworks, with specific details on access, pricing, latency, Danish coverage quality, and legal considerations as of early 2026.

---

## 1. Infomedia: Denmark's indispensable media archive

Infomedia (infomedia.dk) is **Denmark's largest online media archive**, containing millions of articles dating back to **1990**. Originally co-owned 50/50 by JP/Politikens Hus and Berlingske Media, it merged with Sweden's Retriever Group in **June 2024**, creating a combined Nordic media intelligence company with ~400 employees, ~€76M revenue, and over 3,000 corporate customers. The merged entity now operates under the **Retriever** brand.

The archive covers **all national daily newspapers** (Politiken, Berlingske, Jyllands-Posten, Ekstra Bladet, BT, Børsen, Information, Kristeligt Dagblad), all regional and local dailies, weekly newspapers, trade journals and magazines, news agencies (including Ritzau wire content), web-only outlets, and radio/TV broadcast transcripts. Through its 2018 acquisition of Opoint Technology, it also provides access to a **5+ billion global web article archive**. Content is updated daily for print media and near-real-time for web and broadcast monitoring.

**API access** is available through the **Medieresearch API**, a REST-based service specifically designed for academic data extraction. Documentation is accessible to authorized institutional users — the University of Copenhagen's Social Sciences Data Lab publishes a Quick Start Guide. All major Danish universities (KU, SDU, CBS, AU) subscribe through their libraries. Pricing for the research API is negotiated directly with Infomedia and is not publicly listed. Standard terms prohibit bulk downloading, resale, or storage outside Infomedia's systems. For researchers needing comprehensive Danish news data, Infomedia is effectively the only viable source for historical archive access.

---

## 2. Ritzau: the sole Danish wire service

Ritzau (Ritzaus Bureau A/S), founded in 1866, is **Denmark's only remaining national news agency**, having absorbed competitors Newspaq (2012) and Dagbladenes Bureau (2023). Owned by a consortium of Danish media companies including JP/Politikens Hus, DR, Dagbladet Børsen, and Jysk Fynske Medier, it delivers approximately **130,000 news stories annually** to **170 Danish media clients** and operates Ritzau Scanpix, Denmark's leading photo agency with 25+ million archived images.

Direct API access to Ritzau's editorial wire is **not publicly available** — the wire is distributed through proprietary systems to subscribing media houses, with pricing negotiated per client. However, two alternative access paths exist. First, the **Via Ritzau REST API v2** (`https://via.ritzau.dk/json/v2/releases`) provides free, unauthenticated JSON access to press releases distributed through the Via Ritzau platform. It supports filtering by publisher, keyword, channel, and language (Danish, English, Finnish, Norwegian, Swedish). Second, all Ritzau editorial wire content is archived in and searchable through **Infomedia's Mediearkiv**, making Infomedia the practical access point for researchers needing historical wire content.

Ritzau also collaborates with Nordic counterparts TT (Sweden), NTB (Norway), and STT (Finland) through the **Nordic News** service, producing 60 English-language Scandinavian news stories daily. Notably, the Danish police now distribute operational announcements through Ritzau's platform after leaving X/Twitter.

---

## 3. Danish news RSS feeds remain broadly available

Most major Danish news outlets continue to offer RSS feeds as of early 2026, though documentation quality varies significantly. **DR** maintains the most comprehensive offering, with 20+ category and regional feeds accessible from a dedicated page updated in September 2024. Key feeds include `https://www.dr.dk/nyheder/service/feeds/allenyheder` (all news), with separate feeds for domestic, international, politics, sports, science, culture, weather, and nine regional areas. No authentication is required.

**TV2** restored RSS capability through a newer API-based feed at `https://feeds.services.tv2.dk/api/feeds/nyheder/rss` (verified active with current content), replacing feeds discontinued in 2019. **BT** offers an actively maintained feed at `https://www.bt.dk/bt/seneste/rss` (verified active). **Politiken** provides feeds at `http://politiken.dk/rss/senestenyt.rss` (verified active). **Information** offers a feed at `http://www.information.dk/feed`. **Berlingske** publishes at `https://www.berlingske.dk/content/rss`. **Ekstra Bladet** documents its feeds at `https://ekstrabladet.dk/services/rss-feeds-fra-ekstra-bladet/4576561`. **Nordjyske** offers `https://nordjyske.dk/rss/nyheder`, and **Fyens Stiftstidende** uses a `/feed/[category]` pattern shared across the Jysk Fynske Medier group (e.g., `https://fyens.dk/feed/danmark`). **Jyllands-Posten's** RSS status is the most uncertain — historical feeds at `jp.dk/rss/topnyheder.jsp` may have been discontinued as the outlet shifts toward app-based delivery.

No authentication is required for any confirmed feed, though full article content on paywalled sites (Berlingske, Politiken, JP, Ekstra Bladet) requires a subscription. Aggregated directories include FeedSpot's "Top 25 Denmark News RSS Feeds" and the Danish-language catalog RSSKataloget.dk.

---

## 4. LinkedIn data collection faces severe legal constraints in Europe

LinkedIn's official API ecosystem is **highly restricted**. All API access beyond basic "Sign In with LinkedIn" requires approval through LinkedIn's Partner Program, with an approval rate below 10% and timelines of 3–6 months. The Marketing Developer Platform operates in Development (testing) and Standard (production) tiers, both requiring LinkedIn review. Rate limits range from **100–500 API calls per day** for free-tier apps. LinkedIn does not publish standard pricing; reported figures from third-party sources suggest tiers from ~$59/month (500 requests/day) to ~$2,999/month (unlimited), though these are unconfirmed.

For research specifically, LinkedIn launched a **DSA Researcher Access Program** in August 2023, offering access to aggregated, anonymized data on publicly accessible content. Applicants must demonstrate independence from commercial interests, disclose funding, and focus on EU systemic risk topics. Data cannot be downloaded directly. The earlier Economic Graph Research Program (2017–2018) is no longer accepting applications.

**Third-party scraping services** offer alternatives at significant legal risk in Europe. **Bright Data** provides LinkedIn scraper APIs at **$1.50–$2.50 per 1,000 requests** (~$0.001–$0.05 per profile), handling proxies and CAPTCHAs automatically. **Apify** marketplace actors range from $0.004/full profile to $12/1,000 employees (with email enrichment). **PhantomBuster** ($69–$439/month) uses your own LinkedIn cookies, limiting throughput to ~80 profiles/day before triggering account restrictions. **Proxycurl** ($49/month for 1,000 API calls) faces uncertain continuity after LinkedIn publicly announced enforcement action against it in January 2025.

The legal landscape in Europe is fundamentally hostile to LinkedIn scraping. While the US *hiQ v. LinkedIn* case established that scraping public data doesn't violate the Computer Fraud and Abuse Act, **this precedent does not apply in the EU**. Under GDPR, LinkedIn profile data is personal data regardless of public visibility, and processing requires a lawful basis. France's CNIL fined KASPR **€240,000** in December 2024 for scraping ~160 million LinkedIn contacts without informing data subjects. The EU Database Directive provides additional protection. Researchers should treat commercial scraping of LinkedIn as carrying substantial legal risk in Denmark and the EU.

---

## 5. GDPR compliance requires careful navigation of research exemptions

The GDPR creates a **privileged but conditional** framework for social media research. Article 89 exempts research from purpose limitation (Art. 5(1)(b)) and storage limitation (Art. 5(1)(e)), and enables Member State derogations from data subject rights. Denmark has implemented these derogations: under the **Databeskyttelsesloven**, **Articles 15–16, 18, and 21 do not apply** when personal data is processed solely for scientific or statistical purposes.

However, the Danish standard is notably strict. **§10 of the Databeskyttelsesloven** requires that research involving special category data (Art. 9(1)) or criminal convictions data (Art. 10) be of **"significant societal importance" (*væsentlig samfundsmæssig betydning*)** — a higher threshold than the GDPR's general "scientific research purposes." Data processed under §10 **cannot subsequently be used for non-research purposes**, and disclosure to third parties (including for publication in scientific journals) requires **prior authorization from Datatilsynet**.

For legal basis, public university researchers should use **Art. 6(1)(e) combined with Art. 89**, which enables the strongest derogations from data subject rights. Private institutions may need to rely on **Art. 6(1)(f) legitimate interest**, which requires a three-part balancing test and leaves data subjects' right to object intact. For special category data revealed in social media posts (political opinions, health information, religious beliefs), **Art. 9(2)(j) combined with §10** is the appropriate basis.

A **Data Protection Impact Assessment is practically mandatory** for large-scale social media collection. Datatilsynet's DPIA blacklist triggers mandatory assessment when processing involves innovative technology combined with any additional WP29 risk criterion — social media research combining large-scale processing with NLP tools and potential special category data will virtually always qualify. Regarding notification, **Art. 14(5)(b)** provides an exemption when individual notification would involve "disproportionate effort," explicitly applicable to research, but researchers must still publish a privacy notice describing the project and making information publicly available. Datatilsynet has not issued specific guidance on social media research, though its DPIA blacklist was approved by the EDPB without any recommendations — the only Member State to achieve this distinction.

---

## 6. The DSA creates enforceable rights to platform data

The Digital Services Act's **Article 40** establishes a three-tier data access framework that fundamentally reshapes the landscape. Tier 1 gives the European Commission and Digital Services Coordinators (DSCs) access for compliance monitoring. Tier 2 provides **"vetted researcher" access to non-public data** — including algorithmic, recommendation system, and content moderation data — after approval by the relevant DSC. Tier 3 (Art. 40(12)), **operational since August 2023**, grants qualified researchers access to publicly accessible platform data, including through automated means, that platforms cannot block.

The enforcement record demonstrates real teeth. The Commission fined **X (Twitter) €120 million** on December 5, 2025 — with **€40M specifically for researcher access violations** — after finding the platform imposed unnecessary barriers on independent researchers. Preliminary breach findings were issued against TikTok and Meta in October 2025 for inadequate public data access. Critically, the Commission confirmed that **Art. 40 does not permit platforms to charge researchers for access**, and that platforms cannot punish researchers for scraping public data for systemic risk research.

The vetted researcher process became operational in **late October 2025** following the Delegated Act adopted in July 2025. Researchers apply through their Member State's DSC (in Denmark, **Digitaliseringsstyrelsen**, which assumed DSC responsibility on August 29, 2024). Since most VLOPs are established in Ireland, applications are typically transmitted to Ireland's Coimisiún na Meán. Approximately **23 platforms carry VLOP designation**, including Facebook, Instagram, YouTube, TikTok, X, LinkedIn, Snapchat, Pinterest, Amazon, and Wikipedia. Google Search and Bing are designated as VLOSEs.

A significant limitation: DSA data access is restricted to research on **systemic risks** — illegal content dissemination, fundamental rights impacts, effects on civic discourse and elections, public health, and minors' well-being. General academic research outside these topics does not qualify.

---

## 7. Denmark's social media landscape in numbers

Denmark ranks as the **EU's most active social media nation**, with penetration at 91% of those aged 16–74. Facebook remains dominant at **84% usage** among 16–74-year-olds, though daily use has declined from 68% (2022) to ~60% (2024) as younger users migrate to other platforms. Instagram reaches **56%**, Snapchat **45%**, LinkedIn **33%**, Pinterest **21%**, TikTok **19%**, and X/Twitter just **13%**. YouTube's ad audience reaches **4.69 million Danes (78.3% of the population)**, making it the largest single platform by reach.

The age dynamics are striking. Among 16–24-year-olds, daily Facebook use plummeted to 47% (from 69% in 2022), while **70% use TikTok** and **85% use Snapchat**. The 12–24 age group now spends more time on social media alone than on TV and streaming combined. Conversely, the 65+ demographic is *increasing* social media use while younger cohorts express desire to reduce screen time — over 50% of Danes aged 12+ said they wanted to cut social media time.

For **public discourse**, Facebook remains the #1 social media news source (**32%** of Danes get news there), followed by YouTube (28%), Instagram (19%), and TikTok (15%, growing rapidly). X/Twitter, despite only 13% penetration, punches far above its weight in political debate — Danish defence researchers have found X discussions closely mirror parliamentary debate themes. LinkedIn is the **only major platform showing consistent growth** in daily usage through 2024, driven by professional discourse. DR Analyse's "Medieudviklingen 2024" and Danmarks Statistik's "It-anvendelse i befolkningen 2024" are the authoritative sources for these figures; DataReportal and Reuters Institute Digital News Report provide supplementary data.

---

## 8. GDELT's Danish coverage is free but limited

GDELT has supported Danish since its **Translingual 1.0 launch in February 2015**, machine-translating all Danish content into English via a custom pipeline for processing through its Event and Global Knowledge Graph systems. The database updates every 15 minutes and is entirely free via Google BigQuery and various APIs.

However, quality concerns are substantial. Academic research ranks Danish among the **better-performing languages for Google Translate** (Aiken, 2019), but broader assessments place Scandinavian accuracy at **60–80%** — below the 80–90% achieved for major European languages. GDELT's own translation pipeline degrades quality during high-volume periods to maintain throughput. More fundamentally, a ProDem study found that only **21% of valid GDELT protest event URLs** actually described real protests, and a 2025 MDPI review estimated overall key field accuracy at just **~55%** with **~20% data redundancy**.

GDELT does not publish a list of monitored Danish sources, making coverage verification impossible. Denmark does not appear in GDELT's top 10 countries by event volume (dominated by the US, UK, Russia, India, and China), likely representing a fraction of 1% of total events. The platform is best suited for large-scale, cross-language trend analysis where translation artifacts and false positives can be managed statistically, not for precise Danish-language research.

---

## 9. Event Registry offers stronger Danish NLP but at a cost

Event Registry (marketed as **NewsAPI.ai**) indexes **150,000+ sources globally in 60+ languages**, including Danish, with both real-time and historical data since 2014. Unlike GDELT, it performs **native-language NLP** on Danish content — entity recognition, categorization, sentiment analysis, and cross-language event clustering — avoiding translation artifacts entirely. Custom source additions are available on request.

Its key limitation for Danish researchers: **structured Event Types** (sentence-level extraction across 136 categories) remain **English-only**, with multilingual support listed as "coming soon." Pricing operates on a token system starting at **$90/month for 5,000 tokens** (1 token per recent article search retrieving up to 100 articles; 5 tokens per historical search year). Academic discounts are available. The platform is well-regarded commercially (4.7+ Trustpilot rating, used by Bloomberg, World Bank, Palantir) but token costs can escalate quickly for large-scale historical Danish research.

**MediaCloud**, the open-source academic alternative, covers 60,000+ sources with curated country collections, but Danish language processing support appears minimal. It is free with rate limits (~300 web searches/week) but better suited for English-language media ecosystem research than Danish-language analysis.

---

## 10. Threads joins Meta Content Library for researchers

Meta's Threads API, launched **June 18, 2024**, is free and expanding rapidly. As of mid-2025, it supports post publishing, content retrieval, reply management, analytics, keyword/mention search, real-time webhooks, poll creation, location tagging, and public profile access. Rate limits cap publishing at **250 API-published posts per 24 hours** per account, with OAuth 2.0 authentication required.

Crucially for researchers, **Threads is included in the Meta Content Library (MCL)**, which provides access to public content from profiles with **1,000+ followers** across Facebook, Instagram, and Threads. The MCL offers both a web search interface and a programmatic API with 100+ queryable data fields. Researchers at academic institutions or nonprofits apply through Meta's Research Tools Manager, with independent review by France's **CASD** (Secure Data Access Center) typically taking 2–6 weeks. Analysis must occur within a cleanroom environment — Meta's free Secure Research Environment or the SOMAR Virtual Data Enclave at the University of Michigan (**$371/month per team** since January 2026, plus a $1,000 one-time project start fee). A notable limitation: Threads data **cannot be exported as CSV** from the MCL, unlike Facebook and Instagram data from widely-known accounts.

---

## Conclusion: strategic considerations for Danish media researchers

The Danish media data landscape in 2026 is defined by a paradox: extraordinary data richness combined with increasingly stringent access rules. **Infomedia remains the non-negotiable foundation** for any serious Danish news research, offering comprehensive historical coverage through a dedicated research API accessible via university subscriptions. For real-time monitoring, RSS feeds from major outlets provide a surprisingly robust and free alternative — DR alone offers 20+ feeds requiring no authentication.

The legal framework has shifted decisively in researchers' favor for platform data, but only for specific purposes. The DSA's Article 40 — now backed by significant enforcement actions including €120M in fines against X — creates enforceable rights to public platform data for systemic risk research. This effectively supersedes the restrictive API regimes platforms had imposed. However, GDPR compliance remains non-trivial: Danish researchers must navigate the Databeskyttelsesloven's "significant societal importance" threshold, near-mandatory DPIAs, and strict purpose limitation rules. The practical path is to use Art. 6(1)(e) with Art. 89 safeguards as the legal basis, publish a public privacy notice, pseudonymize early and often, and secure Datatilsynet authorization before any data disclosure.

For international news databases, the choice depends on the trade-off between cost and quality. GDELT is free but noisy (55% accuracy, translation artifacts); Event Registry offers cleaner Danish NLP but costs $90+/month. Neither replaces Infomedia for Danish-specific research. LinkedIn remains the hardest platform to access legally in Europe — the KASPR fine signals that commercial scraping services carry real regulatory risk, making the DSA researcher access pathway the safest route despite its narrow scope.