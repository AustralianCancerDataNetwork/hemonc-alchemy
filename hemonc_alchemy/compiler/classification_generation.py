"""Regenerate `toolkit/analytics/treatment/classification/generated.py` from `omop.RData`'s OMOP staging tables, no database or `omop_alchemy` import needed.

Concept identity here is `(concept_code, vocabulary_id)`, not `concept_id` --
`concept_stage`/`concept_relationship_stage` are pre-build staging tables
where `concept_id`/`concept_id_1`/`concept_id_2` are always blank.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pyreadr  # type: ignore[import-untyped]  # no stubs/py.typed marker upstream

from ..naming import resolve_source_csv

OMOP_STAGING_FILENAME = "omop.RData"

# "Endocrine therapeutic" root. concept_code "44970" (concept_id 35807205 once a vocabulary build runs).
ENDOCRINE_ROOT_CONCEPT_CODE = "44970"
ENDOCRINE_ROOT_CONCEPT_ID = 35807205
ENDOCRINE_ROOT_CONCEPT_NAME = "Endocrine therapeutic"

# "Growth factor" root. concept_code "20221" (concept_id 905615 once built).
SUPPORTIVE_ROOT_CONCEPT_CODE = "20221"
SUPPORTIVE_ROOT_CONCEPT_ID = 905615
SUPPORTIVE_ROOT_CONCEPT_NAME = "Growth factor"

# "Steroid" -- genuinely polyhierarchical, excluded rather than forced into either root.
EXCLUDED_TARGET_CONCEPT_CODES = frozenset({"45523"})


@dataclass(frozen=True)
class ClassificationGenerationResult:
    """One run's resolved `main_class` sets, plus what didn't resolve cleanly."""

    endocrine_main_classes: frozenset[str]
    supportive_main_classes: frozenset[str]
    # No component resolves to either root.
    unresolved_main_classes: tuple[str, ...] = field(default_factory=tuple)
    # Components disagree on root -- excluded rather than majority-guessed.
    inconsistent_main_classes: tuple[str, ...] = field(default_factory=tuple)


def _normalised_flag(value: object) -> str | None:
    """Python counterpart to OMOP Alchemy's ``is_valid_expr``: blank -> unset."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def _valid_hemonc_isa_edges(concept: pd.DataFrame, relationship: pd.DataFrame) -> pd.DataFrame:
    """Every active `Is a` edge between two active HemOnc concepts."""
    concept = concept.copy()
    concept["_invalid"] = concept["invalid_reason"].apply(_normalised_flag)
    by_code = concept.set_index(["vocabulary_id", "concept_code"])
    if not by_code.index.is_unique:
        raise ValueError("concept_stage has duplicate (vocabulary_id, concept_code) pairs")

    relationship = relationship.copy()
    relationship["_invalid"] = relationship["invalid_reason"].apply(_normalised_flag)
    isa = relationship[
        (relationship["relationship_id"] == "Is a") & relationship["_invalid"].isna()
    ].copy()

    source = by_code.reindex(list(zip(isa["vocabulary_id_1"], isa["concept_code_1"], strict=True)))
    target = by_code.reindex(list(zip(isa["vocabulary_id_2"], isa["concept_code_2"], strict=True)))
    isa["source_concept_class_id"] = source["concept_class_id"].to_numpy()
    isa["source_found"] = source["concept_class_id"].notna().to_numpy()
    isa["source_invalid"] = source["_invalid"].to_numpy()
    isa["target_concept_class_id"] = target["concept_class_id"].to_numpy()
    isa["target_found"] = target["concept_class_id"].notna().to_numpy()
    isa["target_invalid"] = target["_invalid"].to_numpy()

    return isa[
        (isa["vocabulary_id_1"] == "HemOnc")
        & (isa["vocabulary_id_2"] == "HemOnc")
        & isa["source_found"]
        & isa["target_found"]
        & isa["source_invalid"].isna()
        & isa["target_invalid"].isna()
    ]


def _ancestor_membership(
    isa_edges: pd.DataFrame, target_codes: set[str], root_code: str
) -> set[str]:
    """Of `target_codes`, those that are `root_code` itself or its "Is a" descendant."""
    if not target_codes:
        return set()

    parent_to_children: dict[str, set[str]] = defaultdict(set)
    for parent_code, child_code in zip(
        isa_edges["concept_code_2"], isa_edges["concept_code_1"], strict=True
    ):
        parent_to_children[parent_code].add(child_code)

    seen = {root_code}
    queue: deque[str] = deque([root_code])
    while queue:
        node = queue.popleft()
        for child in parent_to_children.get(node, ()):
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return seen & target_codes


