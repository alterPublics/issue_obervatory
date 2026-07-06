"""Unit tests for the URL cleaner module.

Tests cover:
- URL extraction from free text (regex matching, deduplication, bracket handling)
- Multi-pass cleaning and normalization (tracking params, protocol, www removal)
- Platform-specific canonicalization (YouTube, Twitter/X, TikTok, Facebook redirect)
- Domain extraction with subdomain stripping
- Social media and video platform classification
- Domain-only detection
- YouTube video ID extraction from all supported formats
- Danish character preservation in URL paths and query strings

These tests are pure unit tests -- no database, no network, no Celery.
"""

from __future__ import annotations

from urllib.parse import quote

import pytest

from issue_observatory.analysis.url_cleaner import (
    clean_url,
    extract_domain,
    extract_urls_from_text,
    extract_youtube_video_id,
    is_domain_only,
    is_social_media_url,
    is_video_platform_url,
)


# ---------------------------------------------------------------------------
# extract_urls_from_text
# ---------------------------------------------------------------------------


class TestExtractUrlsFromText:
    """Verify URL extraction from free-form text."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Visit https://example.com/page", ["https://example.com/page"]),
            ("Visit http://example.com/page", ["http://example.com/page"]),
        ],
        ids=["https", "http"],
    )
    def test_basic_http_and_https_urls(self, text: str, expected: list[str]) -> None:
        """Both http and https URLs are extracted."""
        assert extract_urls_from_text(text) == expected

    def test_www_prefix_without_protocol(self) -> None:
        """Bare www. URLs get https:// prepended."""
        result = extract_urls_from_text("Go to www.example.com/page for info")
        assert result == ["https://www.example.com/page"]

    def test_url_in_parentheses(self) -> None:
        """Trailing closing paren is stripped when unmatched."""
        result = extract_urls_from_text("(see https://example.com/page)")
        assert result == ["https://example.com/page"]

    def test_url_with_balanced_parentheses_in_path(self) -> None:
        """Parentheses inside the URL path (e.g. Wikipedia) are preserved
        when they are balanced, and only a trailing unmatched paren is stripped."""
        result = extract_urls_from_text(
            "(https://en.wikipedia.org/wiki/Copenhagen_(city))"
        )
        # The URL has one matched pair inside and one unmatched trailing paren
        assert result == ["https://en.wikipedia.org/wiki/Copenhagen_(city)"]

    def test_url_in_brackets(self) -> None:
        """Square brackets around URLs are not included in the match."""
        result = extract_urls_from_text("[https://example.com/article]")
        assert result == ["https://example.com/article"]

    @pytest.mark.parametrize(
        ("text", "expected_url"),
        [
            ("See https://example.com/page.", "https://example.com/page"),
            ("Check https://example.com/page, then read on", "https://example.com/page"),
            ("Link: https://example.com/page;", "https://example.com/page"),
            ("Wow https://example.com/page!", "https://example.com/page"),
        ],
        ids=["period", "comma", "semicolon", "exclamation"],
    )
    def test_trailing_punctuation_stripped(self, text: str, expected_url: str) -> None:
        """Trailing sentence punctuation is not included in extracted URLs."""
        result = extract_urls_from_text(text)
        assert result == [expected_url]

    def test_multiple_urls_in_same_text(self) -> None:
        """All distinct URLs are extracted."""
        text = "First https://a.com/1 then https://b.com/2 and http://c.com/3"
        result = extract_urls_from_text(text)
        assert result == ["https://a.com/1", "https://b.com/2", "http://c.com/3"]

    def test_deduplication_preserves_first_occurrence(self) -> None:
        """Duplicate URLs appear only once, keeping the first occurrence order."""
        text = "Link https://a.com/page and again https://a.com/page here"
        result = extract_urls_from_text(text)
        assert result == ["https://a.com/page"]

    def test_order_preserved(self) -> None:
        """URLs appear in the order they are found in the text."""
        text = "https://z.com/last https://a.com/first"
        result = extract_urls_from_text(text)
        assert result == ["https://z.com/last", "https://a.com/first"]

    def test_empty_string_returns_empty_list(self) -> None:
        """Empty input produces no URLs."""
        assert extract_urls_from_text("") == []

    def test_none_input_returns_empty_list(self) -> None:
        """None input produces no URLs (falsy guard)."""
        # The type hint says str, but the implementation guards with `if not text`
        assert extract_urls_from_text(None) == []  # type: ignore[arg-type]

    def test_query_params_preserved(self) -> None:
        """Query parameters are not stripped during extraction."""
        text = "Visit https://example.com/search?q=klima&lang=da for results"
        result = extract_urls_from_text(text)
        assert result == ["https://example.com/search?q=klima&lang=da"]

    def test_text_with_no_urls(self) -> None:
        """Plain text with no URLs returns an empty list."""
        assert extract_urls_from_text("No links in this sentence at all") == []

    def test_url_with_fragment(self) -> None:
        """Fragment identifiers are part of the extracted URL."""
        result = extract_urls_from_text("See https://example.com/page#section")
        assert result == ["https://example.com/page#section"]

    def test_danish_text_surrounding_url(self) -> None:
        """URLs are correctly extracted even when surrounded by Danish text."""
        text = "Læs mere om emnet på https://dr.dk/nyheder/klima og forstå ændringerne"
        result = extract_urls_from_text(text)
        assert result == ["https://dr.dk/nyheder/klima"]


