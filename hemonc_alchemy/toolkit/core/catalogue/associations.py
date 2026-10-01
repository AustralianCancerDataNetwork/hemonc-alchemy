"""Explicit evidence-grain relations; names never imply regulatory membership."""

from dataclasses import replace

from sqlalchemy import Integer, cast, exists, literal, select, union_all

from ....model import (
    Conditions,
    Indications,
    Regimens,
    Studies,
    StudyResults,
    Variants,
    indications_Regimen_cuiMap,
    variants_StudyMap,
)
from .specs import DEFAULT_CATALOGUE_SPEC, CatalogueSpec
from .variants import variant_identity_statement


def study_association_statement(spec: CatalogueSpec):
    statement = (
        select(
            Studies.condition_cui,
            Variants.regimen_cui,
            Variants.variant_cui,
            Variants.version,
            Studies.id.label("evidence_id"),
            literal("study").label("basis"),
        )
        .select_from(Variants)
        .join(variants_StudyMap, variants_StudyMap.parent_id == Variants.id)
        .join(
            Studies,
            Studies.study == variants_StudyMap.study,
        )
        .join(Conditions, Conditions.condition_cui == Studies.condition_cui)
        .join(
            Regimens,
            Regimens.regimen_cui == Variants.regimen_cui,
        )
        .where(Variants.id.in_(variant_identity_statement(spec)))
    )
    if spec.condition_cuis is not None:
        statement = statement.where(Studies.condition_cui.in_(spec.condition_cuis))
    if spec.study_context is not None:
        statement = statement.where(
            exists(
                select(1).where(
                    StudyResults.study == Studies.study,
                    StudyResults.context == spec.study_context,
                )
            )
        )
    return statement.distinct()


def regulatory_association_statement(spec: CatalogueSpec):
    statement = (
        select(
            Indications.condition_cui,
            indications_Regimen_cuiMap.regimen_cui,
            cast(literal(None), Integer).label("variant_cui"),
            cast(literal(None), Integer).label("version"),
            Indications.id.label("evidence_id"),
            literal("regulatory").label("basis"),
        )
        .select_from(Indications)
        .join(
            indications_Regimen_cuiMap,
            indications_Regimen_cuiMap.parent_id == Indications.id,
        )
        .join(
            Conditions,
            Conditions.condition_cui == Indications.condition_cui,
        )
        .join(Regimens, Regimens.regimen_cui == indications_Regimen_cuiMap.regimen_cui)
    )
    if spec.condition_cuis is not None:
        statement = statement.where(Indications.condition_cui.in_(spec.condition_cuis))
    if spec.regimen_cuis is not None:
        statement = statement.where(Regimens.regimen_cui.in_(spec.regimen_cuis))
    # A component/context filter requires a qualifying variant, even for a
    # regulatory link. Unfiltered regulatory-only regimens remain visible.
    if spec.component_terms or spec.study_context is not None:
        variants = select(Variants.regimen_cui).where(
            Variants.id.in_(variant_identity_statement(replace(spec, q="")))
        )
        statement = statement.where(Regimens.regimen_cui.in_(variants))
    return statement.distinct()


def condition_regimen_association_statement(
    spec: CatalogueSpec = DEFAULT_CATALOGUE_SPEC,
):
    """Evidence IDs are source-row IDs scoped to a dataset and evidence basis."""
    study = study_association_statement(spec)
    regulatory = regulatory_association_statement(spec)
    if spec.basis == "study":
        return study
    if spec.basis == "regulatory":
        return regulatory
    return union_all(study, regulatory)
