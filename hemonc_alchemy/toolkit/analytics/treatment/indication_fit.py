"""Evaluate patient facts against indication concepts from a vocabulary connector."""

from __future__ import annotations

import operator
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import cast

from hemonc_alchemy.toolkit.core.indication_vocabulary.interface import (
    ConceptBounds,
    ConceptIdTranslator,
    CriterionTerm,
    IndicationVocabulary,
    VocabularyRelationship,
    VocabularyVersion,
    cached_instance_value,
    clear_instance_cache,
    hierarchy_for,
)


class FitStatus(str, Enum):
    FIT = "FIT"
    NO_FIT = "NO_FIT"
    UNKNOWN = "UNKNOWN"


class CriterionStatus(str, Enum):
    SATISFIED = "SATISFIED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    UNEVALUATED = "UNEVALUATED"


class LinkKind(str, Enum):
    EQUAL = "EQUAL"
    IS_A = "IS_A"
    CLINICALLY_IMPLIES = "CLINICALLY_IMPLIES"
    OPPOSITE = "OPPOSITE"


@dataclass(frozen=True)
class BiomarkerMeasurement:
    analyte_concept_id: int | None
    value_as_concept_id: int | None = None
    variant_concept_id: int | None = None
    value_as_number: float | None = None
    unit: str | None = None
    unit_concept_id: int | None = None
    qualifier: str | None = None


@dataclass(frozen=True)
class NumericFact:
    dimension: str
    value: float
    unit: str
    qualifier: str = ""


@dataclass(frozen=True)
class SettingDeclaration:
    has_prior_therapy: bool = False
    prior_line_count: int = 0
    prior_therapy_concept_ids: tuple[int, ...] = ()
    context_concept_ids: tuple[int, ...] = ()
    months_since_last_treatment: float | None = None


@dataclass(frozen=True)
class PatientState:
    biomarker_measurements: tuple[BiomarkerMeasurement, ...] = ()
    biomarker_state_concept_ids: tuple[int, ...] = ()
    measurement_state_concept_ids: tuple[int, ...] = ()
    observed_analyte_concept_ids: tuple[int, ...] = ()
    condition_concept_ids: tuple[int, ...] = ()
    disease_extent_concept_ids: tuple[int, ...] = ()
    disease_status_concept_ids: tuple[int, ...] = ()
    age_value: float | None = None
    age_unit: str | None = None
    sex_concept_id: int | None = None
    setting: SettingDeclaration = field(default_factory=SettingDeclaration)
    prior_therapy_concept_ids: tuple[int, ...] = ()
    numeric_facts: tuple[NumericFact, ...] = ()
    limitations: tuple[str, ...] = ()

    @classmethod
    def from_measurements(
        cls,
        measurements: Sequence[BiomarkerMeasurement],
        *,
        vocabulary: IndicationVocabulary | None = None,
        condition_concept_ids: Sequence[int] = (),
        disease_extent_concept_ids: Sequence[int] = (),
        disease_status_concept_ids: Sequence[int] = (),
        age_value: float | None = None,
        age_unit: str | None = None,
        sex_concept_id: int | None = None,
        setting: SettingDeclaration | None = None,
        prior_therapy_concept_ids: Sequence[int] = (),
        numeric_facts: Sequence[NumericFact] = (),
        translator: ConceptIdTranslator | None = None,
    ) -> PatientState:
        connector = _connector(vocabulary)
        index = _index_for(connector)
        normalized_measurements = tuple(
            _translate_measurement(measurement, translator)
            for measurement in measurements
        )
        direct = _states_for_measurements(normalized_measurements, connector, index)
        closure = set(direct)
        for concept_id in direct:
            closure.update(index.hierarchy.ancestors(concept_id))
        observed = {
            identifier
            for measurement in normalized_measurements
            for identifier in (measurement.analyte_concept_id,)
            if identifier is not None
        }
        observed.update(
            measurement.variant_concept_id
            for measurement in normalized_measurements
            if measurement.variant_concept_id is not None
        )
        limitations: tuple[str, ...] = ()
        if not connector.has_bounds and any(
            measurement.value_as_number is not None
            for measurement in normalized_measurements
        ):
            limitations = ("Vocabulary connector does not provide numeric bounds.",)
        if not connector.has_source_map:
            limitations = (
                *limitations,
                "Vocabulary connector does not provide source mappings.",
            )
        return cls(
            biomarker_measurements=normalized_measurements,
            biomarker_state_concept_ids=tuple(sorted(closure)),
            measurement_state_concept_ids=tuple(sorted(direct)),
            observed_analyte_concept_ids=tuple(sorted(observed)),
            condition_concept_ids=_translate_ids(condition_concept_ids, translator),
            disease_extent_concept_ids=_translate_ids(
                disease_extent_concept_ids, translator
            ),
            disease_status_concept_ids=_translate_ids(
                disease_status_concept_ids, translator
            ),
            age_value=age_value,
            age_unit=age_unit,
            sex_concept_id=(
                translator.to_local(sex_concept_id)
                if translator and sex_concept_id is not None
                else sex_concept_id
            ),
            setting=setting or SettingDeclaration(),
            prior_therapy_concept_ids=_translate_ids(
                prior_therapy_concept_ids, translator
            ),
            numeric_facts=tuple(numeric_facts),
            limitations=limitations,
        )


