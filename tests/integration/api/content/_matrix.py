"""Shared filter-spec matrix for the content-page regression harness.

This module declares one list — ``FILTER_CASES`` — that every test file in
``tests/integration/api/content/`` parametrizes over. Adding a new filter
combination means adding ONE row here, not editing N test files.

Structure of a case
===================

Each ``FilterCase`` has four parts:

1. ``name``: short pytest-id-safe slug.
2. ``params``: the query-parameter dict that would be passed to
   ``/content/records`` (or any sibling route). ``None`` values are dropped
   before the request is sent.
3. ``expected_labels``: the set of seed labels a **bug-free** implementation
   should return for the owner user. Tests that compare against this set are
   marked ``xfail(strict=False)`` where the code is known to diverge today.
4. ``bug_tags``: optional set of tag strings keyed on the bug the case is
   primarily pinning. Used as xfail reason hints so a greppable filename +
   file:line reference is preserved in the test output.

Scope of "expected"
===================

"Expected" is the **fixed** behavior after Phase 2 P0 fixes, applied against
the owner user (the owner of the seeded corpus). Admin and stranger
behavior is derived programmatically in the test files:

- Admin sees the same set the owner sees (plus any rows from other runs,
  but the fixture only seeds one owner, so they coincide).
- Collaborator sees the same set as the owner AFTER Phase 2 decision D
  (collaborator scoping everywhere).
- Stranger always sees the empty set.

The "currently observed" state is NOT hardcoded here. The current-behavior
test file captures it at runtime by calling the route and recording the
result. Subsequent runs compare against that snapshot.

Bug tag reference
=================

- ``show_all_mutation``    — content.py:1063, 1324 (UX Blocker #3).
- ``content_types_default`` — content.py:1067, 1330 (UX Blocker #1).
- ``language_default``     — content.py:1043-1051 (UX Blocker #2).
- ``export_filter_drop``   — content.py:1686-1722 (QA §2.2).
- ``count_row_divergence`` — content.py:1157, 1456 (QA §3.2).
- ``link_deadend``         — content.py:527-534 (UX Major #6).
- ``collaborator_scoping`` — content.py:488-499 vs :215-223 (QA §2.6).
- ``arena_singular_dropped`` — content.py:1336, 1447 (QA §2.3).
- ``dedup_parity``         — analysis/_filters.py:181 vs content.py (QA §2.5).

Owned by: QA Guardian.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FilterCase:
    """One filter scenario that every test file in the suite runs.

    Equality is defined by ``name`` so the pytest-id is stable and unique.
    """

    name: str
    params: dict[str, Any]
    expected_labels: set[str]
    bug_tags: frozenset[str] = field(default_factory=frozenset)
    # Optional: if set, this case is explicitly marked as "known divergent"
    # for the count-vs-rows invariant test. The xfail reason is surfaced from
    # this field so the pytest short report is human-readable.
    count_rows_xfail_reason: str | None = None
    # Optional: if set, this case is explicitly marked as "known divergent"
    # for the export-vs-browse parity test.
    export_browse_xfail_reason: str | None = None


# ---------------------------------------------------------------------------
# Label helpers — keep these in sync with tests/integration/api/content/conftest.py.
#
# We duplicate the labels here (rather than importing from conftest) so that
# this module is a pure-data declaration with no fixture-import side effects.
# If a label changes in conftest.py, the test author must update it here too;
# the test will fail loudly if a label referenced here isn't in the seed.
# ---------------------------------------------------------------------------

# Every non-duplicate record, grouped for readability.
_REDDIT = {
    "reddit_post_term_matched_da",
    "reddit_comment_term_matched_da",
    "reddit_post_non_term_matched_en",
    "reddit_comment_danish_characters",
}
_BLUESKY = {
    "bluesky_post_term_matched_en",
    "bluesky_post_term_matched_da",
    "bluesky_post_non_term_matched_da",
}
_FACEBOOK = {
    "facebook_post_actor_only_da",
    "facebook_post_actor_only_da_2",
    "facebook_comment_actor_only_en",
    "facebook_post_empty_lang_enriched_da",
}
_INSTAGRAM = {
    "instagram_reel_actor_only_da",
    "instagram_post_actor_only_en",
    "instagram_post_actor_only_none_lang",
}
_YOUTUBE = {
    "youtube_video_term_matched_da",
    "youtube_video_term_matched_en",
    "youtube_video_locale_variant_danish",
}
_X = {
    "x_tweet_term_matched_da",
    "x_reply_term_matched_da",
    "x_tweet_non_term_matched_de",
}
_GOOGLE = {
    "google_search_result_da",
    "google_search_result_en",
    "google_article_term_matched_da",
    "google_article_pending_scrape_da",
}
_WIKIPEDIA = {
    "wikipedia_pageview_da",
    "wikipedia_pageview_en",
    "wikipedia_pageview_empty_lang_enriched",
}
_TELEGRAM = {
    "telegram_post_term_matched_da",
    "telegram_post_no_lang_enriched_da",
    "telegram_post_non_term_matched_en",
}
_DUPLICATES = {
    "reddit_dup_of_reddit_post_term_matched_da",
    "bluesky_dup_of_bluesky_post_term_matched_en",
    "youtube_dup_of_youtube_video_term_matched_da",
    "x_dup_of_x_tweet_term_matched_da",
    "telegram_dup_of_telegram_post_term_matched_da",
}

ALL_RECORDS: set[str] = (
    _REDDIT
    | _BLUESKY
    | _FACEBOOK
    | _INSTAGRAM
    | _YOUTUBE
    | _X
    | _GOOGLE
    | _WIKIPEDIA
    | _TELEGRAM
    | _DUPLICATES
)

# Records that are ``term_matched=TRUE`` (the default filter).
TERM_MATCHED: set[str] = {
    "reddit_post_term_matched_da",
    "reddit_comment_term_matched_da",
    "reddit_comment_danish_characters",
    "bluesky_post_term_matched_en",
    "bluesky_post_term_matched_da",
    "youtube_video_term_matched_da",
    "youtube_video_term_matched_en",
    "youtube_video_locale_variant_danish",
    "x_tweet_term_matched_da",
    "x_reply_term_matched_da",
    "google_search_result_da",
    "google_search_result_en",
    "google_article_term_matched_da",
    "google_article_pending_scrape_da",
    "wikipedia_pageview_da",
    "wikipedia_pageview_en",
    "wikipedia_pageview_empty_lang_enriched",
    "telegram_post_term_matched_da",
    "telegram_post_no_lang_enriched_da",
} | _DUPLICATES  # duplicates are all term_matched=TRUE in the seed

# Records that are actor-only (Facebook/Instagram) — term_matched=FALSE but
# always visible because Phase 2 applies the actor-only exemption.
ACTOR_ONLY: set[str] = _FACEBOOK | _INSTAGRAM

# Records on platforms the plan calls out as actor-only.
_ACTOR_ONLY_PLATFORMS = {"facebook", "instagram"}

# Post-only (content_type="post" exactly).
POST_ONLY: set[str] = {
    "reddit_post_term_matched_da",
    "reddit_post_non_term_matched_en",
    "bluesky_post_term_matched_en",
    "bluesky_post_term_matched_da",
    "bluesky_post_non_term_matched_da",
    "facebook_post_actor_only_da",
    "facebook_post_actor_only_da_2",
    "facebook_post_empty_lang_enriched_da",
    "instagram_reel_actor_only_da",  # content_type="post" in fixture despite label
    "instagram_post_actor_only_en",
    "instagram_post_actor_only_none_lang",
    "telegram_post_term_matched_da",
    "telegram_post_no_lang_enriched_da",
    "telegram_post_non_term_matched_en",
    "reddit_dup_of_reddit_post_term_matched_da",
    "bluesky_dup_of_bluesky_post_term_matched_en",
    "telegram_dup_of_telegram_post_term_matched_da",
}

# Phase 2 default result set — no explicit filters.
# Applies: content_types=["post"] default, show_all=False + actor-only exemption,
# include_duplicates=False.
# = POST_ONLY & (TERM_MATCHED | ACTOR_ONLY) - _DUPLICATES
P2_DEFAULT: set[str] = (POST_ONLY & (TERM_MATCHED | ACTOR_ONLY)) - _DUPLICATES

# Language partitions, accounting for Phase-2 fallback semantics.
# NOTE: these reflect what a *fixed* language filter should return.
# Phase 2 also excludes duplicates by default; when a language filter is
# applied, the content_types=["post"] default and show_all=False are still
# in effect unless explicitly overridden. Language filter rows already exclude
# duplicates (the language filter is combined with the dedup filter).
LANG_DA_NO_DUP: set[str] = {
    "reddit_post_term_matched_da",
    "reddit_comment_term_matched_da",
    "reddit_comment_danish_characters",
    "bluesky_post_term_matched_da",
    "bluesky_post_non_term_matched_da",
    "facebook_post_actor_only_da",
    "facebook_post_actor_only_da_2",
    "facebook_post_empty_lang_enriched_da",  # enrichment fallback
    "instagram_reel_actor_only_da",
    "youtube_video_term_matched_da",
    "youtube_video_locale_variant_danish",  # da-DK split_part
    "x_tweet_term_matched_da",
    "x_reply_term_matched_da",
    "google_search_result_da",
    "google_article_term_matched_da",
    "google_article_pending_scrape_da",
    "wikipedia_pageview_da",
    "telegram_post_term_matched_da",
    "telegram_post_no_lang_enriched_da",  # enrichment fallback
}
# Full LANG_DA including duplicates (used when content_types filter broadens the
# result set or when include_duplicates is explicitly True).
LANG_DA: set[str] = LANG_DA_NO_DUP | {
    "reddit_dup_of_reddit_post_term_matched_da",
    "youtube_dup_of_youtube_video_term_matched_da",
    "x_dup_of_x_tweet_term_matched_da",
    "telegram_dup_of_telegram_post_term_matched_da",
}
LANG_EN_NO_DUP: set[str] = {
    "reddit_post_non_term_matched_en",
    "bluesky_post_term_matched_en",
    "facebook_comment_actor_only_en",
    "instagram_post_actor_only_en",
    "youtube_video_term_matched_en",
    "google_search_result_en",
    "wikipedia_pageview_en",
    "telegram_post_non_term_matched_en",
}
LANG_EN: set[str] = LANG_EN_NO_DUP | {"bluesky_dup_of_bluesky_post_term_matched_en"}

# The live run holds exactly one directly-collected record; run_batch holds
# every other row. Link rows cross-join 3 records into run_live as well, but
# those are link-join rows rather than direct collection_run_id membership.
RUN_BATCH: set[str] = ALL_RECORDS - {"bluesky_post_term_matched_da"}
RUN_LIVE_LINKED: set[str] = {
    # Records directly collected in the live run (bluesky_post_term_matched_da)
    "bluesky_post_term_matched_da",
    # Records linked to the live run via content_record_links.
    "reddit_post_term_matched_da",
    "bluesky_post_term_matched_en",
    "wikipedia_pageview_en",
}


# ---------------------------------------------------------------------------
# The filter matrix
# ---------------------------------------------------------------------------

FILTER_CASES: list[FilterCase] = [
    # ------------------------------------------------------------------
    # Baseline (no filters)
    # Phase 2 behavior: content_types=["post"] default, show_all=False +
    # actor-only exemption (FB/IG always visible), include_duplicates=False.
    # ------------------------------------------------------------------
    FilterCase(
        name="baseline_no_filters",
        params={},
        # Phase 2 correct: posts only, non-duplicates, term_matched OR actor-only.
        expected_labels=P2_DEFAULT,
    ),
    # ------------------------------------------------------------------
    # Single-filter cases
    # ------------------------------------------------------------------
    FilterCase(
        name="q_danish_fulltext_klima",
        params={"q": "klima"},
        # Full-text search (text_content || title) with plainto_tsquery('danish', 'klima').
        # Only records whose text_content or title contains the literal word "klima" match;
        # compound words like "Klimapolitik" or "klimaafgifter" do NOT stem to "klima" in
        # the Danish dictionary. Content_types=["post"] default excludes videos, articles,
        # search_results, tweets, replies. No dups. show_all=False + actor-only exemption.
        #
        # FTS match analysis:
        #   telegram_post_term_matched_da: "Telegram-besked om klima." → match, post ✓
        #   reddit_post_term_matched_da: title="Klimakamp i Danmark", text="En lang ..."
        #     → "klimakamp" ≠ "klima" → NO match
        #   bluesky_post_term_matched_da: "Klimapolitik på Bluesky." → NO match
        #   youtube_video_term_matched_da: "Description: klima og co2..." → match,
        #     but content_type=video → excluded by content_types default
        #   google_search_result_da: title="Dansk søgeresultat om klima" → match,
        #     but content_type=search_result → excluded
        #   google_article_term_matched_da: title="Politiken-artikel om klima" → match,
        #     but content_type=article → excluded
        #   telegram_post_no_lang_enriched_da: "Telegram-besked med sprogdetektion..."
        #     → no "klima" in text or title → NO match
        expected_labels={
            "telegram_post_term_matched_da",
        },
    ),
    FilterCase(
        name="arenas_single_reddit",
        params={"arenas": ["reddit"]},
        # Reddit: term_matched records only (not actor-only), posts only, no dups.
        expected_labels={
            "reddit_post_term_matched_da",
        },
    ),
    FilterCase(
        name="arenas_single_facebook",
        params={"arenas": ["facebook"]},
        # Facebook: actor-only exemption → all FB records visible.
        # content_types=["post"] default → only posts (not comment).
        # No dups (FB has none).
        expected_labels={
            "facebook_post_actor_only_da",
            "facebook_post_actor_only_da_2",
            "facebook_post_empty_lang_enriched_da",
        },
    ),
    FilterCase(
        name="arenas_multi_reddit_bluesky",
        params={"arenas": ["reddit", "bluesky"]},
        # Multi-arena: Reddit + Bluesky. content_types=["post"] default.
        # show_all=False: reddit/bluesky not actor-only → term_matched required.
        # No dups.
        expected_labels={
            "reddit_post_term_matched_da",
            "bluesky_post_term_matched_en",
            "bluesky_post_term_matched_da",
        },
    ),
    FilterCase(
        name="date_from_only_december",
        params={"date_from": "2025-12-01"},
        # Records from Dec 1 onwards. content_types=["post"] default.
        # show_all=False + actor-only exemption. No dups.
        #
        # December+ records by label:
        #   bluesky_post_non_term_matched_da: Dec 15, bluesky (not actor-only),
        #     term_matched=False → excluded by show_all=False
        #   facebook_comment_actor_only_en: Dec 15+2h, actor-only but content_type=comment
        #     → excluded by content_types=["post"] default
        #   instagram_post_actor_only_none_lang: Dec 16, actor-only, content_type=post → included
        #   youtube_video_locale_variant_danish: Dec 17, content_type=video → excluded
        #   x_tweet_non_term_matched_de: Dec 18, content_type=tweet → excluded
        #   google_article_pending_scrape_da: Dec 19, content_type=article → excluded
        #   telegram_post_non_term_matched_en: Dec 20, not term_matched, not actor-only → excluded
        #   facebook_post_empty_lang_enriched_da: Jan 15, actor-only, post → included
        #   All duplicates in Jan: excluded by include_duplicates=False
        expected_labels={
            "instagram_post_actor_only_none_lang",
            "facebook_post_empty_lang_enriched_da",
        },
    ),
    FilterCase(
        name="date_to_only_november_end",
        params={"date_to": "2025-11-30"},
        # Records before Dec 1. content_types=["post"] default.
        # show_all=False + actor-only exemption. No dups.
        expected_labels={
            "reddit_post_term_matched_da",       # oct — term_matched, post
            "bluesky_post_term_matched_en",      # oct — term_matched, post
            "bluesky_post_term_matched_da",      # oct+2d — term_matched, post
            "facebook_post_actor_only_da",       # oct — actor-only, post
            "facebook_post_actor_only_da_2",     # oct — actor-only, post
            "instagram_reel_actor_only_da",      # oct+3d — actor-only, content_type=post
            "instagram_post_actor_only_en",      # nov — actor-only, post
            "youtube_video_term_matched_da",     # oct+4d — term_matched, but video → excluded
            "youtube_video_term_matched_en",     # nov+5d — term_matched, but video → excluded
            "x_tweet_term_matched_da",           # oct+5d — term_matched, tweet → excluded
            "x_reply_term_matched_da",           # nov+6d — term_matched, reply → excluded
            "google_search_result_da",           # oct+6d — term_matched, search_result → excluded
            "google_search_result_en",           # nov — term_matched, search_result → excluded
            "google_article_term_matched_da",    # nov+7d — term_matched, article → excluded
            "wikipedia_pageview_da",             # nov+8d — term_matched, wiki_pageview → excluded
            "wikipedia_pageview_en",             # nov+9d — term_matched, wiki_pageview → excluded
            "telegram_post_term_matched_da",     # oct+7d — term_matched, post
            "telegram_post_no_lang_enriched_da", # nov+10d — term_matched, post
        } - {
            # Remove the non-post content_types (applying the default filter):
            "youtube_video_term_matched_da",
            "youtube_video_term_matched_en",
            "x_tweet_term_matched_da",
            "x_reply_term_matched_da",
            "google_search_result_da",
            "google_search_result_en",
            "google_article_term_matched_da",
            "wikipedia_pageview_da",
            "wikipedia_pageview_en",
        },
    ),
    FilterCase(
        name="language_da",
        params={"language": "da"},
        # language=da filter + content_types=["post"] default + no dups.
        # show_all=False + actor-only exemption.
        # Intersection: LANG_DA_NO_DUP & POST_ONLY & (TERM_MATCHED | ACTOR_ONLY).
        expected_labels=LANG_DA_NO_DUP & POST_ONLY & (TERM_MATCHED | ACTOR_ONLY),
    ),
    FilterCase(
        name="language_en",
        params={"language": "en"},
        # language=en + content_types=["post"] default + no dups.
        expected_labels=LANG_EN_NO_DUP & POST_ONLY & (TERM_MATCHED | ACTOR_ONLY),
    ),
    FilterCase(
        name="language_empty_explicit_clear",
        params={"language": ""},
        # Explicit empty string = clear language filter; show everything with defaults.
        # content_types=["post"] default + show_all=False + actor-only + no dups.
        expected_labels=P2_DEFAULT,
    ),
    FilterCase(
        name="language_unknown_xx",
        params={"language": "xx"},
        # Phase 6 (Task 2): invalid language is now validated and dropped.
        # The filter is ignored and P2_DEFAULT (all-language default set) is
        # returned — the same result as if language was not supplied.
        # An inline warning banner is shown to the researcher.
        expected_labels=P2_DEFAULT,
    ),
    FilterCase(
        name="mode_batch",
        params={"mode": "batch"},
        # run_batch has all directly-collected rows; run_live has bluesky_post_term_matched_da.
        # content_types=["post"] default + no dups + show_all=False + actor-only.
        # P2_DEFAULT minus bluesky_post_term_matched_da (which is in run_live only).
        expected_labels=P2_DEFAULT - {"bluesky_post_term_matched_da"},
    ),
    FilterCase(
        name="mode_live",
        params={"mode": "live"},
        # run_live has bluesky_post_term_matched_da directly collected.
        # content_types=["post"] default → bluesky_post is a post, included.
        expected_labels={"bluesky_post_term_matched_da"},
    ),
    FilterCase(
        name="search_term_klima",
        params={"search_term": "klima"},
        # search_terms_matched @> ['klima'] + content_types=["post"] default + no dups.
        # Only posts with klima in search_terms_matched.
        expected_labels={
            "reddit_post_term_matched_da",
            "bluesky_post_term_matched_da",
            "telegram_post_term_matched_da",
            "telegram_post_no_lang_enriched_da",
        },
    ),
    FilterCase(
        name="search_term_climate_only_via_link",
        params={"search_term": "climate"},
        # search_terms_matched @> ['climate'] + content_types=["post"] default + no dups.
        # bluesky_post_term_matched_en has climate in search_terms → included.
        expected_labels={
            "bluesky_post_term_matched_en",
        },
    ),
    FilterCase(
        name="scrape_status_scraped",
        params={"scrape_status": "scraped"},
        # google_article_term_matched_da has scrape_status="scraped".
        # content_type is "article" → excluded by default content_types=["post"].
        # So result is empty.
        expected_labels=set(),
    ),
    FilterCase(
        name="scrape_status_pending",
        params={"scrape_status": "pending"},
        # google_article_pending_scrape_da has scrape_status="pending".
        # content_type is "article" → excluded by default content_types=["post"].
        expected_labels=set(),
    ),
    FilterCase(
        name="show_all_true",
        params={"show_all": "true"},
        # show_all=True → no term_matched filter. content_types=["post"] default.
        # No dups.
        expected_labels=POST_ONLY - _DUPLICATES,
    ),
    FilterCase(
        name="show_all_false_default_explicit",
        params={"show_all": "false"},
        # show_all=False (explicit) → same as default.
        expected_labels=P2_DEFAULT,
    ),
    FilterCase(
        name="content_types_post",
        params={"content_types": ["post"]},
        # Explicit content_types=["post"]. show_all=False + actor-only + no dups.
        expected_labels=POST_ONLY & (TERM_MATCHED | ACTOR_ONLY) - _DUPLICATES,
    ),
    FilterCase(
        name="content_types_comment",
        params={"content_types": ["comment"]},
        # Explicit content_types=["comment"]. show_all=False + actor-only + no dups.
        expected_labels={
            "reddit_comment_term_matched_da",
            "reddit_comment_danish_characters",
            "facebook_comment_actor_only_en",
        },
    ),
    FilterCase(
        name="content_types_video",
        params={"content_types": ["video"]},
        # Explicit content_types=["video"]. show_all=False + no dups.
        # youtube videos are term_matched → included.
        expected_labels={
            "youtube_video_term_matched_da",
            "youtube_video_term_matched_en",
            "youtube_video_locale_variant_danish",
        },
    ),
    FilterCase(
        name="sort_by_published_at_desc",
        params={"sort_by": "published_at", "sort_dir": "desc"},
        # Sort doesn't change filter — same as baseline.
        expected_labels=P2_DEFAULT,
    ),
    FilterCase(
        name="sort_by_platform_asc",
        params={"sort_by": "platform", "sort_dir": "asc"},
        # Sort doesn't change filter — same as baseline.
        expected_labels=P2_DEFAULT,
    ),
    # ------------------------------------------------------------------
    # Pairs
    # ------------------------------------------------------------------
    FilterCase(
        name="arenas_facebook_language_da",
        params={"arenas": ["facebook"], "language": "da"},
        # Facebook + Danish. Actor-only exemption → all FB visible.
        # content_types=["post"] default → only posts.
        # No dups.
        expected_labels={
            "facebook_post_actor_only_da",
            "facebook_post_actor_only_da_2",
            "facebook_post_empty_lang_enriched_da",
        },
    ),
    FilterCase(
        name="arenas_reddit_date_from_nov",
        params={"arenas": ["reddit"], "date_from": "2025-11-01"},
        # Reddit + date_from Nov 1. Reddit is not actor-only → term_matched required.
        # content_types=["post"] default. No dups.
        # reddit_post_non_term_matched_en is not term_matched → excluded.
        # reddit_comment_danish_characters is term_matched but content_type=comment → excluded.
        expected_labels=set(),
    ),
    FilterCase(
        name="arenas_facebook_show_all_false",
        params={"arenas": ["facebook"], "show_all": "false"},
        # Phase 2: actor-only platforms always visible regardless of show_all.
        # content_types=["post"] default → only FB posts.
        expected_labels={
            "facebook_post_actor_only_da",
            "facebook_post_actor_only_da_2",
            "facebook_post_empty_lang_enriched_da",
        },
    ),
    FilterCase(
        name="arenas_youtube_content_types_video",
        params={"arenas": ["youtube"], "content_types": ["video"]},
        # YouTube + explicit content_types=["video"]. YouTube is not actor-only.
        # term_matched required. No dups.
        expected_labels={
            "youtube_video_term_matched_da",
            "youtube_video_term_matched_en",
            "youtube_video_locale_variant_danish",
        },
    ),
    FilterCase(
        name="run_id_batch_search_term_klima",
        params={"search_term": "klima"},  # run_id set at call time to run_batch_id
        # Klima (search_terms_matched) + run_batch + content_types=["post"] default + no dups.
        # bluesky_post_term_matched_da is in run_LIVE not run_batch → excluded.
        # google_article_pending_scrape_da has search_terms_matched=["klima"] and run_batch,
        #   but content_type=article → excluded by content_types default.
        expected_labels={
            "reddit_post_term_matched_da",
            "telegram_post_term_matched_da",
            "telegram_post_no_lang_enriched_da",
        },
    ),
    FilterCase(
        name="project_id_primary_language_da",
        params={"language": "da"},  # project_id filled in at call time
        # language=da + content_types=["post"] default + no dups.
        expected_labels=LANG_DA_NO_DUP & POST_ONLY & (TERM_MATCHED | ACTOR_ONLY),
    ),
    # ------------------------------------------------------------------
    # Triples
    # ------------------------------------------------------------------
    FilterCase(
        name="arenas_date_language_triple",
        params={
            "arenas": ["reddit", "bluesky"],
            "date_from": "2025-10-01",
            "date_to": "2025-11-30",
            "language": "da",
        },
        # Multi-arena reddit+bluesky + date window + language=da.
        # Neither reddit nor bluesky is actor-only → term_matched required.
        # content_types=["post"] default. No dups.
        expected_labels={
            "reddit_post_term_matched_da",
            "bluesky_post_term_matched_da",
        },
    ),
    FilterCase(
        name="arenas_show_all_content_types_triple",
        params={
            "arenas": ["facebook", "instagram"],
            "show_all": "true",
            "content_types": ["post"],
        },
        # FB + IG, show_all=True, explicit content_types=["post"]. No dups.
        expected_labels={
            "facebook_post_actor_only_da",
            "facebook_post_actor_only_da_2",
            "facebook_post_empty_lang_enriched_da",
            "instagram_reel_actor_only_da",
            "instagram_post_actor_only_en",
            "instagram_post_actor_only_none_lang",
        },
    ),
    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------
    FilterCase(
        name="date_from_future",
        params={"date_from": "2099-01-01"},
        expected_labels=set(),
    ),
    FilterCase(
        name="date_to_past",
        params={"date_to": "2000-01-01"},
        expected_labels=set(),
    ),
    # ------------------------------------------------------------------
    # Phase 3 — new filters (actor, query_design, show_duplicates, reset).
    # actor_id and query_design_id params are injected at call time in
    # test files (like run_id_batch_search_term_klima above).
    # ------------------------------------------------------------------
    # show_duplicates=true — should return duplicates that are normally hidden.
    FilterCase(
        name="show_duplicates_true",
        params={"show_duplicates": "true", "content_types": ["post"]},
        # show_duplicates=true + content_types=["post"] + no show_all restriction.
        # POST_ONLY includes the duplicate posts. show_all=False + actor-only exemption.
        expected_labels=POST_ONLY & (TERM_MATCHED | ACTOR_ONLY),
    ),
    # show_duplicates=false explicit — should match the default (exclude dups).
    FilterCase(
        name="show_duplicates_false_explicit",
        params={"show_duplicates": "false", "content_types": ["post"]},
        # Same as baseline (posts, term_matched, no dups).
        expected_labels=(POST_ONLY & (TERM_MATCHED | ACTOR_ONLY)) - _DUPLICATES,
    ),
    # reset=true — bypasses auto-project and auto-language defaults.
    # The posts-only default still applies per decision B.
    FilterCase(
        name="reset_true",
        params={"reset": "true"},
        # reset=true clears project/language auto-selection but keeps posts default.
        # Result: same as baseline_no_filters (posts default still applies).
        expected_labels=P2_DEFAULT,
    ),
    # query_design_id filter — injected at call time (like run_id_batch).
    # DA design: all records that belong to qd_da (content_types default=post).
    # qd_da records that are posts and term_matched (or actor-only): varies.
    # This case is parametrized at call time — placeholder expected set.
    FilterCase(
        name="query_design_id_da",
        params={},  # query_design_id injected at call time
        # Records in qd_da that are posts and pass standard filters.
        # P2_DEFAULT intersect qd_da records: all P2_DEFAULT rows that use qd_da.
        # qd_da is used by reddit (da), bluesky (da), facebook, instagram, youtube (da),
        # x (da), google (da), wikipedia (da), telegram (da).
        # Non-qd_da records: bluesky_post_term_matched_en, reddit_post_non_term_matched_en,
        #   facebook_comment_actor_only_en, instagram_post_actor_only_en,
        #   youtube_video_term_matched_en, google_search_result_en,
        #   wikipedia_pageview_en, telegram_post_non_term_matched_en,
        #   wikipedia_pageview_empty_lang_enriched.
        # P2_DEFAULT for qd_da:
        expected_labels=P2_DEFAULT - {
            "bluesky_post_term_matched_en",
            "instagram_post_actor_only_en",
        },
    ),
    # actor filter — actor_id is injected at call time from seeded_corpus.actor_ids.
    # Phase 5 seeded two actors:
    #   - "actor:reddit" owns reddit_post_term_matched_da (post) and
    #     reddit_comment_term_matched_da (comment). With content_types=["post"]
    #     default, only the post is visible.
    #   - "actor:bluesky" owns bluesky_post_term_matched_da (post, term_matched,
    #     run_live). Visible under default filters.
    # The test injects actor:reddit's UUID so the expected set is one post.
    # No duplicates are attributed to either actor; no dup-exclusion effect.
    FilterCase(
        name="actor_id_filter",
        params={},  # actor_id injected at call time from corpus.actor_ids["actor:reddit"]
        # Reddit actor owns reddit_post_term_matched_da (post, term_matched=True,
        # no dup) and reddit_comment_term_matched_da (comment → excluded by
        # content_types=["post"] default). Expected: the post only.
        expected_labels={"reddit_post_term_matched_da"},
        # Phase 6: export route now accepts actor_id — xfail removed.
    ),
    # Combination: query_design + language
    FilterCase(
        name="query_design_da_language_da",
        params={"language": "da"},  # query_design_id injected at call time
        # qd_da + language=da + posts default + no dups.
        expected_labels=(P2_DEFAULT - {
            "bluesky_post_term_matched_en",
            "instagram_post_actor_only_en",
        }) & LANG_DA_NO_DUP & POST_ONLY & (TERM_MATCHED | ACTOR_ONLY),
    ),
]


# ---------------------------------------------------------------------------
# Legacy Phase 3 placeholder — kept for backward compat with test files that
# reference PHASE_3_NOT_YET_BUILT. Now empty since the filters are built.
# ---------------------------------------------------------------------------

PHASE_3_NOT_YET_BUILT: list[FilterCase] = []


def pytest_ids(cases: list[FilterCase]) -> list[str]:
    """Return ``name`` fields as pytest test ids."""
    return [c.name for c in cases]
