"""Factory Boy factories for content record models.

Usage::

    from tests.factories.content import ContentRecordFactory

    record = ContentRecordFactory.build(
        platform="bluesky",
        arena="social_media",
        text_content="Klimaforandringer truer de danske kyster",
    )
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from datetime import datetime, timezone

import factory


def _compute_content_hash(text: str) -> str:
    """Mirror of Normalizer.compute_content_hash for factory use."""
    normalized = unicodedata.normalize("NFC", text)
    normalized = normalized.strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class ContentRecordFactory(factory.Factory):
    """Factory for universal content record dicts.

    Produces records that conform to the ``content_records`` schema defined in
    :class:`issue_observatory.core.models.content.UniversalContentRecord`.

    Danish text is used by default to exercise æ/ø/å handling.
    """

    class Meta:
        model = dict

    # Core identifiers
    id = factory.LazyFunction(uuid.uuid4)
    platform = "bluesky"
    arena = "social_media"
    platform_id = factory.Sequence(lambda n: f"at://did:plc:test{n}/post/{n}")
    content_type = "post"

    # Content
    text_content = factory.Sequence(
        lambda n: f"Testindhold {n}: klimaforandringer påvirker de grønne områder og søerne"
    )
    title = None
    url = factory.Sequence(lambda n: f"https://bsky.app/profile/test{n}/post/{n}")
    language = "da"

    # Timestamps (UTC-aware)
    published_at = factory.LazyFunction(
        lambda: datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc).isoformat()
    )
    collected_at = factory.LazyFunction(
        lambda: datetime.now(tz=timezone.utc).isoformat()
    )

    # Author
    author_platform_id = factory.Sequence(lambda n: f"did:plc:testauthor{n}")
    author_display_name = factory.Sequence(lambda n: f"Testforfatter {n}")
    author_id = None
    pseudonymized_author_id = factory.LazyAttribute(
        # Mirrors Normalizer.pseudonymize_author with test salt
        lambda o: hashlib.sha256(
            f"{o.platform}{o.author_platform_id}test-pseudonymization-salt-for-unit-tests".encode()
        ).hexdigest()
        if o.author_platform_id
        else None
    )

    # Engagement
    views_count = None
    likes_count = factory.Faker("random_int", min=0, max=500)
    shares_count = factory.Faker("random_int", min=0, max=100)
    comments_count = factory.Faker("random_int", min=0, max=50)
    engagement_score = None

    # Collection context
    collection_run_id = None
    query_design_id = None
    search_terms_matched = factory.LazyFunction(list)
    collection_tier = "free"

    # Platform-specific passthrough
    raw_metadata = factory.LazyFunction(dict)
    media_urls = factory.LazyFunction(list)

    # Deduplication
    content_hash = factory.LazyAttribute(
        lambda o: _compute_content_hash(o.text_content) if o.text_content else None
    )


class GoogleSearchResultFactory(factory.Factory):
    """Factory for Serper.dev organic result dicts (raw, pre-normalization).

    Use this to build raw API response fixtures for google_search collector
    unit tests.
    """

    class Meta:
        model = dict

    title = factory.Sequence(lambda n: f"Dansk nyhed {n} om klima og velfærd")
    link = factory.Sequence(lambda n: f"https://dr.dk/nyheder/klima/artikel-{n}")
    snippet = factory.Sequence(
        lambda n: (
            f"Artikel {n} om grøn omstilling og klimaforandringer i Danmark. "
            "Politikere debatterer velfærdsstatens fremtid i Aalborg og Aarhus."
        )
    )
    position = factory.Sequence(lambda n: n + 1)
    date = "1 jan 2024"
    displayLink = factory.Sequence(lambda n: f"dr.dk")
    content_type = "search_result"
