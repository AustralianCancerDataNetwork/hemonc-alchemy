"""Component-level statements used by treatment selection."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy import Select, select

from .....model import (
    Drugs,
    Sigs,
    Studies,
    StudyResults,
    Variants,
    drugs_Canmed_major_classMap,
    drugs_Canmed_minor_classMap,
    variants_StudyMap,
)
from .....model.enums import Sigs_PhaseEnum
from .....toolkit.core.catalogue.variants import (
    latest_variant_ids as _latest_variant_ids,
)
from .....toolkit.core.coercion import coerce_enum_value
from .....toolkit.core.components import COMPONENT_SEARCH_COLUMNS
from .specs import CategoryMapping, ComponentRequirement, TreatmentSelectionSpec

_SEARCH_COLUMNS = frozenset(COMPONENT_SEARCH_COLUMNS)


def category_expression(
    components: Any,
    category_mapping: CategoryMapping | None,
) -> Any:
    if category_mapping is None:
        return sa.cast(sa.null(), sa.String).label("broad_category")
    if not category_mapping:
        raise ValueError("category_mapping must contain at least one source column.")

    expressions = []
    for column_name, mapping in category_mapping.items():
        if column_name not in _SEARCH_COLUMNS:
            raise ValueError(f"Unknown category source column: {column_name}")
        if not mapping:
            raise ValueError(f"Category mapping for {column_name!r} must not be empty.")
        column = getattr(components.c, column_name)
        expressions.append(
            sa.case(
                *[(column == source, target) for source, target in mapping.items()]
            )
        )
    expression = expressions[0] if len(expressions) == 1 else sa.func.coalesce(*expressions)
    return expression.label("broad_category")


def build_component_statement(
    spec: TreatmentSelectionSpec,
) -> Select:
    """Build one row per variant/sig/study component candidate.

    The returned statement is intentionally not grouped. Selection criteria
    are applied by :func:`build_variant_query_artifacts`, which can expose the
    intermediate projection for inspection in notebooks and tests.
    """
    columns: list[Any] = [
        Variants.id.label("variant_id"),
        Variants.variant_cui.label("variant_cui"),
        Variants.version.label("version"),
        Variants.regimen.label("regimen"),
        Variants.variant.label("variant"),
        Sigs.id.label("sig_id"),
        Sigs.component_cui.label("component_cui"),
        Sigs.component.label("component"),
        Sigs.class_field.label("class_field"),
        Sigs.phase.label("phase"),
        Studies.id.label("study_id"),
        Studies.study.label("study"),
        Studies.study_cui.label("study_cui"),
        Drugs.drug.label("drug"),
        Drugs.drug_inn.label("drug_inn"),
        Drugs.main_class.label("main_class"),
        drugs_Canmed_major_classMap.canmed_major_class.label("canmed_major_class"),
        drugs_Canmed_minor_classMap.canmed_minor_class.label("canmed_minor_class"),
    ]
    stmt = (
        select(*columns)
        .select_from(Variants)
        .join(Sigs, Sigs.variant_cui == Variants.variant_cui)
        .join(variants_StudyMap, variants_StudyMap.parent_id == Variants.id)
        .join(Studies, Studies.study == variants_StudyMap.study)
        .outerjoin(Drugs, Sigs.component_cui == Drugs.drug_cui)
        .outerjoin(
            drugs_Canmed_major_classMap,
            drugs_Canmed_major_classMap.parent_id == Drugs.id,
        )
        .outerjoin(
            drugs_Canmed_minor_classMap,
            drugs_Canmed_minor_classMap.parent_id == Drugs.id,
        )
        .where(Studies.condition_cui.in_(spec.condition_cuis))
        .distinct()
    )
    if spec.version_policy == "latest":
        ranked = _latest_variant_ids()
        stmt = stmt.join(ranked, ranked.c.variant_id == Variants.id)
        stmt = stmt.where(ranked.c.version_rank == 1)
    if spec.regimens:
        stmt = stmt.where(Variants.regimen.in_(spec.regimens))
    if spec.phase is not None:
        phase = coerce_enum_value(Sigs_PhaseEnum, spec.phase, "sig phase")
        stmt = stmt.where(Sigs.phase == phase)
    if spec.study_context is not None:
        stmt = stmt.where(
            sa.exists(
                select(1).where(
                    StudyResults.study == Studies.study,
                    StudyResults.context == spec.study_context,
                )
            )
        )
    return stmt


def component_search_predicate(
    components: Any,
    requirement: ComponentRequirement,
) -> Any:
    """Build the OR expression for one component requirement."""
    unknown = sorted(set(requirement.columns) - _SEARCH_COLUMNS)
    if unknown:
        raise ValueError(f"Unknown component search column(s): {unknown}")
    columns = [getattr(components.c, name) for name in requirement.columns]
    return sa.or_(
        *[
            column.ilike(f"%{term}%")
            for term in requirement.terms
            for column in columns
        ]
    )
