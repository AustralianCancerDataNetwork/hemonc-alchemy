"""Propose corrections to HemOnc's condition -> SNOMED mappings, as a patch file in the conditions table's own shape.

Inputs are HemOnc's conditions table and the OMOP vocabulary (the same ones the runtime reads), plus an NCIt -> UMLS ->
SNOMEDCT_US crosswalk fetched separately (`scripts/fetch_ncit_snomed_crosswalk.py`). Machine corrections (crosswalk
gap-fills, demotions of exact maps no narrower than a parent's) go to `condition_patches.csv` for merging upstream;
anything needing a human decision goes to a suggestions sheet with a ready-to-paste override line.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from ..integrations.omop.diagnostics import vocabulary_versions
from ..integrations.omop.mapping import resolve_hemonc_concepts
from ..integrations.omop.standardise import (
    StandardisedCode,
    concept_labels,
    standardise_codes,
    subsumption_pairs,
)
from ..toolkit.core.condition_targets import (
    PATCHES_PATH,
    ConditionMapping,
    condition_parents,
    is_conjunction,
    load_overrides,
    raw_condition_mappings,
)

CROSSWALK_FILENAME = "ncit_snomed_crosswalk.json"
PROPOSALS_FILENAME = "condition_target_proposals.csv"

HEMONC_SNOMED = "hemonc_snomed"
NCIT_UMLS = "ncit_umls"
OVERRIDE = "override"
ACCEPTED = frozenset({"exact", "override"})


@dataclass(frozen=True)
class Candidate:
    """One proposed SNOMED target for one HemOnc condition."""

    condition_cui: int
    snomed_code: str
    source: str
    map_type: str | None
    status: str = ""
    note: str = ""


@dataclass(frozen=True)
class ConditionTargetResult:
    """One run's classified candidates, patch rows, suggested changes and coverage flags."""

    targets: tuple[Candidate, ...]
    patches: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    suggestions: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    coverage_flags: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    vocabulary_version: str | None = None


class Vocabulary(Protocol):
    def standardise(self, codes: Iterable[str]) -> Mapping[str, StandardisedCode]: ...

    def subsumes(self, concept_ids: Iterable[int]) -> set[tuple[int, int]]: ...

    def labels(self, concept_ids: Iterable[int]) -> Mapping[int, tuple[str, str]]: ...

    def hemonc_concept_ids(self, condition_cuis: Iterable[int]) -> Mapping[int, int]: ...


@dataclass(frozen=True)
class SessionVocabulary:
    """`Vocabulary` backed by an OMOP vocabulary session."""

    session: Any

    def standardise(self, codes: Iterable[str]) -> Mapping[str, StandardisedCode]:
        return standardise_codes(self.session, codes)

    def subsumes(self, concept_ids: Iterable[int]) -> set[tuple[int, int]]:
        return subsumption_pairs(self.session, concept_ids)

    def labels(self, concept_ids: Iterable[int]) -> Mapping[int, tuple[str, str]]:
        return concept_labels(self.session, concept_ids)

    def hemonc_concept_ids(self, condition_cuis: Iterable[int]) -> Mapping[int, int]:
        found = resolve_hemonc_concepts(self.session, list(condition_cuis), domain="Condition")
        return {int(c.hemonc_cui): c.concept.concept_id for c in found}


def load_crosswalk(path: Path) -> dict[str, tuple[str, ...]]:
    """NCIt code -> active SNOMED codes."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {ncit: tuple(entry["code"] for entry in entries) for ncit, entries in payload["crosswalk"].items()}


def load_proposals(path: Path) -> list[dict[str, str]]:
    """Search proposals (`condition_cui,snomed_code,judgement,...`); rows judged `reject...` are dropped later."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [row for row in csv.DictReader(handle) if row.get("condition_cui")]


def _closure(edges: Mapping[int, Iterable[int]], start: int) -> set[int]:
    seen: set[int] = set()
    stack = list(edges.get(start, ()))
    while stack:
        node = stack.pop()
        if node not in seen:
            seen.add(node)
            stack.extend(edges.get(node, ()))
    return seen


def _related(left: frozenset[int], right: frozenset[int], pairs: set[tuple[int, int]]) -> bool:
    return bool(left & right) or any((a, b) in pairs or (b, a) in pairs for a in left for b in right)


def _covers(broad: frozenset[int], narrow: frozenset[int], pairs: set[tuple[int, int]]) -> bool:
    """Whether some concept in `broad` equals or subsumes some concept in `narrow`."""
    return bool(broad & narrow) or any((a, b) in pairs for a in broad for b in narrow)


