"""Hand-written relationships between entities.

HemOnc's tables are linked by shared concept identifiers rather than by
declared foreign keys. Where a column name happens to match another table's
unique key, the generated `*_obj`/`*_objects` relationships in entities.py
already follow it. The ones defined here are the links that pattern can't
reach, because the columns are named differently on each side
(`Sigs.component_cui` to `Drugs.drug_cui`), because the target column repeats
across rows (`Variants.variant_cui`, `Studies.study`), or because the useful
direction is one-to-many (`Conditions.studies`).

All of them are read-only. Because they are assigned onto the entity classes
here rather than declared in entities.py, they only exist once
`hemonc_alchemy.model` has been imported.
"""

from __future__ import annotations

from sqlalchemy import and_, exists, literal, or_, select, union_all
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import foreign, relationship

from .entities import (
    Conditions,
    Drugs,
    Sigs,
    Studies,
    StudyResults,
    Variants,
    variants_StudyMap,
)


def dedupe_by(items, key_fn):
    """
    Deduplicate an iterable by a derived key, preserving first-seen order.

    Skips None items and items whose key_fn returns None
    """
    seen = {}
    for item in items:
        if item is None:
            continue
        key = key_fn(item)
        if key is None:
            continue
        seen.setdefault(key, item)
    return list(seen.values())


def split_pipe_values(value):
    """Split a pipe-delimited free-text field into deduplicated, stripped tokens."""
    if value is None:
        return []
    return dedupe_by(
        (part.strip() for part in str(value).split("|")),
        lambda part: part or None,
    )


Variants.component_sigs = relationship(
    Sigs,
    primaryjoin=foreign(Sigs.variant_cui) == Variants.variant_cui,
    viewonly=True,
    lazy="selectin",
)

Drugs.sigs = relationship(
    Sigs,
    primaryjoin=foreign(Sigs.component_cui) == Drugs.drug_cui,
    viewonly=True,
    lazy="selectin",
)

Sigs.variant_object = relationship(
    Variants,
    primaryjoin=and_(foreign(Sigs.variant_cui) == Variants.variant_cui, Variants.version == 1),
    viewonly=True,
    lazy="select",
)

Sigs.drug_object = relationship(
    Drugs,
    primaryjoin=foreign(Sigs.component_cui) == Drugs.drug_cui,
    viewonly=True,
    lazy="selectin",
)

Conditions.studies = relationship(
    Studies,
    primaryjoin=foreign(Studies.condition_cui) == Conditions.condition_cui,
    viewonly=True,
    lazy="selectin",
)

variants_StudyMap.study_objects = relationship(
    Studies,
    # A map row's text is sometimes "study--substudy" (e.g. a trial-phase or
    # arm suffix). Resolve either the exact name or that split form against
    # Studies' own study/substudy columns.
    primaryjoin=or_(
        foreign(Studies.study) == variants_StudyMap.study,
        foreign(Studies.study + "--" + Studies.substudy) == variants_StudyMap.study,
    ),
    viewonly=True,
    lazy="selectin",
)


def join_mapped_studies(statement):
    """Join `variants_StudyMap` to `Studies` as `study_objects` does, using equality joins.

    The relationship's OR condition stops PostgreSQL hashing or indexing the
    join, so it compares every map row with every study.
    """
    return join_study_references(statement, variants_StudyMap.study)


def join_study_references(statement, study_column):
    """Resolve bare or study--substudy tokens using hashable equality joins."""
    keys = union_all(
        select(Studies.id.label("study_id"), Studies.study.label("study_key")),
        select(Studies.id, Studies.study + "--" + Studies.substudy).where(
            Studies.substudy.is_not(None)
        ),
    ).subquery("study_keys")
    return statement.join(keys, keys.c.study_key == study_column).join(
        Studies, Studies.id == keys.c.study_id
    )


def study_context_predicate(context):
    """Match a result's study identity and its substudy/condition/biomarker grain."""
    context_matches = StudyResults.context == context
    if context is not None and "|" not in context:
        delimited_contexts = literal("|") + StudyResults.context + literal("|")
        context_matches = or_(
            context_matches, delimited_contexts.contains(f"|{context}|", autoescape=True),
        )
    return exists(select(1).where(
        or_(
            StudyResults.study_cui == Studies.study_cui,
            and_(StudyResults.study_cui.is_(None), StudyResults.study == Studies.study),
        ),
        StudyResults.substudy_cui.is_not_distinct_from(Studies.substudy_cui),
        StudyResults.condition_cui.is_not_distinct_from(Studies.condition_cui),
        StudyResults.biomarker_finding.is_not_distinct_from(Studies.biomarker_finding),
        context_matches,
    ))


variants_StudyMap.variant_objects = relationship(
    Variants,
    primaryjoin=foreign(Variants.id) == variants_StudyMap.parent_id,
    viewonly=True,
    lazy="selectin",
)

Studies.variants = relationship(
    Variants,
    secondary=variants_StudyMap.__table__,
    primaryjoin=or_(
        foreign(variants_StudyMap.study) == Studies.study,
        foreign(variants_StudyMap.study) == Studies.study + "--" + Studies.substudy,
    ),
    secondaryjoin=foreign(variants_StudyMap.parent_id) == Variants.id,
    viewonly=True,
    lazy="selectin",
)

Variants.drugs = association_proxy("component_sigs", "drug_object")
