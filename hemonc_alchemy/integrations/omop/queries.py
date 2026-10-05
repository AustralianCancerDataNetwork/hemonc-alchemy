"""Explicit HemOnc/OMOP queries and HemOnc relationship accessors."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import aliased

from hemonc_alchemy.model import Conditions, Drugs, Regimens

from .binding import load_omop_binding, omop_available
from .mapping import (
    HemOncConcept,
    OmopConceptReference,
    StandardConceptMapping,
    _values,
    map_to_standard,
    resolve_hemonc_concepts,
)


@dataclass(frozen=True)
class HemOncRelationship:
    """One directed HemOnc relationship with both concept references."""

    relationship_id: str
    source: OmopConceptReference
    target: OmopConceptReference


def condition_to_snomed(
    session: Any,
    condition_cuis: Iterable[str | int],
    *,
    include_invalid: bool = False,
) -> list[StandardConceptMapping]:
    """Map condition CUIs to active SNOMED disorder concepts."""

    return map_to_standard(
        session,
        condition_cuis,
        target_vocabulary="SNOMED",
        source_domain="Condition",
        target_domain="Condition",
        target_concept_class="Disorder",
        include_invalid=include_invalid,
    )


def drug_to_rxnorm_ingredient(
    session: Any,
    drug_cuis: Iterable[str | int],
    *,
    include_invalid: bool = False,
) -> list[StandardConceptMapping]:
    """Map HemOnc drug/component CUIs to RxNorm ingredients."""

    return map_to_standard(
        session,
        drug_cuis,
        target_vocabulary="RxNorm",
        source_domain="Drug",
        target_domain="Drug",
        target_concept_class="Ingredient",
        include_invalid=include_invalid,
    )


def regimen_to_hemonc(
    session: Any,
    regimen_cuis: Iterable[str | int],
    *,
    include_invalid: bool = False,
) -> list[HemOncConcept]:
    """Resolve regimen CUIs to HemOnc concepts in the ``Regimen`` domain."""

    return resolve_hemonc_concepts(
        session,
        regimen_cuis,
        domain="Regimen",
        include_invalid=include_invalid,
    )


def _hemonc_relationships(
    session: Any,
    relationship_ids: Iterable[str],
    *,
    source_cuis: Iterable[str | int] | None = None,
    source_class: str | None = None,
    target_class: str | None = None,
    include_invalid: bool = False,
) -> list[HemOncRelationship]:
    binding = load_omop_binding()
    relationships = tuple(relationship_ids)
    if (
        binding is None
        or not relationships
        or not omop_available(session)
    ):
        return []

    source = aliased(binding.concept, name="source")
    target = aliased(binding.concept, name="target")
    relation = binding.concept_relationship
    source_from = sa.inspect(source).selectable
    target_from = sa.inspect(target).selectable
    statement = (
        sa.select(
            relation.relationship_id,
            source.concept_id.label("source_concept_id"),
            source.concept_code.label("source_concept_code"),
            source.concept_name.label("source_concept_name"),
            source.vocabulary_id.label("source_vocabulary_id"),
            source.domain_id.label("source_domain_id"),
            source.concept_class_id.label("source_concept_class_id"),
            source.standard_concept.label("source_standard_concept"),
            target.concept_id.label("target_concept_id"),
            target.concept_code.label("target_concept_code"),
            target.concept_name.label("target_concept_name"),
            target.vocabulary_id.label("target_vocabulary_id"),
            target.domain_id.label("target_domain_id"),
            target.concept_class_id.label("target_concept_class_id"),
            target.standard_concept.label("target_standard_concept"),
        )
        .select_from(
            source_from.join(
                relation, relation.concept_id_1 == source.concept_id
            ).join(target_from, target.concept_id == relation.concept_id_2)
        )
        .where(
            source.vocabulary_id == "HemOnc",
            target.vocabulary_id == "HemOnc",
            relation.relationship_id.in_(relationships),
        )
    )
    if source_cuis is not None:
        values = _values(source_cuis)
        if not values:
            return []
        statement = statement.where(source.concept_code.in_(values))
    if source_class is not None:
        statement = statement.where(source.concept_class_id == source_class)
    if target_class is not None:
        statement = statement.where(target.concept_class_id == target_class)
    if not include_invalid:
        statement = statement.where(
            relation.is_valid_expr(),
            source.is_valid_expr(),
            target.is_valid_expr(),
        )
    statement = statement.order_by(
        source.concept_code,
        relation.relationship_id,
        target.concept_code,
    )

    result: list[HemOncRelationship] = []
    for row in session.execute(statement).mappings():
        result.append(
            HemOncRelationship(
                relationship_id=str(row["relationship_id"]),
                source=OmopConceptReference(
                    concept_id=int(row["source_concept_id"]),
                    concept_code=str(row["source_concept_code"]),
                    concept_name=str(row["source_concept_name"]),
                    vocabulary_id=str(row["source_vocabulary_id"]),
                    domain_id=str(row["source_domain_id"]),
                    concept_class_id=str(row["source_concept_class_id"]),
                    standard_concept=row["source_standard_concept"],
                ),
                target=OmopConceptReference(
                    concept_id=int(row["target_concept_id"]),
                    concept_code=str(row["target_concept_code"]),
                    concept_name=str(row["target_concept_name"]),
                    vocabulary_id=str(row["target_vocabulary_id"]),
                    domain_id=str(row["target_domain_id"]),
                    concept_class_id=str(row["target_concept_class_id"]),
                    standard_concept=row["target_standard_concept"],
                ),
            )
        )
    return result


def regimen_modalities(
    session: Any,
    regimen_cuis: Iterable[str | int] | None = None,
    *,
    include_invalid: bool = False,
) -> list[HemOncRelationship]:
    """Return the curated ``Has modality`` links attached to regimens."""

    return _hemonc_relationships(
        session,
        ("Has modality",),
        source_cuis=regimen_cuis,
        source_class="Regimen",
        target_class="Modality",
        include_invalid=include_invalid,
    )


COMPONENT_ROLE_RELATIONSHIPS = (
    "Cytotoxic chemo of",
    "Targeted therapy of",
    "Immunotherapy of",
    "Local therapy of",
    "Endocrine tx of",
    "Antineoplastic of",
    "Radiotherapy of",
    "AB-drug cjgt of",
    "Radioconjugate of",
    "Pept-drug cjgt of",
    "Steroid tx of",
    "Supportive med of",
    "Immunosuppressor of",
    "Growth factor of",
    "Anticoag tx of",
)


def component_roles(
    session: Any,
    component_cuis: Iterable[str | int] | None = None,
    *,
    include_invalid: bool = False,
) -> list[HemOncRelationship]:
    """Return directed component-role links without collapsing their labels."""

    return _hemonc_relationships(
        session,
        COMPONENT_ROLE_RELATIONSHIPS,
        source_cuis=component_cuis,
        include_invalid=include_invalid,
    )


def component_class_hierarchy(
    session: Any,
    component_cuis: Iterable[str | int] | None = None,
    *,
    include_invalid: bool = False,
) -> list[HemOncRelationship]:
    """Return direct ``Is a`` links whose target is a Component Class.

    This is deliberately a direct-edge accessor.  Use OMOP Alchemy's public
    ``Concept.ancestors``/``Concept.descendants`` relationships or the
    ``Concept_Ancestor`` model for transitive closure when needed.
    """

    return _hemonc_relationships(
        session,
        ("Is a",),
        source_cuis=component_cuis,
        target_class="Component Class",
        include_invalid=include_invalid,
    )


def public_hemonc_cuis(session: Any, entity: str) -> list[int]:
    """Return source CUIs from one of the generated public entity tables."""

    tables = {"conditions": Conditions, "drugs": Drugs, "regimens": Regimens}
    table = tables[entity]
    column = {
        Conditions: Conditions.condition_cui,
        Drugs: Drugs.drug_cui,
        Regimens: Regimens.regimen_cui,
    }[table]
    return list(session.execute(sa.select(column).order_by(column)).scalars())


__all__ = [
    "COMPONENT_ROLE_RELATIONSHIPS",
    "HemOncRelationship",
    "component_class_hierarchy",
    "component_roles",
    "condition_to_snomed",
    "drug_to_rxnorm_ingredient",
    "public_hemonc_cuis",
    "regimen_modalities",
    "regimen_to_hemonc",
]
