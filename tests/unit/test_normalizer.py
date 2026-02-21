"""Unit tests for the Normalizer pipeline.

Tests cover:
- Pseudonymization determinism and platform isolation
- Content hash normalization (whitespace, Unicode)
- Field mapping: required fields always present, optional fields default to None
- Danish character preservation (æ, ø, å) through the pipeline
- Missing / malformed field graceful handling

These tests are pure unit tests — no database, no network, no Celery.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from issue_observatory.core.normalizer import Normalizer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_SALT = "test-pseudonymization-salt-for-unit-tests"


@pytest.fixture
def norm() -> Normalizer:
    """Normalizer with a known test salt for deterministic pseudonyms."""
    return Normalizer(pseudonymization_salt=TEST_SALT)


# ---------------------------------------------------------------------------
# Pseudonymization
# ---------------------------------------------------------------------------


class TestPseudonymization:
    def test_pseudonymize_author_is_deterministic(self, norm: Normalizer) -> None:
        """Same platform + user ID always produce the same pseudonym.

        Determinism is required for cross-run actor linkage: if the same
        author appears in two collection runs, they must map to the same
        pseudonymized ID so the corpus can be analysed cohesively.
        """
        result_1 = norm.pseudonymize_author("bluesky", "did:plc:abc123")
        result_2 = norm.pseudonymize_author("bluesky", "did:plc:abc123")

        assert result_1 == result_2

    def test_pseudonymize_author_different_platforms_differ(self, norm: Normalizer) -> None:
        """The same native user ID on different platforms produces different pseudonyms.

        This prevents cross-platform re-identification when platform_user_ids
        coincidentally share the same value string.  SHA-256 incorporates
        the platform string, so 'reddit/12345' != 'youtube/12345'.
        """
        reddit_pseudonym = norm.pseudonymize_author("reddit", "user12345")
        youtube_pseudonym = norm.pseudonymize_author("youtube", "user12345")

        assert reddit_pseudonym != youtube_pseudonym

    def test_pseudonymize_author_returns_64_char_hex(self, norm: Normalizer) -> None:
        """Output is always a 64-character lowercase hex SHA-256 digest."""
        result = norm.pseudonymize_author("bluesky", "did:plc:testuser")

        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_pseudonymize_author_matches_expected_sha256(self, norm: Normalizer) -> None:
        """Verify the exact SHA-256 formula: SHA-256(platform + user_id + salt)."""
        platform = "reddit"
        user_id = "u_testuser"
        expected = hashlib.sha256(
            f"{platform}:{user_id}:{TEST_SALT}".encode("utf-8")
        ).hexdigest()

        result = norm.pseudonymize_author(platform, user_id)

        assert result == expected

    def test_pseudonymize_author_with_danish_username(self, norm: Normalizer) -> None:
        """Danish characters in platform user IDs are handled without error.

        Some platforms allow Unicode in usernames.  The normalizer must not
        crash or silently corrupt the identity.
        """
        result = norm.pseudonymize_author("bluesky", "søren.ærlighed@bsky.social")

        assert len(result) == 64

    def test_pseudonymize_author_different_salts_differ(self) -> None:
        """Different pseudonymization salts produce different pseudonyms.

        Ensures that the salt is actually incorporated into the hash, so
        that two deployments with different salts cannot be linked.
        """
        norm_a = Normalizer(pseudonymization_salt="salt_project_a")
        norm_b = Normalizer(pseudonymization_salt="salt_project_b")

        result_a = norm_a.pseudonymize_author("bluesky", "user123")
        result_b = norm_b.pseudonymize_author("bluesky", "user123")

        assert result_a != result_b


# ---------------------------------------------------------------------------
# Content hash
# ---------------------------------------------------------------------------


class TestContentHash:
    def test_content_hash_normalizes_whitespace(self, norm: Normalizer) -> None:
        """Extra spaces and newlines between words do not change the hash.

        Cross-platform reposts of the same content may have inconsistent
        whitespace (e.g. Twitter truncation vs RSS full text vs API response).
        The hash must treat them as duplicates.
        """
        text_a = "The quick  brown  fox\njumps over the lazy dog"
        text_b = "The quick brown fox jumps over the lazy dog"

        assert norm.compute_content_hash(text_a) == norm.compute_content_hash(text_b)

    def test_content_hash_normalizes_leading_trailing_whitespace(self, norm: Normalizer) -> None:
        """Leading and trailing whitespace is stripped before hashing."""
        text_a = "  hello world  "
        text_b = "hello world"

        assert norm.compute_content_hash(text_a) == norm.compute_content_hash(text_b)

    def test_content_hash_is_case_insensitive(self, norm: Normalizer) -> None:
        """Content hash is lowercased before hashing for cross-platform dedup."""
        text_a = "KLIMAFORANDRINGER"
        text_b = "klimaforandringer"

        assert norm.compute_content_hash(text_a) == norm.compute_content_hash(text_b)

    def test_content_hash_returns_64_char_hex(self, norm: Normalizer) -> None:
        """Content hash is a 64-character lowercase hex SHA-256 digest."""
        result = norm.compute_content_hash("some content")

        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_content_hash_different_texts_differ(self, norm: Normalizer) -> None:
        """Distinct content produces distinct hashes (no trivial collisions)."""
        hash_a = norm.compute_content_hash("klimaforandringer")
        hash_b = norm.compute_content_hash("velfærdsstat")

        assert hash_a != hash_b

    def test_content_hash_preserves_danish_characters(self, norm: Normalizer) -> None:
        """æ, ø, å are preserved through Unicode NFC normalization.

        NFC normalization must not strip or alter Danish characters —
        it only affects composed vs decomposed forms of the same character.
        The hash of 'æøå' must be stable regardless of whether the input
        is NFC or NFD encoded.
        """
        import unicodedata  # noqa: PLC0415

        text_nfc = unicodedata.normalize("NFC", "grønne søer i Ålborg")
        text_nfd = unicodedata.normalize("NFD", "grønne søer i Ålborg")

        # After our normalization step, NFC and NFD inputs must hash identically.
        assert norm.compute_content_hash(text_nfc) == norm.compute_content_hash(text_nfd)


# ---------------------------------------------------------------------------
# Field mapping — normalize()
# ---------------------------------------------------------------------------


class TestNormalizeFieldMapping:
    def test_normalize_maps_required_fields(self, norm: Normalizer) -> None:
        """Required fields are always present in the normalized record.

        The five required fields (platform, arena, content_type, collected_at,
        collection_tier) must never be absent or None — downstream storage
        and analysis depend on them.
        """
        raw = {"id": "post-1", "text": "Hello"}
        result = norm.normalize(raw, platform="bluesky", arena="social_media")

        assert result["platform"] == "bluesky"
        assert result["arena"] == "social_media"
        assert result["content_type"] == "post"  # default when not in raw
        assert result["collected_at"] is not None
        assert result["collection_tier"] == "free"  # default

    def test_normalize_handles_missing_optional_fields(self, norm: Normalizer) -> None:
        """Missing optional fields produce None, not a KeyError.

        Downstream code can rely on key presence even when the platform
        does not provide a value.  This is especially important for:
        - engagement metrics (views, likes, shares, comments)
        - author display name and platform ID
        - language
        - title
        """
        raw: dict = {}  # completely empty raw item
        result = norm.normalize(raw, platform="reddit", arena="social_media")

        for optional_field in (
            "platform_id",
            "title",
            "text_content",
            "url",
            "language",
            "published_at",
            "author_platform_id",
            "author_display_name",
            "author_id",
            "pseudonymized_author_id",
            "views_count",
            "likes_count",
            "shares_count",
            "comments_count",
            "engagement_score",
            "collection_run_id",
            "query_design_id",
            "content_hash",
        ):
            assert optional_field in result, f"Missing key: {optional_field}"
            # Optional fields with no platform data should be None
            assert result[optional_field] is None, (
                f"Expected None for {optional_field}, got {result[optional_field]!r}"
            )

    def test_normalize_raw_metadata_is_preserved(self, norm: Normalizer) -> None:
        """The original raw item is stored in raw_metadata without modification.

        No upstream information must be lost during normalization.  The raw
        item is kept as-is so that future schema changes can re-derive fields
        from the original API response.
        """
        raw = {"id": "abc", "custom_field": "platform_specific_value", "score": 42}
        result = norm.normalize(raw, platform="reddit", arena="social_media")

        assert result["raw_metadata"] == raw

    def test_normalize_computes_content_hash_from_text(self, norm: Normalizer) -> None:
        """content_hash is computed from text_content when present."""
        text = "Klimaforandringer er en global udfordring"
        raw = {"text": text}
        result = norm.normalize(raw, platform="bluesky", arena="social_media")

        assert result["content_hash"] == norm.compute_content_hash(text)

    def test_normalize_falls_back_to_url_hash_when_no_text(self, norm: Normalizer) -> None:
        """content_hash is computed from URL when text_content is absent."""
        url = "https://dr.dk/nyheder/artikel-123"
        raw = {"url": url}
        result = norm.normalize(raw, platform="dr_rss", arena="news_media")

        assert result["content_hash"] == norm.compute_content_hash(url)

    def test_normalize_pseudonymizes_author_when_id_present(self, norm: Normalizer) -> None:
        """pseudonymized_author_id is set when author_id is available."""
        raw = {"author_id": "did:plc:abc123", "text": "test"}
        result = norm.normalize(raw, platform="bluesky", arena="social_media")

        expected = norm.pseudonymize_author("bluesky", "did:plc:abc123")
        assert result["pseudonymized_author_id"] == expected

    def test_normalize_no_pseudonym_when_no_author_id(self, norm: Normalizer) -> None:
        """pseudonymized_author_id is None when no author identifier is available."""
        raw = {"text": "anonymous post with no author"}
        result = norm.normalize(raw, platform="reddit", arena="social_media")

        assert result["pseudonymized_author_id"] is None

    def test_normalize_passes_collection_context(self, norm: Normalizer) -> None:
        """collection_run_id, query_design_id, and search_terms_matched are threaded through."""
        import uuid  # noqa: PLC0415

        run_id = str(uuid.uuid4())
        design_id = str(uuid.uuid4())
        terms = ["klimaforandringer", "grøn omstilling"]
        raw = {"text": "test"}

        result = norm.normalize(
            raw,
            platform="bluesky",
            arena="social_media",
            collection_run_id=run_id,
            query_design_id=design_id,
            search_terms_matched=terms,
        )

        assert result["collection_run_id"] == run_id
        assert result["query_design_id"] == design_id
        assert result["search_terms_matched"] == terms


# ---------------------------------------------------------------------------
# Danish character preservation
# ---------------------------------------------------------------------------


class TestDanishCharacterPreservation:
    def test_normalize_preserves_danish_text_content(self, norm: Normalizer) -> None:
        """æ, ø, å in text_content survive normalization intact."""
        danish_text = "Grøn omstilling, velfærdsstat og Aalborg kommunes planer"
        raw = {"text": danish_text}
        result = norm.normalize(raw, platform="bluesky", arena="social_media")

        assert result["text_content"] == danish_text

    def test_normalize_preserves_danish_in_author_name(self, norm: Normalizer) -> None:
        """Danish characters in author display names are not stripped."""
        raw = {
            "author_id": "user_123",
            "author_name": "Søren Ærlighed-Øberg",
        }
        result = norm.normalize(raw, platform="bluesky", arena="social_media")

        assert result["author_display_name"] == "Søren Ærlighed-Øberg"

    def test_normalize_preserves_danish_in_title(self, norm: Normalizer) -> None:
        """Danish characters in title field survive normalization."""
        raw = {"title": "Velfærdsstatens fremtid i Ålborg diskuteres", "url": "https://dr.dk/1"}
        result = norm.normalize(raw, platform="dr_rss", arena="news_media")

        assert result["title"] == "Velfærdsstatens fremtid i Ålborg diskuteres"

    @pytest.mark.parametrize("char", ["æ", "ø", "å", "Æ", "Ø", "Å"])
    def test_content_hash_handles_each_danish_character(
        self, norm: Normalizer, char: str
    ) -> None:
        """Each Danish special character can be hashed without error."""
        text = f"tekst med {char} i midten"
        result = norm.compute_content_hash(text)

        assert len(result) == 64


# ---------------------------------------------------------------------------
# Timestamp extraction
# ---------------------------------------------------------------------------


class TestTimestampExtraction:
    def test_normalize_parses_iso_timestamp(self, norm: Normalizer) -> None:
        """ISO 8601 string is parsed and returned as ISO 8601 string."""
        raw = {"timestamp": "2024-01-15T14:30:00Z"}
        result = norm.normalize(raw, platform="bluesky", arena="social_media")

        assert result["published_at"] is not None
        assert "2024-01-15" in result["published_at"]

    def test_normalize_parses_unix_timestamp(self, norm: Normalizer) -> None:
        """Unix epoch integer is converted to ISO 8601 UTC string."""
        epoch = 1705329000  # 2024-01-15 14:30:00 UTC
        raw = {"created_utc": epoch}
        result = norm.normalize(raw, platform="reddit", arena="social_media")

        assert result["published_at"] is not None
        assert "2024-01-15" in result["published_at"]

    def test_normalize_parses_datetime_object(self, norm: Normalizer) -> None:
        """Python datetime objects are accepted and returned as ISO strings."""
        dt = datetime(2024, 3, 20, 9, 0, 0, tzinfo=timezone.utc)
        raw = {"published_at": dt}
        result = norm.normalize(raw, platform="dr_rss", arena="news_media")

        assert result["published_at"] is not None
        assert "2024-03-20" in result["published_at"]

    def test_normalize_returns_none_for_missing_timestamp(self, norm: Normalizer) -> None:
        """Missing timestamp produces None without raising."""
        raw = {"text": "no timestamp here"}
        result = norm.normalize(raw, platform="bluesky", arena="social_media")

        assert result["published_at"] is None


# ---------------------------------------------------------------------------
# Engagement metric extraction
# ---------------------------------------------------------------------------


class TestEngagementMetrics:
    def test_normalize_extracts_likes_count(self, norm: Normalizer) -> None:
        """'likes' key is mapped to likes_count."""
        raw = {"text": "t", "likes": 42}
        result = norm.normalize(raw, platform="bluesky", arena="social_media")

        assert result["likes_count"] == 42

    def test_normalize_extracts_reddit_score_as_likes(self, norm: Normalizer) -> None:
        """Reddit 'score' (upvotes minus downvotes) maps to likes_count."""
        raw = {"text": "t", "score": 1337, "num_comments": 25}
        result = norm.normalize(raw, platform="reddit", arena="social_media")

        assert result["likes_count"] == 1337
        assert result["comments_count"] == 25

    def test_normalize_engagement_is_none_when_absent(self, norm: Normalizer) -> None:
        """Engagement fields are None when not provided by the platform."""
        raw = {"text": "no engagement data"}
        result = norm.normalize(raw, platform="bluesky", arena="social_media")

        assert result["views_count"] is None
        assert result["likes_count"] is None
        assert result["shares_count"] is None
        assert result["comments_count"] is None


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


class TestNormalizerConstruction:
    def test_empty_salt_raises_normalization_error(self) -> None:
        """An empty pseudonymization salt raises NormalizationError at construction.

        BB-01: GDPR compliance requires a valid pseudonymization salt.
        Collection must not proceed without it. This is a security hard requirement.
        """
        from issue_observatory.core.exceptions import NormalizationError

        with pytest.raises(NormalizationError) as exc_info:
            Normalizer(pseudonymization_salt="")

        assert "PSEUDONYMIZATION_SALT is required" in str(exc_info.value)

    def test_explicit_salt_overrides_settings(self) -> None:
        """An explicitly passed salt does not read from settings."""
        norm = Normalizer(pseudonymization_salt="explicit-test-salt")
        # Should not raise, and should use the provided salt
        result = norm.pseudonymize_author("bluesky", "user123")
        assert len(result) == 64
