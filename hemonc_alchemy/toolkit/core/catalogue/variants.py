"""Variant catalogue membership does not require a dosing instruction."""

from sqlalchemy import exists, func, or_, select

from ....model import Sigs, Studies, StudyResults, Variants, variants_StudyMap
from ._queries import paginate, search_predicate
from .read_models import VariantRecord
from .specs import DEFAULT_CATALOGUE_SPEC, DEFAULT_PAGINATION, CatalogueSpec, Pagination


def latest_variant_ids():
    """Rank all imported rows before any condition or component predicate."""
    return select(
        Variants.id.label("variant_id"),
        func.row_number()
        .over(
            partition_by=Variants.variant_cui,
            order_by=(Variants.version.desc(), Variants.id.desc()),
        )
        .label("version_rank"),
    ).subquery("ranked_variants")


def variant_identity_statement(spec: CatalogueSpec):
    statement = select(Variants.id)
    if spec.version_policy == "latest":
        ranked = latest_variant_ids()
        statement = statement.join(ranked, ranked.c.variant_id == Variants.id).where(
            ranked.c.version_rank == 1
        )
    if spec.regimen_cuis is not None:
        statement = statement.where(Variants.regimen_cui.in_(spec.regimen_cuis))
    if spec.component_terms:
        statement = statement.where(
            exists(
                select(1).where(
                    Sigs.variant_cui == Variants.variant_cui,
                    or_(
                        *(
                            Sigs.component.icontains(term, autoescape=True)
                            for term in spec.component_terms
                        )
                    ),
                )
            )
        )
    if spec.condition_cuis is not None or spec.study_context is not None:
        evidence = (
            select(1)
            .select_from(variants_StudyMap)
            .join(variants_StudyMap.study_objects)  # type: ignore[attr-defined]
            .where(variants_StudyMap.parent_id == Variants.id)
        )
        if spec.condition_cuis is not None:
            evidence = evidence.where(Studies.condition_cui.in_(spec.condition_cuis))
        if spec.study_context is not None:
            evidence = evidence.where(
                exists(
                    select(1).where(
                        StudyResults.study == Studies.study,
                        StudyResults.context == spec.study_context,
                    )
                )
            )
        statement = statement.where(exists(evidence))
    return statement


def variant_catalogue_statement(spec: CatalogueSpec = DEFAULT_CATALOGUE_SPEC):
    sig_count = (
        select(func.count())
        .select_from(Sigs)
        .where(Sigs.variant_cui == Variants.variant_cui)
        .scalar_subquery()
    )
    statement = select(
        Variants.variant_cui,
        Variants.version,
        Variants.regimen_cui,
        Variants.regimen,
        Variants.variant,
        Variants.fullyspecified.label("source_fullyspecified"),
        sig_count.label("sig_count"),
    ).where(Variants.id.in_(variant_identity_statement(spec)))
    if spec.q:
        statement = statement.where(
            or_(
                search_predicate(Variants.variant, Variants.variant_cui, spec.q),
                Variants.regimen.icontains(spec.q, autoescape=True),
            )
        )
    order = (
        Variants.variant_cui.desc() if spec.descending else Variants.variant_cui.asc()
    )
    return statement.order_by(order, Variants.version.desc())


def list_variants(
    session,
    spec: CatalogueSpec = DEFAULT_CATALOGUE_SPEC,
    pagination: Pagination = DEFAULT_PAGINATION,
):
    return paginate(
        session, variant_catalogue_statement(spec), pagination, VariantRecord
    )


def get_variant(session, variant_cui: int, version: int):
    statement = variant_catalogue_statement(CatalogueSpec(version_policy="all")).where(
        Variants.variant_cui == variant_cui, Variants.version == version
    )
    row = session.execute(statement).mappings().one_or_none()
    return VariantRecord(**row) if row else None
