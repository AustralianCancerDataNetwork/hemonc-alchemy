"""Check the packaged indication vocabulary for integrity and list what still needs review."""

import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .loader import (
    LOCAL_CONCEPT_BASE,
    IndicationVocabulary,
    normalise_source_value,
)

TABLES = (
    "concept",
    "concept_relationship",
    "relationship",
    "concept_class",
    "domain",
    "vocabulary",
    "indication_criterion",
    "criterion_term",
    "source_value_terms",
    "concept_status",
    "relationship_review",
    "source_concept_map",
    "mapping_to_existing",
    "existing_concepts",
    "indication_notes",
    "unanchored_indications",
    "gap_register",
)
REVIEWED_RELATIONSHIPS = frozenset(
    {"Is a", "Clinically implies", "Equiv in indic", "Opposite of"}
)
ANCHOR_CLASSES = {
    "Ind has component": "Component",
    "Ind has condition": "Condition",
    "Ind has regimen": "Regimen",
}
DIMENSIONS = frozenset(
    {
        "biomarker",
        "stage",
        "status",
        "stage_or_status",
        "age",
        "sex",
        "prior_therapy",
        "prior_therapy_setting",
        "with_field",
        "ineligibility",
        "demographics",
        "response_contingency",
        "risk_stratification",
        "exposure_phenotype",
        "time_contingency",
    }
)
COMPARATORS = frozenset({"=", ">", ">=", "<", "<="})
CONCEPT_STATUSES = frozenset({"proposed-new", "mapped-to-existing", "existing"})
PLACEHOLDER_NAMES = frozenset({"0", "none", "not applicable", "true", "false"})


def _is_placeholder_name(name: str) -> bool:
    text = name.strip().casefold()
    return (
        text in PLACEHOLDER_NAMES or re.fullmatch(r"[+-]?\d+(\.\d+)?", text) is not None
    )


@dataclass(frozen=True)
class VocabularyLint:
    failures: tuple[str, ...]
    unmapped_values: tuple[str, ...]
    needs_review: tuple[str, ...]
    warnings: tuple[str, ...]


def _cycles(edges: dict[int, list[int]]) -> list[int]:
    state: dict[int, int] = {}
    found: list[int] = []
    for root in edges:
        if root in state:
            continue
        stack = [(root, iter(edges.get(root, ())))]
        state[root] = 1
        while stack:
            node, children = stack[-1]
            for child in children:
                if state.get(child) == 1:
                    found.append(child)
                elif child not in state:
                    state[child] = 1
                    stack.append((child, iter(edges.get(child, ()))))
                    break
            else:
                state[node] = 2
                stack.pop()
    return found


def _tables(
    vocab: IndicationVocabulary, failures: list[str]
) -> dict[str, list[dict[str, str]]]:
    out = {}
    for name in TABLES:
        if not (Path(vocab.directory) / f"{name}.tsv").exists():
            failures.append(f"missing table {name}.tsv")
            continue
        out[name] = vocab.table(name)
    return out


def _check_concepts(vocab, tables, failures) -> set[int]:
    local = {int(r["concept_id"]): r for r in tables["concept"]}
    if len(local) != len(tables["concept"]):
        failures.append("duplicate concept_id in concept.tsv")
    codes = Counter(r["concept_code"] for r in tables["concept"])
    failures.extend(
        f"duplicate concept_code {code}" for code, n in codes.items() if n > 1
    )
    classes = {r["concept_class_id"] for r in tables["concept_class"]}
    domains = {r["domain_id"] for r in tables["domain"]} | {"Observation", "Procedure"}
    vocabularies = {r["vocabulary_id"] for r in tables["vocabulary"]}
    for cid, row in local.items():
        if cid < LOCAL_CONCEPT_BASE:
            failures.append(f"local concept {cid} is below the local id range")
        if row["concept_class_id"] not in classes:
            failures.append(
                f"concept {cid} has undefined concept_class_id {row['concept_class_id']}"
            )
        if row["domain_id"] not in domains:
            failures.append(f"concept {cid} has undefined domain_id {row['domain_id']}")
        name = row["concept_name"]
        if _is_placeholder_name(name) or _is_placeholder_name(name.split(": ", 1)[-1]):
            failures.append(f"concept {cid} is named with a bare placeholder: {name!r}")
        if row["vocabulary_id"] not in vocabularies:
            failures.append(
                f"concept {cid} has undefined vocabulary_id {row['vocabulary_id']}"
            )
    statuses = {r["concept_id"]: r for r in tables["concept_status"]}
    for cid in local:
        row = statuses.get(str(cid))
        if row is None:
            failures.append(f"concept {cid} has no concept_status row")
        elif (
            row["status"] not in CONCEPT_STATUSES
            or not row["provenance"]
            or not row["proposed_owner"]
        ):
            failures.append(f"concept {cid} has an incomplete concept_status row")
    return set(local)


