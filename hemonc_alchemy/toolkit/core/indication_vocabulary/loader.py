"""Read access to the packaged indication vocabulary tables."""

import csv
import re
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Protocol

LOCAL_CONCEPT_BASE = 2_000_000_000
HIERARCHY = ("Is a",)
IMPLICATION = ("Is a", "Clinically implies", "Equiv in indic")


def normalise_source_value(value: str) -> str:
    """Fold case, spacing and enum underscores so raw values compare equal."""
    text = value.strip().casefold().replace("_to_", "-").replace("_", " ")
    return re.sub(r"\s+", " ", text)


@dataclass(frozen=True)
class Concept:
    concept_id: int
    concept_name: str
    domain_id: str
    vocabulary_id: str
    concept_class_id: str
    standard_concept: str
    concept_code: str
    valid_start_date: str
    valid_end_date: str
    invalid_reason: str

    @property
    def is_local(self) -> bool:
        return self.concept_id >= LOCAL_CONCEPT_BASE


@dataclass(frozen=True)
class Relationship:
    concept_id_1: int
    concept_id_2: int
    relationship_id: str


@dataclass(frozen=True)
class SourceMatch:
    target_concept_id: int | None
    target_kind: str
    fit: str
    status: str
    provenance: str


@dataclass(frozen=True)
class Bounds:
    qualifier: str
    comparator_low: str
    value_low: float | None
    comparator_high: str
    value_high: float | None
    unit: str


@dataclass(frozen=True)
class Criterion:
    """One AND-ed requirement of an indication; the alternatives are ORed."""

    indication_id: int
    dimension: str
    polarity: str
    alternatives: tuple[tuple[int, ...], ...]


@dataclass(frozen=True)
class RelationshipType:
    relationship_id: str
    relationship_name: str
    is_hierarchical: bool
    defines_ancestry: bool
    reverse_relationship_id: str
    relationship_concept_id: int


class ConceptSource(Protocol):
    """The subset of OMOP concept and concept_relationship access that consumers use."""

    def concept(self, concept_id: int) -> Concept | None: ...

    def relationships(
        self, concept_id: int, relationship_id: str | None = None
    ) -> tuple[Relationship, ...]: ...


def data_directory() -> Path:
    return Path(
        str(
            resources.files(
                "hemonc_alchemy.toolkit.core.indication_vocabulary"
            ).joinpath("data")
        )
    )


