"""Regulatory records survive missing condition and regimen links."""

from sqlalchemy import exists, func, select

from ....model import Conditions, Indications, Regimens, indications_Regimen_cuiMap
from ....model.enums import Indications_RegulatorEnum
from ..coercion import coerce_enum_value
from ._queries import paginate, search_predicate
from .read_models import IndicationRecord
from .specs import (
    DEFAULT_INDICATION_SPEC,
    DEFAULT_PAGINATION,
    IndicationSpec,
    Pagination,
)


def indication_statement(spec: IndicationSpec = DEFAULT_INDICATION_SPEC):
    regimen_links = (
        select(func.count(func.distinct(Regimens.regimen_cui)))
        .select_from(indications_Regimen_cuiMap)
        .join(
            Regimens,
            Regimens.regimen_cui == indications_Regimen_cuiMap.regimen_cui,
        )
        .where(indications_Regimen_cuiMap.parent_id == Indications.id)
        .scalar_subquery()
    )
    statement = select(
        Indications.id.label("record_id"),
        Indications.condition_cui,
        Indications.condition,
        Indications.component_cui,
        Indications.component,
        Indications.regulator,
        Indications.withdrawn,
        Indications.status.label("clinical_status"),
        Indications.stage,
        Indications.biomarker,
        Indications.prior_therapy,
        exists(
            select(1).where(Conditions.condition_cui == Indications.condition_cui)
        ).label("condition_resolves"),
        regimen_links.label("linked_regimen_count"),
    )
    if spec.condition_cuis is not None:
        statement = statement.where(Indications.condition_cui.in_(spec.condition_cuis))
    if spec.regimen_cuis is not None:
        statement = statement.where(
            exists(
                select(1).where(
                    indications_Regimen_cuiMap.parent_id == Indications.id,
                    indications_Regimen_cuiMap.regimen_cui.in_(spec.regimen_cuis),
                )
            )
        )
    if spec.regulators:
        regulators = tuple(
            coerce_enum_value(Indications_RegulatorEnum, value, "regulator")
            for value in spec.regulators
        )
        statement = statement.where(Indications.regulator.in_(regulators))
    if spec.withdrawn_values:
        statement = statement.where(Indications.withdrawn.in_(spec.withdrawn_values))
    if spec.q:
        statement = statement.where(
            search_predicate(Indications.component, Indications.component_cui, spec.q)
        )
    return statement.order_by(Indications.id)


def list_indications(
    session,
    spec: IndicationSpec = DEFAULT_INDICATION_SPEC,
    pagination: Pagination = DEFAULT_PAGINATION,
):
    return paginate(session, indication_statement(spec), pagination, IndicationRecord)
