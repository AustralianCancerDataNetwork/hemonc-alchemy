"""Composable queries for condition-scoped HemOnc sig candidates."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

import sqlalchemy as sa
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from ...model import (
    Drugs,
    Sigs,
    Studies,
    drugs_Canmed_major_classMap,
    drugs_Canmed_minor_classMap,
    sigs_StudyMap,
)
from ...model.enums import Sigs_Class_fieldEnum, Sigs_PhaseEnum
from ...model.relationships import join_study_references, study_context_predicate
from .coercion import coerce_enum_value
from .components import COMPONENT_SEARCH_COLUMNS, COMPONENT_SEARCH_EXPRESSIONS

VariantPolicy = Literal["any", "only", "none"]


def _optional_strings(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(value.strip() for value in values if value and value.strip())
    )


def _add_component_joins(stmt: Select, columns: tuple[str, ...]) -> Select:
    """Add only the model joins needed by the requested search columns."""
    requested = set(columns)
    if requested & {
        "drug",
        "drug_inn",
        "main_class",
        "canmed_major_class",
        "canmed_minor_class",
    }:
        stmt = stmt.outerjoin(Drugs, Drugs.drug_cui == Sigs.component_cui)
    if "canmed_major_class" in requested:
        stmt = stmt.outerjoin(
            drugs_Canmed_major_classMap,
            drugs_Canmed_major_classMap.parent_id == Drugs.id,
        )
    if "canmed_minor_class" in requested:
        stmt = stmt.outerjoin(
            drugs_Canmed_minor_classMap,
            drugs_Canmed_minor_classMap.parent_id == Drugs.id,
        )
    return stmt


@dataclass(frozen=True)
class SigSelectionSpec:
    """Describe a composable query for sigs attached to HemOnc conditions.

    Condition membership is resolved through the normalized ``sigs_study``
    table. ``variant_policy`` makes the distinction needed by downstream
    consumers with non-variant protocol phases explicit:

    - ``"any"`` includes both variant-backed and standalone sigs;
    - ``"only"`` includes sigs with a ``variant_cui``; and
    - ``"none"`` includes sigs without a ``variant_cui``.

    Condition membership is intentionally resolved from direct ``sigs_study``
    rows. It does not include the variant-study fallback used by
    ``toolkit.core.links.sig_study_objects`` when a sig has no direct study
    link; callers needing that best-effort object traversal should use the
    link helper instead.

    Sigs do not carry a version column. Version selection therefore belongs to
    variant queries, where ``TreatmentSelectionSpec.version_policy`` can
    select the latest or all ``Variants`` rows explicitly.
    """

    condition_cuis: tuple[int, ...]
    component_terms: tuple[str, ...] = field(default_factory=tuple)
    component_columns: tuple[str, ...] = ("component",)
    regimens: tuple[str, ...] = field(default_factory=tuple)
    phase: str | Sigs_PhaseEnum | None = None
    class_field: str | Sigs_Class_fieldEnum | None = None
    study_context: str | None = None
    variant_policy: VariantPolicy = "any"

    def __post_init__(self) -> None:
        cuis = tuple(dict.fromkeys(int(cui) for cui in self.condition_cuis))
        if not cuis:
            raise ValueError("At least one condition CUI is required.")
        object.__setattr__(self, "condition_cuis", cuis)

        object.__setattr__(self, "component_terms", _optional_strings(self.component_terms))
        columns = _optional_strings(self.component_columns)
        if not columns:
            raise ValueError("At least one component search column is required.")
        unknown = sorted(set(columns) - set(COMPONENT_SEARCH_COLUMNS))
        if unknown:
            raise ValueError(f"Unknown component search column(s): {unknown}")
        object.__setattr__(self, "component_columns", columns)
        object.__setattr__(self, "regimens", _optional_strings(self.regimens))
        if self.variant_policy not in {"any", "only", "none"}:
            raise ValueError("Variant policy must be 'any', 'only', or 'none'.")

    @classmethod
    def for_conditions(
        cls,
        condition_cuis: Iterable[int],
        *,
        component_terms: str | Sequence[str] = (),
        component_columns: Sequence[str] = ("component",),
        regimens: Sequence[str] = (),
        phase: str | Sigs_PhaseEnum | None = None,
        class_field: str | Sigs_Class_fieldEnum | None = None,
        study_context: str | None = None,
        variant_policy: VariantPolicy = "any",
    ) -> SigSelectionSpec:
        if isinstance(component_terms, str):
            component_terms = (component_terms,)
        return cls(
            condition_cuis=tuple(condition_cuis),
            component_terms=tuple(component_terms),
            component_columns=tuple(component_columns),
            regimens=tuple(regimens),
            phase=phase,
            class_field=class_field,
            study_context=study_context,
            variant_policy=variant_policy,
        )


def sig_search_statement(spec: SigSelectionSpec) -> Select:
    """Build a condition-scoped sig statement using normalized study links.

    The returned statement selects ORM ``Sigs`` rows and is intentionally
    composable. It can be further filtered or used as a subquery by a
    downstream application without importing legacy model adapters.
    """

    stmt = (
        join_study_references(
            select(Sigs).select_from(Sigs)
            .join(sigs_StudyMap, sigs_StudyMap.parent_id == Sigs.id),
            sigs_StudyMap.study,
        )
        .where(Studies.condition_cui.in_(spec.condition_cuis))
    )

    if spec.component_terms:
        stmt = _add_component_joins(stmt, spec.component_columns)
        columns = [
            COMPONENT_SEARCH_EXPRESSIONS[name] for name in spec.component_columns
        ]
        stmt = stmt.where(
            sa.or_(
                *[
                    column.ilike(f"%{term}%")
                    for term in spec.component_terms
                    for column in columns
                ]
            )
        )
    if spec.regimens:
        stmt = stmt.where(Sigs.regimen.in_(spec.regimens))
    if spec.phase is not None:
        stmt = stmt.where(
            Sigs.phase == coerce_enum_value(Sigs_PhaseEnum, spec.phase, "sig phase")
        )
    if spec.class_field is not None:
        stmt = stmt.where(
            Sigs.class_field
            == coerce_enum_value(
                Sigs_Class_fieldEnum, spec.class_field, "sig class field"
            )
        )
    if spec.variant_policy == "only":
        stmt = stmt.where(Sigs.variant_cui.is_not(None))
    elif spec.variant_policy == "none":
        stmt = stmt.where(Sigs.variant_cui.is_(None))
    if spec.study_context is not None:
        stmt = stmt.where(
            study_context_predicate(spec.study_context)
        )

    return stmt.distinct()


def find_sigs(session: Session, spec: SigSelectionSpec) -> list[Sigs]:
    """Execute :func:`sig_search_statement` with a caller-supplied session."""

    return list(session.execute(sig_search_statement(spec)).scalars())


__all__ = ["SigSelectionSpec", "VariantPolicy", "find_sigs", "sig_search_statement"]
