"""Queries for HemOnc conditions."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from ...model import Conditions

logger = logging.getLogger(__name__)


def _as_names(names: str | Iterable[str]) -> tuple[str, ...]:
    if isinstance(names, str):
        names = (names,)
    result = tuple(dict.fromkeys(name for name in names if name))
    if not result:
        raise ValueError("At least one condition name is required.")
    return result


def condition_cui_statement(names: str | Iterable[str]) -> Select:
    """Return a composable statement selecting condition CUIs by exact name."""
    return select(Conditions.condition_cui, Conditions.condition).where(
        Conditions.condition.in_(_as_names(names))
    )


def conditions_by_names(
    session: Session,
    names: str | Iterable[str],
) -> list[Conditions]:
    """Resolve exact condition names to rows in caller-supplied order.

    Missing names are logged and omitted. If a source contains more than one
    row for a name, all matching rows are returned in CUI order rather than an
    arbitrary row being selected.
    """
    requested = _as_names(names)
    rows = (
        session.execute(
            select(Conditions)
            .where(Conditions.condition.in_(requested))
            .order_by(Conditions.condition_cui)
        )
        .scalars()
        .all()
    )
    by_name: dict[str, list[Conditions]] = {}
    for row in rows:
        by_name.setdefault(row.condition, []).append(row)

    missing = [name for name in requested if name not in by_name]
    if missing:
        logger.warning("No HemOnc condition found for: %s", missing)

    return [row for name in requested for row in by_name.get(name, ())]


def condition_cuis_by_names(
    session: Session,
    names: str | Iterable[str],
) -> list[int]:
    """Resolve exact condition names to distinct condition CUIs."""
    return list(
        dict.fromkeys(row.condition_cui for row in conditions_by_names(session, names))
    )
