"""URL extraction, cleaning, and standardization utilities.

Standalone stateless utility for extracting URLs from text, cleaning
tracking parameters, normalizing platform-specific URL formats, and
classifying URL types.

Inspired by spreadAnalysis's LinkCleaner approach but adapted for the
Issue Observatory's multi-platform content pipeline.

Key design principle: query parameters are NOT blindly stripped. Only an
explicit set of known tracking parameters is removed. Blog post IDs in
query strings (e.g., ``?p=12345``) are preserved.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse, urlunparse

# ---------------------------------------------------------------------------
# Known tracking parameters to strip
# ---------------------------------------------------------------------------

_TRACKING_PARAMS: frozenset[str] = frozenset({
    "fbclid",
    "ocid",
    "gclid",
    "gclsrc",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "utm_id",
    "mc_cid",
    "mc_eid",
    "_ga",
    "_gl",
    "_hsenc",
    "_hsmi",
    "igshid",
    "s",
    "si",
    "__twitter_impression",
    "msclkid",
    "ref",
    "ref_src",
})

# ---------------------------------------------------------------------------
# Social media domains
# ---------------------------------------------------------------------------

_SOCIAL_MEDIA_DOMAINS: frozenset[str] = frozenset({
    "facebook.com",
    "fb.com",
    "fb.me",
    "instagram.com",
    "twitter.com",
    "x.com",
    "t.co",
    "tiktok.com",
    "vm.tiktok.com",
    "reddit.com",
    "old.reddit.com",
    "linkedin.com",
    "pinterest.com",
    "tumblr.com",
    "snapchat.com",
    "threads.net",
    "mastodon.social",
    "bsky.app",
    "gab.com",
    "truth social.com",
    "truthsocial.com",
    "vk.com",
    "weibo.com",
    "telegram.org",
    "t.me",
    "discord.com",
    "discord.gg",
    "youtube.com",
    "youtu.be",
    "m.youtube.com",
})

_VIDEO_PLATFORM_DOMAINS: frozenset[str] = frozenset({
    "youtube.com",
    "youtu.be",
    "m.youtube.com",
    "www.youtube.com",
    "tiktok.com",
    "vm.tiktok.com",
    "www.tiktok.com",
})

#: Known URL shortener domains.  URLs resolving to these carry no analytic
#: signal — the real destination lives behind a redirect which we don't
#: resolve inline.  Collectors that expose ``expanded_url`` (e.g. Twitter's
#: ``entities.urls[].expanded_url``) surface the real domain via the
#: structured-field path, so dropping shorteners avoids polluting network
#: analysis with a single "t.co" super-node aggregating thousands of tweets.
_URL_SHORTENER_DOMAINS: frozenset[str] = frozenset({
    "t.co",            # Twitter
    "bit.ly",
    "bitly.com",
    "tinyurl.com",
    "ow.ly",           # Hootsuite
    "buff.ly",         # Buffer
    "is.gd",
    "tiny.cc",
    "ift.tt",          # IFTTT
    "lnkd.in",         # LinkedIn
    "dlvr.it",
    "shar.es",         # ShareThis
    "goo.gl",          # Google (retired but still in old data)
    "fb.me",           # Facebook
    "trib.al",         # SocialFlow
    "cutt.ly",
    "rebrand.ly",
    "s.id",
    "t.ly",
    "qr.ae",           # Quora
})

# ---------------------------------------------------------------------------
# URL extraction regex
# ---------------------------------------------------------------------------

# Matches http(s):// URLs and bare www. URLs
_URL_PATTERN = re.compile(
    r"""(?:https?://|www\.)"""           # protocol or www.
    r"""[^\s<>\[\]\(\)\"'`|,;]+""",      # URL body (non-whitespace, non-delimiter)
    re.IGNORECASE | re.VERBOSE,
)

# YouTube video ID patterns
_YT_WATCH_RE = re.compile(r"[?&]v=([a-zA-Z0-9_-]{11})")
_YT_EMBED_RE = re.compile(r"/embed/([a-zA-Z0-9_-]{11})")
_YT_SHORTS_RE = re.compile(r"/shorts/([a-zA-Z0-9_-]{11})")
_YT_SHORT_RE = re.compile(r"youtu\.be/([a-zA-Z0-9_-]{11})")

