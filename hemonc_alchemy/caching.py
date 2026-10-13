"""Per-engine caching for lookups over tables that never change within a process."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, Protocol, cast
from weakref import WeakKeyDictionary


def cache_context(session: Any) -> tuple[Any, tuple[tuple[str, str | None], ...]]:
    """Return the base engine and frozen schema map for a Session."""
    bind = session.get_bind()
    engine = getattr(bind, "engine", bind)
    mapping = session.info.get("schema_translate_map")
    if mapping is None:
        mapping = bind.get_execution_options().get("schema_translate_map")
    return engine, tuple(sorted((mapping or {}).items()))


class CacheClearable[**P, T](Protocol):
    """A callable with an explicit cache invalidation operation."""

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T: ...

    cache_clear: Callable[[], None]


def with_cache_clear[**P, T](
    clear: Callable[[], None],
) -> Callable[[Callable[P, T]], CacheClearable[P, T]]:
    """Attach a typed cache invalidator while preserving the call signature."""
    def decorate(fn: Callable[P, T]) -> CacheClearable[P, T]:
        decorated = cast(CacheClearable[P, T], fn)
        decorated.cache_clear = clear
        return decorated

    return decorate


def cached_per_engine[T](fn: Callable[[Any], T]) -> CacheClearable[[Any], T]:
    """Cache `fn(session)` per engine and schema map."""
    store: WeakKeyDictionary[Any, dict[tuple[tuple[str, str | None], ...], T]] = WeakKeyDictionary()

    @with_cache_clear(store.clear)
    @wraps(fn)
    def wrapper(session: Any) -> T:
        engine, schema_map = cache_context(session)
        values = store.setdefault(engine, {})
        if schema_map not in values:
            values[schema_map] = fn(session)
        return values[schema_map]

    return wrapper


__all__ = ["CacheClearable", "cache_context", "cached_per_engine", "with_cache_clear"]
