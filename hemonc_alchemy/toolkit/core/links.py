"""Following HemOnc's cross-references between sigs, studies, variants and
conditions.

Some of these links are only recorded as free text — a `study` field holding
several study names separated by `|`, for example — so resolving them means
splitting that text and looking the names up. That is a best-effort match on
what the source wrote, not a guaranteed join, and a name that doesn't resolve
is simply absent from the result rather than raising.

Each function takes an entity and returns the related entities, deduplicated.
Several issue their own queries, so the entity must be attached to a session.
"""

from __future__ import annotations

from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import object_session

from ...model import Studies, Variants
from ...model.relationships import dedupe_by


def study_condition_object(study):
    """A study's resolved condition, preferring the condition_cui-keyed
    match over the condition-name-keyed one."""
    return study.condition_cui_obj or study.condition_obj


def study_variant_objects(study):
    """A study's resolved variants, keeping the highest imported version.

    ``Variants.variant_cui`` is not unique. When a study relationship loads
    several versions, this helper deliberately prefers the greatest
    ``(version, id)`` rather than depending on select-in loading order.
    """
    latest = {}
    for variant in study.variants:
        variant_cui = getattr(variant, "variant_cui", None)
        if variant_cui is None:
            continue
        current = latest.get(variant_cui)
        candidate_key = (getattr(variant, "version", -1), getattr(variant, "id", -1))
        current_key = (
            getattr(current, "version", -1),
            getattr(current, "id", -1),
        ) if current is not None else None
        if current_key is None or candidate_key > current_key:
            latest[variant_cui] = variant
    return list(latest.values())


def variant_condition_objects(variant):
    """A variant's distinct resolved conditions, via its raw study tokens."""
    conditions = (
        study_condition_object(study)
        for study_map_row in variant.study_items
        for study in study_map_row.study_objects
    )
    return dedupe_by(
        conditions,
        lambda condition: (getattr(condition, "condition_cui", None), getattr(condition, "condition", None)),
    )


def condition_variant_objects(condition):
    """A condition's distinct resolved variants, via its resolved studies."""
    variants = []
    for study in condition.studies:
        variants.extend(study_variant_objects(study))
    return dedupe_by(variants, lambda variant: getattr(variant, "variant_cui", None))


def sig_study_tokens(sig) -> list[str]:
    """Return the normalized study names attached to a sig.

    Older HemOnc exports exposed these names as a pipe-delimited ``study``
    field. The current generated model stores them in ``sigs_study`` rows;
    reading the map rows keeps this helper correct for the imported schema.
    """
    return dedupe_by(
        (getattr(study_map_row, "study", None) for study_map_row in sig.study_items),
        lambda study: study,
    )


def sig_variant_context(sig) -> Variants | None:
    """The most recent Variants row matching a sig's `variant_cui`, if any.

    Requires the sig to be attached to a session (this issues a query).
    """
    variant_cui = getattr(sig, "variant_cui", None)
    session = object_session(sig)
    if session is None or variant_cui is None:
        return None
    return (
        session.execute(
            select(Variants).where(Variants.variant_cui == variant_cui).order_by(Variants.version.desc(), Variants.id.desc())
        )
        .scalars()
        .first()
    )


def sig_study_objects(sig) -> list[Studies]:
    """A sig's resolved studies from normalized links and variant context.

    A sig normally has direct ``study_objects`` in the current schema. The
    variant-context fallback preserves the useful legacy behavior for sigs
    whose study map is absent but whose variant has study links.
    """
    studies: list[Studies] = []
    studies.extend(cast(list[Studies], getattr(sig, "study_objects", ())))
    variant = sig_variant_context(sig)
    if variant is not None:
        for study_map_row in variant.study_items:
            # cast: attached in model.relationships, so invisible statically.
            study_objects = cast(list[Studies], getattr(study_map_row, "study_objects", ()))
            studies.extend(study_objects)

    return dedupe_by(
        studies,
        lambda study: (getattr(study, "id", None), getattr(study, "study", None), getattr(study, "condition_cui", None)),
    )


def sig_condition_objects(sig):
    """A sig's resolved conditions: via its variant context, plus via its resolved studies."""
    variant = sig_variant_context(sig)
    conditions = []
    if variant is not None:
        conditions.extend(variant_condition_objects(variant))
    conditions.extend(study_condition_object(study) for study in sig_study_objects(sig))
    return dedupe_by(
        conditions,
        lambda condition: (getattr(condition, "condition_cui", None), getattr(condition, "condition", None)),
    )