@dataclass(frozen=True)
class FitPolicy:
    assume_no_prior_therapy: bool = True
    allowed_context_concept_ids: frozenset[int] = frozenset(
        {
            35803480,
            35803496,
            35803514,
            35803584,
            35804409,
            35804597,
            35804141,
        }
    )


DEFAULT_POLICY = FitPolicy()


@dataclass(frozen=True)
class EdgeUsed:
    source_concept_id: int
    target_concept_id: int
    relationship_id: str
    review_status: str | None


@dataclass(frozen=True)
class CriterionResult:
    index: int
    dimension: str
    polarity: str
    status: CriterionStatus
    satisfied_alternative: tuple[int, ...] | None
    link_kinds: tuple[LinkKind, ...]
    reason: str


@dataclass(frozen=True)
class UnevaluatedCriterion:
    dimension: str
    concept_ids: tuple[int, ...]
    reason: str


@dataclass(frozen=True)
class FitResult:
    indication_concept_id: int
    status: FitStatus
    criteria: tuple[CriterionResult, ...]
    edges_used: tuple[EdgeUsed, ...]
    unevaluated: tuple[UnevaluatedCriterion, ...]
    vocabulary_version: VocabularyVersion
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class RegimenFitGroup:
    component_concept_id: int
    regimen_concept_id: int | None
    regulator_concept_ids: tuple[int, ...]
    indication_concept_ids: tuple[int, ...]

    @property
    def indication_count(self) -> int:
        return len(self.indication_concept_ids)


@dataclass(frozen=True)
class FitRegimensResult:
    fits: tuple[FitResult, ...]
    regimens: tuple[RegimenFitGroup, ...]
    components_only: tuple[RegimenFitGroup, ...]
    vocabulary_version: VocabularyVersion
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class _Criterion:
    dimension: str
    polarity: str
    alternatives: tuple[tuple[CriterionTerm, ...], ...]


@dataclass(frozen=True)
class _Indication:
    concept_id: int
    criteria: tuple[_Criterion, ...]
    components: tuple[int, ...]
    conditions: tuple[int, ...]
    regimens: tuple[int, ...]
    regulators: tuple[int, ...]
    contexts: tuple[int, ...]


@dataclass(frozen=True)
class _State:
    concept_id: int
    analytes: tuple[int, ...]
    variants: tuple[int, ...]
    results: tuple[int, ...]
    is_score: bool = False
    qualifiers: frozenset[str] = frozenset()


class _VocabularyIndex:
    def __init__(self, vocabulary: IndicationVocabulary) -> None:
        self.hierarchy = hierarchy_for(vocabulary)
        self.indications = {
            concept.concept_id: self._indication(vocabulary, concept.concept_id)
            for concept in vocabulary.concepts_of_class("Indication")
        }
        qualifiers: dict[int, set[str]] = defaultdict(set)
        for indication in self.indications.values():
            for criterion in indication.criteria:
                for alternative in criterion.alternatives:
                    for term in alternative:
                        if term.concept_id is not None and term.bounds is not None:
                            qualifiers[term.concept_id].add(
                                _normalise_source_value(term.bounds.qualifier)
                            )
        self.states = {
            concept.concept_id: self._state(
                vocabulary, concept.concept_id, qualifiers.get(concept.concept_id)
            )
            for concept in vocabulary.concepts_of_class("Biomarker State")
        }

    def _state(
        self,
        vocabulary: IndicationVocabulary,
        concept_id: int,
        qualifiers: set[str] | None,
    ) -> _State:
        return _State(
            concept_id,
            _related_ids(vocabulary, concept_id, "State has analyte"),
            _related_ids(vocabulary, concept_id, "State has variant"),
            _related_ids(vocabulary, concept_id, "State has result"),
            qualifiers is not None,
            frozenset(qualifiers or ()),
        )

    def _indication(
        self, vocabulary: IndicationVocabulary, concept_id: int
    ) -> _Indication:
        criteria = tuple(
            _Criterion(item.dimension.casefold(), item.polarity, item.alternatives)
            for item in vocabulary.criteria(concept_id)
        )
        return _Indication(
            concept_id,
            criteria,
            _related_ids(vocabulary, concept_id, "Ind has component"),
            _related_ids(vocabulary, concept_id, "Ind has condition"),
            _related_ids(vocabulary, concept_id, "Ind has regimen"),
            _related_ids(vocabulary, concept_id, "Ind has regulator"),
            _related_ids(vocabulary, concept_id, "Ind has context"),
        )


_INDEX_NAMESPACE = "indication-fit"
_DEFAULT_VOCABULARY: IndicationVocabulary | None = None


