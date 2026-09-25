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
