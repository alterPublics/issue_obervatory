"""Pydantic request/response schemas for scraping jobs.

Used by the scraping job API routes for validation, serialisation, and
OpenAPI documentation generation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ScrapingJobCreate(BaseModel):
    """Payload for creating a new scraping job.

    Attributes:
        source_type: ``"collection_run"`` to enrich thin records from a prior
            collection run, or ``"manual_urls"`` for user-supplied URLs.
        source_collection_run_id: UUID of the collection run to enrich.
            Required when ``source_type="collection_run"``.
        source_urls: List of URLs to scrape.
            Required when ``source_type="manual_urls"``.
        query_design_id: Optional reference to a query design for bookkeeping.
        delay_min: Minimum inter-request delay in seconds (default 2.0).
        delay_max: Maximum inter-request delay in seconds (default 5.0).
        timeout_seconds: HTTP request timeout (default 30).
        respect_robots_txt: Whether to honour robots.txt rules (default True).
        use_playwright_fallback: Whether to retry JS-only pages with Playwright
            (default True).
        max_retries: Per-URL retry count on transient errors (default 2).
    """

    source_type: str = Field(pattern="^(collection_run|manual_urls)$")
    source_collection_run_id: Optional[uuid.UUID] = None
    source_urls: Optional[List[str]] = None
    query_design_id: Optional[uuid.UUID] = None

    delay_min: float = Field(default=2.0, ge=0.0)
    delay_max: float = Field(default=5.0, ge=0.0)
    timeout_seconds: int = Field(default=30, ge=5, le=300)
    respect_robots_txt: bool = True
    use_playwright_fallback: bool = True
    max_retries: int = Field(default=2, ge=0, le=10)


class ScrapingJobRead(BaseModel):
    """Full representation of a persisted scraping job.

    Returned by list, create, and detail endpoints.
    """

    id: uuid.UUID
    created_by: uuid.UUID
    query_design_id: Optional[uuid.UUID]
    source_type: str
    source_collection_run_id: Optional[uuid.UUID]
    source_urls: Optional[list]

    delay_min: float
    delay_max: float
    timeout_seconds: int
    respect_robots_txt: bool
    use_playwright_fallback: bool
    max_retries: int

    status: str
    celery_task_id: Optional[str]
    error_message: Optional[str]

    total_urls: int
    urls_enriched: int
    urls_failed: int
    urls_skipped: int

    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)