def _index_for(vocabulary: IndicationVocabulary) -> _VocabularyIndex:
    return cast(
        _VocabularyIndex,
        cached_instance_value(
            vocabulary, _INDEX_NAMESPACE, lambda: _VocabularyIndex(vocabulary)
        ),
    )


def clear_fit_cache(vocabulary: IndicationVocabulary | None = None) -> None:
    clear_instance_cache(vocabulary, _INDEX_NAMESPACE)


def _connector(vocabulary: IndicationVocabulary | None) -> IndicationVocabulary:
    global _DEFAULT_VOCABULARY
    if vocabulary is not None:
        return vocabulary
    if _DEFAULT_VOCABULARY is not None:
        return _DEFAULT_VOCABULARY
    from hemonc_alchemy.toolkit.core.indication_vocabulary.loader import (
        load_vocabulary,
    )

    _DEFAULT_VOCABULARY = load_vocabulary()
    return _DEFAULT_VOCABULARY


def _edges(
    vocabulary: IndicationVocabulary,
    concept_id: int,
    relationship_id: str | None = None,
) -> tuple[VocabularyRelationship, ...]:
    relationship_ids = (relationship_id,) if relationship_id else None
    return vocabulary.relationships(concept_id, relationship_ids, "out")


def _related_ids(
    vocabulary: IndicationVocabulary, concept_id: int, relationship_id: str
) -> tuple[int, ...]:
    return tuple(
        sorted(
            edge.concept_id_2
            for edge in _edges(vocabulary, concept_id, relationship_id)
        )
    )


def _translate_ids(
    concept_ids: Iterable[int], translator: ConceptIdTranslator | None
) -> tuple[int, ...]:
    return tuple(
        sorted(
            {
                translator.to_local(concept_id) if translator else concept_id
                for concept_id in concept_ids
            }
        )
    )


def _translate_measurement(
    measurement: BiomarkerMeasurement, translator: ConceptIdTranslator | None
) -> BiomarkerMeasurement:
    if translator is None:
        return measurement
    return replace(
        measurement,
        analyte_concept_id=(
            translator.to_local(measurement.analyte_concept_id)
            if measurement.analyte_concept_id is not None
            else None
        ),
        value_as_concept_id=(
            translator.to_local(measurement.value_as_concept_id)
            if measurement.value_as_concept_id is not None
            else None
        ),
        variant_concept_id=(
            translator.to_local(measurement.variant_concept_id)
            if measurement.variant_concept_id is not None
            else None
        ),
        unit_concept_id=(
            translator.to_local(measurement.unit_concept_id)
            if measurement.unit_concept_id is not None
            else None
        ),
    )


def _translate_state(
    state: PatientState, translator: ConceptIdTranslator | None
) -> PatientState:
    if translator is None:
        return state
    return replace(
        state,
        biomarker_measurements=tuple(
            _translate_measurement(item, translator)
            for item in state.biomarker_measurements
        ),
        biomarker_state_concept_ids=_translate_ids(
            state.biomarker_state_concept_ids, translator
        ),
        measurement_state_concept_ids=_translate_ids(
            state.measurement_state_concept_ids, translator
        ),
        observed_analyte_concept_ids=_translate_ids(
            state.observed_analyte_concept_ids, translator
        ),
        condition_concept_ids=_translate_ids(state.condition_concept_ids, translator),
        disease_extent_concept_ids=_translate_ids(
            state.disease_extent_concept_ids, translator
        ),
        disease_status_concept_ids=_translate_ids(
            state.disease_status_concept_ids, translator
        ),
        sex_concept_id=(
            translator.to_local(state.sex_concept_id)
            if state.sex_concept_id is not None
            else None
        ),
        prior_therapy_concept_ids=_translate_ids(
            state.prior_therapy_concept_ids, translator
        ),
        setting=replace(
            state.setting,
            prior_therapy_concept_ids=_translate_ids(
                state.setting.prior_therapy_concept_ids, translator
            ),
            context_concept_ids=_translate_ids(
                state.setting.context_concept_ids, translator
            ),
        ),
    )


def _normalise_unit(unit: str | None) -> str:
    if unit is None:
        return ""
    value = " ".join(unit.strip().casefold().split())
    aliases = {
        "year": "years",
        "yr": "years",
        "y": "years",
        "month": "months",
        "mo": "months",
        "d": "days",
        "day": "days",
        "unspecified": "years",
        "week": "weeks",
        "ng/ml": "ng/ml",
        "mutations/mb": "mut/mb",
        "mutation/mb": "mut/mb",
    }
    return aliases.get(value, value)


_TO_MONTHS = {"days": 1 / 30.4375, "weeks": 12 / 52.1775, "months": 1.0, "years": 12.0}


def _convert_value(value: float, from_unit: str, to_unit: str) -> float | None:
    source, target = _normalise_unit(from_unit), _normalise_unit(to_unit)
    if source == target:
        return value
    if source in _TO_MONTHS and target in _TO_MONTHS:
        return value * _TO_MONTHS[source] / _TO_MONTHS[target]
    return None