def read_table(directory: Path, name: str) -> list[dict[str, str]]:
    with (directory / f"{name}.tsv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _number(value: str) -> float | None:
    return float(value) if value.strip() else None


class IndicationVocabulary:
    """Local concepts, relationships and source-value maps for HemOnc indications."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._concepts: dict[int, Concept] = {}
        for name in ("concept", "existing_concepts"):
            for row in read_table(directory, name):
                concept = Concept(
                    int(row["concept_id"]),
                    row["concept_name"],
                    row["domain_id"],
                    row["vocabulary_id"],
                    row["concept_class_id"],
                    row.get("standard_concept", ""),
                    row["concept_code"],
                    row.get("valid_start_date", ""),
                    row.get("valid_end_date", ""),
                    row.get("invalid_reason", ""),
                )
                self._concepts[concept.concept_id] = concept
        self._by_code = {
            c.concept_code: c for c in self._concepts.values() if c.is_local
        }
        self._out: dict[int, list[Relationship]] = {}
        self.relationship_rows = [
            Relationship(
                int(r["concept_id_1"]), int(r["concept_id_2"]), r["relationship_id"]
            )
            for r in read_table(directory, "concept_relationship")
        ]
        for rel in self.relationship_rows:
            self._out.setdefault(rel.concept_id_1, []).append(rel)
        self.relationship_types = {
            r["relationship_id"]: RelationshipType(
                r["relationship_id"],
                r["relationship_name"],
                r["is_hierarchical"] == "1",
                r["defines_ancestry"] == "1",
                r["reverse_relationship_id"],
                int(r["relationship_concept_id"]),
            )
            for r in read_table(directory, "relationship")
        }
        self._source: dict[tuple[str, str, str], SourceMatch] = {}
        for row in read_table(directory, "source_concept_map"):
            key = (
                row["source_column"],
                normalise_source_value(row["raw_value"]),
                normalise_source_value(row["context"]),
            )
            target = int(row["target_concept_id"]) if row["target_concept_id"] else None
            self._source[key] = SourceMatch(
                target, row["target_kind"], row["fit"], row["status"], row["provenance"]
            )
        self._bounds = {
            int(r["concept_id"]): Bounds(
                r["qualifier"],
                r["comparator_low"],
                _number(r["value_low"]),
                r["comparator_high"],
                _number(r["value_high"]),
                r["unit"],
            )
            for r in read_table(directory, "concept_bounds")
        }

    def concept(self, concept_id: int) -> Concept | None:
        return self._concepts.get(concept_id)

    def concept_by_code(self, concept_code: str) -> Concept | None:
        return self._by_code.get(concept_code)

    def concepts(self, concept_class_id: str | None = None) -> tuple[Concept, ...]:
        return tuple(
            c
            for c in self._concepts.values()
            if c.is_local
            and (concept_class_id is None or c.concept_class_id == concept_class_id)
        )

    def lookup(
        self, source_column: str, raw_value: str, context: str = ""
    ) -> SourceMatch | None:
        """Match for a source column and raw value, with an optional context such as the gene or age unit."""
        value = normalise_source_value(raw_value)
        return self._source.get(
            (source_column, value, normalise_source_value(context))
        ) or self._source.get((source_column, value, ""))

    def concept_for(
        self, source_column: str, raw_value: str, context: str = ""
    ) -> int | None:
        match = self.lookup(source_column, raw_value, context)
        return match.target_concept_id if match else None

    def relationships(
        self, concept_id: int, relationship_id: str | None = None
    ) -> tuple[Relationship, ...]:
        rels = self._out.get(concept_id, ())
        return tuple(
            r
            for r in rels
            if relationship_id is None or r.relationship_id == relationship_id
        )

    def related(self, concept_id: int, relationship_id: str) -> tuple[int, ...]:
        return tuple(
            r.concept_id_2 for r in self.relationships(concept_id, relationship_id)
        )

    def _walk(self, start: int, relationship_ids: Iterable[str]) -> tuple[int, ...]:
        ids = tuple(relationship_ids)
        seen = {start}
        order: list[int] = []
        queue = deque((start,))
        while queue:
            node = queue.popleft()
            for rel in self.relationships(node):
                if rel.relationship_id in ids and rel.concept_id_2 not in seen:
                    seen.add(rel.concept_id_2)
                    order.append(rel.concept_id_2)
                    queue.append(rel.concept_id_2)
        return tuple(order)

    def ancestors(self, concept_id: int) -> tuple[int, ...]:
        """Concepts above this one through Is a, nearest first."""
        return self._walk(concept_id, ("Is a",))

    def descendants(self, concept_id: int) -> tuple[int, ...]:
        """Concepts below this one through Subsumes, nearest first."""
        return self._walk(concept_id, ("Subsumes",))

    def implied(self, concept_id: int) -> tuple[int, ...]:
        """Concepts a result also satisfies: Is a ancestors, clinical implications and equivalents."""
        return self._walk(concept_id, IMPLICATION)

    def bounds(self, concept_id: int) -> Bounds | None:
        return self._bounds.get(concept_id)

    def threshold_states(
        self, analyte_id: int, qualifier: str, value: float, unit: str
    ) -> tuple[int, ...]:
        """Biomarker states on an analyte whose threshold a measured value meets."""
        met = []
        for state in self.concepts("Biomarker State"):
            if analyte_id not in self.related(state.concept_id, "State has analyte"):
                continue
            for threshold in self.related(state.concept_id, "State has threshold"):
                bounds = self._bounds.get(threshold)
                if (
                    bounds
                    and bounds.qualifier == qualifier
                    and bounds.unit == unit
                    and _meets(bounds, value)
                ):
                    met.append(state.concept_id)
        return tuple(sorted(met))

    def criteria(self, indication_id: int) -> tuple[Criterion, ...]:
        """Criteria of an indication as ORed alternatives of ANDed concepts."""
        out = []
        for rel in self.relationships(indication_id):
            if rel.relationship_id not in {"Ind requires", "Ind excludes"}:
                continue
            dimension = next(
                iter(self.related(rel.concept_id_2, "Set has dimension")), None
            )
            out.append(
                Criterion(
                    indication_id,
                    self._dimension_name(dimension),
                    "requires" if rel.relationship_id == "Ind requires" else "excludes",
                    self._alternatives(rel.concept_id_2),
                )
            )
        return tuple(out)

    def _dimension_name(self, dimension_id: int | None) -> str:
        concept = self._concepts.get(dimension_id) if dimension_id is not None else None
        return concept.concept_code.removeprefix("HOL-DIM-") if concept else ""

    def _alternatives(self, set_id: int) -> tuple[tuple[int, ...], ...]:
        all_members = self.related(set_id, "Set has all")
        if all_members:
            return (tuple(sorted(all_members)),)
        out: list[tuple[int, ...]] = []
        for member in self.related(set_id, "Set has any"):
            concept = self._concepts.get(member)
            if concept is not None and concept.concept_class_id == "Criterion Set":
                out.extend(self._alternatives(member))
            else:
                out.append((member,))
        return tuple(sorted(out))

    def indication_ids(self) -> tuple[int, ...]:
        return tuple(sorted(c.concept_id for c in self.concepts("Indication")))

    def table(self, name: str) -> list[dict[str, str]]:
        return read_table(self.directory, name)


def _meets(bounds: Bounds, value: float) -> bool:
    if bounds.value_low is not None:
        low = bounds.value_low
        if (bounds.comparator_low == ">=" and value < low) or (
            bounds.comparator_low == ">" and value <= low
        ):
            return False
        if bounds.comparator_low == "=" and value != low:
            return False
    if bounds.value_high is not None:
        high = bounds.value_high
        if (bounds.comparator_high == "<=" and value > high) or (
            bounds.comparator_high == "<" and value >= high
        ):
            return False
    return True


@lru_cache(maxsize=1)
def load_vocabulary() -> IndicationVocabulary:
    """Read the packaged tables once per process."""
    return IndicationVocabulary(data_directory())


__all__ = [
    "Bounds",
    "Concept",
    "ConceptSource",
    "Criterion",
    "IndicationVocabulary",
    "Relationship",
    "RelationshipType",
    "SourceMatch",
    "data_directory",
    "load_vocabulary",
    "normalise_source_value",
    "read_table",
]
