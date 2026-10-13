"""Resolve drug main_class groups against the configured live OMOP vocabulary."""

from __future__ import annotations

from collections import defaultdict
from types import MappingProxyType
from typing import Any
from weakref import WeakKeyDictionary

import sqlalchemy as sa

from ...caching import cache_context, cached_per_engine, with_cache_clear
from ...model import Drugs
from ...toolkit.analytics.treatment.classification.ancestry import (
    ENDOCRINE_ROOT_CUI,
    SUPPORTIVE_ROOT_CUI,
    MainClassAncestry,
    compute_main_class_ancestry,
)
from .mapping import resolve_hemonc_concepts
from .queries import _hemonc_relationships
from .schema import omop_availability


@cached_per_engine
def _ancestry_indexes(
    session: Any,
) -> WeakKeyDictionary[Any, dict[tuple[tuple[str, str | None], ...], MainClassAncestry]]:
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
    availability = omop_availability(vocabulary_session, require_relationships=True)
    if not availability.available:
        return MainClassAncestry(
            MappingProxyType({}), availability.reason or "OMOP vocabulary is unavailable"
        )
    engine, schema_map = cache_context(vocabulary_session)
    indexes = _ancestry_indexes(session)
    engine_indexes = indexes.setdefault(engine, {})
    if schema_map in engine_indexes:
        return engine_indexes[schema_map]

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
    engine_indexes[schema_map] = index
    return index


__all__ = ["main_class_ancestry"]
