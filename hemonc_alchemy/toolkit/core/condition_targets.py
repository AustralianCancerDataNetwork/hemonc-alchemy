"""HemOnc condition -> standard SNOMED targets, read at runtime from HemOnc's conditions table and the OMOP vocabulary.

Two committed CSVs beside this module adjust the table until their contents are merged upstream into it:
`condition_patches.csv` holds generated corrections in the table's own shape (`map_SNOMED`/`map_type_SNOMED`;
crosswalk gap-fills and demotions, written by `hemonc-alchemy regen-condition-targets`), and
`condition_overrides.csv` holds reviewed additions/removals. Results are cached per engine.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import aliased

from ...caching import cached_per_engine
from ...integrations.omop.binding import load_omop_binding, omop_available
from ...integrations.omop.standardise import StandardisedCode, standardise_codes
from ...model import Conditions

PATCHES_PATH = Path(__file__).with_name("condition_patches.csv")
OVERRIDES_PATH = Path(__file__).with_name("condition_overrides.csv")


@dataclass(frozen=True)
class ConditionMapping:
    """One condition's HemOnc row fields used for matching; `map_snomed` may hold several codes."""

    condition_cui: int
    condition: str
    map_snomed: tuple[str, ...]
    map_type_snomed: str | None
    map_ncit: str | None
    map_type_ncit: str | None


def _value(field: Any) -> str | None:
    value = getattr(field, "value", field)
    return None if value is None or str(value).strip() == "" else str(value).strip()


def _snomed_codes(field: Any) -> tuple[str, ...]:
    """Normalize a scalar or pipe-separated mapping into individual codes."""
    value = _value(field)
    return tuple(code.strip() for code in value.split("|") if code.strip()) if value is not None else ()


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [row for row in csv.DictReader(handle) if row.get("condition_cui")]


def load_patches(path: Path = PATCHES_PATH) -> dict[int, dict[str, str]]:
    """Patched `map_SNOMED` (pipe-separated) and `map_type_SNOMED` per condition."""
    return {int(row["condition_cui"]): row for row in _read_rows(path)}


def load_overrides(path: Path = OVERRIDES_PATH) -> list[dict[str, str]]:
    """Reviewed `condition_cui,snomed_code,action,note` rows, action `add` or `remove`."""
    return _read_rows(path)


def apply_patches(mappings: Iterable[ConditionMapping], patches: Mapping[int, Mapping[str, str]]) -> dict[int, ConditionMapping]:
    """`mappings` with patched SNOMED fields replacing the table's."""
    result = {}
    for mapping in mappings:
        patch = patches.get(mapping.condition_cui)
        if patch is not None:
            mapping = replace(
                mapping,
                map_snomed=_snomed_codes(patch["map_SNOMED"]),
                map_type_snomed=_value(patch["map_type_SNOMED"]),
            )
        result[mapping.condition_cui] = mapping
    return result


def accepted_codes(
    mappings: Mapping[int, ConditionMapping], overrides: Iterable[Mapping[str, str]]
) -> dict[int, tuple[str, ...]]:
    """SNOMED codes per condition whose map type is exact, adjusted by reviewed overrides."""
    codes: dict[int, list[str]] = defaultdict(list)
    for cui, mapping in mappings.items():
        if mapping.map_type_snomed == "exact":
            codes[cui].extend(mapping.map_snomed)
    for row in overrides:
        cui, code, action = int(row["condition_cui"]), str(row["snomed_code"]), row["action"].strip()
        if action == "add" and code not in codes[cui]:
            codes[cui].append(code)
        elif action == "remove" and code in codes[cui]:
            codes[cui].remove(code)
        elif action not in ("add", "remove"):
            raise ValueError(f"override action must be add or remove, got {action!r}")
    return {cui: tuple(found) for cui, found in codes.items() if found}


def broader_codes(mappings: Mapping[int, ConditionMapping]) -> dict[int, tuple[str, ...]]:
    """SNOMED codes per condition that HemOnc marks `up` (the condition sits inside them)."""
    return {cui: m.map_snomed for cui, m in mappings.items() if m.map_type_snomed == "up" and m.map_snomed}