def _bounds_satisfied(bounds: ConceptBounds, value: float, unit: str) -> bool:
    converted = _convert_value(value, unit, bounds.unit)
    if converted is None:
        return False
    return all(
        _satisfies_bound(converted, bound)
        for bound in (bounds.lower, bounds.upper)
        if bound is not None
    )


def _satisfies_bound(value: float, bound) -> bool:
    compare = {
        "=": operator.eq,
        ">": operator.gt,
        ">=": operator.ge,
        "<": operator.lt,
        "<=": operator.le,
    }.get(bound.comparator)
    return compare is not None and compare(value, bound.value)


def _result_matches(
    value_concept_id: int,
    expected_result_id: int,
    vocabulary: IndicationVocabulary,
) -> bool:
    if value_concept_id == expected_result_id:
        return True
    hierarchy = hierarchy_for(vocabulary)
    return any(
        hierarchy.path(value_concept_id, expected_result_id, relationship_id)
        for relationship_id in ("Is a", "Clinically implies", "Equiv in indic")
    )


def _measurement_identity_matches(
    measurement: BiomarkerMeasurement, state: _State
) -> bool:
    if measurement.variant_concept_id is not None:
        return measurement.variant_concept_id in state.variants
    return (
        measurement.analyte_concept_id is not None
        and measurement.analyte_concept_id in state.analytes
    )


def _numeric_measurement_matches(
    measurement: BiomarkerMeasurement, state: _State
) -> bool:
    """A numeric result identifies a score state; the cut-off is checked on the criterion term."""
    if measurement.value_as_number is None or not state.is_score:
        return False
    if not measurement.qualifier or "" in state.qualifiers:
        return True
    return _normalise_source_value(measurement.qualifier) in state.qualifiers


def _measurement_matches_state(
    measurement: BiomarkerMeasurement,
    state: _State,
    vocabulary: IndicationVocabulary,
) -> bool:
    if measurement.value_as_number is not None:
        return _numeric_measurement_matches(measurement, state)
    if measurement.value_as_concept_id is None:
        return measurement.variant_concept_id is not None and bool(state.results)
    return any(
        _result_matches(measurement.value_as_concept_id, expected, vocabulary)
        for expected in state.results
    )


def _states_for_measurements(
    measurements: Sequence[BiomarkerMeasurement],
    vocabulary: IndicationVocabulary,
    index: _VocabularyIndex,
) -> set[int]:
    matched = set()
    for measurement in measurements:
        for state in index.states.values():
            if not _measurement_identity_matches(measurement, state):
                continue
            if _measurement_matches_state(measurement, state, vocabulary):
                matched.add(state.concept_id)
    return matched


def _path_match(
    fact_id: int,
    target_id: int,
    vocabulary: IndicationVocabulary,
) -> tuple[LinkKind, tuple[VocabularyRelationship, ...]] | None:
    if fact_id == target_id:
        return LinkKind.EQUAL, ()
    hierarchy = hierarchy_for(vocabulary)
    path = hierarchy.path(fact_id, target_id, "Is a")
    if path:
        return LinkKind.IS_A, path
    path = hierarchy.path(fact_id, target_id, "Clinically implies")
    if path:
        return LinkKind.CLINICALLY_IMPLIES, path
    path = hierarchy.path(fact_id, target_id, "Equiv in indic")
    if path:
        return LinkKind.EQUAL, path
    return None


def _opposite_path(
    fact_id: int, target_id: int, vocabulary: IndicationVocabulary
) -> tuple[VocabularyRelationship, ...] | None:
    hierarchy = hierarchy_for(vocabulary)
    return hierarchy.path(fact_id, target_id, "Opposite of") or hierarchy.path(
        target_id, fact_id, "Opposite of"
    )


def _normalise_source_value(value: str) -> str:
    return " ".join(value.casefold().replace("_", " ").split())


def _fact_ids(state: PatientState, dimension: str) -> tuple[int, ...]:
    if dimension == "biomarker":
        return state.measurement_state_concept_ids or state.biomarker_state_concept_ids
    if dimension == "sex":
        return (state.sex_concept_id,) if state.sex_concept_id is not None else ()
    if dimension in {"stage", "disease_extent"}:
        return (*state.disease_extent_concept_ids, *state.condition_concept_ids)
    if dimension in {
        "stage_or_status",
        "disease_status",
        "response_contingency",
        "status",
    }:
        return (*state.disease_status_concept_ids, *state.condition_concept_ids)
    if dimension in {"condition", "disease"}:
        return state.condition_concept_ids
    if dimension in {"prior_therapy", "prior_therapy_negation"}:
        return (
            *state.prior_therapy_concept_ids,
            *state.setting.prior_therapy_concept_ids,
        )
    if dimension in {
        "context",
        "treatment_context",
        "setting",
        "prior_therapy_setting",
    }:
        return state.setting.context_concept_ids
    return ()