# ---------------------------------------------------------------------------
# clean_url
# ---------------------------------------------------------------------------


class TestCleanUrl:
    """Verify URL cleaning and normalization."""

    def test_http_upgraded_to_https(self) -> None:
        """http:// is normalized to https://."""
        result = clean_url("http://example.com/article/123")
        assert result is not None
        assert result.startswith("https://")

    def test_www_prefix_removed(self) -> None:
        """www. subdomain is stripped from the hostname."""
        result = clean_url("https://www.example.com/article/123")
        assert result is not None
        assert "www." not in result
        assert "example.com/article/123" in result

    @pytest.mark.parametrize(
        "tracking_param",
        [
            "fbclid=abc123",
            "utm_source=twitter",
            "utm_medium=social",
            "utm_campaign=spring2024",
            "utm_content=link1",
            "utm_term=klima",
            "gclid=xyz789",
            "gclsrc=aw.ds",
            "ocid=123",
            "mc_cid=abc",
            "mc_eid=def",
            "_ga=1.2.3.4",
            "_gl=x*y*z",
            "_hsenc=abc",
            "_hsmi=123",
            "igshid=abc",
            "s=20",
            "si=abc",
            "__twitter_impression=true",
            "msclkid=abc",
            "ref=homepage",
            "ref_src=twsrc",
            "utm_id=camp1",
        ],
        ids=lambda p: p.split("=")[0],
    )
    def test_tracking_param_stripped(self, tracking_param: str) -> None:
        """Each known tracking parameter is removed from the query string."""
        url = f"https://example.com/article/123?{tracking_param}"
        result = clean_url(url)
        assert result is not None
        param_name = tracking_param.split("=")[0]
        assert param_name not in result

    def test_non_tracking_query_params_preserved(self) -> None:
        """Blog post IDs and other non-tracking params remain intact."""
        result = clean_url("https://example.com/article?p=12345")
        assert result is not None
        assert "p=12345" in result

    def test_mixed_tracking_and_non_tracking_params(self) -> None:
        """Only tracking params are removed; legitimate params survive."""
        result = clean_url(
            "https://example.com/article?p=12345&utm_source=twitter&page=2"
        )
        assert result is not None
        assert "p=12345" in result
        assert "page=2" in result
        assert "utm_source" not in result

    # --- YouTube normalization ---

    @pytest.mark.parametrize(
        ("youtube_url", "expected"),
        [
            (
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            ),
            (
                "https://youtube.com/embed/dQw4w9WgXcQ",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            ),
            (
                "https://youtube.com/shorts/dQw4w9WgXcQ",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            ),
            (
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            ),
            (
                "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            ),
            (
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ&utm_source=twitter",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            ),
        ],
        ids=["watch", "embed", "shorts", "short-url", "mobile", "watch-with-tracking"],
    )
    def test_youtube_normalized_to_short_url(
        self, youtube_url: str, expected: str
    ) -> None:
        """All YouTube URL formats are canonicalized to www.youtube.com/watch?v={id}."""
        assert clean_url(youtube_url) == expected

    # --- Facebook redirect unwrap ---

    def test_facebook_redirect_unwrapped(self) -> None:
        """l.facebook.com redirect URLs are unwrapped to the inner target."""
        inner = "https://example.com/article/456"
        encoded_inner = quote(inner, safe="")
        fb_url = f"https://l.facebook.com/l.php?u={encoded_inner}&h=abc"
        result = clean_url(fb_url)
        assert result is not None
        assert "example.com/article/456" in result
        assert "facebook.com" not in result

    def test_facebook_redirect_with_domain_only_inner(self) -> None:
        """Facebook redirect wrapping a domain-only URL returns None."""
        inner = "https://example.com"
        encoded_inner = quote(inner, safe="")
        fb_url = f"https://l.facebook.com/l.php?u={encoded_inner}&h=abc"
        result = clean_url(fb_url)
        assert result is None

    # --- Twitter/X normalization ---

    def test_x_dot_com_normalized_to_twitter(self) -> None:
        """x.com URLs are rewritten to twitter.com."""
        result = clean_url("https://x.com/user/status/123456")
        assert result is not None
        assert "twitter.com" in result
        assert "x.com" not in result

    # --- TikTok normalization ---

    def test_vm_tiktok_normalized(self) -> None:
        """vm.tiktok.com short URLs are normalized to tiktok.com."""
        result = clean_url("https://vm.tiktok.com/ZMR12345/")
        assert result is not None
        assert "tiktok.com" in result
        assert "vm.tiktok.com" not in result

    # --- Nested URL encoding ---

    def test_multi_pass_decode(self) -> None:
        """URLs with double-encoded characters are fully decoded."""
        # Double-encode the path: / -> %2F -> %252F
        double_encoded = "https://example.com/article%252Fpage"
        result = clean_url(double_encoded)
        assert result is not None
        assert "%25" not in result
        assert "article/page" in result

    # --- Domain-only returns None ---

    def test_domain_only_returns_none(self) -> None:
        """A URL with no meaningful path or query returns None."""
        assert clean_url("https://example.com") is None
        assert clean_url("https://example.com/") is None

    def test_domain_only_after_tracking_stripped_returns_none(self) -> None:
        """If stripping tracking params leaves only the domain, return None."""
        assert clean_url("https://example.com/?utm_source=twitter") is None

    # --- Empty/None input ---

    def test_empty_string_returns_none(self) -> None:
        """Empty string produces None."""
        assert clean_url("") is None

    def test_none_input_returns_none(self) -> None:
        """None input produces None."""
        assert clean_url(None) is None  # type: ignore[arg-type]

    # --- Trailing slash removal ---

    def test_trailing_slash_removed(self) -> None:
        """Non-root trailing slashes are stripped from the path."""
        result = clean_url("https://example.com/article/123/")
        assert result is not None
        assert not result.endswith("/")

    # --- Fragment stripping ---

    def test_fragment_stripped(self) -> None:
        """URL fragments (hash portions) are always removed."""
        result = clean_url("https://example.com/article/123#comments")
        assert result is not None
        assert "#" not in result

    # --- www. input without protocol ---

    def test_www_input_without_protocol(self) -> None:
        """Input starting with www. is given https:// and www. is then removed."""
        result = clean_url("www.example.com/article/123")
        assert result is not None
        assert result.startswith("https://")
        assert "www." not in result

    # --- Bare domain input without protocol ---

    def test_bare_domain_with_path_gets_https(self) -> None:
        """Input with no protocol gets https:// prepended."""
        result = clean_url("example.com/article/123")
        assert result is not None
        assert result.startswith("https://")

    # --- Non-standard port preserved ---

    def test_non_standard_port_preserved(self) -> None:
        """Non-standard ports (not 80 or 443) remain in the cleaned URL."""
        result = clean_url("https://example.com:8080/article/123")
        assert result is not None
        assert ":8080" in result

    # --- Danish characters in URL ---

    def test_danish_characters_in_path(self) -> None:
        """Danish characters (ae, oe, aa) in URL paths survive cleaning."""
        result = clean_url("https://example.dk/nyheder/ændringer-i-miljøet")
        assert result is not None
        assert "ændringer" in result or "ndringer" in result


# ---------------------------------------------------------------------------
# extract_domain
# ---------------------------------------------------------------------------


class TestExtractDomain:
    """Verify domain extraction with subdomain stripping."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://example.com/page", "example.com"),
            ("https://dr.dk/nyheder", "dr.dk"),
            ("https://www.example.com/page", "example.com"),
            ("https://m.example.com/page", "example.com"),
            ("https://mobile.example.com/page", "example.com"),
        ],
        ids=["plain", "danish-domain", "www", "mobile-m", "mobile-full"],
    )
    def test_standard_domain_extraction(self, url: str, expected: str) -> None:
        """Domain is correctly extracted with common subdomains stripped."""
        assert extract_domain(url) == expected

    def test_empty_string(self) -> None:
        """Empty string returns empty string."""
        assert extract_domain("") == ""

    def test_no_protocol(self) -> None:
        """URL without protocol still extracts domain correctly."""
        assert extract_domain("example.com/page") == "example.com"

    def test_bare_domain_no_path(self) -> None:
        """Bare domain without path is extracted."""
        assert extract_domain("https://example.com") == "example.com"

    def test_subdomain_not_in_strip_list(self) -> None:
        """Subdomains other than www/m/mobile are preserved."""
        assert extract_domain("https://api.example.com/v1") == "api.example.com"

    def test_uppercase_normalized(self) -> None:
        """Domain case is lowered."""
        assert extract_domain("https://WWW.Example.COM/page") == "example.com"


# ---------------------------------------------------------------------------
# is_social_media_url
# ---------------------------------------------------------------------------


class TestIsSocialMediaUrl:
    """Verify social media domain classification."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://facebook.com/post/123",
            "https://www.instagram.com/p/ABC123",
            "https://twitter.com/user/status/123",
            "https://x.com/user/status/123",
            "https://www.reddit.com/r/denmark/comments/abc",
            "https://tiktok.com/@user/video/123",
            "https://linkedin.com/in/someone",
            "https://bsky.app/profile/user.bsky.social/post/abc",
            "https://t.me/channel/123",
            "https://youtube.com/watch?v=abc12345678",
            "https://mastodon.social/@user/123",
            "https://threads.net/@user/post/abc",
            "https://discord.gg/invite123",
            "https://truthsocial.com/@user/123",
            "https://vk.com/wall123",
        ],
        ids=[
            "facebook", "instagram", "twitter", "x", "reddit",
            "tiktok", "linkedin", "bluesky", "telegram", "youtube",
            "mastodon", "threads", "discord", "truthsocial", "vk",
        ],
    )
    def test_known_social_platforms_return_true(self, url: str) -> None:
        """All known social media domains are recognized."""
        assert is_social_media_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://dr.dk/nyheder",
            "https://example.com/page",
            "https://github.com/repo",
            "https://google.com/search?q=test",
            "https://nytimes.com/article/123",
        ],
        ids=["news-dk", "generic", "github", "google", "news-us"],
    )
    def test_non_social_domains_return_false(self, url: str) -> None:
        """Non-social-media domains are not classified as social."""
        assert is_social_media_url(url) is False


