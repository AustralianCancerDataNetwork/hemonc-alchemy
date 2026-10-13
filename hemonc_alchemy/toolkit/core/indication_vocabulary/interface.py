"""Connector-neutral types and hierarchy access for indication vocabularies."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast
from weakref import ReferenceType, ref


@dataclass(frozen=True)
class VocabularyConcept:
    concept_id: int
    concept_name: str
    domain_id: str
    vocabulary_id: str
    concept_class_id: str
    standard_concept: str
    concept_code: str
    valid_start_date: str
    valid_end_date: str
    invalid_reason: str = ""

    @property
    def standard(self) -> bool:
        return bool(self.standard_concept)

    @property
    def is_local(self) -> bool:
        return self.concept_id >= 2_000_000_000


@dataclass(frozen=True)
class VocabularyRelationship:
    concept_id_1: int
    concept_id_2: int
    relationship_id: str
    valid_start_date: str = ""
    valid_end_date: str = ""
    direction: str = "out"

    @property
    def other_concept_id(self) -> int:
        return self.concept_id_2 if self.direction == "out" else self.concept_id_1


@dataclass(frozen=True)
class NumericBound:
    comparator: str
    value: float


@dataclass(frozen=True)
class ConceptBounds:
    """Numeric attribute of a criterion term, held outside the concept tables."""

    qualifier: str
    comparator_low: str
    value_low: float | None
    comparator_high: str
    value_high: float | None
    unit: str
    unit_concept_id: int | None = None

    @staticmethod
    def _bound(comparator: str, value: float | None) -> NumericBound | None:
        return NumericBound(comparator, value) if value is not None else None

    @property
    def lower(self) -> NumericBound | None:
        return self._bound(self.comparator_low, self.value_low)

    @property
    def upper(self) -> NumericBound | None:
        return self._bound(self.comparator_high, self.value_high)


@dataclass(frozen=True)
class CriterionTerm:
    """One ANDed element of a criterion alternative: a concept, numeric bounds, text, or a mix."""

    concept_id: int | None = None
    bounds: ConceptBounds | None = None
    text: str = ""


@dataclass(frozen=True)
class VocabularyCriterion:
    """One ANDed requirement of an indication; the alternatives are ORed."""

    indication_id: int
    dimension: str
    polarity: str
    alternatives: tuple[tuple[CriterionTerm, ...], ...]


@dataclass(frozen=True)
class SourceConceptMatch:
    target_concept_id: int | None
    target_kind: str
    fit: str
    status: str
    provenance: str


@dataclass(frozen=True)
class VocabularyVersion:
    vocabulary_id: str
    release: str
    concept_count: int


@dataclass(frozen=True)
class ConceptIdTranslator:
    """Translate local concept ids to adopted ids and back by id only."""

    local_to_real: Mapping[int, int]

    def to_local(self, concept_id: int) -> int:
        reverse = {real: local for local, real in self.local_to_real.items()}
        return reverse.get(concept_id, concept_id)

    def to_real(self, concept_id: int) -> int:
        return self.local_to_real.get(concept_id, concept_id)


class IndicationVocabulary(Protocol):
    has_bounds: bool
    has_source_map: bool
    has_review_status: bool

    def concept(self, concept_id: int) -> VocabularyConcept | None: ...

    def concept_by_code(
        self, vocabulary_id: str, code: str
    ) -> VocabularyConcept | None: ...

    def concepts_of_class(
        self, concept_class_id: str
    ) -> tuple[VocabularyConcept, ...]: ...

    def relationships(
        self,
        concept_id: int,
        relationship_ids: Sequence[str] | None = None,
        direction: str = "out",
    ) -> tuple[VocabularyRelationship, ...]: ...

    def criteria(self, indication_id: int) -> tuple[VocabularyCriterion, ...]: ...

    def concept_for_source(
        self, source_column: str, raw_value: str, context: str | None = None
    ) -> SourceConceptMatch | None: ...

    def version(self) -> VocabularyVersion: ...

    def review_status(self, concept_id: int) -> str | None: ...

    def edge_review_status(
        self, concept_id_1: int, concept_id_2: int, relationship_id: str
    ) -> str | None: ...


_INSTANCE_CACHE: dict[tuple[int, str], tuple[ReferenceType[object], object]] = {}


def cached_instance_value(
    instance: object, namespace: str, factory: Callable[[], object]
) -> object:
    key = (id(instance), namespace)
    cached = _INSTANCE_CACHE.get(key)
    if cached is not None and cached[0]() is instance:
        return cached[1]
    try:
        reference = ref(instance)
    except TypeError:
        return factory()

    def remove(dead: ReferenceType[object], cache_key: tuple[int, str] = key) -> None:
        current = _INSTANCE_CACHE.get(cache_key)
        if current is not None and current[0] is dead:
            _INSTANCE_CACHE.pop(cache_key, None)

    reference = ref(instance, remove)
    value = factory()
    _INSTANCE_CACHE[key] = (reference, value)
    return value


def clear_instance_cache(
    instance: object | None = None, namespace: str | None = None
) -> None:
    for key in tuple(_INSTANCE_CACHE):
        cached = _INSTANCE_CACHE[key]
        instance_matches = instance is None or (
            key[0] == id(instance) and cached[0]() is instance
        )
        namespace_matches = namespace is None or key[1] == namespace
        if instance_matches and namespace_matches:
            _INSTANCE_CACHE.pop(key, None)


class HierarchyWalker:
    """Walk taxonomy relationships with cycle, depth and ordering guards."""

    def __init__(self, vocabulary: IndicationVocabulary, max_depth: int = 64) -> None:
        self._vocabulary_ref: ReferenceType[IndicationVocabulary] | None = None
        self._strong_vocabulary: IndicationVocabulary | None = None
        try:
            self._vocabulary_ref = ref(vocabulary)
        except TypeError:
            self._strong_vocabulary = vocabulary
        self.max_depth = max_depth
        self._walk_cache: dict[tuple[int, tuple[str, ...]], tuple[int, ...]] = {}
        self._path_cache: dict[
            tuple[int, int, str], tuple[VocabularyRelationship, ...] | None
        ] = {}

    @property
    def vocabulary(self) -> IndicationVocabulary:
        if self._strong_vocabulary is not None:
            return self._strong_vocabulary
        reference = self._vocabulary_ref
        if reference is None:
            raise ReferenceError("The vocabulary connector no longer exists.")
        vocabulary = reference()
        if vocabulary is None:
            raise ReferenceError("The vocabulary connector no longer exists.")
        return vocabulary

    def ancestors(self, concept_id: int) -> tuple[int, ...]:
        return self.walk(concept_id, ("Is a",))

    def descendants(self, concept_id: int) -> tuple[int, ...]:
        return self.walk(concept_id, ("Subsumes",))

    def walk(self, concept_id: int, relationship_ids: Sequence[str]) -> tuple[int, ...]:
        key = (concept_id, tuple(sorted(relationship_ids)))
        if key not in self._walk_cache:
            seen = {concept_id}
            order = []
            queue = deque([(concept_id, 0)])
            while queue:
                node, depth = queue.popleft()
                if depth >= self.max_depth:
                    continue
                edges = self.vocabulary.relationships(node, key[1], "out")
                for edge in sorted(edges, key=lambda item: item.concept_id_2):
                    other = edge.concept_id_2
                    if other not in seen:
                        seen.add(other)
                        order.append(other)
                        queue.append((other, depth + 1))
            self._walk_cache[key] = tuple(order)
        return self._walk_cache[key]

    def path(
        self, source_id: int, target_id: int, relationship_id: str = "Is a"
    ) -> tuple[VocabularyRelationship, ...] | None:
        key = (source_id, target_id, relationship_id)
        if key not in self._path_cache:
            self._path_cache[key] = self._find_path(*key)
        return self._path_cache[key]

    def _walk(self, start: int, relationship_id: str) -> tuple[int, ...]:
        return self.walk(start, (relationship_id,))

    def _find_path(
        self, source_id: int, target_id: int, relationship_id: str
    ) -> tuple[VocabularyRelationship, ...] | None:
        if source_id == target_id:
            return ()
        queue: deque[tuple[int, tuple[VocabularyRelationship, ...]]] = deque(
            [(source_id, ())]
        )
        seen = {source_id}
        while queue:
            node, path = queue.popleft()
            if len(path) >= self.max_depth:
                continue
            edges = self.vocabulary.relationships(node, (relationship_id,), "out")
            for edge in sorted(edges, key=lambda item: item.concept_id_2):
                other = edge.concept_id_2
                next_path = (*path, edge)
                if other == target_id:
                    return next_path
                if other not in seen:
                    seen.add(other)
                    queue.append((other, next_path))
        return None


def hierarchy_for(vocabulary: IndicationVocabulary) -> HierarchyWalker:
    return cast(
        HierarchyWalker,
        cached_instance_value(
            vocabulary, "hierarchy", lambda: HierarchyWalker(vocabulary)
        ),
    )


def clear_hierarchy_cache(vocabulary: IndicationVocabulary | None = None) -> None:
    clear_instance_cache(vocabulary, "hierarchy")


__all__ = [
    "ConceptBounds",
    "ConceptIdTranslator",
    "CriterionTerm",
    "HierarchyWalker",
    "IndicationVocabulary",
    "NumericBound",
    "SourceConceptMatch",
    "VocabularyConcept",
    "VocabularyCriterion",
    "VocabularyRelationship",
    "VocabularyVersion",
    "cached_instance_value",
    "clear_hierarchy_cache",
    "clear_instance_cache",
    "hierarchy_for",
]
