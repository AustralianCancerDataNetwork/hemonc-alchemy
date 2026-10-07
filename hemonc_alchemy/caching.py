"""Per-engine caching for lookups over tables that never change within a process."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, Protocol, cast
from weakref import WeakKeyDictionary


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
    """Cache `fn(session)` per engine; the underlying tables never change within a process."""
    store: WeakKeyDictionary[Any, T] = WeakKeyDictionary()

    @with_cache_clear(store.clear)
    @wraps(fn)
    def wrapper(session: Any) -> T:
        bind = session.get_bind()
        engine = getattr(bind, "engine", bind)
        if engine not in store:
            store[engine] = fn(session)
        return store[engine]

    return wrapper


__all__ = ["CacheClearable", "cached_per_engine", "with_cache_clear"]