def _initial_candidates(mappings: Mapping[int, ConditionMapping], crosswalk: Mapping[str, tuple[str, ...]]) -> list[Candidate]:
    candidates = []
    for cui, mapping in mappings.items():
        for code in mapping.map_snomed:
            candidates.append(Candidate(cui, code, HEMONC_SNOMED, mapping.map_type_snomed))
        for code in crosswalk.get(mapping.map_ncit or "", ()):
            # Same code from both sources: HemOnc's own SNOMED judgement is kept.
            if code not in mapping.map_snomed:
                candidates.append(Candidate(cui, code, NCIT_UMLS, mapping.map_type_ncit))
    return candidates


def generate(
    mappings: Mapping[int, ConditionMapping],
    parents: Mapping[int, tuple[int, ...]],
    crosswalk: Mapping[str, tuple[str, ...]],
    vocabulary: Vocabulary,
    overrides: Iterable[Mapping[str, str]] = (),
    proposals: Iterable[Mapping[str, str]] = (),
) -> ConditionTargetResult:
    """Classify every candidate target and derive patches and suggestions; pure apart from `vocabulary` lookups."""
    names = {cui: mapping.condition for cui, mapping in mappings.items()}
    parents = {cui: tuple(p for p in found if p in names) for cui, found in parents.items() if cui in names}
    children: dict[int, set[int]] = defaultdict(set)
    for child, found in parents.items():
        for parent in found:
            children[parent].add(child)
    ancestors = {cui: _closure(parents, cui) for cui in names}
    descendants = {cui: _closure(children, cui) for cui in names}
    roots = [cui for cui in names if not parents.get(cui)]
    grouping = {max(roots, key=lambda cui: len(descendants[cui]))} if roots else set()
    proposals = [p for p in proposals if not str(p.get("judgement", "")).startswith("reject")]

    candidates = _initial_candidates(mappings, crosswalk)
    standard = vocabulary.standardise({c.snomed_code for c in candidates} | {str(p["snomed_code"]) for p in proposals})
    leg = {code: found.condition_leg for code, found in standard.items()}

    def initial_status(candidate: Candidate) -> Candidate:
        if candidate.condition_cui in grouping:
            return replace(candidate, status="grouping")
        if candidate.snomed_code not in standard:
            return replace(candidate, status="unresolved")
        if not leg[candidate.snomed_code]:
            return replace(candidate, status="not_condition")
        if candidate.map_type != "exact":
            return replace(candidate, status=candidate.map_type or "untyped")
        note = "conjunction" if is_conjunction(standard[candidate.snomed_code]) else ""
        return replace(candidate, status="exact", note=note)

    candidates = [initial_status(c) for c in candidates]
    pairs = vocabulary.subsumes({cid for c in candidates if c.status == "exact" for cid in leg[c.snomed_code]})
    by_cui: dict[int, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        by_cui[candidate.condition_cui].append(candidate)

    accepted_legs: dict[int, list[frozenset[int]]] = defaultdict(list)

    def not_narrower(candidate: Candidate) -> Candidate | None:
        if candidate.note == "conjunction":
            return None
        own = leg[candidate.snomed_code]
        for ancestor in sorted(ancestors[candidate.condition_cui] - grouping):
            if any(_covers(own, found, pairs) for found in accepted_legs[ancestor]):
                return replace(candidate, status="demoted", note=f"not_narrower_than:{names[ancestor]}")
        return None

    depth = {cui: len(ancestors[cui]) for cui in names}
    for cui in sorted(names, key=lambda cui: (depth[cui], cui)):
        rows = by_cui[cui]
        hemonc = [c for c in rows if c.source == HEMONC_SNOMED and c.status == "exact"]
        crosswalked = [c for c in rows if c.source == NCIT_UMLS and c.status == "exact"]
        decided: dict[int, Candidate] = {}
        for c in hemonc:
            decided[id(c)] = not_narrower(c) or c
        kept = [c for c in hemonc if decided[id(c)].status == "exact"]
        for c in crosswalked:
            own = leg[c.snomed_code]
            if kept:
                # The crosswalk only fills gaps; next to an accepted HemOnc target it is evidence.
                related = any(_related(own, leg[k.snomed_code], pairs) for k in kept)
                decided[id(c)] = replace(c, status="supporting" if related else "review",
                                         note="" if related else "conflicts_with_hemonc_snomed")
            elif any(o is not c and not _related(own, leg[o.snomed_code], pairs) for o in crosswalked):
                decided[id(c)] = replace(c, status="review", note="composite_crosswalk")
            else:
                decided[id(c)] = not_narrower(c) or c
        by_cui[cui] = [decided.get(id(c), c) for c in rows]
        # A conjunction's parts are broader than the condition, so they never constrain its descendants.
        accepted_legs[cui] = [
            leg[c.snomed_code] for c in by_cui[cui] if c.status == "exact" and c.note != "conjunction"
        ]

    candidates = [c for cui in names for c in by_cui[cui]]
    patches = _patches(candidates, mappings)
    candidates = _apply_overrides(candidates, overrides, names)
    suggestions = _suggestions(candidates, proposals, mappings, standard, vocabulary)
    flags = _coverage_flags(candidates, names, grouping, descendants, leg, pairs)
    targets = tuple(sorted(candidates, key=lambda c: (c.condition_cui, c.source, c.snomed_code)))
    return ConditionTargetResult(targets, tuple(patches), tuple(suggestions), tuple(flags))


PATCH_COLUMNS = ["condition_cui", "condition", "map_SNOMED", "map_type_SNOMED",
                 "original_map_SNOMED", "original_map_type_SNOMED", "reason"]


def _patches(candidates: list[Candidate], mappings: Mapping[int, ConditionMapping]) -> list[dict[str, Any]]:
    """Machine corrections in the conditions table's shape: crosswalk gap-fills, else demotions to `up`."""
    by_cui: dict[int, list[Candidate]] = defaultdict(list)
    for c in candidates:
        by_cui[c.condition_cui].append(c)
    rows = []
    for cui, found in sorted(by_cui.items()):
        mapping = mappings[cui]
        original = {"original_map_SNOMED": "|".join(mapping.map_snomed), "original_map_type_SNOMED": mapping.map_type_snomed or ""}
        filled = sorted(c.snomed_code for c in found if c.source == NCIT_UMLS and c.status == "exact")
        demoted = [c for c in found if c.source == HEMONC_SNOMED and c.status == "demoted"]
        if filled:
            reason = f"crosswalk gap-fill from NCIt {mapping.map_ncit} ({mapping.map_type_ncit})"
            if demoted:
                reason += f"; HemOnc's map demoted ({demoted[0].note})"
            rows.append({"condition_cui": cui, "condition": mapping.condition, "map_SNOMED": "|".join(filled),
                         "map_type_SNOMED": "exact", **original, "reason": reason})
        elif demoted:
            rows.append({"condition_cui": cui, "condition": mapping.condition, "map_SNOMED": "|".join(mapping.map_snomed),
                         "map_type_SNOMED": "up", **original, "reason": f"demoted: {demoted[0].note}"})
    return rows


def _apply_overrides(
    candidates: list[Candidate], overrides: Iterable[Mapping[str, str]], names: Mapping[int, str]
) -> list[Candidate]:
    result = list(candidates)
    for row in overrides:
        cui, code, action = int(row["condition_cui"]), str(row["snomed_code"]), row["action"].strip()
        if cui not in names:
            raise ValueError(f"override for unknown condition_cui {cui}")
        if action == "add":
            result.append(Candidate(cui, code, OVERRIDE, "exact", "override", row.get("note", "")))
        elif action == "remove":
            result = [
                replace(c, status="removed", note=row.get("note", ""))
                if c.condition_cui == cui and c.snomed_code == code else c
                for c in result
            ]
        else:
            raise ValueError(f"override action must be add or remove, got {action!r}")
    return result


SUGGESTION_COLUMNS = [
    "action", "reason", "override_line",
    "condition_cui", "condition", "hemonc_concept_id",
    "map_NCIT", "map_type_NCIT", "map_SNOMED", "map_type_SNOMED",
    "hemonc_snomed_concept_id", "hemonc_snomed_name", "hemonc_snomed_standard",
    "target_snomed_code", "target_source", "target_concept_id", "target_name", "target_standard",
]


def _suggestions(
    candidates: list[Candidate],
    proposals: Iterable[Mapping[str, str]],
    mappings: Mapping[int, ConditionMapping],
    standard: Mapping[str, StandardisedCode],
    vocabulary: Vocabulary,
) -> list[dict[str, Any]]:
    """Changes needing a human decision: conflicting or composite crosswalk targets, and search proposals."""
    decided = {(c.condition_cui, c.snomed_code) for c in candidates if c.status in ACCEPTED | {"removed"}}
    changes: list[tuple[str, str, Candidate]] = []
    for c in candidates:
        if c.status == "review":
            changes.append((c.note, "crosswalk target reviewed", c))
    for p in proposals:
        cui, code = int(p["condition_cui"]), str(p["snomed_code"])
        if (cui, code) not in decided and code in standard and standard[code].condition_leg:
            reason = f"search proposal ({p.get('match_tier', '')}): {p.get('judgement', '')}"
            changes.append((reason, "search proposal reviewed", Candidate(cui, code, "search", "exact")))
    if not changes:
        return []

    codes = {code for *_, c in changes for code in mappings[c.condition_cui].map_snomed} | {c.snomed_code for *_, c in changes}
    involved = [standard[code] for code in codes if code in standard]
    labels = vocabulary.labels({s.concept_id for s in involved} | {cid for s in involved for cid in s.condition_leg})
    hemonc_ids = vocabulary.hemonc_concept_ids({c.condition_cui for *_, c in changes})

    def described(code: str | None) -> tuple[Any, str, str]:
        found = standard.get(code or "")
        if found is None:
            return "", "", "not in vocabulary" if code else ""
        parts = "; ".join(f"{cid} {labels.get(cid, ('', ''))[1]}" for cid in sorted(found.condition_leg)) or "no condition concept"
        return found.concept_id, labels.get(found.concept_id, ("", ""))[1], parts + (" (+ value)" if found.has_value_leg else "")

    rows = []
    for reason, note, c in changes:
        mapping = mappings[c.condition_cui]
        hemonc_code = mapping.map_snomed[0] if mapping.map_snomed else None
        hemonc_id, hemonc_name, hemonc_std = described(hemonc_code)
        target_id, target_name, target_std = described(c.snomed_code)
        rows.append({
            "action": "add", "reason": reason, "override_line": f"{c.condition_cui},{c.snomed_code},add,{note}",
            "condition_cui": c.condition_cui, "condition": mapping.condition,
            "hemonc_concept_id": hemonc_ids.get(c.condition_cui, ""),
            "map_NCIT": mapping.map_ncit or "", "map_type_NCIT": mapping.map_type_ncit or "",
            "map_SNOMED": "|".join(mapping.map_snomed), "map_type_SNOMED": mapping.map_type_snomed or "",
            "hemonc_snomed_concept_id": hemonc_id, "hemonc_snomed_name": hemonc_name, "hemonc_snomed_standard": hemonc_std,
            "target_snomed_code": c.snomed_code, "target_source": c.source,
            "target_concept_id": target_id, "target_name": target_name, "target_standard": target_std,
        })
    return sorted(rows, key=lambda r: (str(r["condition"]), str(r["target_snomed_code"])))


def _coverage_flags(
    candidates: list[Candidate],
    names: Mapping[int, str],
    grouping: set[int],
    descendants: Mapping[int, set[int]],
    leg: Mapping[str, frozenset[int]],
    pairs: set[tuple[int, int]],
) -> list[dict[str, Any]]:
    """Accepted single-concept targets that also cover conditions outside the condition's HemOnc subtree."""
    accepted = [c for c in candidates if c.status in ACCEPTED and c.snomed_code in leg]
    rows = []
    for c in accepted:
        if c.condition_cui in grouping or c.note == "conjunction":
            continue
        outside = sorted({
            names[o.condition_cui] for o in accepted
            if o.condition_cui != c.condition_cui and o.condition_cui not in descendants[c.condition_cui]
            and leg[o.snomed_code] != leg[c.snomed_code]
            and any((a, b) in pairs for a in leg[c.snomed_code] for b in leg[o.snomed_code])
        })
        if outside:
            rows.append({"condition_cui": c.condition_cui, "condition": names[c.condition_cui], "snomed_code": c.snomed_code,
                         "source": c.source, "covers_count": len(outside), "covers": "; ".join(outside)})
    return rows


def _write_csv(path: Path, columns: list[str], rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def regenerate(
    data_dir: Path,
    session: Any,
    suggestions_path: Path,
    *,
    patches_path: Path = PATCHES_PATH,
    crosswalk_path: Path | None = None,
    proposals_path: Path | None = None,
    coverage_flags_path: Path | None = None,
) -> ConditionTargetResult:
    """Run `generate` against `session`'s tables and vocabulary; write the patch file, suggestions and optional flags."""
    result = generate(
        raw_condition_mappings(session),
        condition_parents(session),
        load_crosswalk(crosswalk_path or data_dir / CROSSWALK_FILENAME),
        SessionVocabulary(session),
        load_overrides(),
        load_proposals(proposals_path or data_dir / PROPOSALS_FILENAME),
    )
    versions = {v.vocabulary_id: v.vocabulary_version for v in vocabulary_versions(session, ["SNOMED"])}
    result = replace(result, vocabulary_version=versions.get("SNOMED"))
    _write_csv(patches_path, PATCH_COLUMNS, result.patches)
    _write_csv(suggestions_path, SUGGESTION_COLUMNS, result.suggestions)
    if coverage_flags_path is not None:
        _write_csv(coverage_flags_path, ["condition_cui", "condition", "snomed_code", "source", "covers_count", "covers"],
                   result.coverage_flags)
    return result
