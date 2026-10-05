"""HemOnc condition families: clinically coherent slices of the condition hierarchy, and associated variants.

A family is a child of one of HemOnc's top-level categories (e.g. Gastrointestinal cancer, Lymphoma,
Hemoglobinopathy). A condition belongs to the families among its ancestors-or-self; a category or a node
above one stands for every family beneath it; a condition outside every category belongs to its topmost
non-category ancestor-or-self, so e.g. Atrial fibrillation is its own family.

A family's OMOP coverage is an omop-alchemy concept group anchored on its members' accepted targets, so a
patient's families come from their condition concepts in O(1) once a vocabulary's groups are built. The
hierarchy is read from the OMOP vocabulary's HemOnc `Is a` edges.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from weakref import WeakKeyDictionary

from sqlalchemy import select

from ...caching import cached_per_engine
from ...integrations.omop.standardise import standardise_codes
from ...model import Studies, Variants, variants_StudyMap
from .catalogue.variants import latest_variant_ids
from .condition_targets import (
    broader_codes,
    condition_mappings,
    condition_parents,
    resolve_condition_targets,
)

ROOT_CUI = 30789  # Condition
# Malignant solid neoplasm, Malignant hematologic neoplasm, Pediatric cancer,
# Cross-disciplinary condition, Classical hematologic condition.
CATEGORY_CUIS = frozenset({44382, 46212, 46085, 46218, 46208})
# Solid and haematologic malignancy are disjoint: a fallback target in one excludes the other's coverage.
DISJOINT_CATEGORIES = {44382: 46212, 46212: 44382}


def _closure(edges: Mapping[int, Any], start: int) -> set[int]:
    seen: set[int] = set()
    stack = list(edges.get(start, ()))
    while stack:
        node = stack.pop()
        if node not in seen:
            seen.add(node)
            stack.extend(edges.get(node, ()))
    return seen


def compute_condition_families(
    condition_cuis: Iterable[int], parents: Mapping[int, tuple[int, ...]]
) -> dict[int, frozenset[int]]:
    """Each condition's families, from the condition set and its `Is a` parents."""
    children: dict[int, set[int]] = defaultdict(set)
    for child, found in parents.items():
        for parent in found:
            children[parent].add(child)
    in_categories = {cui for cui, found in parents.items() if CATEGORY_CUIS & set(found)}
    # The root, the categories and anything above a category are never families themselves.
    structural = {ROOT_CUI} | CATEGORY_CUIS | {a for category in CATEGORY_CUIS for a in _closure(parents, category)}

    result: dict[int, frozenset[int]] = {}
    for cui in condition_cuis:
        lineage = {cui} | _closure(parents, cui)
        families = lineage & in_categories
        if not families and cui in structural:
            families = _closure(children, cui) & in_categories
        elif not families:
            # Outside every category: its topmost non-structural ancestor(s)-or-self.
            families = {node for node in lineage - structural if set(parents.get(node, ())) <= structural}
        result[cui] = frozenset(families)
    return result


def compute_family_members(
    families: Mapping[int, frozenset[int]], parents: Mapping[int, tuple[int, ...]]
) -> dict[int, frozenset[int]]:
    """Each family's member conditions: the family and the conditions beneath it, never a structural node above it."""
    all_families = {family for found in families.values() for family in found}
    members: dict[int, set[int]] = defaultdict(set)
    for cui in families:
        for family in ({cui} | _closure(parents, cui)) & all_families:
            members[family].add(cui)
    return {family: frozenset(found) for family, found in members.items()}


@cached_per_engine
def condition_families(session: Any) -> dict[int, frozenset[int]]:
    """Each HemOnc condition's families."""
    return compute_condition_families(condition_mappings(session), condition_parents(session))


def family_cuis(session: Any) -> frozenset[int]:
    """Every family that some condition belongs to."""
    return frozenset(family for found in condition_families(session).values() for family in found)


def family_categories(session: Any) -> dict[int, frozenset[int]]:
    """Each family's top-level categories; empty for a family outside every category."""
    parents = condition_parents(session)
    return {family: frozenset(set(parents.get(family, ())) & CATEGORY_CUIS) for family in family_cuis(session)}


@cached_per_engine
def family_members(session: Any) -> dict[int, frozenset[int]]:
    """Each family's member conditions."""
    return compute_family_members(condition_families(session), condition_parents(session))


def variant_conditions(session: Any) -> dict[int, frozenset[int]]:
    """Latest variants' conditions, via their studies; variants with no study condition are omitted."""
    ranked = latest_variant_ids()
    rows = session.execute(
        select(Variants.variant_cui, Studies.condition_cui)
        .join(ranked, ranked.c.variant_id == Variants.id)
        .join(variants_StudyMap, variants_StudyMap.parent_id == Variants.id)
        .join(Studies, Studies.study == variants_StudyMap.study)
        .where(ranked.c.version_rank == 1)
        .distinct()
    ).all()
    result: dict[int, set[int]] = defaultdict(set)
    for variant_cui, condition_cui in rows:
        if condition_cui is not None:
            result[int(variant_cui)].add(int(condition_cui))
    return {cui: frozenset(found) for cui, found in result.items()}


