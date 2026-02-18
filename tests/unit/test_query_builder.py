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
