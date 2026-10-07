"""One row per regimen, aggregated before sorting or pagination."""

from dataclasses import replace

from sqlalchemy import case, func, select

from ....model import Regimens, Variants
from ._queries import paginate, search_predicate
from .associations import condition_regimen_association_statement
from .read_models import RegimenSummary
from .specs import DEFAULT_CATALOGUE_SPEC, DEFAULT_PAGINATION, CatalogueSpec, Pagination
from .variants import variant_identity_statement


def regimen_catalogue_statement(spec: CatalogueSpec = DEFAULT_CATALOGUE_SPEC):
    evidence = condition_regimen_association_statement(
        replace(spec, q="", basis="any")
    ).subquery("catalogue_evidence")
    summary = (
        select(
            evidence.c.regimen_cui,
            func.count(
                func.distinct(
                    case((evidence.c.basis == "study", evidence.c.evidence_id))
                )
            ).label("study_count"),
            func.max(case((evidence.c.basis == "study", 1), else_=0)).label(
                "study_linked"
            ),
            func.max(case((evidence.c.basis == "regulatory", 1), else_=0)).label(
                "regulatory_linked"
            ),
        )
        .group_by(evidence.c.regimen_cui)
        .subquery("regimen_evidence_summary")
    )
    variants = (
        select(
            Variants.regimen_cui,
            func.count(func.distinct(Variants.variant_cui)).label(
                "matching_variant_count"
            ),
        )
        .where(Variants.id.in_(variant_identity_statement(spec)))
        .group_by(
            Variants.regimen_cui,
        )
        .subquery("matching_variants")
    )
    statement = (
        select(
            Regimens.regimen_cui,
            Regimens.regimen_name,
            Regimens.regimen_type,
            func.coalesce(variants.c.matching_variant_count, 0).label(
                "matching_variant_count"
            ),
            func.coalesce(summary.c.study_count, 0).label("study_count"),
            (func.coalesce(summary.c.study_linked, 0) > 0).label("study_linked"),
            (func.coalesce(summary.c.regulatory_linked, 0) > 0).label(
                "regulatory_linked"
            ),
        )
        .outerjoin(summary, summary.c.regimen_cui == Regimens.regimen_cui)
        .outerjoin(
            variants,
            variants.c.regimen_cui == Regimens.regimen_cui,
        )
    )
    if spec.condition_cuis is not None:
        statement = statement.where(summary.c.regimen_cui.is_not(None))
    if spec.basis != "any":
        statement = statement.where(getattr(summary.c, f"{spec.basis}_linked") > 0)
    if spec.regimen_cuis is not None:
        statement = statement.where(Regimens.regimen_cui.in_(spec.regimen_cuis))
    if spec.component_terms or spec.study_context is not None:
        statement = statement.where(
            Regimens.regimen_cui.in_(
                select(Variants.regimen_cui).where(
                    Variants.id.in_(variant_identity_statement(spec))
                )
            )
        )
    if spec.q:
        statement = statement.where(
            search_predicate(Regimens.regimen_name, Regimens.regimen_cui, spec.q)
        )
    order = (
        Regimens.regimen_name.desc() if spec.descending else Regimens.regimen_name.asc()
    )
    return statement.order_by(order, Regimens.regimen_cui)


def list_regimens(
    session,
    spec: CatalogueSpec = DEFAULT_CATALOGUE_SPEC,
    pagination: Pagination = DEFAULT_PAGINATION,
):
    return paginate(
        session, regimen_catalogue_statement(spec), pagination, RegimenSummary
    )


def get_regimen_detail(
    session, regimen_cui: int, scope: CatalogueSpec = DEFAULT_CATALOGUE_SPEC
):
    page = list_regimens(
        session,
        replace(scope, regimen_cuis=(regimen_cui,), q=""),
        Pagination(page_size=1),
    )
    return page.items[0] if page.items else None
