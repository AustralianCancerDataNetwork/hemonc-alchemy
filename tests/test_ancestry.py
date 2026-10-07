"""Runtime whole-class ancestry rules and drug-only purity."""

from types import SimpleNamespace as NS

import pytest

from hemonc_alchemy.model.enums import Sigs_Class_fieldEnum
from hemonc_alchemy.toolkit.analytics.treatment.classification import (
    DrugAncestry,
    compute_main_class_ancestry,
    is_endocrine_block,
    is_endocrine_regimen,
    is_supportive_block,
)
from hemonc_alchemy.toolkit.analytics.treatment.classification.ancestry import (
    ENDOCRINE_ROOT_CUI,
    SUPPORTIVE_ROOT_CUI,
)


@pytest.fixture
def ancestry():
    return compute_main_class_ancestry(
        {
            "Endocrine": (1, 2), "Supportive": (3,), "Other": (4,),
            "Incomplete": (5, 6), "Inconsistent": (7, 8), "Excluded": (9,),
        },
        (
            ("10", ENDOCRINE_ROOT_CUI, "Component Class"),
            ("11", SUPPORTIVE_ROOT_CUI, "Component Class"),
            ("1", "10", "Component Class"), ("2", "10", "Component Class"),
            ("3", "11", "Component Class"), ("4", "12", "Component Class"),
            ("5", "10", "Component Class"),
            ("7", "10", "Component Class"), ("8", "12", "Component Class"),
            ("9", "45523", "Component Class"),
            ("45523", ENDOCRINE_ROOT_CUI, "Component Class"),
            # A cycle in the class graph cannot prevent closure termination.
            (ENDOCRINE_ROOT_CUI, "10", "Component Class"),
        ),
        available_roots=(ENDOCRINE_ROOT_CUI, SUPPORTIVE_ROOT_CUI),
    )


@pytest.mark.parametrize("main_class,status", [
    ("Endocrine", DrugAncestry.ENDOCRINE), ("Supportive", DrugAncestry.SUPPORTIVE),
    ("Other", DrugAncestry.OTHER), ("Incomplete", DrugAncestry.UNRESOLVED),
    ("Inconsistent", DrugAncestry.INCONSISTENT), ("Excluded", DrugAncestry.UNRESOLVED),
])
def test_whole_group_classification(ancestry, main_class, status):
    assert ancestry.resolutions[main_class].status is status


def test_missing_and_excluded_targets_remain_visible(ancestry):
    assert ancestry.resolutions["Incomplete"].component_cuis == {5, 6}
    assert ancestry.resolutions["Incomplete"].unresolved_cuis == {6}
    assert ancestry.resolutions["Excluded"].unresolved_cuis == {9}


@pytest.mark.parametrize("classes,expected", [
    ({"Endocrine"}, True), ({"Other"}, False), ({"Supportive"}, False),
    ({"Incomplete"}, None), ({"Inconsistent"}, False), ({None}, None),
    ({"Endocrine", None}, None), ({"Endocrine", "Unrecorded"}, None),
    ({"Other", None}, False), (set(), False),
])
def test_purity_preserves_unknown_evidence(ancestry, classes, expected):
    assert ancestry.purity(classes, DrugAncestry.ENDOCRINE) is expected


def test_missing_roots_are_explicit():
    index = compute_main_class_ancestry({"Endocrine": (1,)}, (), available_roots=())
    assert ENDOCRINE_ROOT_CUI in index.unavailable_reason
    assert SUPPORTIVE_ROOT_CUI in index.unavailable_reason
    assert index.purity({"Endocrine"}, DrugAncestry.ENDOCRINE) is None


def test_empty_group_cannot_be_vacuously_classified():
    index = compute_main_class_ancestry(
        {"Empty": ()}, (), available_roots=(ENDOCRINE_ROOT_CUI, SUPPORTIVE_ROOT_CUI),
    )
    assert index.resolutions["Empty"].status is DrugAncestry.UNRESOLVED


def test_pure_predicates_support_detached_objects_and_generators(ancestry):
    endocrine = NS(drug_object=NS(main_class="Endocrine"))
    supportive = NS(drug_object=NS(main_class="Supportive"))
    variant = NS(component_sigs=[endocrine])
    assert is_endocrine_regimen(variant, ancestry=ancestry) is True
    assert is_endocrine_block(iter([endocrine]), ancestry=ancestry) is True
    assert is_supportive_block(iter([supportive]), ancestry=ancestry) is True
    assert is_endocrine_regimen(variant) is None


@pytest.mark.parametrize("sig_class,expected", [
    (Sigs_Class_fieldEnum.IV_INTERMITTENT_CANONICAL_SIG, None),
    (Sigs_Class_fieldEnum.IV_CONTINUOUS_CANONICAL_SIG, None),
    (Sigs_Class_fieldEnum.NON_TO_IV_CANONICAL_SIG, None),
    (Sigs_Class_fieldEnum.RAD_SIG, True),
    (Sigs_Class_fieldEnum.NON_TO_CANONICAL_SIG, True),
])
def test_missing_drug_record_respects_instruction_kind(ancestry, sig_class, expected):
    endocrine = NS(drug_object=NS(main_class="Endocrine"))
    sig = NS(drug_object=None, class_field=sig_class)
    assert is_endocrine_regimen(NS(component_sigs=[endocrine, sig]), ancestry=ancestry) is expected
    event = NS(drug_object=None, sig=sig)
    assert is_endocrine_block([endocrine, event], ancestry=ancestry) is expected


def test_unknown_drug_class_prevents_pure_regimen_and_block(ancestry):
    items = [NS(drug_object=NS(main_class="Endocrine")), NS(drug_object=NS(main_class=None))]
    assert is_endocrine_regimen(NS(component_sigs=items), ancestry=ancestry) is None
    assert is_endocrine_block(items, ancestry=ancestry) is None
