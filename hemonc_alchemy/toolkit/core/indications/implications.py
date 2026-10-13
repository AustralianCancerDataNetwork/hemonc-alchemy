"""Close biomarker findings over structural and curated implications."""

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

import yaml  # type: ignore[import-untyped]

from .loader import BiomarkerSource, IndicationSource
from .model import Finding, Kind, Presence
from .normalisers.biomarker import BiomarkerNormaliser


@dataclass(frozen=True)
class FindingImplication:
    biomarker: str
    finding: str
    satisfies: tuple[str, ...]


@dataclass(frozen=True)
class ImplicationData:
    implications: tuple[FindingImplication, ...]
    no_implication: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ImplicationLint:
    failures: tuple[str, ...]


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


_ENTRY_KEYS = {"biomarker", "finding", "satisfies"}


def _mapping(value: object, label: str, keys: set[str]) -> Mapping:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    if set(value) != keys:
        raise ValueError(f"{label} must contain exactly {', '.join(sorted(keys))}")
    return value


def _parse_entry(raw: object, index: int) -> FindingImplication:
    label = f"implications[{index}]"
    raw = _mapping(raw, label, _ENTRY_KEYS)
    biomarker = _required_text(raw["biomarker"], f"{label}.biomarker")
    finding = _required_text(raw["finding"], f"{label}.finding")
    satisfies = raw["satisfies"]
    if not isinstance(satisfies, list):
        raise TypeError(f"{label}.satisfies must be a list")
    if any(not isinstance(item, str) or not item.strip() for item in satisfies):
        raise ValueError(f"{label}.satisfies must contain non-empty strings")
    satisfies = tuple(item.strip() for item in satisfies)
    if len({item.casefold() for item in satisfies}) != len(satisfies):
        raise ValueError(f"{label}.satisfies contains duplicate findings")
    return FindingImplication(biomarker, finding, satisfies)


def _parse_no_implication(raw: object, index: int) -> tuple[str, str]:
    label = f"no_implication[{index}]"
    raw = _mapping(raw, label, {"biomarker", "finding"})
    return (
        _required_text(raw["biomarker"], f"{label}.biomarker"),
        _required_text(raw["finding"], f"{label}.finding"),
    )


def _unique_pairs(
    entries: tuple[FindingImplication, ...], exclusions: tuple[tuple[str, str], ...]
) -> None:
    pairs = [
        (entry.biomarker.casefold(), entry.finding.casefold()) for entry in entries
    ] + [
        (biomarker.casefold(), finding.casefold()) for biomarker, finding in exclusions
    ]
    if len(pairs) != len(set(pairs)):
        raise ValueError("implication and no_implication pairs must be unique")


def parse_implication_data(data: object) -> ImplicationData:
    """Validate and freeze the plain YAML mapping."""
    if not isinstance(data, Mapping):
        raise TypeError("top level must be a mapping")
    if set(data) != {"implications", "no_implication"}:
        raise ValueError("top level must contain implications and no_implication")
    raw_entries, raw_exclusions = data["implications"], data["no_implication"]
    if not isinstance(raw_entries, list) or not isinstance(raw_exclusions, list):
        raise TypeError("implications and no_implication must be lists")
    entries = tuple(_parse_entry(raw, index) for index, raw in enumerate(raw_entries))
    exclusions = tuple(
        _parse_no_implication(raw, index) for index, raw in enumerate(raw_exclusions)
    )
    _unique_pairs(entries, exclusions)
    return ImplicationData(entries, exclusions)


def _read_yaml() -> object:
    path = resources.files("hemonc_alchemy.toolkit.core.indications").joinpath(
        "data", "finding_implications.yaml"
    )
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_implication_data() -> ImplicationData:
    """Read and validate packaged implications once per process."""
    return parse_implication_data(_read_yaml())


def clear_implication_cache() -> None:
    load_implication_data.cache_clear()


def _data_findings(data: ImplicationData, biomarker: str) -> tuple[str, ...]:
    marker = biomarker.casefold()
    values = {
        text.casefold(): text
        for entry in data.implications
        if entry.biomarker.casefold() == marker
        for text in (entry.finding, *entry.satisfies)
    }
    values.update(
        {
            finding.casefold(): finding
            for name, finding in data.no_implication
            if name.casefold() == marker
        }
    )
    return tuple(values[key] for key in sorted(values))


def _same_optional(left: str | None, right: str | None) -> bool:
    return (left or "").casefold() == (right or "").casefold()


def _threshold_implies(patient: Finding, target: Finding) -> bool:
    if (
        patient.value is None
        or target.value is None
        or patient.detail is None
        or target.detail is None
        or patient.unit is None
        or target.unit is None
        or not _same_optional(patient.detail, target.detail)
        or not _same_optional(patient.unit, target.unit)
    ):
        return False
    if patient.comparator == target.comparator == ">=":
        return target.value <= patient.value
    if patient.comparator == target.comparator == "<=":
        return target.value >= patient.value
    return False


