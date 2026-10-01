"""Classifying a regimen variant or cycle block by drug `main_class` ancestry.

A variant or block counts as endocrine or supportive-care only when *every*
drug it carries resolves to that ancestry -- see `generated.py` for how the
`main_class` sets themselves are derived.
"""

from __future__ import annotations

from .generated import ENDOCRINE_MAIN_CLASSES, SUPPORTIVE_MAIN_CLASSES


def _drug_main_classes(drug_bearing) -> frozenset[str]:
    """The distinct `main_class` values among items each exposing `drug_object` (sigs or `ScheduleEvent`s)."""
    return frozenset(
        drug.main_class
        for item in drug_bearing
        if (drug := item.drug_object) is not None and drug.main_class is not None
    )


def _component_drug_main_classes(variant) -> frozenset[str]:
    """The distinct `main_class` values of a variant's component drugs."""
    return _drug_main_classes(variant.component_sigs)


def _is_pure(classes: frozenset[str], allowed: frozenset[str]) -> bool:
    return bool(classes) and classes <= allowed


def is_endocrine_regimen(variant) -> bool:
    """Whether a variant's drugs are entirely endocrine therapy (GnRH analogs, antiandrogens, aromatase inhibitors, etc)."""
    return _is_pure(_component_drug_main_classes(variant), ENDOCRINE_MAIN_CLASSES)


def is_supportive_regimen(variant) -> bool:
    """Whether a variant's drugs are entirely supportive-care growth factors (G-CSF, EPO, TPO-RA, etc)."""
    return _is_pure(_component_drug_main_classes(variant), SUPPORTIVE_MAIN_CLASSES)


def is_endocrine_block(events) -> bool:
    """Whether one cycle block's own drugs are entirely endocrine therapy."""
    return _is_pure(_drug_main_classes(events), ENDOCRINE_MAIN_CLASSES)


def is_supportive_block(events) -> bool:
    """Whether one cycle block's own drugs are entirely supportive-care growth factors."""
    return _is_pure(_drug_main_classes(events), SUPPORTIVE_MAIN_CLASSES)
