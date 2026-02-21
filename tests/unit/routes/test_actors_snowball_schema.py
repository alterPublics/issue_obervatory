"""Tests for snowball sampling and corpus co-occurrence Pydantic schemas.

These are pure schema validation tests -- no database, HTTP, or async I/O
required.  They verify the request/response models defined in
``issue_observatory.api.routes.actors`` serialize and validate correctly,
with particular attention to new fields (``discovery_method``,
``min_comention_records``) and the corpus co-occurrence endpoint schemas.

Owned by QA Engineer.
"""

from __future__ import annotations

import os
import uuid

import pytest

# ---------------------------------------------------------------------------
# Env bootstrap -- required before any app module import triggers Settings()
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault(
    "CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA=="
)

from issue_observatory.api.routes.actors import (  # noqa: E402
    CoOccurrencePair,
    CorpusCoOccurrenceRequest,
    CorpusCoOccurrenceResponse,
    SnowballActorEntry,
    SnowballRequest,
)


# ===========================================================================
# SnowballActorEntry
# ===========================================================================


class TestSnowballActorEntry:
    """Validate SnowballActorEntry schema, focusing on the discovery_method field."""

    def test_instantiate_with_all_fields(self) -> None:
        """A SnowballActorEntry can be created with every field explicitly set."""
        entry = SnowballActorEntry(
            actor_id="abc-123",
            canonical_name="Anders And",
            platforms=["bluesky", "reddit"],
            discovery_depth=1,
            discovery_method="bluesky_follows",
        )
        assert entry.actor_id == "abc-123"
        assert entry.canonical_name == "Anders And"
        assert entry.platforms == ["bluesky", "reddit"]
        assert entry.discovery_depth == 1
        assert entry.discovery_method == "bluesky_follows"

    def test_discovery_method_defaults_to_empty_string(self) -> None:
        """When discovery_method is omitted, it defaults to an empty string."""
        entry = SnowballActorEntry(
            actor_id="",
            canonical_name="Test Actor",
            platforms=["reddit"],
            discovery_depth=0,
        )
        assert entry.discovery_method == ""

    def test_discovery_method_serializes_in_model_dump(self) -> None:
        """discovery_method is included when the model is serialized via model_dump()."""
        entry = SnowballActorEntry(
            actor_id="uuid-placeholder",
            canonical_name="Mette Frederiksen",
            platforms=["x_twitter"],
            discovery_depth=2,
            discovery_method="comention_fallback",
        )
        dumped = entry.model_dump()
        assert "discovery_method" in dumped
        assert dumped["discovery_method"] == "comention_fallback"

    def test_discovery_method_default_serializes_in_model_dump(self) -> None:
        """Even the default empty-string value appears in model_dump() output."""
        entry = SnowballActorEntry(
            actor_id="",
            canonical_name="Seed Actor",
            platforms=["bluesky"],
            discovery_depth=0,
        )
        dumped = entry.model_dump()
        assert "discovery_method" in dumped
        assert dumped["discovery_method"] == ""

    def test_discovery_method_accepts_arbitrary_strings(self) -> None:
        """discovery_method is a free-form string -- any value is valid."""
        for method in ["seed", "bluesky_follows", "comention_fallback", "reddit_moderated"]:
            entry = SnowballActorEntry(
                actor_id="id",
                canonical_name="Name",
                platforms=["bluesky"],
                discovery_depth=1,
                discovery_method=method,
            )
            assert entry.discovery_method == method

    def test_danish_characters_in_canonical_name_preserved(self) -> None:
        """Danish characters (ae, oe, aa) survive round-trip through the schema."""
        entry = SnowballActorEntry(
            actor_id="dk-actor",
            canonical_name="Soeren Broestroem",
            platforms=["bluesky"],
            discovery_depth=0,
            discovery_method="seed",
        )
        assert entry.canonical_name == "Soeren Broestroem"

        # Also with actual special characters
        entry2 = SnowballActorEntry(
            actor_id="dk-actor-2",
            canonical_name="\u00c6rlig \u00d8ster\u00e5",
            platforms=["reddit"],
            discovery_depth=1,
            discovery_method="comention_fallback",
        )
        dumped = entry2.model_dump()
        assert dumped["canonical_name"] == "\u00c6rlig \u00d8ster\u00e5"


