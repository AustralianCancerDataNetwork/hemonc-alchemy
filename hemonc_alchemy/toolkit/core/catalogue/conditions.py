"""Paged source condition search; exact-name lookup remains in core.conditions."""

from sqlalchemy import select

from ....model import Conditions
from ._queries import paginate, search_predicate
from .read_models import ConditionSummary
from .specs import DEFAULT_CATALOGUE_SPEC, DEFAULT_PAGINATION, CatalogueSpec, Pagination


def condition_search_statement(spec: CatalogueSpec = DEFAULT_CATALOGUE_SPEC):
    statement = select(
        Conditions.condition_cui, Conditions.condition, Conditions.section
    )
    if spec.condition_cuis is not None:
        statement = statement.where(Conditions.condition_cui.in_(spec.condition_cuis))
    if spec.q:
        statement = statement.where(
            search_predicate(Conditions.condition, Conditions.condition_cui, spec.q)
        )
    order = (
        Conditions.condition.desc() if spec.descending else Conditions.condition.asc()
    )
    return statement.order_by(order, Conditions.condition_cui)


def search_conditions(
    session,
    spec: CatalogueSpec = DEFAULT_CATALOGUE_SPEC,
    pagination: Pagination = DEFAULT_PAGINATION,
):
    return paginate(
        session, condition_search_statement(spec), pagination, ConditionSummary
    )