def _structural_targets(
    finding: Finding,
    biomarker: str,
    data: ImplicationData,
    normaliser: BiomarkerNormaliser,
) -> tuple[Finding, ...]:
    targets = []
    if finding.presence is Presence.PRESENT and finding.kind in {
        Kind.VARIANT,
        Kind.EXON_ALTERATION,
        Kind.MUTATION_CLASS,
    }:
        targets.append(normaliser.parse_finding("mutated"))
    if finding.kind is Kind.VARIANT and finding.detail:
        detail = finding.detail
        if len(detail) > 4 and detail[-1].isalpha() and detail[-2].isdigit():
            partial = normaliser.parse_finding(detail[:-1])
            if partial.kind is Kind.VARIANT:
                targets.append(partial)
    candidates = _data_findings(data, biomarker)
    for raw in candidates:
        candidate = normaliser.parse_finding(raw)
        if _threshold_implies(finding, candidate):
            targets.append(candidate)
    return tuple(targets)


def _closure(
    biomarker: str, finding: Finding, data: ImplicationData
) -> tuple[Finding, ...]:
    normaliser = BiomarkerNormaliser()
    marker = normaliser.canonical_name(biomarker) or biomarker.strip()
    marker_key = marker.casefold()
    edges = {
        (entry.biomarker.casefold(), entry.finding.casefold()): entry.satisfies
        for entry in data.implications
    }
    found = {finding.raw.casefold()}
    queue = deque((finding,))
    result = []
    while queue:
        current = queue.popleft()
        result.append(current)
        targets = list(_structural_targets(current, marker, data, normaliser))
        targets.extend(
            normaliser.parse_finding(raw)
            for raw in edges.get((marker_key, current.raw.casefold()), ())
        )
        for target in targets:
            key = target.raw.casefold()
            if key not in found:
                found.add(key)
                queue.append(target)
    return tuple(result)


def implied_findings(biomarker: str, finding: str) -> tuple[Finding, ...]:
    """Return a deterministic, cycle-safe closure including the input finding."""
    normaliser = BiomarkerNormaliser()
    initial = normaliser.parse_finding(finding)
    if not initial.parsed:
        return (initial,)
    return _closure(biomarker, initial, load_implication_data())


def _slot_pairs(
    slot: BiomarkerSource, normaliser: BiomarkerNormaliser
) -> set[tuple[str, str]]:
    return {
        (
            (normaliser.canonical_name(biomarker) or biomarker.strip()).casefold(),
            finding.casefold(),
        )
        for biomarker in slot.biomarkers
        for finding in slot.findings
    }


def _observed_pairs(
    sources: tuple[IndicationSource, ...],
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    normaliser = BiomarkerNormaliser()
    observed = set()
    lung = set()
    for source in sources:
        pairs = set().union(
            *(_slot_pairs(slot, normaliser) for slot in source.biomarkers)
        )
        observed.update(pairs)
        if "lung" in source.condition.casefold():
            lung.update(pairs)
    return observed, lung


def _declared_pairs(data: ImplicationData) -> set[tuple[str, str]]:
    pairs = {
        (entry.biomarker.casefold(), text.casefold())
        for entry in data.implications
        for text in (entry.finding, *entry.satisfies)
    }
    pairs.update(
        (biomarker.casefold(), finding.casefold())
        for biomarker, finding in data.no_implication
    )
    return pairs


def _token_failures(
    data: ImplicationData, observed: set[tuple[str, str]]
) -> tuple[str, ...]:
    failures = []
    for entry in data.implications:
        pair = (entry.biomarker.casefold(), entry.finding.casefold())
        if pair not in observed:
            failures.append(
                f"finding token not used in indications: {entry.biomarker}: {entry.finding}"
            )
        failures.extend(
            f"satisfies token not used in indications: {entry.biomarker}: {target}"
            for target in entry.satisfies
            if (entry.biomarker.casefold(), target.casefold()) not in observed
        )
    failures.extend(
        f"no_implication token not used in indications: {biomarker}: {finding}"
        for biomarker, finding in data.no_implication
        if (biomarker.casefold(), finding.casefold()) not in observed
    )
    return tuple(failures)


def lint_finding_implications(
    sources: tuple[IndicationSource, ...], data: ImplicationData | None = None
) -> ImplicationLint:
    """Check implication tokens and lung-pair coverage against live indications."""
    try:
        data = data or load_implication_data()
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        return ImplicationLint((f"invalid finding implication data: {exc}",))
    observed, lung = _observed_pairs(sources)
    declared = _declared_pairs(data)
    failures = list(_token_failures(data, observed))
    failures.extend(
        f"unaccounted lung finding pair: {biomarker}: {finding}"
        for biomarker, finding in sorted(lung - declared)
    )
    return ImplicationLint(tuple(failures))


__all__ = [
    "FindingImplication",
    "ImplicationData",
    "ImplicationLint",
    "clear_implication_cache",
    "implied_findings",
    "lint_finding_implications",
    "load_implication_data",
    "parse_implication_data",
]
