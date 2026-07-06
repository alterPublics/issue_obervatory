"""Unit tests for the URL extraction enricher.

Focus on platform-specific tagging of the record's own ``url`` field so
downstream consumers (e.g. the domain network builder) can safely filter
``type="self_reference"`` without dropping legitimate outbound links.
"""

from __future__ import annotations

import pytest

from issue_observatory.analysis.enrichments.url_extractor import UrlExtractor


@pytest.fixture
def extractor() -> UrlExtractor:
    return UrlExtractor()


class TestGoogleSearchUrlExtraction:
    """Google Search target URLs must be tagged ``structured``, not ``self_reference``.

    The Google Search collector populates ``record.url`` from the Serper /
    SerpAPI ``link`` field — which is the outbound search target, not a
    post permalink.  Tagging it as ``self_reference`` would make the
    domain-network self-reference filter silently drop every Google Search
    record.
    """

    @pytest.mark.asyncio
    async def test_google_search_link_is_structured(
        self, extractor: UrlExtractor
    ) -> None:
        record = {
            "platform": "google_search",
            "url": "https://www.dr.dk/nyheder/klima",
            "text_content": None,
            "raw_metadata": {
                "title": "Klima",
                "link": "https://www.dr.dk/nyheder/klima",
                "snippet": "...",
                "displayLink": "dr.dk",
            },
        }
        result = await extractor.enrich(record)

        assert result["urls_found"] == 1
        entry = result["urls"][0]
        assert entry["type"] == "structured"
        assert entry["domain"] == "dr.dk"

    @pytest.mark.asyncio
    async def test_google_search_is_applicable(
        self, extractor: UrlExtractor
    ) -> None:
        """``is_applicable`` should stay True for Google Search via structured fields."""
        record = {
            "platform": "google_search",
            "url": "https://www.dr.dk/nyheder/klima",
            "text_content": None,
            "raw_metadata": {"link": "https://www.dr.dk/nyheder/klima"},
        }
        assert extractor.is_applicable(record) is True

    @pytest.mark.asyncio
    async def test_google_search_without_link_yields_nothing(
        self, extractor: UrlExtractor
    ) -> None:
        """Defensive: if ``link`` is missing, no URL is emitted (no silent self_reference)."""
        record = {
            "platform": "google_search",
            "url": "https://www.dr.dk/nyheder/klima",
            "text_content": None,
            "raw_metadata": {},
        }
        result = await extractor.enrich(record)
        assert result["urls_found"] == 0


class TestNonGoogleSearchSelfReferencePreserved:
    """Other platforms still tag ``record.url`` as ``self_reference``."""

    @pytest.mark.asyncio
    async def test_bluesky_post_url_is_self_reference(
        self, extractor: UrlExtractor
    ) -> None:
        record = {
            "platform": "bluesky",
            "url": "https://bsky.app/profile/alice.bsky.social/post/abc123",
            "text_content": "Check https://example.com/story",
            "raw_metadata": {},
        }
        result = await extractor.enrich(record)
        types = {u["type"] for u in result["urls"]}
        assert "self_reference" in types
        assert "text_extracted" in types


class TestShortenerFilter:
    """URLs on known shorteners (t.co, bit.ly, ...) are dropped entirely.

    Shorteners mask the real destination.  When the upstream source
    exposes ``expanded_url`` the real domain is already extracted via
    the structured-field path; when it does not, the t.co URL is
    uninformative and would otherwise dominate domain networks.
    """

    @pytest.mark.asyncio
    async def test_bare_t_co_url_in_text_is_dropped(
        self, extractor: UrlExtractor
    ) -> None:
        record = {
            "platform": "x_twitter",
            "url": "https://x.com/alice/status/123",
            "text_content": "Læs mere https://t.co/abc123",
            "raw_metadata": {},
        }
        result = await extractor.enrich(record)
        cleaned_domains = {u["domain"] for u in result["urls"]}
        assert "t.co" not in cleaned_domains

    @pytest.mark.asyncio
    async def test_expanded_url_keeps_real_domain_even_with_t_co_in_text(
        self, extractor: UrlExtractor
    ) -> None:
        """When entities.urls has a proper expanded_url the real domain wins;
        the t.co fragment in text_content is silently dropped."""
        record = {
            "platform": "x_twitter",
            "url": "https://x.com/alice/status/123",
            "text_content": "Se artiklen https://t.co/abc123 i dag",
            "raw_metadata": {
                "entities": {
                    "urls": [
                        {"expanded_url": "https://borsen.dk/nyheder/okonomi/formueskat"}
                    ]
                }
            },
        }
        result = await extractor.enrich(record)
        domains = {u["domain"] for u in result["urls"]}
        assert "borsen.dk" in domains
        assert "t.co" not in domains

    @pytest.mark.asyncio
    async def test_bit_ly_is_dropped(self, extractor: UrlExtractor) -> None:
        record = {
            "platform": "bluesky",
            "url": "https://bsky.app/profile/alice.bsky.social/post/abc",
            "text_content": "Spændende læsning https://bit.ly/42abcXYZ",
            "raw_metadata": {},
        }
        result = await extractor.enrich(record)
        domains = {u["domain"] for u in result["urls"]}
        assert "bit.ly" not in domains

    def test_is_shortener_url_recognises_common_shorteners(self) -> None:
        from issue_observatory.analysis.url_cleaner import is_shortener_url

        for url in [
            "https://t.co/abc",
            "https://bit.ly/xyz",
            "http://ow.ly/foo",
            "https://tinyurl.com/bar",
            "https://lnkd.in/abc",
        ]:
            assert is_shortener_url(url) is True, url

    def test_is_shortener_url_rejects_real_domains(self) -> None:
        from issue_observatory.analysis.url_cleaner import is_shortener_url

        for url in [
            "https://dr.dk/nyheder",
            "https://borsen.dk/article",
            "https://twitter.com/alice/status/1",
            "https://www.example.com/path",
        ]:
            assert is_shortener_url(url) is False, url