def _has_prior_therapy(state: PatientState) -> bool:
    return bool(
        state.setting.has_prior_therapy
        or state.prior_therapy_concept_ids
        or state.setting.prior_therapy_concept_ids
        or state.setting.prior_line_count
    )


def _line_facts(
    state: PatientState, policy: FitPolicy
) -> tuple[tuple[float, str, str], ...]:
    """Prior lines of therapy: declared, at least one when any prior therapy is declared, else the policy default."""
    if state.setting.prior_line_count > 0:
        return ((float(state.setting.prior_line_count), "lines", ""),)
    if _has_prior_therapy(state):
        return ((1.0, "lines", ""),)
    if policy.assume_no_prior_therapy:
        return ((0.0, "lines", ""),)
    return ()


def _term_facts(
    state: PatientState,
    dimension: str,
    analytes: set[int],
    policy: FitPolicy,
) -> tuple[tuple[float, str, str], ...]:
    facts = [
        (fact.value, fact.unit, fact.qualifier)
        for fact in state.numeric_facts
        if fact.dimension == dimension
    ]
    if dimension == "age" and state.age_value is not None and state.age_unit:
        facts.append((state.age_value, state.age_unit, ""))
    if dimension == "biomarker":
        facts.extend(
            (item.value_as_number, item.unit or "", item.qualifier or "")
            for item in state.biomarker_measurements
            if item.value_as_number is not None and item.analyte_concept_id in analytes
        )
    if dimension in {"prior_therapy", "prior_therapy_setting"}:
        facts.extend(_line_facts(state, policy))
    if (
        dimension == "time_contingency"
        and state.setting.months_since_last_treatment is not None
    ):
        facts.append((state.setting.months_since_last_treatment, "months", ""))
    return tuple(facts)


def _scalar_outcome(
    bounds: ConceptBounds, facts: Sequence[tuple[float, str, str]]
) -> _TargetOutcome:
    relevant = [
        (value, unit)
        for value, unit, qualifier in facts
        if not bounds.qualifier
        or _normalise_source_value(qualifier)
        == _normalise_source_value(bounds.qualifier)
    ]
    if any(_bounds_satisfied(bounds, value, unit) for value, unit in relevant):
        return _TargetOutcome((LinkKind.EQUAL, ()), False, False)
    return _TargetOutcome(None, bool(relevant), not relevant)


def _concept_match(
    target_id: int,
    state: PatientState,
    dimension: str,
    vocabulary: IndicationVocabulary,
) -> tuple[LinkKind, tuple[VocabularyRelationship, ...]] | None:
    for fact_id in _fact_ids(state, dimension):
        match = _path_match(fact_id, target_id, vocabulary)
        if match:
            return match
    return None


@dataclass(frozen=True)
class _TargetOutcome:
    match: tuple[LinkKind, tuple[VocabularyRelationship, ...]] | None
    known_failure: bool
    unknown: bool
    opposite_edges: tuple[VocabularyRelationship, ...] = ()


@dataclass(frozen=True)
class _MatchContext:
    state: PatientState
    vocabulary: IndicationVocabulary
    policy: FitPolicy
    index: _VocabularyIndex
    observed_analytes: frozenset[int]


@dataclass(frozen=True)
class _AlternativeMatch:
    concepts: tuple[int, ...] | None = None
    link_kinds: tuple[LinkKind, ...] = ()
    edges: tuple[VocabularyRelationship, ...] = ()
    unknown: bool = False
    opposite_edges: tuple[VocabularyRelationship, ...] = ()


def _term_outcome(
    term: CriterionTerm, dimension: str, context: _MatchContext
) -> _TargetOutcome:
    state = context.state
    if term.concept_id is None:
        if term.bounds is None:
            return _TargetOutcome(None, False, True)
        facts = _term_facts(state, dimension, set(), context.policy)
        return _scalar_outcome(term.bounds, facts)
    outcome = _concept_outcome(term.concept_id, dimension, context)
    if term.bounds is None or outcome.match is None:
        return outcome
    analytes = set(
        _related_ids(context.vocabulary, term.concept_id, "State has analyte")
    )
    facts = _term_facts(state, dimension, analytes, context.policy)
    scalar = _scalar_outcome(term.bounds, facts)
    if scalar.match is None:
        return scalar
    return outcome


def _concept_outcome(
    target_id: int,
    dimension: str,
    context: _MatchContext,
) -> _TargetOutcome:
    state = context.state
    policy = context.policy
    match = _concept_match(target_id, state, dimension, context.vocabulary)
    if match:
        return _TargetOutcome(match, False, False)
    if dimension == "biomarker":
        return _biomarker_target_outcome(target_id, context)
    if dimension == "prior_therapy":
        known = _has_prior_therapy(state) or policy.assume_no_prior_therapy
        return _TargetOutcome(None, known, not known)
    known = (dimension == "age" and state.age_value is not None) or bool(
        _fact_ids(state, dimension)
    )
    return _TargetOutcome(None, known, not known)


