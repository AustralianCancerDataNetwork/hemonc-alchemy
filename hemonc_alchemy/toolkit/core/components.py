"""Reusable component search statements for the HemOnc model."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from ...model import (
    Drugs,
    Sigs,
    drugs_Canmed_major_classMap,
    drugs_Canmed_minor_classMap,
)


@dataclass(frozen=True)
class ComponentHit:
    """A distinct component search result with useful model labels."""

    component_cui: int
    component: str
    drug: str | None
    drug_inn: str | None
    main_class: str | None
    canmed_major_class: str | None
    canmed_minor_class: str | None


COMPONENT_SEARCH_COLUMNS = (
    "component",
    "drug",
    "drug_inn",
    "main_class",
    "canmed_major_class",
    "canmed_minor_class",
)

COMPONENT_SEARCH_EXPRESSIONS = {
    "component": Sigs.component,
    "drug": Drugs.drug,
    "drug_inn": Drugs.drug_inn,
    "main_class": Drugs.main_class,
    "canmed_major_class": drugs_Canmed_major_classMap.canmed_major_class,
    "canmed_minor_class": drugs_Canmed_minor_classMap.canmed_minor_class,
}


def _as_terms(search_terms: str | Iterable[str]) -> tuple[str, ...]:
    if isinstance(search_terms, str):
        search_terms = (search_terms,)
    terms = tuple(term.strip() for term in search_terms if term and term.strip())
    if not terms:
        raise ValueError("At least one component search term is required.")
    return terms


def _search_expressions(
    terms: Iterable[str],
    columns: tuple[Any, ...],
) -> list[Any]:
    return [column.ilike(f"%{term}%") for term in terms for column in columns]


def _search_columns(columns: tuple[str, ...]) -> tuple[Any, ...]:
    if not columns:
        raise ValueError("At least one component search column is required.")
    unknown = sorted(set(columns) - set(COMPONENT_SEARCH_EXPRESSIONS))
    if unknown:
        raise ValueError(f"Unknown component search column(s): {unknown}")
    return tuple(COMPONENT_SEARCH_EXPRESSIONS[name] for name in columns)


def component_search_statement(
    search_terms: str | Iterable[str],
    *,
    columns: tuple[str, ...] = COMPONENT_SEARCH_COLUMNS,
) -> Select:
    """Return a statement selecting distinct components matching text.

    Searchable fields include the sig's source component label, the drug name
    and INN, the main class, and normalized CanMED class child rows. The
    statement is intentionally composable: callers may add condition, study,
    or treatment-policy predicates before execution.
    """
    selected: list[Any] = [
        Sigs.component_cui.label("component_cui"),
        Sigs.component.label("component"),
        Drugs.drug.label("drug"),
        Drugs.drug_inn.label("drug_inn"),
        Drugs.main_class.label("main_class"),
        drugs_Canmed_major_classMap.canmed_major_class.label("canmed_major_class"),
        drugs_Canmed_minor_classMap.canmed_minor_class.label("canmed_minor_class"),
    ]
    return (
        select(*selected)
        .select_from(Sigs)
        .outerjoin(Drugs, Sigs.component_cui == Drugs.drug_cui)
        .outerjoin(
            drugs_Canmed_major_classMap,
            drugs_Canmed_major_classMap.parent_id == Drugs.id,
        )
        .outerjoin(
            drugs_Canmed_minor_classMap,
            drugs_Canmed_minor_classMap.parent_id == Drugs.id,
        )
        .where(
            sa.or_(
                *_search_expressions(_as_terms(search_terms), _search_columns(columns))
            )
        )
        .distinct()
    )


def component_cui_subquery(
    search_terms: str | Iterable[str],
    *,
    columns: tuple[str, ...] = COMPONENT_SEARCH_COLUMNS,
) -> Any:
    """Return a distinct ``component_cui`` subquery for composition in filters."""
    return (
        select(Sigs.component_cui)
        .select_from(Sigs)
        .outerjoin(Drugs, Sigs.component_cui == Drugs.drug_cui)
        .outerjoin(
            drugs_Canmed_major_classMap,
            drugs_Canmed_major_classMap.parent_id == Drugs.id,
        )
        .outerjoin(
            drugs_Canmed_minor_classMap,
            drugs_Canmed_minor_classMap.parent_id == Drugs.id,
        )
        .where(
            sa.or_(
                *_search_expressions(_as_terms(search_terms), _search_columns(columns))
            )
        )
        .distinct()
        .subquery("matching_component_cuis")
    )


def search_components(
    session: Session,
    search_terms: str | Iterable[str],
    *,
    columns: tuple[str, ...] = COMPONENT_SEARCH_COLUMNS,
) -> list[ComponentHit]:
    """Execute :func:`component_search_statement` and return component hits."""
    rows = session.execute(
        component_search_statement(search_terms, columns=columns)
    ).mappings()
    return [ComponentHit(**dict(row)) for row in rows]