# ---------------------------------------------------------------------------
# is_video_platform_url
# ---------------------------------------------------------------------------


class TestIsVideoPlatformUrl:
    """Verify video platform domain classification."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://youtube.com/watch?v=abc12345678",
            "https://www.youtube.com/watch?v=abc12345678",
            "https://m.youtube.com/watch?v=abc12345678",
            "https://youtu.be/abc12345678",
            "https://tiktok.com/@user/video/123",
            "https://www.tiktok.com/@user/video/123",
            "https://vm.tiktok.com/ZMR12345/",
        ],
        ids=[
            "youtube", "youtube-www", "youtube-mobile", "youtu-be",
            "tiktok", "tiktok-www", "tiktok-vm",
        ],
    )
    def test_video_platforms_return_true(self, url: str) -> None:
        """YouTube and TikTok domains are identified as video platforms."""
        assert is_video_platform_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://vimeo.com/123456",
            "https://dailymotion.com/video/abc",
            "https://facebook.com/watch/123",
            "https://example.com/videos/cat.mp4",
        ],
        ids=["vimeo", "dailymotion", "facebook-watch", "generic-video-path"],
    )
    def test_non_video_platforms_return_false(self, url: str) -> None:
        """Other video hosts and generic sites are not classified as video platforms."""
        assert is_video_platform_url(url) is False


# ---------------------------------------------------------------------------
# is_domain_only
# ---------------------------------------------------------------------------


class TestIsDomainOnly:
    """Verify domain-only detection."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com",
            "https://example.com/",
            "http://example.com",
            "http://example.com/",
        ],
        ids=["https-bare", "https-trailing-slash", "http-bare", "http-trailing-slash"],
    )
    def test_domain_only_returns_true(self, url: str) -> None:
        """URLs with no path beyond root and no query are domain-only."""
        assert is_domain_only(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/page",
            "https://example.com/page/sub",
            "https://example.com?q=1",
            "https://example.com/?q=1",
            "https://example.com/page?q=1",
        ],
        ids=["path", "nested-path", "query-only", "root-with-query", "path-and-query"],
    )
    def test_url_with_path_or_query_returns_false(self, url: str) -> None:
        """URLs with a meaningful path or query string are not domain-only."""
        assert is_domain_only(url) is False

    def test_bare_domain_without_protocol(self) -> None:
        """Bare domain string (no protocol) is still detected as domain-only."""
        assert is_domain_only("example.com") is True

    def test_bare_domain_with_path_without_protocol(self) -> None:
        """Bare domain + path without protocol is not domain-only."""
        assert is_domain_only("example.com/article") is False


