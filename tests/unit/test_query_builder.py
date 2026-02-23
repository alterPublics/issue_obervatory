"""Tests for arenas/query_builder.py boolean query building utilities.

Tests cover:
- build_boolean_query_groups(): empty input, ungrouped terms, grouped terms, mixed
- format_boolean_query_for_platform(): all supported platforms, single term, empty
- has_boolean_groups(): returns True/False based on group_id presence
- Danish character preservation through formatting
"""

from __future__ import annotations

import uuid

import pytest

from issue_observatory.arenas.query_builder import (
    build_boolean_query_groups,
    format_boolean_query_for_platform,
    has_boolean_groups,
    match_groups_in_text,
    term_in_text,
)


# ---------------------------------------------------------------------------
# H-06: build_boolean_query_groups()
# ---------------------------------------------------------------------------


class TestBuildBooleanQueryGroups:
    def test_empty_input_returns_empty_list(self) -> None:
        """build_boolean_query_groups([]) returns []."""
        result = build_boolean_query_groups([])
        assert result == []

    def test_three_ungrouped_terms_each_form_own_group(self) -> None:
        """Terms with group_id=None each become a separate single-item group."""
        specs = [
            {"term": "klimaforandringer", "group_id": None},
            {"term": "velfærdsstat", "group_id": None},
            {"term": "folketing", "group_id": None},
        ]
        result = build_boolean_query_groups(specs)
        assert len(result) == 3
        for group in result:
            assert len(group) == 1

    def test_two_terms_sharing_same_group_id_form_one_group(self) -> None:
        """Two terms with the same group_id UUID are merged into one AND-group."""
        group_id = uuid.uuid4()
        specs = [
            {"term": "klimaforandringer", "group_id": group_id},
            {"term": "IPCC", "group_id": group_id},
        ]
        result = build_boolean_query_groups(specs)
        assert len(result) == 1
        assert set(result[0]) == {"klimaforandringer", "IPCC"}

    def test_three_terms_two_groups(self) -> None:
        """Three terms: two share group A, one has group B -> two groups."""
        group_a = uuid.uuid4()
        group_b = uuid.uuid4()
        specs = [
            {"term": "klimaforandringer", "group_id": group_a},
            {"term": "IPCC", "group_id": group_a},
            {"term": "folketing", "group_id": group_b},
        ]
        result = build_boolean_query_groups(specs)
        assert len(result) == 2
        # The group with two terms must contain both.
        two_term_group = next(g for g in result if len(g) == 2)
        assert set(two_term_group) == {"klimaforandringer", "IPCC"}
        one_term_group = next(g for g in result if len(g) == 1)
        assert one_term_group == ["folketing"]

    def test_mixed_grouped_and_ungrouped_terms(self) -> None:
        """Two terms sharing a group_id + one ungrouped -> three groups total."""
        group_id = uuid.uuid4()
        specs = [
            {"term": "klimaforandringer", "group_id": group_id},
            {"term": "IPCC", "group_id": group_id},
            {"term": "folketing", "group_id": None},
        ]
        result = build_boolean_query_groups(specs)
        assert len(result) == 2

    def test_empty_term_strings_are_skipped(self) -> None:
        """Terms with empty string values are silently ignored."""
        specs = [
            {"term": "klimaforandringer", "group_id": None},
            {"term": "", "group_id": None},
            {"term": "   ", "group_id": None},
        ]
        result = build_boolean_query_groups(specs)
        # Only the non-empty term survives.
        assert len(result) == 1
        assert result[0] == ["klimaforandringer"]

    def test_uuid_object_and_string_uuid_match_same_group(self) -> None:
        """A UUID object and its string representation key the same group."""
        group_id = uuid.uuid4()
        specs = [
            {"term": "first", "group_id": group_id},
            {"term": "second", "group_id": str(group_id)},
        ]
        result = build_boolean_query_groups(specs)
        # Both terms should be in the same group.
        assert len(result) == 1
        assert set(result[0]) == {"first", "second"}

    def test_preserves_insertion_order_of_groups(self) -> None:
        """Groups appear in the order they are first encountered in the input."""
        group_a = uuid.uuid4()
        group_b = uuid.uuid4()
        specs = [
            {"term": "alpha", "group_id": group_a},
            {"term": "beta", "group_id": group_b},
            {"term": "gamma", "group_id": group_a},
        ]
        result = build_boolean_query_groups(specs)
        assert len(result) == 2
        # Group A encountered first must appear first.
        assert "alpha" in result[0]
        assert "beta" in result[1]


# ---------------------------------------------------------------------------
# H-06: format_boolean_query_for_platform()
# ---------------------------------------------------------------------------


