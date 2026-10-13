"""Contract tests for matching patient facts against an indication vocabulary."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import replace

import pytest

from hemonc_alchemy.toolkit.analytics.treatment.indication_fit import (
    BiomarkerMeasurement,
    CoTherapyMode,
    CriterionStatus,
    FitPolicy,
    FitStatus,
    PatientState,
    SettingDeclaration,
    fit_regimens,
    fits,
)
from hemonc_alchemy.toolkit.core.indication_vocabulary import (
    ConceptBounds,
    ConceptIdTranslator,
    CriterionTerm,
    VocabularyConcept,
    VocabularyCriterion,
    VocabularyVersion,
    hierarchy_for,
    load_vocabulary,
)


@pytest.fixture(scope="module", params=(load_vocabulary,))
def vocabulary(request):
    return request.param()


def local_id(vocabulary, code):
    concept = vocabulary.concept_by_code("HemOnc Local", code)
    assert concept is not None
    return concept.concept_id


def source_target(vocabulary, source_column, raw_value, context=None):
    match = vocabulary.concept_for_source(source_column, raw_value, context)
    return match.target_concept_id if match else None


def state_for(vocabulary, *codes):
    return PatientState(
        biomarker_state_concept_ids=tuple(local_id(vocabulary, code) for code in codes)
    )


def criterion_for(result, dimension):
    return next(item for item in result.criteria if item.dimension == dimension)


@pytest.mark.parametrize(
    ("indication", "findings"),
    [
        (
            "HOL-IND-201",
            ("HOL-BST-HER2-negative", "HOL-BST-ER-negative", "HOL-BST-PR-negative"),
        ),
    ],
)
def test_three_negative_breast_criteria_are_anded(vocabulary, indication, findings):
    state = state_for(vocabulary, *findings)
    result = fits(state, local_id(vocabulary, indication), vocabulary=vocabulary)
    assert result.status is FitStatus.FIT
    assert len([item for item in result.criteria if item.dimension == "biomarker"]) == 3
    assert all(item.status is CriterionStatus.SATISFIED for item in result.criteria)


def test_unknown_biomarker_and_definite_failure_are_distinct(vocabulary):
    indication = local_id(vocabulary, "HOL-IND-201")
    missing = fits(PatientState(), indication, vocabulary=vocabulary)
    assert missing.status is FitStatus.UNKNOWN
    assert all(item.status is CriterionStatus.UNKNOWN for item in missing.criteria)

    conflicting = state_for(vocabulary, "HOL-BST-HER2-positive")
    failed = fits(conflicting, indication, vocabulary=vocabulary)
    assert failed.status is FitStatus.NO_FIT

    explicit_unknown = fits(
        state_for(vocabulary, "HOL-BST-ER-unknown"), indication, vocabulary=vocabulary
    )
    er = next(item for item in explicit_unknown.criteria if item.index == 0)
    assert er.status is CriterionStatus.UNKNOWN
    assert explicit_unknown.status is FitStatus.UNKNOWN


def test_mmr_msi_sets_keep_their_or_and_structure(vocabulary):
    deficient = state_for(vocabulary, "HOL-BST-MMR-deficient")
    deficient_result = fits(
        deficient, local_id(vocabulary, "HOL-IND-964"), vocabulary=vocabulary
    )
    assert (
        criterion_for(deficient_result, "biomarker").status is CriterionStatus.SATISFIED
    )
    assert criterion_for(deficient_result, "biomarker").satisfied_alternative == (
        local_id(vocabulary, "HOL-BST-MMR-deficient"),
    )

    combined = state_for(vocabulary, "HOL-BST-MMR-proficient", "HOL-BST-MSI-not-high")
    result = fits(combined, local_id(vocabulary, "HOL-IND-1580"), vocabulary=vocabulary)
    biomarker = criterion_for(result, "biomarker")
    assert biomarker.status is CriterionStatus.SATISFIED
    assert len(biomarker.satisfied_alternative or ()) == 2


def test_positive_or_unknown_er_pr_are_independent_alternatives(vocabulary):
    state = state_for(vocabulary, "HOL-BST-ER-positive")
    result = fits(state, local_id(vocabulary, "HOL-IND-110"), vocabulary=vocabulary)
    assert criterion_for(result, "biomarker").status is CriterionStatus.SATISFIED

    unknown = state_for(vocabulary, "HOL-BST-ER-unknown")
    unknown_result = fits(
        unknown, local_id(vocabulary, "HOL-IND-110"), vocabulary=vocabulary
    )
    assert criterion_for(unknown_result, "biomarker").satisfied_alternative == (
        local_id(vocabulary, "HOL-BST-ER-unknown"),
    )


@pytest.mark.parametrize(
    ("indication_code", "variant_id", "link_kind"),
    [
        ("HOL-IND-45", 19478184, "CLINICALLY_IMPLIES"),
        ("HOL-IND-45", 35976971, "CLINICALLY_IMPLIES"),
        ("HOL-IND-47", 19478184, "IS_A"),
        ("HOL-IND-193", 19596981, "IS_A"),
    ],
)
def test_variant_measurements_roll_up_to_indication_classes(
    vocabulary, indication_code, variant_id, link_kind
):
    from hemonc_alchemy.toolkit.analytics.treatment.indication_fit import (
        BiomarkerMeasurement,
    )

    state = PatientState.from_measurements(
        (BiomarkerMeasurement(None, variant_concept_id=variant_id),),
        vocabulary=vocabulary,
    )
    result = fits(state, local_id(vocabulary, indication_code), vocabulary=vocabulary)
    criterion = criterion_for(result, "biomarker")
    assert criterion.status is CriterionStatus.SATISFIED
    assert link_kind in {kind.value for kind in criterion.link_kinds}


def test_numeric_tps_sixty_percent_meets_lower_thresholds(vocabulary):
    analyte = source_target(vocabulary, "biomarker", "PD-L1")
    assert analyte is not None
    state = PatientState.from_measurements(
        (BiomarkerMeasurement(analyte, value_as_number=60, unit="%", qualifier="TPS"),),
        vocabulary=vocabulary,
    )
    codes = {
        vocabulary.concept(identifier).concept_code
        for identifier in state.biomarker_state_concept_ids
    }
    assert "HOL-BST-PD-L1-score-tps" in codes
    indication = local_id(vocabulary, "HOL-IND-203")
    result = fits(state, indication, vocabulary=vocabulary)
    assert any("unit concept id" in limitation for limitation in result.limitations)
    assert criterion_for(result, "biomarker").status is CriterionStatus.SATISFIED

    below = PatientState.from_measurements(
        (BiomarkerMeasurement(analyte, value_as_number=20, unit="%", qualifier="TPS"),),
        vocabulary=vocabulary,
    )
    assert (
        criterion_for(
            fits(below, indication, vocabulary=vocabulary), "biomarker"
        ).status
        is CriterionStatus.FAILED
    )

    other_assay = PatientState.from_measurements(
        (BiomarkerMeasurement(analyte, value_as_number=60, unit="%", qualifier="CPS"),),
        vocabulary=vocabulary,
    )
    assert (
        criterion_for(
            fits(other_assay, indication, vocabulary=vocabulary), "biomarker"
        ).status
        is not CriterionStatus.SATISFIED
    )


def test_numeric_age_bounds_convert_months_and_years(vocabulary):
    from hemonc_alchemy.toolkit.analytics.treatment.indication_fit import (
        _bounds_satisfied,
    )
    from hemonc_alchemy.toolkit.core.indication_vocabulary import ConceptBounds

    bounds = ConceptBounds("", ">=", 18, "", None, "years")
    assert _bounds_satisfied(bounds, 240, "months")


def test_edges_used_surface_proposal_review_status(vocabulary):
    her2_negative = local_id(vocabulary, "HOL-BST-HER2-negative")
    detailed = hierarchy_for(vocabulary).descendants(her2_negative)
    state = PatientState(biomarker_state_concept_ids=(detailed[0],))
    result = fits(state, local_id(vocabulary, "HOL-IND-201"), vocabulary=vocabulary)
    assert result.edges_used
    assert all(edge.review_status == "proposed" for edge in result.edges_used)


def test_opposite_biomarker_fails_with_its_evidence_edge(vocabulary):
    indication = local_id(vocabulary, "HOL-IND-201")
    result = fits(
        state_for(vocabulary, "HOL-BST-HER2-positive"),
        indication,
        vocabulary=vocabulary,
    )
    (her2,) = [
        item for item in result.criteria if item.status is CriterionStatus.FAILED
    ]
    assert her2.status is CriterionStatus.FAILED
    assert "OPPOSITE" in {kind.value for kind in her2.link_kinds}
    assert any(edge.relationship_id == "Opposite of" for edge in result.edges_used)


def test_ind_excludes_uses_default_no_prior_therapy_policy(vocabulary):
    indication = local_id(vocabulary, "HOL-IND-17")
    no_prior = fits(PatientState(), indication, vocabulary=vocabulary)
    excluded = next(item for item in no_prior.criteria if item.polarity == "excludes")
    assert excluded.status is CriterionStatus.SATISFIED

    prior = PatientState(
        setting=SettingDeclaration(has_prior_therapy=True),
        prior_therapy_concept_ids=(35803401,),
    )
    with_prior = fits(prior, indication, vocabulary=vocabulary)
    excluded = next(item for item in with_prior.criteria if item.polarity == "excludes")
    assert excluded.status is CriterionStatus.FAILED


# One more drug-level fit than before: a tumour-agnostic indication for a malignant neoplasm now applies to lung cancer through the condition hierarchy.
def test_nsclc_patient_snapshot_counts_are_stable(vocabulary):
    lung = 42542211
    pd_l1 = source_target(vocabulary, "biomarker", "PD-L1")
    assert pd_l1 is not None
    driver_negative = tuple(
        identifier
        for gene, finding in (
            ("EGFR", "wild-type"),
            ("ALK", "negative"),
            ("ROS1", "negative"),
            ("BRAF", "wild-type"),
            ("KRAS", "wild-type"),
        )
        if (identifier := source_target(vocabulary, "biomarker_finding", finding, gene))
        is not None
    )
    patients = (
        PatientState.from_measurements(
            (BiomarkerMeasurement(None, variant_concept_id=35976971),),
            vocabulary=vocabulary,
            condition_concept_ids=(lung,),
        ),
        PatientState.from_measurements(
            (
                BiomarkerMeasurement(
                    source_target(vocabulary, "biomarker", "ALK"),
                    value_as_concept_id=9191,
                ),
            ),
            vocabulary=vocabulary,
            condition_concept_ids=(lung,),
        ),
        PatientState.from_measurements(
            (BiomarkerMeasurement(None, variant_concept_id=35977097),),
            vocabulary=vocabulary,
            condition_concept_ids=(lung,),
        ),
        PatientState.from_measurements(
            (BiomarkerMeasurement(None, variant_concept_id=19596981),),
            vocabulary=vocabulary,
            condition_concept_ids=(lung,),
        ),
        PatientState.from_measurements(
            (BiomarkerMeasurement(None, variant_concept_id=19566395),),
            vocabulary=vocabulary,
            condition_concept_ids=(lung,),
        ),
        PatientState.from_measurements(
            (
                BiomarkerMeasurement(
                    pd_l1, value_as_number=60, unit="%", qualifier="TPS"
                ),
            ),
            vocabulary=vocabulary,
            condition_concept_ids=(lung,),
        ),
    )
    patients = (
        *patients[:-1],
        replace(
            patients[-1],
            biomarker_state_concept_ids=tuple(
                sorted(
                    set(patients[-1].biomarker_state_concept_ids) | set(driver_negative)
                )
            ),
            measurement_state_concept_ids=tuple(
                sorted(
                    set(patients[-1].measurement_state_concept_ids)
                    | set(driver_negative)
                )
            ),
        ),
    )
    snapshot = tuple(
        (
            len(result.fits),
            len(result.regimens),
            len(result.components_only),
        )
        for state in patients
        for result in (fit_regimens(state, (lung,), vocabulary=vocabulary),)
    )
    assert snapshot == (
        (21, 0, 18),
        (21, 0, 18),
        (20, 0, 17),
        (20, 0, 17),
        (20, 0, 17),
        (20, 0, 17),
    )


def test_concept_id_translator_preserves_fit_result(vocabulary):
    state_id = local_id(vocabulary, "HOL-BST-HER2-negative")
    indication = local_id(vocabulary, "HOL-IND-201")
    original = PatientState(biomarker_state_concept_ids=(state_id,))
    remapped = replace(original, biomarker_state_concept_ids=(9_000_000_001,))
    translator = ConceptIdTranslator({state_id: 9_000_000_001})
    expected = fits(original, indication, vocabulary=vocabulary)
    actual = fits(remapped, indication, vocabulary=vocabulary, translator=translator)
    translated_expected = replace(
        expected,
        criteria=tuple(
            replace(
                criterion,
                satisfied_alternative=(
                    tuple(
                        translator.to_real(value)
                        for value in criterion.satisfied_alternative
                    )
                    if criterion.satisfied_alternative is not None
                    else None
                ),
            )
            for criterion in expected.criteria
        ),
    )
    assert actual == translated_expected


class _TinyVocabulary:
    __hash__ = None

    has_bounds = True
    has_source_map = False
    has_review_status = False

    def __init__(self):
        self._concepts = {
            1: VocabularyConcept(
                1, "one", "Indication", "test", "Indication", "", "i1", "", ""
            ),
            4: VocabularyConcept(
                4, "state", "Measurement", "test", "Biomarker State", "", "b1", "", ""
            ),
        }
        self._criteria = (
            VocabularyCriterion(1, "biomarker", "requires", ((CriterionTerm(4),),)),
            VocabularyCriterion(
                1,
                "age",
                "requires",
                (
                    (
                        CriterionTerm(
                            None, ConceptBounds("", ">=", 18, "", None, "years")
                        ),
                    ),
                ),
            ),
        )

    def concept(self, concept_id):
        return self._concepts.get(concept_id)

    def concept_by_code(self, vocabulary_id, code):
        return None

    def concepts_of_class(self, concept_class_id):
        return tuple(
            item
            for item in self._concepts.values()
            if item.concept_class_id == concept_class_id
        )

    def relationships(self, concept_id, relationship_ids=None, direction="out"):
        return ()

    def criteria(self, indication_id):
        return self._criteria if indication_id == 1 else ()

    def concept_for_source(self, source_column, raw_value, context=None):
        return None

    def version(self):
        return VocabularyVersion("test", "1", len(self._concepts))

    def review_status(self, concept_id):
        return None

    def edge_review_status(self, concept_id_1, concept_id_2, relationship_id):
        return None


def test_evaluator_uses_only_the_vocabulary_protocol():
    result = fits(
        PatientState(
            biomarker_state_concept_ids=(4,), age_value=240, age_unit="months"
        ),
        1,
        vocabulary=_TinyVocabulary(),
    )
    assert result.status is FitStatus.FIT


def test_import_does_not_load_tsv_data():
    script = (
        "from hemonc_alchemy.toolkit.core.indication_vocabulary import loader; "
        "loader.load_vocabulary = lambda: (_ for _ in ()).throw(AssertionError()); "
        "import hemonc_alchemy.toolkit.analytics.treatment.indication_fit"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


class _AgeGroupVocabulary(_TinyVocabulary):
    def __init__(self):
        super().__init__()
        self._concepts[8] = VocabularyConcept(
            8, "Adult", "Observation", "test", "Population Qualifier", "", "q1", "", ""
        )
        self._criteria = (
            VocabularyCriterion(1, "age", "requires", ((CriterionTerm(8),),)),
        )


@pytest.mark.parametrize(
    ("age", "unit", "policy", "expected"),
    [
        (240, "months", FitPolicy(), FitStatus.FIT),
        (17, "years", FitPolicy(), FitStatus.NO_FIT),
        (None, None, FitPolicy(), FitStatus.UNKNOWN),
        (19, "years", FitPolicy(adult_min_age_years=21), FitStatus.NO_FIT),
        (19, "years", FitPolicy(adult_min_age_years=16), FitStatus.FIT),
    ],
)
def test_adult_group_is_evaluated_against_the_policy_age(age, unit, policy, expected):
    state = PatientState(age_value=age, age_unit=unit)
    result = fits(state, 1, policy, vocabulary=_AgeGroupVocabulary())
    assert result.status is expected
    assert not result.unevaluated


def test_fit_regimens_also_returns_the_unknown_indications(vocabulary):
    lung = 42542211
    state = PatientState.from_measurements(
        (BiomarkerMeasurement(None, variant_concept_id=35976971),),
        vocabulary=vocabulary,
        condition_concept_ids=(lung,),
        age_value=60,
        age_unit="years",
    )
    result = fit_regimens(state, (lung,), vocabulary=vocabulary)
    assert result.fits and result.unknown_fits
    assert all(item.status is FitStatus.FIT for item in result.fits)
    assert all(item.status is FitStatus.UNKNOWN for item in result.unknown_fits)
    assert {item.indication_concept_id for item in result.fits}.isdisjoint(
        item.indication_concept_id for item in result.unknown_fits
    )
    grouped = {
        indication
        for group in (*result.unknown_regimens, *result.unknown_components_only)
        for indication in group.indication_concept_ids
    }
    assert grouped == {item.indication_concept_id for item in result.unknown_fits}


def test_co_therapy_is_reported_by_default_and_matched_on_request(vocabulary):
    indication = local_id(vocabulary, "HOL-IND-92")
    carboplatin, pemetrexed = (
        term.concept_id
        for criterion in vocabulary.criteria(indication)
        if criterion.dimension == "with_field"
        for term in criterion.alternatives[0]
    )
    state = PatientState()

    reported = fits(state, indication, vocabulary=vocabulary)
    assert criterion_for(reported, "with_field").status is CriterionStatus.SATISFIED
    assert reported.co_therapy_requirements == (
        tuple(sorted((carboplatin, pemetrexed))),
    )

    match = FitPolicy(co_therapy=CoTherapyMode.MATCH)
    unknown = fits(state, indication, match, vocabulary=vocabulary)
    assert criterion_for(unknown, "with_field").status is CriterionStatus.UNKNOWN
    given = fits(
        replace(state, co_therapy_concept_ids=(carboplatin, pemetrexed)),
        indication,
        match,
        vocabulary=vocabulary,
    )
    assert criterion_for(given, "with_field").status is CriterionStatus.SATISFIED
    alone = fits(
        replace(state, co_therapy_concept_ids=()),
        indication,
        match,
        vocabulary=vocabulary,
    )
    assert criterion_for(alone, "with_field").status is CriterionStatus.FAILED


def test_monotherapy_term_matches_only_a_declared_absence_of_co_therapy(vocabulary):
    indication = local_id(vocabulary, "HOL-IND-203")
    match = FitPolicy(co_therapy=CoTherapyMode.MATCH)
    for given, expected in (
        (None, CriterionStatus.UNKNOWN),
        ((), CriterionStatus.SATISFIED),
        ((35802856,), CriterionStatus.FAILED),
    ):
        result = fits(
            PatientState(co_therapy_concept_ids=given),
            indication,
            match,
            vocabulary=vocabulary,
        )
        assert criterion_for(result, "with_field").status is expected


def test_a_more_specific_patient_condition_matches_the_broader_indications(vocabulary):
    lung, egfr_lung = 42542211, 42542290
    findings = (BiomarkerMeasurement(None, variant_concept_id=35976971),)

    def run(condition):
        state = PatientState.from_measurements(
            findings,
            vocabulary=vocabulary,
            condition_concept_ids=(condition,),
            age_value=60,
            age_unit="years",
        )
        return fit_regimens(state, (condition,), vocabulary=vocabulary)

    parent, child = run(lung), run(egfr_lung)
    assert child.fits and child.unknown_fits
    assert {item.indication_concept_id for item in parent.fits} <= {
        item.indication_concept_id for item in child.fits
    }
