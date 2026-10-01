"""Classifying a regimen variant by treatment modality.

HemOnc records radiotherapy as a sig like any other, distinguished by its
`class` field. So whether a variant is radiotherapy alone, systemic therapy
alone, or the two given together is read off its component sigs.
"""

from __future__ import annotations

from ....model.enums import Sigs_Class_fieldEnum

RAD_SIG_CLASS_VALUE = Sigs_Class_fieldEnum.RAD_SIG


def sig_class_value(sig_or_value):
    value = getattr(sig_or_value, "class_field", sig_or_value)
    if isinstance(value, Sigs_Class_fieldEnum):
        return value
    if value is None:
        return None
    try:
        return Sigs_Class_fieldEnum(str(value).strip().lower())
    except ValueError:
        return None


def has_radiation_sig(variant) -> bool:
    """Whether any of a variant's component sigs are a radiation sig."""
    return any(sig_class_value(sig) == RAD_SIG_CLASS_VALUE for sig in variant.component_sigs)


def has_non_radiation_sig(variant) -> bool:
    """Whether any *classified* component sig is not a radiation sig.

    Sigs with a NULL or unknown class are unclassified, not systemic therapy.
    This avoids reporting concurrent chemoradiotherapy based on an unknown
    classification.
    """
    return any(
        (value := sig_class_value(sig)) is not None
        and value != RAD_SIG_CLASS_VALUE
        for sig in variant.component_sigs
    )


def _has_unclassified_sig(variant) -> bool:
    return any(sig_class_value(sig) is None for sig in variant.component_sigs)


def is_concurrent_chemort(variant) -> bool:
    """Whether a variant mixes radiation and non-radiation sigs (concurrent chemoradiotherapy)."""
    return has_radiation_sig(variant) and has_non_radiation_sig(variant)


def is_rt_only(variant) -> bool:
    """Whether a variant is confidently radiation-only.

    An unclassified sig makes the answer unknown, rather than treating it as
    evidence of either radiation or systemic treatment.
    """
    return (
        has_radiation_sig(variant)
        and not has_non_radiation_sig(variant)
        and not _has_unclassified_sig(variant)
    )


GNRH_MAIN_CLASSES = frozenset(
    {
        "GnRH agonist",
        "GnRH antagonist",
        "First-generation nonsteroidal antiandrogen",
    }
)

HORMONE_MAIN_CLASSES = frozenset(
    {
        "Aromatase inhibitor first generation",
        "Aromatase inhibitor second generation",
        "Aromatase inhibitor third generation",
        "Second-generation nonsteroidal antiandrogen",
        "Antiandrogen",
        "Estrogen receptor inhibitor",
        "Estrogen replacement therapy",
        "Selective estrogen receptor modulator",
    }
)

SUPPORTIVE_MAIN_CLASSES = frozenset(
    {
        "Megakaryocyte growth factor",
        "Erythrocyte growth factor",
        "Granulocyte colony-stimulating factor",
        "Somatostatin analog",
        "IL-1R antagonist",
        "Anti-IL-6R antibody",
    }
)


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


def is_gnrh_regimen(variant) -> bool:
    """Whether a variant's drugs are entirely GnRH agonists/antagonists or first-generation antiandrogens."""
    return _is_pure(_component_drug_main_classes(variant), GNRH_MAIN_CLASSES)


def is_hormone_regimen(variant) -> bool:
    """Whether a variant's drugs are entirely endocrine therapy, but not purely GnRH-class."""
    classes = _component_drug_main_classes(variant)
    return _is_pure(classes, GNRH_MAIN_CLASSES | HORMONE_MAIN_CLASSES) and not _is_pure(classes, GNRH_MAIN_CLASSES)


def is_supportive_regimen(variant) -> bool:
    """Whether a variant's drugs are entirely supportive-care agents (growth factors, TPO/IL antagonists, somatostatin analogs)."""
    return _is_pure(_component_drug_main_classes(variant), SUPPORTIVE_MAIN_CLASSES)


def is_gnrh_block(events) -> bool:
    """Whether one cycle block's own drugs are entirely GnRH agonists/antagonists or first-generation antiandrogens."""
    return _is_pure(_drug_main_classes(events), GNRH_MAIN_CLASSES)


def is_hormone_block(events) -> bool:
    """Whether one cycle block's own drugs are entirely endocrine therapy, but not purely GnRH-class."""
    classes = _drug_main_classes(events)
    return _is_pure(classes, GNRH_MAIN_CLASSES | HORMONE_MAIN_CLASSES) and not _is_pure(classes, GNRH_MAIN_CLASSES)


def is_supportive_block(events) -> bool:
    """Whether one cycle block's own drugs are entirely supportive-care agents."""
    return _is_pure(_drug_main_classes(events), SUPPORTIVE_MAIN_CLASSES)