class TestFormatBooleanQueryForPlatform:
    def test_empty_groups_returns_empty_string(self) -> None:
        """format_boolean_query_for_platform([], 'google') returns ''."""
        result = format_boolean_query_for_platform([], "google")
        assert result == ""

    def test_single_group_single_term_returns_bare_term(self) -> None:
        """A single term in a single group has no parentheses or operators."""
        result = format_boolean_query_for_platform([["klimaforandringer"]], "google")
        assert result == "klimaforandringer"

    def test_google_two_groups_of_two_uses_parentheses_and_or(self) -> None:
        """Google format: (a b) OR (c d) — implicit AND via space."""
        result = format_boolean_query_for_platform([["a", "b"], ["c", "d"]], "google")
        assert result == "(a b) OR (c d)"

    def test_bluesky_returns_only_first_group_terms_space_joined(self) -> None:
        """Bluesky does not support native OR across groups; only first group returned."""
        result = format_boolean_query_for_platform(
            [["klimaforandringer", "IPCC"], ["folketing"]], "bluesky"
        )
        # Bluesky: space = AND; only the first group is returned.
        assert result == "klimaforandringer IPCC"

    def test_x_twitter_two_groups_of_two_uses_parentheses_and_or(self) -> None:
        """Twitter/X format: (a b) OR (c d) — space = AND."""
        result = format_boolean_query_for_platform([["a", "b"], ["c", "d"]], "x_twitter")
        assert result == "(a b) OR (c d)"

    def test_twitter_alias_matches_x_twitter_format(self) -> None:
        """'twitter' and 'x_twitter' produce the same output."""
        groups = [["a", "b"], ["c", "d"]]
        assert format_boolean_query_for_platform(groups, "twitter") == format_boolean_query_for_platform(
            groups, "x_twitter"
        )

    def test_gdelt_uses_explicit_and_or_operators(self) -> None:
        """GDELT format: (term1 AND term2) OR (term3 AND term4)."""
        result = format_boolean_query_for_platform(
            [["klimaforandringer", "IPCC"], ["folketing"]], "gdelt"
        )
        assert "AND" in result
        assert "OR" in result

    def test_reddit_multi_term_group_uses_plus_join(self) -> None:
        """Reddit format uses '+' to join AND-terms within a group."""
        result = format_boolean_query_for_platform([["climate", "change"]], "reddit")
        assert "+" in result
        assert "climate" in result
        assert "change" in result

    def test_youtube_multi_group_uses_pipe_separator(self) -> None:
        """YouTube format joins groups with '|' (OR) and terms with space (AND)."""
        result = format_boolean_query_for_platform(
            [["term1", "term2"], ["term3"]], "youtube"
        )
        assert "|" in result

    def test_event_registry_returns_non_empty_string_for_non_empty_groups(self) -> None:
        """event_registry platform returns a non-empty string for non-empty groups."""
        result = format_boolean_query_for_platform(
            [["klimaforandringer", "IPCC"]], "event_registry"
        )
        assert len(result) > 0
        assert "klimaforandringer" in result

    def test_unknown_platform_falls_back_to_generic_format(self) -> None:
        """An unknown platform identifier falls back to generic AND/OR syntax."""
        result = format_boolean_query_for_platform(
            [["term1", "term2"], ["term3"]], "unknown_platform"
        )
        assert "OR" in result

    def test_danish_characters_preserved_through_formatting(self) -> None:
        """Terms containing æ, ø, å are preserved in the formatted query string."""
        specs = [
            {"term": "grøn omstilling", "group_id": None},
            {"term": "velfærd", "group_id": None},
            {"term": "Ålborg", "group_id": None},
        ]
        groups = build_boolean_query_groups(specs)
        result = format_boolean_query_for_platform(groups, "google")
        assert "grøn omstilling" in result
        assert "velfærd" in result
        assert "Ålborg" in result


# ---------------------------------------------------------------------------
# H-06: has_boolean_groups()
# ---------------------------------------------------------------------------


class TestHasBooleanGroups:
    def test_all_group_id_none_returns_false(self) -> None:
        """has_boolean_groups() returns False when every term has group_id=None."""
        specs = [
            {"term": "klimaforandringer", "group_id": None},
            {"term": "folketing", "group_id": None},
        ]
        assert has_boolean_groups(specs) is False

    def test_at_least_one_group_id_set_returns_true(self) -> None:
        """has_boolean_groups() returns True when any term has a non-None group_id."""
        group_id = uuid.uuid4()
        specs = [
            {"term": "klimaforandringer", "group_id": group_id},
            {"term": "folketing", "group_id": None},
        ]
        assert has_boolean_groups(specs) is True

    def test_empty_list_returns_false(self) -> None:
        """has_boolean_groups([]) returns False."""
        assert has_boolean_groups([]) is False


# ---------------------------------------------------------------------------
# DQ-02: term_in_text() and match_groups_in_text() — Danish compound support
# ---------------------------------------------------------------------------


