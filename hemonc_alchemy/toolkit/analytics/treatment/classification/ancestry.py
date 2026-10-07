"""Drug ancestry rules and whole-main-class interpretation of live vocabulary data.

Purity is drug-only: radiation and generic component instructions without
drug records are outside its scope. Missing ancestry returns None, rather
than asserting a negative classification.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

import sqlalchemy as sa

from .....model.enums import Sigs_Class_fieldEnum
from .modality import sig_class_value

# Vocabulary-qualified concept codes remain stable across OMOP builds.
ENDOCRINE_ROOT_CUI = "44970"  # Endocrine therapeutic
SUPPORTIVE_ROOT_CUI = "20221"  # Growth factor; deliberately narrower than all supportive care
EXCLUDED_COMPONENT_CLASS_CUIS = frozenset({"45523"})  # Steroid: polyhierarchical
_ROOT_CUIS = frozenset({ENDOCRINE_ROOT_CUI, SUPPORTIVE_ROOT_CUI})
_DRUG_SIG_CLASSES = frozenset({
    Sigs_Class_fieldEnum.IV_INTERMITTENT_CANONICAL_SIG,
    Sigs_Class_fieldEnum.IV_CONTINUOUS_CANONICAL_SIG,
    Sigs_Class_fieldEnum.NON_TO_IV_CANONICAL_SIG,
})


class DrugAncestry(str, Enum):
    ENDOCRINE = "endocrine"
    SUPPORTIVE = "supportive"
    OTHER = "other"
    UNRESOLVED = "unresolved"
    INCONSISTENT = "inconsistent"


@dataclass(frozen=True)
class MainClassResolution:
    """One source main_class group, classified only when every component resolves."""

    status: DrugAncestry
    component_cuis: frozenset[int]
    unresolved_cuis: frozenset[int] = frozenset()


@dataclass(frozen=True)
class MainClassAncestry:
    """Runtime resolutions and an explicit reason when vocabulary data is unavailable."""

    resolutions: Mapping[str, MainClassResolution]
    unavailable_reason: str | None = None

    def purity(self, classes: Iterable[str | None], ancestry: DrugAncestry) -> bool | None:
        """True for pure drugs, False for a known exclusion, None for incomplete evidence."""
        classes = frozenset(classes)
        if not classes:
            return False
        if self.unavailable_reason is not None:
            return None
        statuses = set()
        for cls in classes:
            resolution = self.resolutions.get(cls) if cls else None
            statuses.add(resolution.status if resolution else DrugAncestry.UNRESOLVED)
        if statuses - {ancestry, DrugAncestry.UNRESOLVED}:
            return False
        return None if DrugAncestry.UNRESOLVED in statuses else True


def _descendants(children: Mapping[str, set[str]], root: str) -> set[str]:
    """Active Is a closure, including the root and terminating even for cyclic data."""
    seen = {root}
    pending = [root]
    while pending:
        for child in children.get(pending.pop(), ()):
            if child not in seen:
                seen.add(child)
                pending.append(child)
    return seen


def _resolve_group(cuis, targets, endocrine, supportive) -> MainClassResolution:
    missing = frozenset(cui for cui in cuis if not targets.get(str(cui)))
    if not cuis or missing:
        return MainClassResolution(DrugAncestry.UNRESOLVED, cuis, missing)
    endocrine_matches = [bool(targets[str(cui)] & endocrine) for cui in cuis]
    supportive_matches = [bool(targets[str(cui)] & supportive) for cui in cuis]
    if all(endocrine_matches):
        status = DrugAncestry.ENDOCRINE
    elif all(supportive_matches):
        status = DrugAncestry.SUPPORTIVE
    elif any(endocrine_matches) or any(supportive_matches):
        status = DrugAncestry.INCONSISTENT
    else:
        status = DrugAncestry.OTHER
    return MainClassResolution(status, cuis)


def compute_main_class_ancestry(
    groups: Mapping[str, Iterable[int]],
    relationships: Iterable[tuple[str, str, str]],
    *,
    available_roots: Iterable[str],
) -> MainClassAncestry:
    """Interpret active HemOnc Is a edges: (source code, target code, target class).

    Direct Component Class targets establish typing; the full hierarchy
    establishes root ancestry. An excluded-only target leaves a drug unresolved.
    """
    missing_roots = _ROOT_CUIS - frozenset(available_roots)
    if missing_roots:
        return MainClassAncestry(
            MappingProxyType({}),
            "Missing active HemOnc ancestry roots: " + ", ".join(sorted(missing_roots)),
        )
    children: dict[str, set[str]] = defaultdict(set)
    targets: dict[str, set[str]] = defaultdict(set)
    for source, target, target_class in relationships:
        children[target].add(source)
        if target_class == "Component Class" and target not in EXCLUDED_COMPONENT_CLASS_CUIS:
            targets[source].add(target)
    endocrine = _descendants(children, ENDOCRINE_ROOT_CUI)
    supportive = _descendants(children, SUPPORTIVE_ROOT_CUI)
    resolutions = {
        main_class: _resolve_group(frozenset(cuis), targets, endocrine, supportive)
        for main_class, cuis in groups.items()
    }
    return MainClassAncestry(MappingProxyType(resolutions))


def _drug_main_classes(drug_bearing) -> frozenset[str | None]:
    """Retain unknown classes and missing records for canonical drug instructions."""
    classes: set[str | None] = set()
    for item in drug_bearing:
        drug = item.drug_object
        if drug is not None:
            classes.add(drug.main_class)
        elif sig_class_value(getattr(item, "sig", item)) in _DRUG_SIG_CLASSES:
            classes.add(None)
    return frozenset(classes)


def _ancestry_for_items(items) -> MainClassAncestry:
    """Infer an attached source session; explicit indexes support separate databases."""
    # Keep the optional integration out of ordinary imports and avoid its
    # CycleTemplate enrichment module's import cycle.
    from .....integrations.omop.ancestry import main_class_ancestry

    for item in items:
        state = sa.inspect(getattr(item, "sig", item), raiseerr=False)
        session = getattr(state, "session", None)
        if session is not None:
            return main_class_ancestry(session)
    return MainClassAncestry(MappingProxyType({}), "No attached session or explicit ancestry index")


def _purity(items, target: DrugAncestry, ancestry: MainClassAncestry | None) -> bool | None:
    items = tuple(items)
    index = ancestry if ancestry is not None else _ancestry_for_items(items)
    return index.purity(_drug_main_classes(items), target)


def is_endocrine_regimen(variant, *, ancestry: MainClassAncestry | None = None) -> bool | None:
    """Whether every drug is endocrine; None means ancestry is unresolved."""
    return _purity(variant.component_sigs, DrugAncestry.ENDOCRINE, ancestry)


def is_supportive_regimen(variant, *, ancestry: MainClassAncestry | None = None) -> bool | None:
    """Whether every drug has Growth factor ancestry; None means unresolved."""
    return _purity(variant.component_sigs, DrugAncestry.SUPPORTIVE, ancestry)


def is_endocrine_block(events, *, ancestry: MainClassAncestry | None = None) -> bool | None:
    """Whether this block's own drugs are entirely endocrine; None means unresolved."""
    return _purity(events, DrugAncestry.ENDOCRINE, ancestry)


def is_supportive_block(events, *, ancestry: MainClassAncestry | None = None) -> bool | None:
    """Whether this block's own drugs have Growth factor ancestry; None means unresolved."""
    return _purity(events, DrugAncestry.SUPPORTIVE, ancestry)
