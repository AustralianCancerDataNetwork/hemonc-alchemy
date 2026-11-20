"""Inspectable and executable variant selection APIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from .....model import Variants
from .components import (
    build_component_statement,
    category_expression,
    component_search_predicate,
)
from .specs import CategoryMapping, TreatmentSelectionSpec


@dataclass(frozen=True)
class VariantQueryArtifacts:
    """The stages of a treatment query, retained for inspection and testing.

    Variant identity is the generated surrogate ``Variants.id``. The
    default query selects one latest row per ``variant_cui``; the ``all``
    policy is available when callers explicitly need every imported version.
    ``Sigs`` has no version column, so sigs joined by ``variant_cui`` remain
    shared across versions.
    """

    components: Select
    categorized_components: Any
    variant_ids: Any
    variants: Select


def _categorized_components(
    components: Select,
    category_mapping: CategoryMapping | None,
) -> Any:
    source = components.subquery("treatment_components")
    return select(
        source,
        category_expression(source, category_mapping),
    ).subquery("categorized_components")


def build_variant_query_artifacts(
    spec: TreatmentSelectionSpec,
    *,
    category_mapping: CategoryMapping | None = None,
) -> VariantQueryArtifacts:
    """Build inspectable component, grouping, and final variant statements."""
    if spec.category_requirements and category_mapping is None:
        raise ValueError(
            "category_mapping is required when category_requirements are supplied."
        )

    components = build_component_statement(spec)
    categorized = _categorized_components(components, category_mapping)

    predicates = []
    for component_requirement in spec.component_requirements:
        predicates.append(
            sa.func.count(sa.distinct(categorized.c.sig_id)).filter(
                component_search_predicate(categorized, component_requirement)
            )
            >= 1
        )
    for category_requirement in spec.category_requirements:
        count = sa.func.count(sa.distinct(categorized.c.sig_id)).filter(
            categorized.c.broad_category == category_requirement.category
        )
        predicates.append(
            count == category_requirement.amount
            if category_requirement.match == "exact"
            else count >= category_requirement.amount
        )

    variant_ids = (
        select(categorized.c.variant_id)
        .group_by(categorized.c.variant_id)
        .having(sa.and_(*predicates) if predicates else sa.true())
        .subquery("matching_variant_ids")
    )
    variants = select(Variants).join(
        variant_ids,
        variant_ids.c.variant_id == Variants.id,
    )
    return VariantQueryArtifacts(
        components=components,
        categorized_components=categorized,
        variant_ids=variant_ids,
        variants=variants,
    )


def build_variant_statement(
    spec: TreatmentSelectionSpec,
    *,
    category_mapping: CategoryMapping | None = None,
) -> Select:
    """Build a statement returning selected ``Variants`` ORM rows."""
    return build_variant_query_artifacts(
        spec,
        category_mapping=category_mapping,
    ).variants


def select_variants(
    session: Session,
    spec: TreatmentSelectionSpec,
    *,
    category_mapping: CategoryMapping | None = None,
) -> list[Variants]:
    """Execute the variant query under its explicit version policy.

    ``latest`` returns one generated parent row per ``variant_cui``. Because
    ``Sigs`` has no version column, returned variants still expose sigs joined
    by that shared CUI rather than version-provenance-specific sig membership.
    """
    return list(
        session.execute(
            build_variant_statement(spec, category_mapping=category_mapping)
        )
        .unique()
        .scalars()
    )