# Facebook redirect unwrap
_FB_REDIRECT_RE = re.compile(r"l\.facebook\.com/l\.php\?u=([^&]+)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_urls_from_text(text: str) -> list[str]:
    """Extract URLs from free text, deduplicated and order-preserved.

    Handles URLs in parentheses, brackets, and strips trailing punctuation
    that is commonly appended in natural text.

    Args:
        text: Free-form text that may contain URLs.

    Returns:
        Deduplicated list of raw URL strings in order of appearance.
    """
    if not text:
        return []

    raw_matches = _URL_PATTERN.findall(text)
    seen: set[str] = set()
    result: list[str] = []

    for url in raw_matches:
        # Strip trailing punctuation that's not part of URLs
        url = url.rstrip(".,;:!?)>]}'\"")

        # Balance parentheses — if the URL has an unmatched closing paren,
        # strip it (common in markdown/wiki: (see https://example.com/page))
        if url.count("(") < url.count(")"):
            url = url.rstrip(")")

        # Ensure protocol
        if url.startswith("www."):
            url = "https://" + url

        if url not in seen:
            seen.add(url)
            result.append(url)

    return result


def clean_url(url: str) -> str | None:
    """Clean and standardize a URL for deduplication and aggregation.

    Multi-pass decode, protocol normalization, tracking param removal,
    and platform-specific canonicalization.

    Args:
        url: A raw URL string.

    Returns:
        Cleaned URL string, or ``None`` if the result is domain-only
        (no meaningful path or query).
    """
    if not url:
        return None

    # Multi-pass URL decode (up to 3 passes for nested encoding)
    decoded = url
    for _ in range(3):
        new_decoded = unquote(decoded)
        if new_decoded == decoded:
            break
        decoded = new_decoded
    url = decoded

    # Ensure protocol
    if url.startswith("www."):
        url = "https://" + url
    elif not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Parse
    parsed = urlparse(url)
    scheme = "https"
    hostname = (parsed.hostname or "").lower()

    # Remove www. prefix
    if hostname.startswith("www."):
        hostname = hostname[4:]

    # Reconstruct netloc with port if non-standard
    netloc = hostname
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port and port not in (80, 443):
        netloc = f"{hostname}:{port}"

    path = parsed.path
    query = parsed.query
    fragment = ""  # Always strip fragments

    # --- Platform-specific normalization ---

    # Facebook: unwrap l.facebook.com redirect
    fb_match = _FB_REDIRECT_RE.search(url)
    if fb_match:
        inner_url = unquote(fb_match.group(1))
        return clean_url(inner_url)

    # Twitter/X: normalize x.com -> twitter.com
    if hostname == "x.com":
        hostname = "twitter.com"
        netloc = "twitter.com"

    # YouTube: normalize to www.youtube.com/watch?v={id}
    if hostname in ("youtube.com", "m.youtube.com", "youtu.be"):
        video_id = _extract_youtube_id(url, parsed)
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"

    # TikTok: normalize vm.tiktok.com -> tiktok.com
    if hostname == "vm.tiktok.com":
        hostname = "tiktok.com"
        netloc = "tiktok.com"

    # --- Strip tracking parameters ---
    if query:
        params = parse_qs(query, keep_blank_values=True)
        filtered = {
            k: v for k, v in params.items()
            if k.lower() not in _TRACKING_PARAMS
        }
        query = urlencode(filtered, doseq=True) if filtered else ""

    # Normalize path: remove trailing slash (except root)
    if path and path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    # Reconstruct
    cleaned = urlunparse((scheme, netloc, path, "", query, fragment))

    # Check if domain-only
    if is_domain_only(cleaned):
        return None

    return cleaned


def extract_domain(url: str) -> str:
    """Extract the effective domain from a URL.

    Strips www, m, and mobile subdomains.

    Args:
        url: A URL string.

    Returns:
        Effective domain string (e.g., ``"dr.dk"``).
    """
    if not url:
        return ""

    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        hostname = (parsed.hostname or "").lower()
    except Exception:
        return ""

    # Strip common mobile/www subdomains
    for prefix in ("www.", "m.", "mobile."):
        if hostname.startswith(prefix):
            hostname = hostname[len(prefix):]
            break

    return hostname


def is_social_media_url(url: str) -> bool:
    """Check if a URL belongs to a known social media platform.

    Args:
        url: A URL string.

    Returns:
        True if the URL's domain matches a known social media platform.
    """
    domain = extract_domain(url)
    return domain in _SOCIAL_MEDIA_DOMAINS


def is_video_platform_url(url: str) -> bool:
    """Check if a URL belongs to a video platform (YouTube or TikTok).

    Args:
        url: A URL string.

    Returns:
        True if the URL matches a YouTube or TikTok domain.
    """
    domain = extract_domain(url)
    return domain in _VIDEO_PLATFORM_DOMAINS or domain.endswith(".tiktok.com")


def is_shortener_url(url: str) -> bool:
    """Check if a URL's domain is a known link shortener.

    Shorteners (``t.co``, ``bit.ly``, etc.) mask the real destination
    behind a redirect.  Because we do not resolve redirects inline, their
    domain is useless for aggregate analysis — every shortener URL would
    collapse into a single super-node.  Upstream sources typically expose
    the un-shortened URL via a structured field (e.g. Twitter's
    ``entities.urls[].expanded_url``), so the extractor can safely drop
    anything matched by this predicate.

    Args:
        url: A URL string.

    Returns:
        True if the URL's domain is a known shortener.
    """
    domain = extract_domain(url)
    return domain in _URL_SHORTENER_DOMAINS


def is_domain_only(url: str) -> bool:
    """Check if a URL has no meaningful path or query parameters.

    Args:
        url: A URL string.

    Returns:
        True if the URL is effectively just a domain with no path/query.
    """
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
    except Exception:
        return True

    path = parsed.path.rstrip("/")
    return not path and not parsed.query


def extract_youtube_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats.

    Args:
        url: A YouTube URL.

    Returns:
        11-character video ID, or None if not found.
    """
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
    except Exception:
        return None
    return _extract_youtube_id(url, parsed)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_youtube_id(url: str, parsed: object) -> str | None:
    """Extract YouTube video ID from parsed URL components."""
    # /watch?v=ID
    match = _YT_WATCH_RE.search(url)
    if match:
        return match.group(1)

    # /embed/ID
    match = _YT_EMBED_RE.search(url)
    if match:
        return match.group(1)

    # /shorts/ID
    match = _YT_SHORTS_RE.search(url)
    if match:
        return match.group(1)

    # youtu.be/ID
    match = _YT_SHORT_RE.search(url)
    if match:
        return match.group(1)

    return None