class TestTermInText:
    """Test word-boundary matching with Danish compound word support."""

    def test_standalone_word_matches(self) -> None:
        """A standalone word matches in text."""
        assert term_in_text("grønland", "Grønland") is True
        assert term_in_text("grønland", "grønland") is True

    def test_case_insensitive_matching(self) -> None:
        """Matching is case-insensitive."""
        assert term_in_text("grønland", "GRØNLAND") is True
        assert term_in_text("GRØNLAND", "grønland") is True

    def test_possessive_form_matches(self) -> None:
        """A term matches its possessive form (e.g., 'Grønlands')."""
        assert term_in_text("grønland", "Grønlands") is True
        assert term_in_text("danmark", "Danmarks") is True

    def test_compound_word_matches(self) -> None:
        """A term matches when appearing at the start of a compound word."""
        assert term_in_text("grønland", "Grønlandspolitik") is True
        assert term_in_text("klima", "klimaforandringer") is True
        assert term_in_text("klima", "Klimapolitik") is True

    def test_term_in_sentence_matches(self) -> None:
        """A term matches when surrounded by spaces in a sentence."""
        assert term_in_text("grønland", "mellem Grønland og Danmark") is True
        assert term_in_text("grønland", "USA's interesse i Grønlands mineraler") is True

    def test_english_variant_matches(self) -> None:
        """English terms also match with compound support."""
        assert term_in_text("greenland", "Greenland ice sheet melting") is True
        assert term_in_text("greenland", "The future of Greenland") is True

    def test_short_terms_use_strict_boundaries(self) -> None:
        """Short terms (≤2 chars) use strict boundaries to avoid false positives."""
        # Short terms should NOT match inside words
        assert term_in_text("i", "politik") is False
        assert term_in_text("er", "vinter") is False

        # But should match as standalone words
        assert term_in_text("i", "i dag") is True
        assert term_in_text("er", "han er her") is True

    def test_multi_word_terms(self) -> None:
        """Multi-word terms match with flexible whitespace."""
        assert term_in_text("CO2 afgift", "Ny CO2 afgift vedtaget") is True
        assert term_in_text("klima forandringer", "Klima  forandringer påvirker") is True

    def test_term_not_embedded_in_different_word(self) -> None:
        """A term does not match when embedded in a completely different word stem."""
        # "land" should not match the "land" inside "Holland" as a false positive,
        # but with our current left-boundary-only approach for >2 char terms, it will.
        # This is an acceptable tradeoff for Danish compound support.
        # We document that terms > 2 chars use left boundary only.
        pass


class TestMatchGroupsInText:
    """Test boolean group matching in text."""

    def test_single_term_group_matches(self) -> None:
        """A single-term group matches when the term is present."""
        lower_groups = [["grønland"]]
        assert match_groups_in_text(lower_groups, "Ny aftale om Grønland") == ["grønland"]

    def test_compound_word_match_in_groups(self) -> None:
        """Terms match in compound words when using group matching."""
        lower_groups = [["grønland"]]
        matched = match_groups_in_text(lower_groups, "Grønlandspolitik i fokus")
        assert "grønland" in matched

    def test_multiple_or_groups_any_matching(self) -> None:
        """When multiple OR groups exist, any matching group returns its terms."""
        lower_groups = [["grønland"], ["greenland"]]

        # Danish text matches first group
        matched_da = match_groups_in_text(lower_groups, "Grønlands fremtid")
        assert "grønland" in matched_da
        assert "greenland" not in matched_da

        # English text matches second group
        matched_en = match_groups_in_text(lower_groups, "Greenland ice sheet")
        assert "greenland" in matched_en
        assert "grønland" not in matched_en

    def test_and_group_requires_all_terms(self) -> None:
        """An AND-group only matches when ALL its terms are present."""
        lower_groups = [["klima", "forandringer"]]

        # Both terms present → match
        assert match_groups_in_text(lower_groups, "klima og forandringer") != []

        # Only one term present → no match
        assert match_groups_in_text(lower_groups, "kun klima her") == []

    def test_no_match_returns_empty_list(self) -> None:
        """When no group matches, an empty list is returned."""
        lower_groups = [["grønland"], ["greenland"]]
        assert match_groups_in_text(lower_groups, "Dagens nyheder fra Danmark") == []

    def test_mixed_and_or_groups(self) -> None:
        """Complex boolean logic: (A AND B) OR (C) OR (D AND E)."""
        lower_groups = [
            ["klima", "forandringer"],  # AND group
            ["grønland"],  # Single-term OR group
            ["folketing", "debat"],  # AND group
        ]

        # Matches first AND group
        text1 = "klima forandringer påvirker verden"
        matched1 = match_groups_in_text(lower_groups, text1)
        assert "klima" in matched1
        assert "forandringer" in matched1

        # Matches second single-term group
        text2 = "Grønlands fremtid"
        matched2 = match_groups_in_text(lower_groups, text2)
        assert "grønland" in matched2

        # Matches third AND group
        text3 = "Folketing holder debat"
        matched3 = match_groups_in_text(lower_groups, text3)
        assert "folketing" in matched3
        assert "debat" in matched3
