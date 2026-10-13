"""Read access to the packaged indication vocabulary tables."""

import csv
import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Protocol

from .interface import (
    ConceptBounds as Bounds,
)
from .interface import (
    CriterionTerm,
    VocabularyCriterion,
    VocabularyVersion,
    hierarchy_for,
)
from .interface import (
    SourceConceptMatch as SourceMatch,
)
from .interface import (
    VocabularyConcept as Concept,
)
from .interface import (
    VocabularyRelationship as Relationship,
)

LOCAL_CONCEPT_BASE = 2_000_000_000
HIERARCHY = ("Is a",)
IMPLICATION = ("Is a", "Clinically implies", "Equiv in indic")


def normalise_source_value(value: str) -> str:
    """Fold case, spacing and enum underscores so raw values compare equal."""
    text = value.strip().casefold().replace("_to_", "-").replace("_", " ")
    return re.sub(r"\s+", " ", text)


Criterion = VocabularyCriterion


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


class LocalTsvVocabulary:
    """Local concepts, relationships and source-value maps for HemOnc indications."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._concepts: dict[int, Concept] = {}
        self._concepts_by_vocabulary_code: dict[tuple[str, str], Concept] = {}
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
                self._concepts_by_vocabulary_code[
                    (concept.vocabulary_id, concept.concept_code)
                ] = concept
        self._by_code = {
            c.concept_code: c for c in self._concepts.values() if c.is_local
        }
        self._out: dict[int, list[Relationship]] = {}
        self._in: dict[int, list[Relationship]] = {}
        self.relationship_rows = [
            Relationship(
                int(r["concept_id_1"]),
                int(r["concept_id_2"]),
                r["relationship_id"],
                r["valid_start_date"],
                r["valid_end_date"],
            )
            for r in read_table(directory, "concept_relationship")
        ]
        self.existing_relationship_rows = [
            Relationship(
                int(r["concept_id_1"]),
                int(r["concept_id_2"]),
                r["relationship_id"],
                "",
                "",
            )
            for r in read_table(directory, "existing_relationships")
        ]
        for rel in (*self.relationship_rows, *self.existing_relationship_rows):
            self._out.setdefault(rel.concept_id_1, []).append(rel)
            self._in.setdefault(rel.concept_id_2, []).append(rel)
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
        self._criteria: dict[int, list[VocabularyCriterion]] = {}
        self._load_criteria(directory)
        self._source_terms: dict[
            tuple[str, str, str], tuple[tuple[CriterionTerm, ...], ...]
        ] = {}
        self._load_source_terms(directory)
        self._concept_status = {
            int(r["concept_id"]): r["review_status"]
            for r in read_table(directory, "concept_status")
        }
        self._edge_status = {
            (int(r["concept_id_1"]), int(r["concept_id_2"]), r["relationship_id"]): r[
                "status"
            ]
            for r in read_table(directory, "relationship_review")
        }
        self.has_bounds = True
        self.has_source_map = True
        self.has_review_status = True
        release_dates = [
            row.get("source_date", "")
            for row in read_table(directory, "existing_concepts")
            if row.get("source_date")
        ]
        self._release = max(release_dates, default="2026-10-13")

    @staticmethod
    def _term(row: dict[str, str]) -> CriterionTerm:
        bounds = None
        if row["value_low"].strip() or row["value_high"].strip():
            bounds = Bounds(
                row["qualifier"],
                row["comparator_low"],
                _number(row["value_low"]),
                row["comparator_high"],
                _number(row["value_high"]),
                row["unit"],
            )
        concept_id = int(row["concept_id"]) if row["concept_id"].strip() else None
        return CriterionTerm(concept_id, bounds, row["text"])

    def _load_criteria(self, directory: Path) -> None:
        terms: dict[int, dict[int, list[tuple[int, CriterionTerm]]]] = {}
        for row in read_table(directory, "criterion_term"):
            terms.setdefault(int(row["criterion_id"]), {}).setdefault(
                int(row["alternative_no"]), []
            ).append((int(row["term_no"]), self._term(row)))
        for row in read_table(directory, "indication_criterion"):
            by_alternative = terms.get(int(row["criterion_id"]), {})
            alternatives = tuple(
                tuple(term for _, term in sorted(by_alternative[number]))
                for number in sorted(by_alternative)
            )
            criterion = VocabularyCriterion(
                int(row["indication_id"]),
                row["dimension"],
                row["polarity"],
                alternatives,
            )
            self._criteria.setdefault(criterion.indication_id, []).append(criterion)

    def _load_source_terms(self, directory: Path) -> None:
        grouped: dict[
            tuple[str, str, str], dict[int, list[tuple[int, CriterionTerm]]]
        ] = {}
        for row in read_table(directory, "source_value_terms"):
            key = (
                row["source_column"],
                normalise_source_value(row["raw_value"]),
                normalise_source_value(row["context"]),
            )
            grouped.setdefault(key, {}).setdefault(
                int(row["alternative_no"]), []
            ).append((int(row["term_no"]), self._term(row)))
        for key, by_alternative in grouped.items():
            self._source_terms[key] = tuple(
                tuple(term for _, term in sorted(by_alternative[number]))
                for number in sorted(by_alternative)
            )

    def concept(self, concept_id: int) -> Concept | None:
        return self._concepts.get(concept_id)

    def concept_by_code(
        self, vocabulary_id: str, code: str | None = None
    ) -> Concept | None:
        if code is None:
            return self._by_code.get(vocabulary_id)
        return self._concepts_by_vocabulary_code.get((vocabulary_id, code))

    def concepts(self, concept_class_id: str | None = None) -> tuple[Concept, ...]:
        return tuple(
            c
            for c in self._concepts.values()
            if c.is_local
            and (concept_class_id is None or c.concept_class_id == concept_class_id)
        )

    def concepts_of_class(self, concept_class_id: str) -> tuple[Concept, ...]:
        return tuple(
            sorted(
                (
                    c
                    for c in self._concepts.values()
                    if c.concept_class_id == concept_class_id
                ),
                key=lambda c: c.concept_id,
            )
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

    def concept_for_source(
        self, source_column: str, raw_value: str, context: str | None = None
    ) -> SourceMatch | None:
        return self.lookup(source_column, raw_value, context or "")

    def relationships(
        self,
        concept_id: int,
        relationship_ids: str | Iterable[str] | None = None,
        direction: str = "out",
    ) -> tuple[Relationship, ...]:
        if direction not in {"out", "in"}:
            raise ValueError("direction must be 'out' or 'in'")
        rels = (self._out if direction == "out" else self._in).get(concept_id, ())
        identifiers = (
            None
            if relationship_ids is None
            else {relationship_ids}
            if isinstance(relationship_ids, str)
            else set(relationship_ids)
        )
        return tuple(
            r
            if direction == "out"
            else Relationship(
                r.concept_id_1,
                r.concept_id_2,
                r.relationship_id,
                r.valid_start_date,
                r.valid_end_date,
                "in",
            )
            for r in rels
            if identifiers is None or r.relationship_id in identifiers
        )

    def related(self, concept_id: int, relationship_id: str) -> tuple[int, ...]:
        return tuple(
            r.concept_id_2 for r in self.relationships(concept_id, relationship_id)
        )

    def _walk(self, start: int, relationship_ids: Iterable[str]) -> tuple[int, ...]:
        return hierarchy_for(self).walk(start, tuple(relationship_ids))

    def ancestors(self, concept_id: int) -> tuple[int, ...]:
        """Concepts above this one through Is a, nearest first."""
        return self._walk(concept_id, ("Is a",))

    def descendants(self, concept_id: int) -> tuple[int, ...]:
        """Concepts below this one through Subsumes, nearest first."""
        return self._walk(concept_id, ("Subsumes",))

    def implied(self, concept_id: int) -> tuple[int, ...]:
        """Concepts a result also satisfies: Is a ancestors, clinical implications and equivalents."""
        return self._walk(concept_id, IMPLICATION)

    def version(self) -> VocabularyVersion:
        return VocabularyVersion("HemOnc Local", self._release, len(self._concepts))

    def review_status(self, concept_id: int) -> str | None:
        return self._concept_status.get(concept_id)

    def edge_review_status(
        self, concept_id_1: int, concept_id_2: int, relationship_id: str
    ) -> str | None:
        status = self._edge_status.get((concept_id_1, concept_id_2, relationship_id))
        if status is not None:
            return status
        reverse = self.relationship_types.get(relationship_id)
        if reverse is None:
            return None
        return self._edge_status.get(
            (concept_id_2, concept_id_1, reverse.reverse_relationship_id)
        )

    def criteria(self, indication_id: int) -> tuple[VocabularyCriterion, ...]:
        """Criteria of an indication as ORed alternatives of ANDed terms."""
        return tuple(self._criteria.get(indication_id, ()))

    def terms_for_source(
        self, source_column: str, raw_value: str, context: str = ""
    ) -> tuple[tuple[CriterionTerm, ...], ...] | None:
        """How a raw value reads as ORed alternatives of ANDed terms, when it is not a single concept."""
        value = normalise_source_value(raw_value)
        return self._source_terms.get(
            (source_column, value, normalise_source_value(context))
        ) or self._source_terms.get((source_column, value, ""))

    def indication_ids(self) -> tuple[int, ...]:
        return tuple(sorted(c.concept_id for c in self.concepts("Indication")))

    def table(self, name: str) -> list[dict[str, str]]:
        return read_table(self.directory, name)


IndicationVocabulary = LocalTsvVocabulary


@lru_cache(maxsize=1)
def load_vocabulary() -> LocalTsvVocabulary:
    """Read the packaged tables once per process."""
    return LocalTsvVocabulary(data_directory())


__all__ = [
    "Bounds",
    "Concept",
    "ConceptSource",
    "Criterion",
    "CriterionTerm",
    "IndicationVocabulary",
    "LocalTsvVocabulary",
    "Relationship",
    "RelationshipType",
    "SourceMatch",
    "data_directory",
    "load_vocabulary",
    "normalise_source_value",
    "read_table",
]