def _biomarker_target_outcome(target_id: int, context: _MatchContext) -> _TargetOutcome:
    vocabulary = context.vocabulary
    state = context.state
    target_state = context.index.states.get(target_id)
    target_analytes = set(target_state.analytes) if target_state else set()
    known = bool(target_analytes & context.observed_analytes)
    patient_states = _fact_ids(state, "biomarker")
    explicit_unknown = any(
        _is_unknown_state(identifier, target_analytes, context)
        for identifier in patient_states
    )
    opposite_edges = tuple(
        edge
        for fact_id in patient_states
        for edge in (_opposite_path(fact_id, target_id, vocabulary) or ())
    )
    return _TargetOutcome(
        None,
        known and not explicit_unknown,
        not known or explicit_unknown,
        opposite_edges,
    )


def _is_unknown_state(
    concept_id: int, analytes: set[int], context: _MatchContext
) -> bool:
    concept = context.vocabulary.concept(concept_id)
    return bool(
        concept
        and concept.concept_name.casefold().endswith(": unknown")
        and set(_related_ids(context.vocabulary, concept_id, "State has analyte"))
        & analytes
    )


def _criterion_status(
    criterion: _Criterion,
    state: PatientState,
    vocabulary: IndicationVocabulary,
    policy: FitPolicy,
    index: _VocabularyIndex,
) -> tuple[
    CriterionStatus,
    tuple[int, ...] | None,
    tuple[LinkKind, ...],
    tuple[VocabularyRelationship, ...],
    str,
]:
    precheck = _criterion_precheck(criterion, state, vocabulary)
    if precheck is not None:
        return precheck
    observed_analytes = set(state.observed_analyte_concept_ids)
    for patient_state_id in _fact_ids(state, "biomarker"):
        observed_analytes.update(
            _related_ids(vocabulary, patient_state_id, "State has analyte")
        )
    context = _MatchContext(
        state, vocabulary, policy, index, frozenset(observed_analytes)
    )
    result = _match_alternatives(criterion, context)
    return _criterion_conclusion(criterion, state, policy, result)


def _criterion_precheck(
    criterion: _Criterion,
    state: PatientState,
    vocabulary: IndicationVocabulary,
) -> tuple[CriterionStatus, None, tuple[()], tuple[()], str] | None:
    dimension = criterion.dimension
    unsupported = {
        "ineligibility",
        "prior_biomarker",
        "prior_biomarker_status",
        "demographics",
        "with_field",
        "risk_stratification",
        "exposure_phenotype",
    }
    if dimension in unsupported:
        return (
            CriterionStatus.UNEVALUATED,
            None,
            (),
            (),
            f"No closed patient input for {dimension}.",
        )
    if dimension == "age" and state.age_value is None:
        return CriterionStatus.UNKNOWN, None, (), (), "Patient age is not stated."
    if (
        dimension == "age"
        and vocabulary.has_bounds
        and not any(
            term.bounds is not None
            for group in criterion.alternatives
            for term in group
        )
    ):
        return (
            CriterionStatus.UNEVALUATED,
            None,
            (),
            (),
            "Age criterion has no numeric bounds in this vocabulary.",
        )
    if dimension == "biomarker" and not _fact_ids(state, dimension):
        return CriterionStatus.UNKNOWN, None, (), (), "No biomarker state is available."
    return None


def _match_alternatives(
    criterion: _Criterion,
    context: _MatchContext,
) -> _AlternativeMatch:
    any_unknown = False
    opposite_edges: list[VocabularyRelationship] = []
    for alternative in criterion.alternatives:
        outcomes = tuple(
            _term_outcome(term, criterion.dimension, context) for term in alternative
        )
        if all(outcome.match is not None for outcome in outcomes):
            kinds = tuple(outcome.match[0] for outcome in outcomes if outcome.match)
            edges = tuple(
                edge
                for outcome in outcomes
                for edge in (outcome.match[1] if outcome.match else ())
            )
            concepts = tuple(
                sorted(term.concept_id for term in alternative if term.concept_id)
            )
            return _AlternativeMatch(
                concepts, kinds, edges, any_unknown, tuple(opposite_edges)
            )
        failed = any(outcome.known_failure for outcome in outcomes)
        any_unknown |= not failed and any(outcome.unknown for outcome in outcomes)
        opposite_edges.extend(
            edge for outcome in outcomes for edge in outcome.opposite_edges
        )
    return _AlternativeMatch(unknown=any_unknown, opposite_edges=tuple(opposite_edges))