def _check_existing(vocab, tables, failures, warnings, local_ids) -> set[int]:
    snapshot = {int(r["concept_id"]): r for r in tables["existing_concepts"]}
    for cid, row in snapshot.items():
        if "groundworkers" not in row["verified_via"]:
            failures.append(
                f"existing concept {cid} was not verified through groundworkers"
            )
        if row["invalid_reason"] or (
            row["valid_end_date"] and row["valid_end_date"] < "2099-12-31"
        ):
            failures.append(
                f"existing concept {cid} ({row['concept_name']}) is not valid in groundworkers"
            )
        if row["vocabulary_id"] != "HemOnc" and row["standard_concept"] not in {
            "S",
            "C",
        }:
            warnings.append(
                f"existing concept {cid} ({row['concept_name']}, {row['vocabulary_id']}) is not standard"
            )
    cited: set[int] = set()
    for rel in vocab.relationship_rows:
        for cid in (rel.concept_id_1, rel.concept_id_2):
            if cid not in local_ids:
                cited.add(cid)
    for row in tables["source_concept_map"]:
        if row["target_concept_id"] and int(row["target_concept_id"]) not in local_ids:
            cited.add(int(row["target_concept_id"]))
    for row in tables["mapping_to_existing"]:
        cid = int(row["concept_id"])
        cited.add(cid)
        known = snapshot.get(cid)
        if known and (
            known["concept_name"],
            known["vocabulary_id"],
            known["concept_class_id"],
        ) != (row["concept_name"], row["vocabulary_id"], row["concept_class_id"]):
            failures.append(
                f"mapping_to_existing disagrees with the groundworkers snapshot for concept {cid}"
            )
    failures.extend(
        f"cited existing concept {cid} is missing from existing_concepts"
        for cid in sorted(cited - set(snapshot))
        if cid not in local_ids
    )
    return set(snapshot)


def _check_relationships(vocab, tables, failures, local_ids, known_ids) -> None:
    types = vocab.relationship_types
    for rid, info in types.items():
        if info.reverse_relationship_id not in types:
            failures.append(
                f"relationship {rid} has no defined reverse {info.reverse_relationship_id}"
            )
        elif types[info.reverse_relationship_id].reverse_relationship_id != rid:
            failures.append(f"relationship {rid} reverse does not point back")
    present = {
        (r.concept_id_1, r.concept_id_2, r.relationship_id)
        for r in vocab.relationship_rows
    }
    valid_ids = known_ids | local_ids
    for a, b, rid in present:
        if rid not in types:
            failures.append(f"relationship_id {rid} is not defined in relationship.tsv")
            continue
        if a not in valid_ids or b not in valid_ids:
            failures.append(
                f"relationship {a} {rid} {b} has an endpoint that does not exist"
            )
        if (b, a, types[rid].reverse_relationship_id) not in present:
            failures.append(f"relationship {a} {rid} {b} has no reverse row")
    edges: dict[int, list[int]] = defaultdict(list)
    for a, b, rid in present:
        if rid == "Is a":
            edges[a].append(b)
    failures.extend(
        f"hierarchy cycle through concept {cid}" for cid in sorted(set(_cycles(edges)))
    )
    reviews = {
        (int(r["concept_id_1"]), int(r["concept_id_2"]), r["relationship_id"]): r
        for r in tables["relationship_review"]
    }
    for key in reviews:
        if key not in present:
            failures.append(f"relationship_review row for a missing relationship {key}")
    for a, b, rid in present:
        if rid not in types:
            continue
        forward = types[rid].is_hierarchical is False and rid in REVIEWED_RELATIONSHIPS
        symmetric = rid in {"Equiv in indic", "Opposite of"} and (b, a, rid) in reviews
        if forward and (a, b, rid) not in reviews and not symmetric:
            failures.append(f"{rid} edge {a} to {b} has no relationship_review row")
    for key, row in reviews.items():
        if row["status"] not in {"reviewed", "proposed"}:
            failures.append(f"relationship_review {key} has status {row['status']}")
        if row["status"] == "reviewed" and not (row["reviewer"] and row["reviewed_on"]):
            failures.append(f"reviewed edge {key} needs a reviewer and a date")
        if not row["provenance"]:
            failures.append(f"relationship_review {key} has no provenance")


def _check_term(row, label, valid_ids, failures) -> None:
    concept = row["concept_id"].strip()
    has_scalar = bool(row["value_low"].strip() or row["value_high"].strip())
    if concept and int(concept) not in valid_ids:
        failures.append(f"{label} cites concept {concept} that does not exist")
    if not (concept or has_scalar or row["text"].strip()):
        failures.append(f"{label} has no concept, number or text")
    for side in ("low", "high"):
        value, comparator = row[f"value_{side}"].strip(), row[f"comparator_{side}"]
        if value:
            try:
                float(value)
            except ValueError:
                failures.append(f"{label} has a non-numeric {side} value {value!r}")
            if comparator not in COMPARATORS:
                failures.append(
                    f"{label} has comparator {comparator!r} for its {side} value"
                )
        elif comparator:
            failures.append(f"{label} has a {side} comparator without a value")
    if has_scalar and not row["unit"].strip():
        failures.append(f"{label} has a number without a unit")


