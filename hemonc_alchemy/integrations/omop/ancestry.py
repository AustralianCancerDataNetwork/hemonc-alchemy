"""Resolve drug main_class groups against the configured live OMOP vocabulary."""

from __future__ import annotations

from collections import defaultdict
from types import MappingProxyType
from typing import Any
from weakref import WeakKeyDictionary

import sqlalchemy as sa

from ...caching import cached_per_engine, with_cache_clear
from ...model import Drugs
from ...toolkit.analytics.treatment.classification.ancestry import (
    ENDOCRINE_ROOT_CUI,
    SUPPORTIVE_ROOT_CUI,
    MainClassAncestry,
    compute_main_class_ancestry,
)
from .binding import omop_available
from .mapping import resolve_hemonc_concepts
from .queries import _hemonc_relationships


@cached_per_engine
def _ancestry_indexes(session: Any) -> WeakKeyDictionary[Any, MainClassAncestry]:
    """One vocabulary-engine cache for each source engine."""
    return WeakKeyDictionary()


@with_cache_clear(_ancestry_indexes.cache_clear)
def main_class_ancestry(session: Any, *, omop_session: Any = None) -> MainClassAncestry:
    """Runtime index cached per source/vocabulary engine pair.

    Both tables may share a database, or separate sessions can be supplied.
    Missing OMOP returns an explicit unavailable result, never a static fallback.
    Transient availability failures are not cached. Clear the cache after
    reloading source or vocabulary data via main_class_ancestry.cache_clear().
    """
    vocabulary_session = session if omop_session is None else omop_session
    bind = vocabulary_session.get_bind()
    engine = getattr(bind, "engine", bind)
    indexes = _ancestry_indexes(session)
    if engine in indexes:
        return indexes[engine]
    if not omop_available(vocabulary_session, require_relationships=True):
        return MainClassAncestry(MappingProxyType({}), "OMOP vocabulary is unavailable")

    roots = resolve_hemonc_concepts(vocabulary_session, (ENDOCRINE_ROOT_CUI, SUPPORTIVE_ROOT_CUI))
    relationships = _hemonc_relationships(vocabulary_session, ("Is a",))
    groups: dict[str, set[int]] = defaultdict(set)
    for main_class, cui in session.execute(sa.select(Drugs.main_class, Drugs.drug_cui)):
        if main_class is not None and str(main_class).strip():
            groups[str(main_class)].add(int(cui))
    index = compute_main_class_ancestry(
        groups,
        ((edge.source.concept_code, edge.target.concept_code, edge.target.concept_class_id)
         for edge in relationships),
        available_roots=(root.hemonc_cui for root in roots
                         if root.concept.concept_class_id == "Component Class"),
    )
    indexes[engine] = index
    return index


__all__ = ["main_class_ancestry"]