# ===========================================================================
# SnowballRequest
# ===========================================================================


class TestSnowballRequest:
    """Validate SnowballRequest schema, focusing on min_comention_records."""

    def test_min_comention_records_defaults_to_two(self) -> None:
        """When min_comention_records is omitted, the default value is 2."""
        req = SnowballRequest(
            seed_actor_ids=[uuid.uuid4()],
            platforms=["bluesky"],
        )
        assert req.min_comention_records == 2

    def test_min_comention_records_accepts_custom_value(self) -> None:
        """A caller can override min_comention_records with any integer."""
        req = SnowballRequest(
            seed_actor_ids=[uuid.uuid4()],
            platforms=["reddit"],
            min_comention_records=5,
        )
        assert req.min_comention_records == 5

    def test_all_defaults_applied(self) -> None:
        """Verify all default values when only required fields are supplied."""
        actor_id = uuid.uuid4()
        req = SnowballRequest(
            seed_actor_ids=[actor_id],
            platforms=["bluesky"],
        )
        assert req.max_depth == 2
        assert req.max_actors_per_step == 20
        assert req.add_to_actor_list_id is None
        assert req.auto_create_actors is True
        assert req.min_comention_records == 2

    def test_full_request_with_all_fields(self) -> None:
        """A fully-specified request round-trips through model_dump() correctly."""
        actor_id = uuid.uuid4()
        list_id = uuid.uuid4()
        req = SnowballRequest(
            seed_actor_ids=[actor_id],
            platforms=["bluesky", "reddit"],
            max_depth=3,
            max_actors_per_step=50,
            add_to_actor_list_id=list_id,
            auto_create_actors=False,
            min_comention_records=10,
        )
        dumped = req.model_dump()
        assert dumped["seed_actor_ids"] == [actor_id]
        assert dumped["platforms"] == ["bluesky", "reddit"]
        assert dumped["max_depth"] == 3
        assert dumped["max_actors_per_step"] == 50
        assert dumped["add_to_actor_list_id"] == list_id
        assert dumped["auto_create_actors"] is False
        assert dumped["min_comention_records"] == 10

    def test_multiple_seed_actors(self) -> None:
        """seed_actor_ids accepts a list with multiple UUIDs."""
        ids = [uuid.uuid4() for _ in range(5)]
        req = SnowballRequest(
            seed_actor_ids=ids,
            platforms=["bluesky"],
        )
        assert len(req.seed_actor_ids) == 5
        assert req.seed_actor_ids == ids

    def test_min_comention_records_zero_accepted(self) -> None:
        """Zero is a valid value for min_comention_records (no minimum threshold)."""
        req = SnowballRequest(
            seed_actor_ids=[uuid.uuid4()],
            platforms=["bluesky"],
            min_comention_records=0,
        )
        assert req.min_comention_records == 0

    def test_min_comention_records_serializes_in_model_dump(self) -> None:
        """min_comention_records appears in model_dump() output."""
        req = SnowballRequest(
            seed_actor_ids=[uuid.uuid4()],
            platforms=["bluesky"],
            min_comention_records=7,
        )
        dumped = req.model_dump()
        assert "min_comention_records" in dumped
        assert dumped["min_comention_records"] == 7


# ===========================================================================
# CorpusCoOccurrenceRequest
# ===========================================================================


