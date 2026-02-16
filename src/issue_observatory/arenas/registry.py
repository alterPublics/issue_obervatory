"""Arena registry for dynamic discovery and registration of collectors.

Arenas register themselves on import using the ``@register`` decorator.
The registry is a module-level singleton that maps ``arena_name`` strings
to ``ArenaCollector`` subclasses.

Example — registering an arena::

    from issue_observatory.arenas.registry import register
    from issue_observatory.arenas.base import ArenaCollector, Tier

    @register
    class BlueskyCollector(ArenaCollector):
        arena_name = "bluesky"
        platform_name = "bluesky"
        supported_tiers = [Tier.FREE]
        ...

Example — looking up a collector::

    from issue_observatory.arenas.registry import get_arena, list_arenas

    cls = get_arena("bluesky")
    collector = cls()

    all_arenas = list_arenas()
    # [{"arena_name": "bluesky", "platform_name": "bluesky", "supported_tiers": ["free"]}, ...]
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from issue_observatory.arenas.base import ArenaCollector

logger = logging.getLogger(__name__)

# Registry singleton: arena_name -> ArenaCollector subclass
_REGISTRY: dict[str, type[ArenaCollector]] = {}


def register(cls: type[ArenaCollector]) -> type[ArenaCollector]:
    """Decorator that registers an ``ArenaCollector`` subclass in the global registry.

    The class must define ``arena_name`` as a class-level string attribute.
    If an arena with the same name has already been registered, the new
    registration overwrites the old one and a warning is emitted.

    Args:
        cls: ``ArenaCollector`` subclass to register.

    Returns:
        The same class (decorator pass-through), enabling normal class
        definition syntax.

    Raises:
        AttributeError: If ``cls`` does not define ``arena_name``.

    Example::

        @register
        class MyCollector(ArenaCollector):
            arena_name = "my_arena"
            ...
    """
    arena_name: str = cls.arena_name  # type: ignore[attr-defined]
    if arena_name in _REGISTRY:
        logger.warning(
            "Arena '%s' is already registered (was %s). Overwriting with %s.",
            arena_name,
            _REGISTRY[arena_name].__qualname__,
            cls.__qualname__,
        )
    _REGISTRY[arena_name] = cls
    logger.debug("Registered arena collector: %s (%s)", arena_name, cls.__qualname__)
    return cls


def get_arena(arena_name: str) -> type[ArenaCollector]:
    """Retrieve a registered ``ArenaCollector`` class by arena name.

    Args:
        arena_name: The ``arena_name`` class attribute value to look up
            (e.g. ``"google_search"``, ``"bluesky"``).

    Returns:
        The ``ArenaCollector`` subclass registered under *arena_name*.

    Raises:
        KeyError: If no arena with the given name is registered. Callers
            should call ``autodiscover()`` before their first lookup if
            registration may not have happened yet.
    """
    try:
        return _REGISTRY[arena_name]
    except KeyError:
        registered = list(_REGISTRY.keys())
        raise KeyError(
            f"Arena '{arena_name}' is not registered. "
            f"Registered arenas: {registered}. "
            "Did you forget to call autodiscover() or import the arena module?"
        ) from None


def list_arenas() -> list[dict]:  # type: ignore[type-arg]
    """Return metadata for all registered arenas.

    The list is ordered alphabetically by ``arena_name``. This output is
    used by the collection launcher's arena configuration grid and by the
    admin health dashboard.

    Returns:
        List of dicts, each containing:
        - ``arena_name`` (str): Logical arena identifier.
        - ``platform_name`` (str): Underlying platform identifier.
        - ``supported_tiers`` (list[str]): Tier values the arena supports.
        - ``collector_class`` (str): Fully qualified class name (for debugging).
    """
    return [
        {
            "arena_name": cls.arena_name,  # type: ignore[attr-defined]
            "platform_name": cls.platform_name,  # type: ignore[attr-defined]
            "supported_tiers": [
                t.value for t in cls.supported_tiers  # type: ignore[attr-defined]
            ],
            "collector_class": f"{cls.__module__}.{cls.__qualname__}",
        }
        for cls in sorted(_REGISTRY.values(), key=lambda c: c.arena_name)  # type: ignore[attr-defined]
    ]


def autodiscover() -> None:
    """Import all arena ``collector`` modules to trigger ``@register`` decorators.

    This walks the ``issue_observatory.arenas`` package tree and imports
    every submodule named ``collector``. Arenas that use the ``@register``
    decorator will be added to the registry on import.

    This function is idempotent — calling it multiple times is safe.

    Raises:
        ImportError: If an individual collector module fails to import.
            Other arenas continue to load; the error is logged.
    """
    import issue_observatory.arenas as arenas_pkg

    arenas_path = arenas_pkg.__path__
    arenas_prefix = arenas_pkg.__name__ + "."

    for finder, module_name, is_pkg in pkgutil.walk_packages(
        path=arenas_path, prefix=arenas_prefix
    ):
        if module_name.endswith(".collector"):
            try:
                importlib.import_module(module_name)
                logger.debug("Autodiscovered arena module: %s", module_name)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Failed to import arena collector module '%s': %s",
                    module_name,
                    exc,
                    exc_info=True,
                )
