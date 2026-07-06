"""Pydantic request/response schemas for the extracted URLs browser.

Used by the extracted URLs API routes for validation, serialisation, and
OpenAPI documentation generation.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ExtractedUrlAggregated(BaseModel):
    """Aggregated URL row for the URL browser table.

    Attributes:
        url_cleaned: Normalised URL (without tracking parameters).
        url_domain: Registered domain extracted from the URL.
        total_count: Number of times this URL appeared in collected content.
        platform_count: Number of distinct platforms that linked to this URL.
        platforms_list: List of distinct platform names.
        first_seen: Earliest extraction timestamp across all appearances.
    """

    url_cleaned: str
    url_domain: str
    total_count: int
    platform_count: int
    platforms_list: list[str]
    first_seen: datetime

    model_config = ConfigDict(from_attributes=True)


class ExtractedUrlStats(BaseModel):
    """Summary statistics for the current URL filter.

    Attributes:
        total_unique_urls: Count of distinct normalised URLs.
        total_appearances: Total row count before deduplication.
        unique_domains: Count of distinct registered domains.
    """

    total_unique_urls: int
    total_appearances: int
    unique_domains: int


class ExtractedUrlFilterParams(BaseModel):
    """Filter parameters for the URL browser.

    Attributes:
        project_id: Restrict to URLs from a specific project.
        query_design_id: Restrict to URLs from a specific query design.
        search_term: Restrict to URLs matched by this search term.
        platform: Restrict to URLs extracted from this platform.
        exclude_social: When True, omit social media domains from results.
        video_only: Restrict to video platform domains (``"youtube"`` or ``"tiktok"``).
        sort_by: Column to order results by.
        page: 1-based page number.
        page_size: Number of rows per page (10-5000).
    """

    project_id: uuid.UUID | None = None
    query_design_id: uuid.UUID | None = None
    search_term: str | None = None
    platform: str | None = None
    category: str | None = None  # "news" | "search" | "web" | "social_media" | None
    exclude_social: bool = True
    video_only: str | None = None  # "youtube" | "tiktok" | None
    sort_by: str = Field(default="count", pattern="^(count|domain|first_seen)$")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=10, le=5000)


class ScrapeFromUrlsRequest(BaseModel):
    """Request to create a scraping job from extracted URLs.

    Either ``selected_urls`` or ``url_filter_criteria`` must be provided.
    ``selected_urls`` takes precedence when both are supplied.

    Attributes:
        url_filter_criteria: Filter the ``extracted_urls`` table to derive the
            URL list dynamically.
        selected_urls: Explicit URL list; overrides ``url_filter_criteria``.
        delay_min: Minimum inter-request delay in seconds.
        delay_max: Maximum inter-request delay in seconds.
        timeout_seconds: HTTP request timeout (5-300 s).
        respect_robots_txt: Whether to honour robots.txt disallow rules.
        use_playwright_fallback: Whether to retry JS-only pages with Playwright.
    """

    url_filter_criteria: ExtractedUrlFilterParams | None = None
    selected_urls: list[str] | None = None  # Explicit URL list (overrides filter)
    delay_min: float = Field(default=2.0, ge=0.0)
    delay_max: float = Field(default=5.0, ge=0.0)
    timeout_seconds: int = Field(default=30, ge=5, le=300)
    respect_robots_txt: bool = True
    use_playwright_fallback: bool = True
