"""Unit tests for the arena base module.

Tests cover:
- Tier enum stability (values must never change — they are stored in the DB)
- ArenaCollector interface contract (abstract methods, optional overrides)
- ArenaRegistry: register, get_arena, list_arenas, overwrite warning
- estimate_credits default returns 0 (free tier behaviour)
- health_check default returns 'not_implemented' status

These are pure unit tests — no database, no network, no Celery.
"""

from __future__ import annotations

import logging

import pytest

from issue_observatory.arenas.base import ArenaCollector, Tier
from issue_observatory.arenas.registry import _REGISTRY, get_arena, list_arenas, register


# ---------------------------------------------------------------------------
# Tier enum
# ---------------------------------------------------------------------------


class TestTierEnum:
    def test_tier_free_value_is_stable(self) -> None:
        """Tier.FREE must equal 'free' — this string is stored in the database.

        If this test fails, it means someone changed the enum value, which would
        corrupt all existing 'free' rows in content_records and collection_runs.
        """
        assert Tier.FREE.value == "free"

    def test_tier_medium_value_is_stable(self) -> None:
        """Tier.MEDIUM must equal 'medium'."""
        assert Tier.MEDIUM.value == "medium"

    def test_tier_premium_value_is_stable(self) -> None:
        """Tier.PREMIUM must equal 'premium'."""
        assert Tier.PREMIUM.value == "premium"

    def test_tier_str_subclass(self) -> None:
        """Tier is a str subclass so it serializes naturally in JSON/JSONB."""
        assert isinstance(Tier.FREE, str)
        assert Tier.FREE == "free"

    def test_tier_from_string(self) -> None:
        """Tier can be constructed from its string value — used when reading DB rows."""
        assert Tier("free") == Tier.FREE
        assert Tier("medium") == Tier.MEDIUM
        assert Tier("premium") == Tier.PREMIUM

    def test_tier_invalid_value_raises(self) -> None:
        """Unknown tier strings raise ValueError — not a silent default."""
        with pytest.raises(ValueError):
            Tier("ultra")


# ---------------------------------------------------------------------------
# Minimal concrete collector for testing
# ---------------------------------------------------------------------------


def _make_minimal_collector() -> type[ArenaCollector]:
    """Return a minimal concrete ArenaCollector subclass for testing.

    Implements all abstract methods with stubs.  Should NOT be registered in
    the live registry to avoid polluting it between tests.
    """

    class _MinimalCollector(ArenaCollector):
        arena_name = "_test_minimal"
        platform_name = "_test_platform"
        supported_tiers = [Tier.FREE]

        async def collect_by_terms(self, terms, tier, date_from=None, date_to=None, max_results=None):  # type: ignore[override]
            return []

        async def collect_by_actors(self, actor_ids, tier, date_from=None, date_to=None, max_results=None):  # type: ignore[override]
            raise NotImplementedError("_MinimalCollector does not support actor-based collection.")

        def get_tier_config(self, tier):  # type: ignore[override]
            return {"provider": "none", "max_results_per_query": 0}

        def normalize(self, raw_item):  # type: ignore[override]
            return {}

    return _MinimalCollector


class TestArenaCollectorInterface:
    def test_abstract_class_cannot_be_instantiated(self) -> None:
        """ArenaCollector cannot be instantiated directly — it is abstract."""
        with pytest.raises(TypeError):
            ArenaCollector()  # type: ignore[abstract]

    def test_concrete_subclass_can_be_instantiated(self) -> None:
        """A fully implemented subclass can be instantiated without errors."""
        cls = _make_minimal_collector()
        instance = cls()
        assert instance.arena_name == "_test_minimal"
        assert instance.platform_name == "_test_platform"

    def test_repr_includes_arena_and_platform(self) -> None:
        """__repr__ includes arena_name and platform_name for debugging."""
        cls = _make_minimal_collector()
        instance = cls()
        r = repr(instance)

        assert "_test_minimal" in r
        assert "_test_platform" in r

    async def test_estimate_credits_default_is_zero(self) -> None:
        """The default estimate_credits() returns 0 — safe for free-tier arenas."""
        cls = _make_minimal_collector()
        instance = cls()

        result = await instance.estimate_credits(terms=["test"], tier=Tier.FREE)

        assert result == 0

    async def test_health_check_default_returns_not_implemented(self) -> None:
        """The default health_check() returns status='not_implemented'."""
        cls = _make_minimal_collector()
        instance = cls()

        result = await instance.health_check()

        assert result["status"] == "not_implemented"
        assert result["arena"] == "_test_minimal"
        assert result["platform"] == "_test_platform"
        assert "checked_at" in result

    def test_validate_tier_raises_for_unsupported_tier(self) -> None:
        """_validate_tier() raises ValueError for a tier not in supported_tiers."""
        cls = _make_minimal_collector()
        instance = cls()

        with pytest.raises(ValueError, match="Tier 'medium' is not supported"):
            instance._validate_tier(Tier.MEDIUM)

    def test_validate_tier_passes_for_supported_tier(self) -> None:
        """_validate_tier() does not raise for a supported tier."""
        cls = _make_minimal_collector()
        instance = cls()
        instance._validate_tier(Tier.FREE)  # should not raise

    def test_credential_pool_and_rate_limiter_default_to_none(self) -> None:
        """Constructor defaults credential_pool and rate_limiter to None."""
        cls = _make_minimal_collector()
        instance = cls()

        assert instance.credential_pool is None
        assert instance.rate_limiter is None

    def test_constructor_accepts_credential_pool_and_rate_limiter(self) -> None:
        """Constructor stores injected credential_pool and rate_limiter."""
        cls = _make_minimal_collector()
        mock_pool = object()
        mock_limiter = object()

        instance = cls(credential_pool=mock_pool, rate_limiter=mock_limiter)

        assert instance.credential_pool is mock_pool
        assert instance.rate_limiter is mock_limiter


