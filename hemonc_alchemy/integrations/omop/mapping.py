"""HemOnc CUI to OMOP vocabulary mapping contracts."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import aliased

from .binding import load_omop_binding, omop_available


@dataclass(frozen=True)
class OmopConceptReference:
    """A stable, vocabulary-qualified reference to an OMOP concept."""

    concept_id: int
    concept_code: str
    concept_name: str
    vocabulary_id: str
    domain_id: str
    concept_class_id: str
    standard_concept: str | None


@dataclass(frozen=True)
class HemOncConcept:
    """A HemOnc vocabulary concept resolved by its CUI code."""

    hemonc_cui: str
    concept: OmopConceptReference
    invalid_reason: str | None


@dataclass(frozen=True)
class StandardConceptMapping:
    """One relationship-stage mapping row, including its provenance."""

    hemonc_cui: str
    hemonc_concept: OmopConceptReference
    relationship_id: str
    target: OmopConceptReference | None
    relationship_invalid_reason: str | None


def _values(values: str | int | Iterable[str | int]) -> tuple[str, ...]:
    if isinstance(values, (str, int)):
        values = (values,)
    return tuple(dict.fromkeys(str(value) for value in values))


def _mapping_columns(source: Any, target: Any) -> tuple[Any, ...]:
    return (
        source.concept_code.label("source_concept_code"),
        source.concept_id.label("source_concept_id"),
        source.concept_name.label("source_concept_name"),
        source.vocabulary_id.label("source_vocabulary_id"),
        source.domain_id.label("source_domain_id"),
        source.concept_class_id.label("source_concept_class_id"),
        source.standard_concept.label("source_standard_concept"),
        source.invalid_reason.label("source_invalid_reason"),
        target.concept_id.label("target_concept_id"),
        target.concept_code.label("target_concept_code"),
        target.concept_name.label("target_concept_name"),
        target.vocabulary_id.label("target_vocabulary_id"),
        target.domain_id.label("target_domain_id"),
        target.concept_class_id.label("target_concept_class_id"),
        target.standard_concept.label("target_standard_concept"),
        target.invalid_reason.label("target_invalid_reason"),
    )


def _concept_reference(row: Any, prefix: str) -> OmopConceptReference:
    return OmopConceptReference(
        concept_id=int(row[f"{prefix}concept_id"]),
        concept_code=str(row[f"{prefix}concept_code"]),
        concept_name=str(row[f"{prefix}concept_name"]),
        vocabulary_id=str(row[f"{prefix}vocabulary_id"]),
        domain_id=str(row[f"{prefix}domain_id"]),
        concept_class_id=str(row[f"{prefix}concept_class_id"]),
        standard_concept=row[f"{prefix}standard_concept"],
    )


def resolve_hemonc_concepts(
    session: Any,
    cuis: str | int | Iterable[str | int],
    *,
    domain: str | None = None,
    include_invalid: bool = False,
) -> list[HemOncConcept]:
    """Resolve HemOnc CUIs to their HemOnc vocabulary concepts.

    The returned ``concept.concept_id`` is an OMOP surrogate identifier; it
    must not be confused with the returned ``hemonc_cui``.  All matching rows
    are returned, although current HemOnc data uses one concept row per CUI.
    Invalid HemOnc concepts are excluded unless explicitly requested.
    """

    values = _values(cuis)
    binding = load_omop_binding()
    if not values or binding is None or not omop_available(session):
        return []

    concept = binding.concept
    statement = sa.select(
        concept.concept_code,
        concept.concept_id,
        concept.concept_name,
        concept.vocabulary_id,
        concept.domain_id,
        concept.concept_class_id,
        concept.standard_concept,
        concept.invalid_reason,
    ).where(
        concept.vocabulary_id == "HemOnc",
        concept.concept_code.in_(values),
    )
    if domain is not None:
        statement = statement.where(concept.domain_id == domain)
    if not include_invalid:
        statement = statement.where(concept.is_valid_expr())
    statement = statement.order_by(concept.concept_code, concept.concept_id)

    return [
        HemOncConcept(
            hemonc_cui=str(row["concept_code"]),
            concept=_concept_reference(row, ""),
            invalid_reason=row["invalid_reason"],
        )
        for row in session.execute(statement).mappings()
    ]


def map_to_standard(
    session: Any,
    cuis: str | int | Iterable[str | int],
    *,
    target_vocabulary: str | Sequence[str] | None = None,
    source_domain: str | None = None,
    target_domain: str | None = None,
    target_concept_class: str | None = None,
    include_invalid: bool = False,
) -> list[StandardConceptMapping]:
    """Follow active ``Maps to`` edges from HemOnc CUIs.

    One result is returned per mapping edge.  This deliberately preserves
    one-to-many mappings and the relationship label.  Treatment relationships
    such as ``Has cytotox chemo Rx`` are not silently reclassified as
    ``Maps to``; callers that need those semantics should use the taxonomy
    accessors in :mod:`hemonc_alchemy.integrations.omop.queries`.

    A missing target concept remains a row with ``target=None`` so callers can
    distinguish an unpublished or stale target from an absent mapping edge.
    """

    values = _values(cuis)
    binding = load_omop_binding()
    if not values or binding is None or not omop_available(session):
        return []

    source = aliased(binding.concept, name="source")
    target = aliased(binding.concept, name="target")
    relation = binding.concept_relationship
    source_from = sa.inspect(source).selectable
    target_from = sa.inspect(target).selectable
    statement = (
        sa.select(
            *_mapping_columns(source, target),
            relation.relationship_id,
            relation.invalid_reason.label("mapping_invalid_reason"),
        )
        .select_from(
            source_from.join(
                relation, relation.concept_id_1 == source.concept_id
            ).outerjoin(
                target_from, target.concept_id == relation.concept_id_2
            )
        )
        .where(
            source.vocabulary_id == "HemOnc",
            source.concept_code.in_(values),
            relation.relationship_id == "Maps to",
        )
    )
    if source_domain is not None:
        statement = statement.where(source.domain_id == source_domain)
    if target_vocabulary is not None:
        vocabularies = (
            (target_vocabulary,)
            if isinstance(target_vocabulary, str)
            else tuple(target_vocabulary)
        )
        statement = statement.where(target.vocabulary_id.in_(vocabularies))
    if target_domain is not None:
        statement = statement.where(target.domain_id == target_domain)
    if target_concept_class is not None:
        statement = statement.where(target.concept_class_id == target_concept_class)
    if not include_invalid:
        statement = statement.where(
            relation.is_valid_expr(),
            source.is_valid_expr(),
            target.is_valid_expr(),
        )
    statement = statement.order_by(
        source.concept_code,
        target.vocabulary_id,
        target.concept_id,
    )

    result: list[StandardConceptMapping] = []
    for row in session.execute(statement).mappings():
        target_reference = (
            _concept_reference(row, "target_")
            if row["target_concept_id"] is not None
            else None
        )
        result.append(
            StandardConceptMapping(
                hemonc_cui=str(row["source_concept_code"]),
                hemonc_concept=_concept_reference(row, "source_"),
                relationship_id=str(row["relationship_id"]),
                target=target_reference,
                relationship_invalid_reason=row["mapping_invalid_reason"],
            )
        )
    return result


def map_from_standard(
    session: Any,
    concept_ids: int | Iterable[int],
    *,
    source_domain: str | None = None,
    include_invalid: bool = False,
) -> list[StandardConceptMapping]:
    """Follow active ``Maps to`` edges back to their HemOnc source concepts.

    Reverse of :func:`map_to_standard`: given standard OMOP concept IDs (e.g.
    the ``drug_concept_id`` values observed on real ``Drug_Exposure`` rows),
    resolve which HemOnc CUI(s), if any, map onto them. One result per
    mapping edge, so a concept reached from more than one HemOnc CUI returns
    multiple rows.
    """
    values = tuple(
        dict.fromkeys(
            int(c) for c in ((concept_ids,) if isinstance(concept_ids, int) else concept_ids)
        )
    )
    binding = load_omop_binding()
    if not values or binding is None or not omop_available(session):
        return []

    source = aliased(binding.concept, name="source")  # the HemOnc concept
    target = aliased(binding.concept, name="target")  # the standard concept
    relation = binding.concept_relationship
    source_from = sa.inspect(source).selectable
    target_from = sa.inspect(target).selectable
    statement = (
        sa.select(
            *_mapping_columns(source, target),
            relation.relationship_id,
            relation.invalid_reason.label("mapping_invalid_reason"),
        )
        .select_from(
            source_from.join(
                relation, relation.concept_id_1 == source.concept_id
            ).join(target_from, target.concept_id == relation.concept_id_2)
        )
        .where(
            source.vocabulary_id == "HemOnc",
            relation.relationship_id == "Maps to",
            target.concept_id.in_(values),
        )
    )
    if source_domain is not None:
        statement = statement.where(source.domain_id == source_domain)
    if not include_invalid:
        statement = statement.where(
            relation.is_valid_expr(),
            source.is_valid_expr(),
            target.is_valid_expr(),
        )
    statement = statement.order_by(target.concept_id, source.concept_code)

    result: list[StandardConceptMapping] = []
    for row in session.execute(statement).mappings():
        result.append(
            StandardConceptMapping(
                hemonc_cui=str(row["source_concept_code"]),
                hemonc_concept=_concept_reference(row, "source_"),
                relationship_id=str(row["relationship_id"]),
                target=_concept_reference(row, "target_"),
                relationship_invalid_reason=row["mapping_invalid_reason"],
            )
        )
    return result


__all__ = [
    "HemOncConcept",
    "OmopConceptReference",
    "StandardConceptMapping",
    "map_from_standard",
    "map_to_standard",
    "resolve_hemonc_concepts",
]