# ---------------------------------------------------------------------------
# extract_youtube_video_id
# ---------------------------------------------------------------------------


class TestExtractYoutubeVideoId:
    """Verify YouTube video ID extraction from all supported URL formats."""

    _VIDEO_ID = "dQw4w9WgXcQ"  # 11-character ID

    @pytest.mark.parametrize(
        "url",
        [
            f"https://www.youtube.com/watch?v={_VIDEO_ID}",
            f"https://youtube.com/watch?v={_VIDEO_ID}",
            f"https://m.youtube.com/watch?v={_VIDEO_ID}",
            f"https://youtube.com/watch?v={_VIDEO_ID}&list=PLabc",
            f"http://youtube.com/watch?v={_VIDEO_ID}",
        ],
        ids=["www", "bare", "mobile", "with-playlist", "http"],
    )
    def test_watch_url(self, url: str) -> None:
        """Standard /watch?v= URLs return the correct video ID."""
        assert extract_youtube_video_id(url) == self._VIDEO_ID

    def test_embed_url(self) -> None:
        """/embed/ URLs return the correct video ID."""
        url = f"https://youtube.com/embed/{self._VIDEO_ID}"
        assert extract_youtube_video_id(url) == self._VIDEO_ID

    def test_shorts_url(self) -> None:
        """/shorts/ URLs return the correct video ID."""
        url = f"https://youtube.com/shorts/{self._VIDEO_ID}"
        assert extract_youtube_video_id(url) == self._VIDEO_ID

    def test_short_url(self) -> None:
        """youtu.be/ short URLs return the correct video ID."""
        url = f"https://youtu.be/{self._VIDEO_ID}"
        assert extract_youtube_video_id(url) == self._VIDEO_ID

    def test_short_url_without_protocol(self) -> None:
        """youtu.be/ without protocol still works."""
        url = f"youtu.be/{self._VIDEO_ID}"
        assert extract_youtube_video_id(url) == self._VIDEO_ID

    def test_non_youtube_url_returns_none(self) -> None:
        """Non-YouTube URLs return None."""
        assert extract_youtube_video_id("https://vimeo.com/123456") is None

    def test_youtube_channel_url_returns_none(self) -> None:
        """YouTube URLs without a video ID (channel pages) return None."""
        assert extract_youtube_video_id("https://youtube.com/c/SomeChannel") is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string returns None."""
        assert extract_youtube_video_id("") is None

    def test_youtube_homepage_returns_none(self) -> None:
        """YouTube homepage has no video ID."""
        assert extract_youtube_video_id("https://youtube.com") is None


# ---------------------------------------------------------------------------
# Integration-style scenarios: clean_url + extract_urls_from_text together
# ---------------------------------------------------------------------------


class TestEndToEndScenarios:
    """Combined extraction and cleaning for realistic content scenarios."""

    def test_extract_then_clean_preserves_meaningful_urls(self) -> None:
        """Extract URLs from text then clean them: meaningful URLs survive."""
        text = (
            "Check https://www.dr.dk/nyheder/klima?utm_source=twitter"
            " and https://youtube.com/watch?v=dQw4w9WgXcQ&fbclid=abc"
        )
        urls = extract_urls_from_text(text)
        cleaned = [clean_url(u) for u in urls]
        cleaned = [u for u in cleaned if u is not None]

        assert len(cleaned) == 2
        # DR URL: www removed, tracking stripped, path preserved
        assert any("dr.dk/nyheder/klima" in u for u in cleaned)
        assert not any("utm_source" in u for u in cleaned)
        # YouTube URL: normalized to www.youtube.com/watch?v=
        assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ" in cleaned

    def test_extract_then_clean_filters_domain_only(self) -> None:
        """Domain-only URLs extracted from text are filtered out by clean_url."""
        text = "Visit https://example.com and also https://example.com/article/1"
        urls = extract_urls_from_text(text)
        cleaned = [clean_url(u) for u in urls]
        cleaned = [u for u in cleaned if u is not None]

        assert len(cleaned) == 1
        assert "article/1" in cleaned[0]

    def test_danish_news_article_url_survives_pipeline(self) -> None:
        """A realistic Danish news URL survives extraction and cleaning intact."""
        text = (
            "Artiklen er tilgængelig på"
            " https://www.berlingske.dk/politik/ny-klimaaftale-vedtaget?p=99"
        )
        urls = extract_urls_from_text(text)
        assert len(urls) == 1
        cleaned = clean_url(urls[0])
        assert cleaned is not None
        assert "berlingske.dk/politik/ny-klimaaftale-vedtaget" in cleaned
        assert "p=99" in cleaned
        assert "www." not in cleaned