def generate(data_dir: Path) -> ClassificationGenerationResult:
    """Resolve every `Drugs.main_class` value against the local OMOP `Is a` hierarchy."""
    staging_path = data_dir / OMOP_STAGING_FILENAME
    tables = pyreadr.read_r(str(staging_path))
    isa_edges = _valid_hemonc_isa_edges(tables["concept_stage"], tables["concept_relationship_stage"])

    drugs_path, ambiguous = resolve_source_csv(data_dir, "drugs")
    if ambiguous:
        raise ValueError(f"Ambiguous CSV matches for table 'drugs': {', '.join(ambiguous)}")
    if drugs_path is None:
        raise ValueError(f"No drugs CSV found under {data_dir}")
    drugs = pd.read_csv(drugs_path)
    columns = {str(column).strip().casefold(): column for column in drugs.columns}
    main_class_col = columns["main_class"]
    drug_cui_col = columns["drug_cui"]

    cuis_by_main_class: dict[str, set[int]] = defaultdict(set)
    for main_class, drug_cui in zip(drugs[main_class_col], drugs[drug_cui_col], strict=True):
        if pd.isna(main_class) or str(main_class).strip() == "":
            continue
        cuis_by_main_class[str(main_class)].add(int(drug_cui))

    all_cuis = {cui for cuis in cuis_by_main_class.values() for cui in cuis}
    all_cuis_str = {str(cui) for cui in all_cuis}

    component_class_edges = isa_edges[
        (isa_edges["target_concept_class_id"] == "Component Class")
        & isa_edges["concept_code_1"].isin(all_cuis_str)
    ]

    targets_by_cui: dict[int, set[str]] = defaultdict(set)
    for source_code, target_code in zip(
        component_class_edges["concept_code_1"], component_class_edges["concept_code_2"], strict=True
    ):
        if target_code in EXCLUDED_TARGET_CONCEPT_CODES:
            continue
        targets_by_cui[int(source_code)].add(target_code)

    all_target_codes = {code for codes in targets_by_cui.values() for code in codes}
    endocrine_hits = _ancestor_membership(isa_edges, all_target_codes, ENDOCRINE_ROOT_CONCEPT_CODE)
    supportive_hits = _ancestor_membership(isa_edges, all_target_codes, SUPPORTIVE_ROOT_CONCEPT_CODE)

    endocrine: set[str] = set()
    supportive: set[str] = set()
    unresolved: list[str] = []
    inconsistent: list[str] = []

    for main_class, cuis in sorted(cuis_by_main_class.items()):
        # Only components with at least one "Is a" edge get a say.
        typed_cuis = [cui for cui in cuis if targets_by_cui[cui]]
        per_drug_endocrine = [bool(targets_by_cui[cui] & endocrine_hits) for cui in typed_cuis]
        per_drug_supportive = [bool(targets_by_cui[cui] & supportive_hits) for cui in typed_cuis]

        if not typed_cuis:
            unresolved.append(main_class)
        elif all(per_drug_endocrine):
            endocrine.add(main_class)
        elif all(per_drug_supportive):
            supportive.add(main_class)
        elif any(per_drug_endocrine) or any(per_drug_supportive):
            inconsistent.append(main_class)

    return ClassificationGenerationResult(
        endocrine_main_classes=frozenset(endocrine),
        supportive_main_classes=frozenset(supportive),
        unresolved_main_classes=tuple(unresolved),
        inconsistent_main_classes=tuple(inconsistent),
    )


def render_module(result: ClassificationGenerationResult) -> str:
    """Render `result` as the text of a generated, plain-Python data module."""
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d")

    def _frozenset_literal(values: frozenset[str]) -> str:
        if not values:
            return "frozenset()"
        items = ",\n        ".join(repr(v) for v in sorted(values))
        return f"frozenset(\n    {{\n        {items},\n    }}\n)"

    unresolved_comment = "\n".join(f"# - {v!r}" for v in result.unresolved_main_classes) or "# (none)"
    inconsistent_comment = (
        "\n".join(f"# - {v!r}" for v in result.inconsistent_main_classes) or "# (none)"
    )

    return f'''"""Generated by `hemonc-alchemy regen-classification` on {generated_at}. Do not hand-edit.

Source: HemOnc extract's local OMOP `Is a` ancestry of each `Drugs.main_class`
value, walked up to two roots -- see `compiler/classification_generation.py`
for the algorithm and the root concept codes/ids/names.

ENDOCRINE_MAIN_CLASSES: every distinct `main_class` value whose components all
resolve (via a real, non-"Steroid" `Is a` chain) to "{ENDOCRINE_ROOT_CONCEPT_NAME}"
(concept_id={ENDOCRINE_ROOT_CONCEPT_ID}). Replaces the old, separately
hand-curated GnRH and Hormone buckets: both converge on this single real
ancestor, and HemOnc's own hierarchy has no cut that reproduces the old split.

SUPPORTIVE_MAIN_CLASSES: every distinct `main_class` value whose components all
resolve to "{SUPPORTIVE_ROOT_CONCEPT_NAME}" (concept_id={SUPPORTIVE_ROOT_CONCEPT_ID}).
Narrower than the old hand-curated set: "Somatostatin analog" moved out (it is a
real "{ENDOCRINE_ROOT_CONCEPT_NAME}" descendant, not supportive care), and
"IL-1R antagonist"/"Anti-IL-6R antibody" are dropped rather than forced in -- no
principled ancestor covers them without also pulling in real antineoplastics
("Targeted therapeutic") or unrelated immunosuppressants.

`main_class` values with no component resolving to either root (own-name
hierarchy gap in the HemOnc extract, not a classification decision):
{unresolved_comment}

`main_class` values whose components disagree (some but not all resolve to a
root) -- excluded from both sets rather than guessed from a majority:
{inconsistent_comment}
"""

from __future__ import annotations

ENDOCRINE_MAIN_CLASSES: frozenset[str] = {_frozenset_literal(result.endocrine_main_classes)}

SUPPORTIVE_MAIN_CLASSES: frozenset[str] = {_frozenset_literal(result.supportive_main_classes)}
'''


def regenerate(data_dir: Path, output_path: Path) -> ClassificationGenerationResult:
    """Run `generate` and write its result to `output_path`."""
    result = generate(data_dir)
    output_path.write_text(render_module(result), encoding="utf-8")
    return result