def _criterion_conclusion(
    criterion: _Criterion,
    state: PatientState,
    policy: FitPolicy,
    match: _AlternativeMatch,
) -> tuple[
    CriterionStatus,
    tuple[int, ...] | None,
    tuple[LinkKind, ...],
    tuple[VocabularyRelationship, ...],
    str,
]:
    dimension = criterion.dimension
    if criterion.polarity == "excludes":
        if match.concepts is not None:
            return (
                CriterionStatus.FAILED,
                match.concepts,
                match.link_kinds,
                match.edges,
                "Excluded fact is present.",
            )
        if (
            dimension == "prior_therapy"
            and not _has_prior_therapy(state)
            and policy.assume_no_prior_therapy
        ):
            return (
                CriterionStatus.SATISFIED,
                None,
                (),
                (),
                "Default policy assumes no prior therapy.",
            )
        if match.unknown:
            return CriterionStatus.UNKNOWN, None, (), (), "Cannot establish absence."
        return CriterionStatus.SATISFIED, None, (), (), "Excluded fact is absent."
    if match.concepts is not None:
        return (
            CriterionStatus.SATISFIED,
            match.concepts,
            match.link_kinds,
            match.edges,
            "A listed alternative matches.",
        )
    if (
        dimension == "prior_therapy"
        and not _has_prior_therapy(state)
        and policy.assume_no_prior_therapy
    ):
        return (
            CriterionStatus.FAILED,
            None,
            (),
            (),
            "Default policy assumes no prior therapy.",
        )
    if (
        dimension in {"context", "treatment_context", "setting"}
        and state.setting.context_concept_ids
        and not set(policy.allowed_context_concept_ids).intersection(
            state.setting.context_concept_ids
        )
    ):
        return (
            CriterionStatus.FAILED,
            None,
            (),
            (),
            "Treatment context is outside the default policy.",
        )
    if match.unknown:
        return (
            CriterionStatus.UNKNOWN,
            None,
            (),
            (),
            "At least one listed alternative has missing patient facts.",
        )
    kinds = (LinkKind.OPPOSITE,) if match.opposite_edges else ()
    return (
        CriterionStatus.FAILED,
        None,
        kinds,
        match.opposite_edges,
        "Known patient facts do not meet any listed alternative.",
    )


def _edge_records(
    edges: Sequence[VocabularyRelationship], vocabulary: IndicationVocabulary
) -> tuple[EdgeUsed, ...]:
    unique = {
        (edge.concept_id_1, edge.concept_id_2, edge.relationship_id): EdgeUsed(
            edge.concept_id_1,
            edge.concept_id_2,
            edge.relationship_id,
            vocabulary.edge_review_status(
                edge.concept_id_1, edge.concept_id_2, edge.relationship_id
            )
            if vocabulary.has_review_status
            else None,
        )
        for edge in edges
    }
    return tuple(unique[key] for key in sorted(unique))


def _translate_result(
    result: FitResult, translator: ConceptIdTranslator | None
) -> FitResult:
    if translator is None:
        return result
    return replace(
        result,
        indication_concept_id=translator.to_real(result.indication_concept_id),
        criteria=tuple(
            replace(
                criterion,
                satisfied_alternative=(
                    tuple(
                        sorted(
                            translator.to_real(value)
                            for value in criterion.satisfied_alternative
                        )
                    )
                    if criterion.satisfied_alternative is not None
                    else None
                ),
            )
            for criterion in result.criteria
        ),
        edges_used=tuple(
            replace(
                edge,
                source_concept_id=translator.to_real(edge.source_concept_id),
                target_concept_id=translator.to_real(edge.target_concept_id),
            )
            for edge in result.edges_used
        ),
        unevaluated=tuple(
            replace(
                criterion,
                concept_ids=tuple(
                    sorted(translator.to_real(value) for value in criterion.concept_ids)
                ),
            )
            for criterion in result.unevaluated
        ),
    )


def _bounds_lack_unit_concept(indication: _Indication) -> bool:
    return any(
        term.bounds is not None and term.bounds.unit_concept_id is None
        for criterion in indication.criteria
        for alternative in criterion.alternatives
        for term in alternative
    )