def variant_families(session: Any) -> dict[int, frozenset[int]]:
    """Latest variants' families, via their studies' conditions; variants with no known condition are omitted."""
    families = condition_families(session)
    result = {
        cui: frozenset(f for condition in conditions for f in families.get(condition, ()))
        for cui, conditions in variant_conditions(session).items()
    }
    return {cui: found for cui, found in result.items() if found}


@dataclass(frozen=True)
class FamilyAnchors:
    """A family's concept-group anchors; satisfies omop-alchemy's `ConceptGroupAnchors`."""

    parent_ids: frozenset[int]
    excluded_parent_ids: frozenset[int] = frozenset()
    exact_ids: frozenset[int] = frozenset()


@cached_per_engine
def family_anchors(session: Any) -> dict[int, FamilyAnchors]:
    """Each family's anchors in `session`'s vocabulary; families with nothing usable are omitted (fail closed).

    In order: the accepted single-concept targets of the family's members; else, for a solid or haematologic
    family, HemOnc's own `up` target minus the disjoint category's coverage; else nothing.
    """
    targets = resolve_condition_targets(session)
    parents = condition_parents(session)
    accepted = {
        family: frozenset(cid for member in members for cid in targets.get(member, ()))
        for family, members in family_members(session).items()
    }
    anchors = {family: FamilyAnchors(ids) for family, ids in accepted.items() if ids}

    def category_coverage(category: int) -> frozenset[int]:
        return frozenset(cid for family in anchors if category in parents.get(family, ()) for cid in anchors[family].parent_ids)

    up = broader_codes(condition_mappings(session))
    missing = [family for family in family_cuis(session) if family not in anchors and family in up]
    standard = standardise_codes(session, {code for family in missing for code in up[family]})
    for family in missing:
        categories = set(parents.get(family, ())) & set(DISJOINT_CATEGORIES)
        legs = frozenset(cid for code in up[family] if code in standard for cid in standard[code].condition_leg)
        if not categories or not legs:
            continue
        excluded = frozenset(cid for category in categories for cid in category_coverage(DISJOINT_CATEGORIES[category]))
        anchors[family] = FamilyAnchors(legs, excluded)
    return anchors


def family_concept_groups(session: Any) -> dict[int, Any]:
    """Each covered family's omop-alchemy `ResolvedConceptGroup`, built once per vocabulary and cached there."""
    from omop_alchemy.toolkit.core.concepts import (  # type: ignore[import-not-found,import-untyped]  # optional extra
        ConceptGroupSpec,
        resolve_concept_group,
    )

    return {
        family: resolve_concept_group(session, ConceptGroupSpec(name=f"hemonc_family:{family}", unit=found))
        for family, found in family_anchors(session).items()
    }


_INDEX_BY_IDENTITY: dict[str, dict[int, frozenset[int]]] = {}
_INDEX_BY_ENGINE: WeakKeyDictionary[Any, dict[int, frozenset[int]]] = WeakKeyDictionary()


def _family_index(session: Any) -> dict[int, frozenset[int]]:
    """concept_id -> families, cached on the same vocabulary scope as omop-alchemy's concept groups."""
    from omop_alchemy.toolkit.core.concepts.identity import (  # type: ignore[import-not-found,import-untyped]
        cache_scope,
    )

    scope = cache_scope(session)
    store: Any = _INDEX_BY_IDENTITY if isinstance(scope, str) else _INDEX_BY_ENGINE
    if scope not in store:
        index: dict[int, set[int]] = defaultdict(set)
        for family, group in family_concept_groups(session).items():
            for concept_id in group.ids:
                index[concept_id].add(family)
        store[scope] = {concept_id: frozenset(found) for concept_id, found in index.items()}
    return store[scope]


def families_for_concepts(session: Any, concept_ids: Iterable[int | None]) -> frozenset[int]:
    """The families covering any of `concept_ids` (e.g. a patient's `condition_concept_id`s)."""
    index = _family_index(session)
    return frozenset(family for concept_id in concept_ids if concept_id is not None for family in index.get(concept_id, ()))


__all__ = [
    "CATEGORY_CUIS",
    "DISJOINT_CATEGORIES",
    "ROOT_CUI",
    "FamilyAnchors",
    "compute_condition_families",
    "compute_family_members",
    "condition_families",
    "families_for_concepts",
    "family_anchors",
    "family_categories",
    "family_concept_groups",
    "family_cuis",
    "family_members",
    "variant_conditions",
    "variant_families",
]