class TestCorpusCoOccurrenceRequest:
    """Validate CorpusCoOccurrenceRequest schema."""

    def test_requires_query_design_id(self) -> None:
        """query_design_id is mandatory -- omitting it raises a ValidationError."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            CorpusCoOccurrenceRequest()  # type: ignore[call-arg]

    def test_accepts_valid_uuid(self) -> None:
        """A valid UUID is accepted for query_design_id."""
        qd_id = uuid.uuid4()
        req = CorpusCoOccurrenceRequest(query_design_id=qd_id)
        assert req.query_design_id == qd_id

    def test_accepts_uuid_as_string(self) -> None:
        """Pydantic coerces a UUID-formatted string to a uuid.UUID."""
        qd_id = uuid.uuid4()
        req = CorpusCoOccurrenceRequest(query_design_id=str(qd_id))
        assert req.query_design_id == qd_id

    def test_min_co_occurrences_defaults_to_three(self) -> None:
        """When min_co_occurrences is omitted, the default value is 3."""
        req = CorpusCoOccurrenceRequest(query_design_id=uuid.uuid4())
        assert req.min_co_occurrences == 3

    def test_min_co_occurrences_custom_value(self) -> None:
        """A caller can set min_co_occurrences to any integer."""
        req = CorpusCoOccurrenceRequest(
            query_design_id=uuid.uuid4(),
            min_co_occurrences=10,
        )
        assert req.min_co_occurrences == 10

    def test_model_dump_includes_all_fields(self) -> None:
        """model_dump() output contains both fields."""
        qd_id = uuid.uuid4()
        req = CorpusCoOccurrenceRequest(
            query_design_id=qd_id,
            min_co_occurrences=5,
        )
        dumped = req.model_dump()
        assert dumped["query_design_id"] == qd_id
        assert dumped["min_co_occurrences"] == 5

    def test_rejects_invalid_uuid(self) -> None:
        """A non-UUID string for query_design_id raises a ValidationError."""
        with pytest.raises(Exception):
            CorpusCoOccurrenceRequest(query_design_id="not-a-uuid")


# ===========================================================================
# CoOccurrencePair
# ===========================================================================


class TestCoOccurrencePair:
    """Validate CoOccurrencePair schema."""

    def test_all_fields_set(self) -> None:
        """A CoOccurrencePair is created with all required fields."""
        pair = CoOccurrencePair(
            actor_a="user_alpha",
            actor_b="user_beta",
            platform="bluesky",
            co_occurrence_count=7,
        )
        assert pair.actor_a == "user_alpha"
        assert pair.actor_b == "user_beta"
        assert pair.platform == "bluesky"
        assert pair.co_occurrence_count == 7

    def test_model_dump_round_trip(self) -> None:
        """model_dump() -> CoOccurrencePair(**dumped) produces an equivalent object."""
        pair = CoOccurrencePair(
            actor_a="a",
            actor_b="b",
            platform="reddit",
            co_occurrence_count=42,
        )
        dumped = pair.model_dump()
        restored = CoOccurrencePair(**dumped)
        assert restored == pair

    def test_danish_actor_names_preserved(self) -> None:
        """Danish characters in actor identifiers survive serialization."""
        pair = CoOccurrencePair(
            actor_a="\u00f8stergaard",
            actor_b="\u00e6blet\u00e5r",
            platform="bluesky",
            co_occurrence_count=3,
        )
        dumped = pair.model_dump()
        assert dumped["actor_a"] == "\u00f8stergaard"
        assert dumped["actor_b"] == "\u00e6blet\u00e5r"

    def test_requires_all_fields(self) -> None:
        """Omitting any required field raises a ValidationError."""
        with pytest.raises(Exception):
            CoOccurrencePair(actor_a="a", actor_b="b", platform="x")  # type: ignore[call-arg]
        with pytest.raises(Exception):
            CoOccurrencePair(actor_a="a", actor_b="b", co_occurrence_count=1)  # type: ignore[call-arg]
        with pytest.raises(Exception):
            CoOccurrencePair(actor_a="a", platform="x", co_occurrence_count=1)  # type: ignore[call-arg]


# ===========================================================================
# CorpusCoOccurrenceResponse
# ===========================================================================


class TestCorpusCoOccurrenceResponse:
    """Validate CorpusCoOccurrenceResponse schema."""

    def test_empty_response(self) -> None:
        """An empty result set has zero total_pairs and an empty pairs list."""
        resp = CorpusCoOccurrenceResponse(pairs=[], total_pairs=0)
        assert resp.pairs == []
        assert resp.total_pairs == 0

    def test_total_pairs_matches_length(self) -> None:
        """total_pairs should equal the actual number of pair entries."""
        pairs = [
            CoOccurrencePair(
                actor_a=f"a{i}", actor_b=f"b{i}", platform="bluesky", co_occurrence_count=i + 1
            )
            for i in range(5)
        ]
        resp = CorpusCoOccurrenceResponse(pairs=pairs, total_pairs=5)
        assert resp.total_pairs == len(resp.pairs)

    def test_model_dump_structure(self) -> None:
        """model_dump() produces a dict with 'pairs' (list of dicts) and 'total_pairs' (int)."""
        pair = CoOccurrencePair(
            actor_a="anna", actor_b="lars", platform="reddit", co_occurrence_count=12
        )
        resp = CorpusCoOccurrenceResponse(pairs=[pair], total_pairs=1)
        dumped = resp.model_dump()

        assert isinstance(dumped["pairs"], list)
        assert len(dumped["pairs"]) == 1
        assert isinstance(dumped["pairs"][0], dict)
        assert dumped["total_pairs"] == 1

    def test_pairs_contain_expected_keys(self) -> None:
        """Each serialized pair dict contains the four expected keys."""
        pair = CoOccurrencePair(
            actor_a="x", actor_b="y", platform="telegram", co_occurrence_count=3
        )
        resp = CorpusCoOccurrenceResponse(pairs=[pair], total_pairs=1)
        dumped = resp.model_dump()
        pair_dict = dumped["pairs"][0]
        assert set(pair_dict.keys()) == {"actor_a", "actor_b", "platform", "co_occurrence_count"}

    def test_total_pairs_can_disagree_with_length(self) -> None:
        """The schema does not enforce total_pairs == len(pairs) at the Pydantic level.

        This is an informational field set by the server. Callers are responsible
        for setting it correctly, but validation does not reject a mismatch.
        """
        pair = CoOccurrencePair(
            actor_a="x", actor_b="y", platform="bluesky", co_occurrence_count=1
        )
        resp = CorpusCoOccurrenceResponse(pairs=[pair], total_pairs=999)
        assert resp.total_pairs == 999
        assert len(resp.pairs) == 1

    def test_multiple_platforms_in_pairs(self) -> None:
        """A response can contain pairs from different platforms."""
        pairs = [
            CoOccurrencePair(
                actor_a="a1", actor_b="b1", platform="bluesky", co_occurrence_count=5
            ),
            CoOccurrencePair(
                actor_a="a2", actor_b="b2", platform="reddit", co_occurrence_count=3
            ),
            CoOccurrencePair(
                actor_a="a3", actor_b="b3", platform="telegram", co_occurrence_count=8
            ),
        ]
        resp = CorpusCoOccurrenceResponse(pairs=pairs, total_pairs=3)
        platforms = {p.platform for p in resp.pairs}
        assert platforms == {"bluesky", "reddit", "telegram"}

    def test_json_serialization_round_trip(self) -> None:
        """model_dump_json() -> model_validate_json() produces an equivalent object."""
        pair = CoOccurrencePair(
            actor_a="finn", actor_b="jake", platform="x_twitter", co_occurrence_count=10
        )
        resp = CorpusCoOccurrenceResponse(pairs=[pair], total_pairs=1)
        json_str = resp.model_dump_json()
        restored = CorpusCoOccurrenceResponse.model_validate_json(json_str)
        assert restored == resp