def _check_criteria(vocab, tables, failures, valid_ids) -> None:
    indications = {c.concept_id for c in vocab.concepts("Indication")}
    criterion_ids = set()
    for row in tables["indication_criterion"]:
        identifier = int(row["criterion_id"])
        if identifier in criterion_ids:
            failures.append(f"duplicate criterion_id {identifier}")
        criterion_ids.add(identifier)
        if int(row["indication_id"]) not in indications:
            failures.append(f"criterion {identifier} belongs to an unknown indication")
        if row["dimension"] not in DIMENSIONS:
            failures.append(
                f"criterion {identifier} has unknown dimension {row['dimension']}"
            )
        if row["polarity"] not in {"requires", "excludes"}:
            failures.append(f"criterion {identifier} has polarity {row['polarity']}")
    seen = set()
    for row in tables["criterion_term"]:
        identifier = int(row["criterion_id"])
        seen.add(identifier)
        if identifier not in criterion_ids:
            failures.append(f"criterion_term row for unknown criterion {identifier}")
        _check_term(row, f"criterion {identifier} term", valid_ids, failures)
    failures.extend(
        f"criterion {identifier} has no terms"
        for identifier in sorted(criterion_ids - seen)
    )
    for row in tables["source_value_terms"]:
        label = f"source value {row['source_column']}: {row['raw_value']}"
        _check_term(row, label, valid_ids, failures)


def _check_anchors(vocab, failures) -> None:
    for indication in vocab.indication_ids():
        counts = Counter(rel.relationship_id for rel in vocab.relationships(indication))
        for needed in ("Ind has component", "Ind has condition", "Ind has regulator"):
            if counts[needed] != 1:
                failures.append(
                    f"indication {indication} has {counts[needed]} {needed} links"
                )
        for rel in vocab.relationships(indication):
            expected = ANCHOR_CLASSES.get(rel.relationship_id)
            target = vocab.concept(rel.concept_id_2)
            if expected and (target is None or target.concept_class_id != expected):
                failures.append(
                    f"indication {indication} {rel.relationship_id} target {rel.concept_id_2} is not a {expected}"
                )


def lint_vocabulary(
    vocab: IndicationVocabulary, source_values: Iterable[tuple[str, str, str]] = ()
) -> VocabularyLint:
    """Run every integrity check; `source_values` are (column, raw value, context) triples from the live data."""
    failures: list[str] = []
    warnings: list[str] = []
    tables = _tables(vocab, failures)
    if failures:
        return VocabularyLint(tuple(failures), (), (), ())
    local_ids = _check_concepts(vocab, tables, failures)
    known_ids = _check_existing(vocab, tables, failures, warnings, local_ids)
    _check_relationships(vocab, tables, failures, local_ids, known_ids)
    _check_criteria(vocab, tables, failures, known_ids | local_ids)
    _check_anchors(vocab, failures)
    unmapped = [
        f"{row['source_column']}: {row['raw_value']}"
        + (f" [{row['context']}]" if row["context"] else "")
        for row in tables["source_concept_map"]
        if not row["target_concept_id"] and row["status"] != "decomposed"
    ]
    for column, raw, context in source_values:
        if vocab.lookup(column, raw, context) is None:
            unmapped.append(
                f"{column}: {raw}"
                + (f" [{context}]" if context else "")
                + " (not in source_concept_map)"
            )
    unmapped.extend(
        f"{r['source_column']}: {r['raw_value']} (free text kept as note, indication {r['indication_id']})"
        for r in tables["indication_notes"]
        if r["source_column"] == "prior_biomarker"
    )
    review: list[str] = []
    status_by_class = Counter(
        (vocab.concept(int(r["concept_id"])).concept_class_id, r["review_status"])  # type: ignore[union-attr]
        for r in tables["concept_status"]
    )
    for (cls, status), n in sorted(status_by_class.items()):
        if status != "reviewed":
            review.append(f"{n} {cls} concepts {status}")
    edge_counts = Counter(
        (r["priority"], r["relationship_id"])
        for r in tables["relationship_review"]
        if r["status"] != "reviewed"
    )
    for (priority, rid), n in sorted(edge_counts.items()):
        review.append(f"{n} {rid} edges proposed, priority {priority}")
    review.append(
        f"{len(tables['unanchored_indications'])} indications unanchored (drug or condition concept missing)"
    )
    return VocabularyLint(
        tuple(failures),
        tuple(sorted(set(unmapped), key=normalise_source_value)),
        tuple(review),
        tuple(warnings),
    )


__all__ = ["VocabularyLint", "lint_vocabulary"]