# ---------------------------------------------------------------------------
# Arena registry
# ---------------------------------------------------------------------------


class TestArenaRegistry:
    def test_register_and_retrieve(self) -> None:
        """@register stores a collector class and get_arena retrieves it."""
        unique_name = "_test_registry_retrieval"

        @register
        class _RegistryTestCollector(ArenaCollector):
            arena_name = unique_name
            platform_name = "_test"
            supported_tiers = [Tier.FREE]

            async def collect_by_terms(self, terms, tier, **kw):  # type: ignore[override]
                return []

            async def collect_by_actors(self, actor_ids, tier, **kw):  # type: ignore[override]
                raise NotImplementedError

            def get_tier_config(self, tier):  # type: ignore[override]
                return {}

            def normalize(self, raw_item):  # type: ignore[override]
                return {}

        retrieved = get_arena(unique_name)
        assert retrieved is _RegistryTestCollector

        # Cleanup to avoid leaking into other tests
        _REGISTRY.pop(unique_name, None)

    def test_get_arena_raises_for_unknown_name(self) -> None:
        """get_arena() raises KeyError for unregistered names."""
        with pytest.raises(KeyError, match="is not registered"):
            get_arena("__definitely_not_registered__")

    def test_list_arenas_returns_metadata(self) -> None:
        """list_arenas() returns a list of dicts with required metadata keys."""
        unique_name = "_test_list_arenas_meta"

        @register
        class _ListArenaTestCollector(ArenaCollector):
            arena_name = unique_name
            platform_name = "_test_platform_meta"
            supported_tiers = [Tier.FREE, Tier.MEDIUM]

            async def collect_by_terms(self, terms, tier, **kw):  # type: ignore[override]
                return []

            async def collect_by_actors(self, actor_ids, tier, **kw):  # type: ignore[override]
                raise NotImplementedError

            def get_tier_config(self, tier):  # type: ignore[override]
                return {}

            def normalize(self, raw_item):  # type: ignore[override]
                return {}

        arenas = list_arenas()
        arena_names = {a["arena_name"] for a in arenas}

        assert unique_name in arena_names
        matching = next(a for a in arenas if a["arena_name"] == unique_name)

        assert matching["platform_name"] == "_test_platform_meta"
        assert set(matching["supported_tiers"]) == {"free", "medium"}
        assert "collector_class" in matching

        # Cleanup
        _REGISTRY.pop(unique_name, None)

    def test_register_overwrites_with_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Registering an arena name twice overwrites the first and logs a warning."""
        unique_name = "_test_overwrite_warning"

        class _Base(ArenaCollector):
            arena_name = unique_name
            platform_name = "_test"
            supported_tiers = [Tier.FREE]

            async def collect_by_terms(self, terms, tier, **kw):  # type: ignore[override]
                return []

            async def collect_by_actors(self, actor_ids, tier, **kw):  # type: ignore[override]
                raise NotImplementedError

            def get_tier_config(self, tier):  # type: ignore[override]
                return {}

            def normalize(self, raw_item):  # type: ignore[override]
                return {}

        class _First(_Base):
            pass

        class _Second(_Base):
            pass

        register(_First)

        with caplog.at_level(logging.WARNING, logger="issue_observatory.arenas.registry"):
            register(_Second)

        assert any("already registered" in rec.message for rec in caplog.records), (
            f"Expected overwrite warning in log records: {[r.message for r in caplog.records]}"
        )
        assert get_arena(unique_name) is _Second

        # Cleanup
        _REGISTRY.pop(unique_name, None)

    def test_list_arenas_is_sorted_alphabetically(self) -> None:
        """list_arenas() returns arenas sorted alphabetically by arena_name."""
        arenas = list_arenas()
        names = [a["arena_name"] for a in arenas]

        assert names == sorted(names), (
            f"list_arenas() must be sorted: {names}"
        )
