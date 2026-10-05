"""Resolve source codes to their standard OMOP condition concepts in the session's vocabulary.

TODO: move "Maps to value" detection and the pairwise `subsumption_pairs` query into omop-alchemy's
`toolkit.core.concepts` alongside `standard_concept_mapping_select` when next feasible.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import aliased

from .binding import load_omop_binding, omop_available


@dataclass(frozen=True)
class StandardisedCode:
    """One source code's standard form: its condition leg and whether a value leg exists."""

    concept_id: int
    standard: bool
    condition_leg: frozenset[int]
    has_value_leg: bool


def standardise_codes(
    session: Any,
    codes: Iterable[str],
    *,
    vocabulary_id: str = "SNOMED",
) -> dict[str, StandardisedCode]:
    """Map valid source codes to their standard condition leg; unknown or invalid codes are omitted."""

    values = tuple(dict.fromkeys(str(code) for code in codes))
    binding = load_omop_binding()
    if not values or binding is None or not omop_available(session):
        return {}
    from omop_alchemy.toolkit.core.concepts import (  # type: ignore[import-not-found,import-untyped]  # optional extra
        StandardConceptMappingSpec,
        standard_concept_mapping_select,
    )

    concept = binding.concept
    sources = session.execute(
        sa.select(concept.concept_code, concept.concept_id, concept.standard_concept).where(
            concept.vocabulary_id == vocabulary_id,
            concept.concept_code.in_(values),
            concept.is_valid_expr(),
        )
    ).all()
    if not sources:
        return {}
    source_ids = tuple(int(row.concept_id) for row in sources)

    # Standard concepts come back as self-maps, so one query covers both cases.
    mapping = standard_concept_mapping_select(StandardConceptMappingSpec(source_concept_ids=source_ids)).subquery()
    target = aliased(concept, name="mapping_target")
    legs: dict[int, set[int]] = defaultdict(set)
    for row in session.execute(
        sa.select(mapping.c.source_concept_id, mapping.c.standard_concept_id)
        .join(target, target.concept_id == mapping.c.standard_concept_id)
        .where(target.domain_id == "Condition")
    ):
        legs[int(row.source_concept_id)].add(int(row.standard_concept_id))

    relation = binding.concept_relationship
    value_legs = {
        int(source_id)
        for source_id in session.scalars(
            sa.select(relation.concept_id_1).where(
                relation.concept_id_1.in_(source_ids),
                relation.relationship_id == "Maps to value",
                relation.is_valid_expr(),
            )
        )
    }

    return {
        str(row.concept_code): StandardisedCode(
            concept_id=int(row.concept_id),
            standard=row.standard_concept == "S",
            condition_leg=frozenset(legs[int(row.concept_id)]),
            has_value_leg=int(row.concept_id) in value_legs,
        )
        for row in sources
    }


def concept_labels(session: Any, concept_ids: Iterable[int]) -> dict[int, tuple[str, str]]:
    """Each concept's (concept_code, concept_name), for human-readable output."""

    values = tuple(dict.fromkeys(int(value) for value in concept_ids))
    binding = load_omop_binding()
    if not values or binding is None or not omop_available(session):
        return {}
    concept = binding.concept
    rows = session.execute(
        sa.select(concept.concept_id, concept.concept_code, concept.concept_name).where(concept.concept_id.in_(values))
    ).all()
    return {int(row.concept_id): (str(row.concept_code), str(row.concept_name)) for row in rows}


def subsumption_pairs(session: Any, concept_ids: Iterable[int]) -> set[tuple[int, int]]:
    """Strict (ancestor, descendant) pairs among `concept_ids`."""

    values = tuple(dict.fromkeys(int(value) for value in concept_ids))
    binding = load_omop_binding()
    if not values or binding is None or not omop_available(session):
        return set()
    ancestor = binding.concept_ancestor
    rows = session.execute(
        sa.select(ancestor.ancestor_concept_id, ancestor.descendant_concept_id).where(
            ancestor.ancestor_concept_id.in_(values),
            ancestor.descendant_concept_id.in_(values),
            ancestor.min_levels_of_separation > 0,
        )
    ).all()
    return {(int(row[0]), int(row[1])) for row in rows}


__all__ = ["StandardisedCode", "concept_labels", "standardise_codes", "subsumption_pairs"]