def is_conjunction(code: StandardisedCode) -> bool:
    """Whether a code's standard form needs several parts at once (a value leg or more than one condition)."""
    return code.has_value_leg or len(code.condition_leg) > 1


@cached_per_engine
def raw_condition_mappings(session: Any) -> dict[int, ConditionMapping]:
    """HemOnc's conditions table as loaded, before patches."""
    # Plain columns: loading `Conditions` entities would also select-in every child mapping table.
    rows = session.execute(
        sa.select(
            Conditions.condition_cui, Conditions.condition, Conditions.map_snomed,
            Conditions.map_type_snomed, Conditions.map_ncit, Conditions.map_type_ncit,
        )
    ).all()
    return {
        int(row.condition_cui): ConditionMapping(
            condition_cui=int(row.condition_cui),
            condition=str(row.condition),
            map_snomed=_snomed_codes(row.map_snomed),
            map_type_snomed=_value(row.map_type_snomed),
            map_ncit=_value(row.map_ncit),
            map_type_ncit=_value(row.map_type_ncit),
        )
        for row in rows
    }


@cached_per_engine
def condition_mappings(session: Any) -> dict[int, ConditionMapping]:
    """HemOnc's conditions table with `condition_patches.csv` applied."""
    return apply_patches(raw_condition_mappings(session).values(), load_patches())


def condition_names(session: Any) -> dict[int, str]:
    """Each condition's HemOnc name."""
    return {cui: mapping.condition for cui, mapping in condition_mappings(session).items()}


@cached_per_engine
def condition_parents(session: Any) -> dict[int, tuple[int, ...]]:
    """Each HemOnc condition's direct `Is a` parents, from the OMOP vocabulary."""
    binding = load_omop_binding()
    if binding is None or not omop_available(session):
        return {}
    child = aliased(binding.concept, name="child")
    parent = aliased(binding.concept, name="parent")
    relation = binding.concept_relationship
    rows = session.execute(
        sa.select(child.concept_code, parent.concept_code)
        .select_from(
            sa.inspect(child).selectable.join(relation, relation.concept_id_1 == child.concept_id).join(
                sa.inspect(parent).selectable, parent.concept_id == relation.concept_id_2
            )
        )
        .where(
            child.vocabulary_id == "HemOnc", child.domain_id == "Condition",
            parent.vocabulary_id == "HemOnc", parent.domain_id == "Condition",
            relation.relationship_id == "Is a",
            relation.is_valid_expr(), child.is_valid_expr(), parent.is_valid_expr(),
        )
    ).all()
    parents: dict[int, set[int]] = defaultdict(set)
    for child_code, parent_code in rows:
        if str(child_code).isdigit() and str(parent_code).isdigit() and child_code != parent_code:
            parents[int(child_code)].add(int(parent_code))
    return {cui: tuple(sorted(found)) for cui, found in parents.items()}


def accepted_snomed_codes(session: Any, condition_cuis: Iterable[int] | None = None) -> dict[int, tuple[str, ...]]:
    """Accepted SNOMED codes per condition (patched exact maps plus overrides), optionally restricted."""
    codes = accepted_codes(condition_mappings(session), load_overrides())
    if condition_cuis is None:
        return codes
    wanted = {int(cui) for cui in condition_cuis}
    return {cui: found for cui, found in codes.items() if cui in wanted}


@cached_per_engine
def resolve_condition_targets(session: Any) -> dict[int, frozenset[int]]:
    """Accepted single-concept targets as standard condition concept ids; conjunction codes are left out."""
    codes = accepted_snomed_codes(session)
    standard = standardise_codes(session, {code for found in codes.values() for code in found})
    usable = {code: found for code, found in standard.items() if not is_conjunction(found)}
    return {
        cui: frozenset(cid for code in found if code in usable for cid in usable[code].condition_leg)
        for cui, found in codes.items()
    }


__all__ = [
    "OVERRIDES_PATH",
    "PATCHES_PATH",
    "ConditionMapping",
    "accepted_codes",
    "accepted_snomed_codes",
    "apply_patches",
    "broader_codes",
    "condition_mappings",
    "condition_names",
    "condition_parents",
    "is_conjunction",
    "load_overrides",
    "load_patches",
    "raw_condition_mappings",
    "resolve_condition_targets",
]
