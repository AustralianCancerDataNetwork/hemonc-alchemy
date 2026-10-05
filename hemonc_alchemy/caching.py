"""Per-engine caching for lookups over tables that never change within a process."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any
from weakref import WeakKeyDictionary


def cached_per_engine[T](fn: Callable[[Any], T]) -> Callable[[Any], T]:
    """Cache `fn(session)` per engine; the underlying tables never change within a process."""
    store: WeakKeyDictionary[Any, T] = WeakKeyDictionary()

    @wraps(fn)
    def wrapper(session: Any) -> T:
        bind = session.get_bind()
        engine = getattr(bind, "engine", bind)
        if engine not in store:
            store[engine] = fn(session)
        return store[engine]

    wrapper.cache_clear = store.clear  # type: ignore[attr-defined]
    return wrapper


__all__ = ["cached_per_engine"]