def fits(
    state: PatientState,
    indication_concept_id: int,
    policy: FitPolicy = DEFAULT_POLICY,
    vocabulary: IndicationVocabulary | None = None,
    translator: ConceptIdTranslator | None = None,
) -> FitResult:
    """Evaluate one indication against the supplied patient facts."""
    connector = _connector(vocabulary)
    state = _translate_state(state, translator)
    local_id = (
        translator.to_local(indication_concept_id)
        if translator
        else indication_concept_id
    )
    index = _index_for(connector)
    indication = index.indications.get(local_id)
    if indication is None:
        raise ValueError(
            f"Concept {indication_concept_id} is not an indication in this vocabulary."
        )
    results = []
    edges: list[VocabularyRelationship] = []
    for number, criterion in enumerate(indication.criteria):
        status, alternative, kinds, used, reason = _criterion_status(
            criterion, state, connector, policy, index
        )
        results.append(
            CriterionResult(
                number,
                criterion.dimension,
                criterion.polarity,
                status,
                alternative,
                kinds,
                reason,
            )
        )
        edges.extend(used)
    if indication.contexts and not set(indication.contexts).intersection(
        policy.allowed_context_concept_ids
    ):
        results.append(
            CriterionResult(
                len(results),
                "treatment_context",
                "requires",
                CriterionStatus.FAILED,
                None,
                (),
                "Indication is limited to a context outside the default policy.",
            )
        )
    states = {item.status for item in results}
    fit_status: FitStatus = (
        FitStatus.NO_FIT
        if CriterionStatus.FAILED in states
        else (
            FitStatus.UNKNOWN
            if states & {CriterionStatus.UNKNOWN, CriterionStatus.UNEVALUATED}
            else FitStatus.FIT
        )
    )
    unevaluated = tuple(
        UnevaluatedCriterion(
            item.dimension,
            tuple(
                sorted(
                    {
                        term.concept_id
                        for group in indication.criteria[item.index].alternatives
                        for term in group
                        if term.concept_id is not None
                    }
                )
            ),
            item.reason,
        )
        for item in results
        if item.status == CriterionStatus.UNEVALUATED
        and item.index < len(indication.criteria)
    )
    limitations = list(state.limitations)
    if not connector.has_bounds:
        limitations.append("Vocabulary connector does not provide numeric bounds.")
    if not connector.has_review_status:
        limitations.append("Vocabulary connector does not provide review status.")
    if not connector.has_source_map:
        limitations.append("Vocabulary connector does not provide source mappings.")
    if _bounds_lack_unit_concept(indication):
        limitations.append(
            "Vocabulary numeric bounds provide unit text but no unit concept id."
        )
    result = FitResult(
        local_id,
        fit_status,
        tuple(results),
        _edge_records(edges, connector),
        unevaluated,
        connector.version(),
        tuple(dict.fromkeys(limitations)),
    )
    return _translate_result(result, translator)


def _condition_matches(
    indication_condition: int,
    conditions: Sequence[int],
    vocabulary: IndicationVocabulary,
) -> bool:
    return any(
        _path_match(condition, indication_condition, vocabulary)
        for condition in conditions
    )


def _group_fits(
    matches: Sequence[tuple[_Indication, FitResult]],
    translator: ConceptIdTranslator | None,
) -> tuple[tuple[RegimenFitGroup, ...], tuple[RegimenFitGroup, ...]]:
    regimen_groups: dict[tuple[int, int], list[int]] = defaultdict(list)
    component_groups: dict[int, list[int]] = defaultdict(list)
    regulators: dict[tuple[int, int | None], set[int]] = defaultdict(set)
    for indication, _ in matches:
        for component in indication.components:
            if indication.regimens:
                for regimen in indication.regimens:
                    regimen_groups[(component, regimen)].append(indication.concept_id)
                    regulators[(component, regimen)].update(indication.regulators)
            else:
                component_groups[component].append(indication.concept_id)
                regulators[(component, None)].update(indication.regulators)

    def make_group(key, ids):
        real_id = translator.to_real if translator else lambda value: value
        return RegimenFitGroup(
            real_id(key[0]),
            real_id(key[1]) if key[1] is not None else None,
            tuple(sorted(real_id(value) for value in regulators[key])),
            tuple(sorted(real_id(value) for value in set(ids))),
        )

    return (
        tuple(make_group(key, ids) for key, ids in sorted(regimen_groups.items())),
        tuple(
            make_group((key, None), ids)
            for key, ids in sorted(component_groups.items())
        ),
    )


def fit_regimens(
    state: PatientState,
    condition_concept_ids: Sequence[int],
    policy: FitPolicy = DEFAULT_POLICY,
    vocabulary: IndicationVocabulary | None = None,
    translator: ConceptIdTranslator | None = None,
) -> FitRegimensResult:
    """Return fitting indications grouped by regimen and by components alone."""
    connector = _connector(vocabulary)
    state = _translate_state(state, translator)
    conditions = _translate_ids(condition_concept_ids, translator)
    index = _index_for(connector)
    matched = []
    for indication in index.indications.values():
        if conditions and (
            not indication.conditions
            or not any(
                _condition_matches(value, conditions, connector)
                for value in indication.conditions
            )
        ):
            continue
        result = fits(state, indication.concept_id, policy, connector, translator)
        if result.status == FitStatus.FIT:
            matched.append((indication, result))
    regimen_groups, component_groups = _group_fits(matched, translator)
    return FitRegimensResult(
        tuple(result for _, result in matched),
        regimen_groups,
        component_groups,
        connector.version(),
        tuple(
            dict.fromkeys(
                limit for _, result in matched for limit in result.limitations
            )
        ),
    )


__all__ = [
    "BiomarkerMeasurement",
    "CriterionResult",
    "CriterionStatus",
    "EdgeUsed",
    "FitPolicy",
    "FitRegimensResult",
    "FitResult",
    "FitStatus",
    "LinkKind",
    "NumericFact",
    "PatientState",
    "RegimenFitGroup",
    "SettingDeclaration",
    "UnevaluatedCriterion",
    "clear_fit_cache",
    "fit_regimens",
    "fits",
]
