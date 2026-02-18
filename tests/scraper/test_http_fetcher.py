"""Unit tests for the HTTP fetcher module.

Tests robots.txt blocking, binary content-type skipping, JS-shell detection,
HTTP error handling, and successful fetches using mocked httpx responses.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from issue_observatory.scraper.http_fetcher import (
    FetchResult,
    _is_binary_content_type,
    _is_js_shell,
    fetch_url,
)


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


class TestIsBinaryContentType:
    def test_pdf_is_binary(self) -> None:
        assert _is_binary_content_type("application/pdf") is True

    def test_image_is_binary(self) -> None:
        assert _is_binary_content_type("image/png") is True
        assert _is_binary_content_type("image/jpeg") is True

    def test_video_is_binary(self) -> None:
        assert _is_binary_content_type("video/mp4") is True

    def test_html_not_binary(self) -> None:
        assert _is_binary_content_type("text/html; charset=utf-8") is False

    def test_json_not_binary(self) -> None:
        assert _is_binary_content_type("application/json") is False

    def test_vnd_is_binary(self) -> None:
        assert _is_binary_content_type("application/vnd.ms-excel") is True


class TestIsJsShell:
    def test_empty_is_js_shell(self) -> None:
        assert _is_js_shell("") is True

    def test_short_body_is_js_shell(self) -> None:
        assert _is_js_shell("<html><body></body></html>") is True

    def test_real_article_not_js_shell(self) -> None:
        html = "<html><body>" + ("word " * 200) + "</body></html>"
        assert _is_js_shell(html) is False


# ---------------------------------------------------------------------------
# Integration tests using respx (mock httpx)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFetchUrl:
    async def test_successful_fetch(self) -> None:
        html_body = "<html><body>" + ("word " * 200) + "</body></html>"
        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/article").mock(
                return_value=httpx.Response(
                    200,
                    text=html_body,
                    headers={"content-type": "text/html; charset=utf-8"},
                )
            )
            async with httpx.AsyncClient() as client:
                result = await fetch_url(
                    "https://example.com/article",
                    client=client,
                    timeout=10,
                    respect_robots=False,
                    robots_cache={},
                )

        assert result.error is None
        assert result.html == html_body
        assert result.status_code == 200
        assert result.needs_playwright is False

    async def test_http_404_returns_error(self) -> None:
        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/missing").mock(return_value=httpx.Response(404))
            async with httpx.AsyncClient() as client:
                result = await fetch_url(
                    "https://example.com/missing",
                    client=client,
                    timeout=10,
                    respect_robots=False,
                    robots_cache={},
                )

        assert result.html is None
        assert result.status_code == 404
        assert "404" in (result.error or "")

    async def test_binary_content_type_skipped(self) -> None:
        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/doc.pdf").mock(
                return_value=httpx.Response(
                    200,
                    content=b"%PDF-1.4",
                    headers={"content-type": "application/pdf"},
                )
            )
            async with httpx.AsyncClient() as client:
                result = await fetch_url(
                    "https://example.com/doc.pdf",
                    client=client,
                    timeout=10,
                    respect_robots=False,
                    robots_cache={},
                )

        assert result.html is None
        assert result.error is not None
        assert "binary" in result.error.lower()

    async def test_js_shell_sets_needs_playwright(self) -> None:
        short_html = "<html><body><div id='app'></div></body></html>"
        with respx.mock(base_url="https://spa.example.com") as mock:
            mock.get("/").mock(
                return_value=httpx.Response(
                    200,
                    text=short_html,
                    headers={"content-type": "text/html"},
                )
            )
            async with httpx.AsyncClient() as client:
                result = await fetch_url(
                    "https://spa.example.com/",
                    client=client,
                    timeout=10,
                    respect_robots=False,
                    robots_cache={},
                )

        assert result.needs_playwright is True
        assert result.html == short_html

    async def test_timeout_returns_error(self) -> None:
        with respx.mock(base_url="https://slow.example.com") as mock:
            mock.get("/slow").mock(side_effect=httpx.TimeoutException("timeout"))
            async with httpx.AsyncClient() as client:
                result = await fetch_url(
                    "https://slow.example.com/slow",
                    client=client,
                    timeout=5,
                    respect_robots=False,
                    robots_cache={},
                )

        assert result.html is None
        assert result.error == "timeout"

    async def test_robots_txt_blocking(self) -> None:
        """When robots.txt disallows, the URL should be blocked."""
        robots_cache: dict[str, bool] = {}

        with patch(
            "issue_observatory.scraper.http_fetcher._is_allowed_by_robots",
            return_value=False,
        ):
            async with httpx.AsyncClient() as client:
                result = await fetch_url(
                    "https://blocked.example.com/secret",
                    client=client,
                    timeout=10,
                    respect_robots=True,
                    robots_cache=robots_cache,
                )

        assert result.html is None
        assert result.error is not None
        assert "robots" in result.error.lower()

    async def test_robots_txt_disabled(self) -> None:
        """With respect_robots=False, robots.txt should not be checked."""
        html_body = "<html><body>" + ("word " * 200) + "</body></html>"
        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/private").mock(
                return_value=httpx.Response(
                    200,
                    text=html_body,
                    headers={"content-type": "text/html"},
                )
            )
            async with httpx.AsyncClient() as client:
                result = await fetch_url(
                    "https://example.com/private",
                    client=client,
                    timeout=10,
                    respect_robots=False,
                    robots_cache={},
                )

        assert result.error is None
        assert result.html is not None
