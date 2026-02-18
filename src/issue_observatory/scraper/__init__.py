"""Web scraper enrichment service.

Fetches and stores page text for URLs already present in ``content_records``
(produced by web archive arenas) or for a user-supplied list of URLs.

Sub-modules:
- ``config``             — constants and tuning parameters
- ``content_extractor``  — trafilatura-based article text extraction
- ``http_fetcher``       — async httpx-based page fetcher with robots.txt support
- ``playwright_fetcher`` — headless Chromium fallback for JS-heavy pages
- ``tasks``              — Celery tasks (``scrape_urls_task``, ``cancel_scraping_job_task``)
- ``router``             — FastAPI router (``/scraping-jobs/``)
"""
