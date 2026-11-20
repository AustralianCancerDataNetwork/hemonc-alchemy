"""Bounded-query loader for indication source records."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from sqlalchemy import select

from ....model import (
    Indications,
    indications_BiomarkerSlots,
    indications_ContextMap,
    indications_DemographicsMap,
    indications_Prior_therapy_negationMap,
    indications_Prior_therapy_settingMap,
    indications_RegimenLinks,
    indications_Response_contingencyMap,
    indications_Risk_stratificationMap,
)
from ..catalogue.indications import indication_statement
from ..catalogue.specs import DEFAULT_INDICATION_SPEC, IndicationSpec
from .model import RegimenLink


@dataclass(frozen=True)
class BiomarkerSource:
    slot: int
    biomarkers: tuple[str, ...]
    findings: tuple[str, ...]
    pairs: tuple[tuple[str | None, str | None], ...] | None = None
    aligned: bool = True
    types: tuple[str | None, ...] = ()


@dataclass(frozen=True)
class IndicationSource:
    indication_id: int
    condition_cui: int | None
    condition: str
    component_cui: int | None
    component: str
    regulator: str
    withdrawn_raw: str
    biomarkers: tuple[BiomarkerSource, ...]
    regimen_cuis: tuple[int, ...]
    raw: Mapping[str, str | None]
    stage: str | None = None
    status: str | None = None
    stage_or_status: str | None = None
    age: str | None = None
    age_unit: str | None = None
    prior_therapy: str | None = None
    sex: str | None = None
    accelerated: bool = False
    context: tuple[str, ...] = ()
    demographics: tuple[str, ...] = ()
    prior_therapy_setting: tuple[str, ...] = ()
    prior_therapy_negation: tuple[str, ...] = ()
    response_contingency: tuple[str, ...] = ()
    risk_stratification: tuple[str, ...] = ()
    regimen_links: tuple[RegimenLink, ...] = ()


def _split(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    text = str(getattr(value, "value", value))
    return tuple(part.strip() for part in text.split("|"))


def _load_child_values(
    session, ids: tuple[int, ...]
) -> dict[tuple[int, str], list[str]]:
    child_values = {}
    for table, attribute in (
        (indications_ContextMap, "context"),
        (indications_DemographicsMap, "demographics"),
        (indications_Prior_therapy_settingMap, "prior_therapy_setting"),
        (indications_Prior_therapy_negationMap, "prior_therapy_negation"),
        (indications_Response_contingencyMap, "response_contingency"),
        (indications_Risk_stratificationMap, "risk_stratification"),
    ):
        column = getattr(table, attribute)
        for parent_id, value in session.execute(
            select(table.parent_id, column)
            .where(table.parent_id.in_(ids))
            .order_by(table.parent_id, column)
        ):
            child_values.setdefault((parent_id, attribute), []).append(str(value))
    return child_values


def _biomarker_slots(row, mapped) -> tuple[BiomarkerSource, ...]:
    slots = []
    for slot in (1, 2, 3, 4):
        links = mapped.get((row.id, slot), ())
        if links:
            slots.append(
                BiomarkerSource(
                    slot,
                    tuple(
                        link.biomarker for link in links if link.biomarker is not None
                    ),
                    tuple(
                        link.biomarker_finding
                        for link in links
                        if link.biomarker_finding is not None
                    ),
                    tuple(
                        (link.biomarker, link.biomarker_finding)
                        for link in links
                        if link.aligned
                    ),
                    all(link.aligned for link in links),
                    tuple(link.biomarker_type for link in links),
                )
            )
        elif slot == 1:
            # Scalar/raw-only manually constructed parents remain supported.
            slots.append(
                BiomarkerSource(
                    1,
                    _split(row["biomarker_raw"] or row["biomarker"]),
                    _split(row["biomarker_finding_raw"] or row["biomarker_finding"]),
                )
            )
        else:
            slots.append(BiomarkerSource(slot, (), (), ()))
    return tuple(slots)


def load_indication_sources(
    session, spec: IndicationSpec = DEFAULT_INDICATION_SPEC
) -> tuple[IndicationSource, ...]:
    """Load selected indications and their normalized links in a fixed number of queries."""
    statement = indication_statement(spec).with_only_columns(
        *Indications.__table__.columns
    )
    rows = tuple(session.execute(statement).mappings())
    if not rows:
        return ()
    ids = tuple(row["id"] for row in rows)
    mapped = {}
    for link in session.execute(
        select(indications_BiomarkerSlots.__table__)
        .where(indications_BiomarkerSlots.parent_id.in_(ids))
        .order_by(
            indications_BiomarkerSlots.parent_id,
            indications_BiomarkerSlots.slot,
            indications_BiomarkerSlots.position,
        )
    ).mappings():
        mapped.setdefault((link.parent_id, link.slot), []).append(link)
    regimens = {}
    for link in session.execute(
        select(indications_RegimenLinks.__table__)
        .where(indications_RegimenLinks.parent_id.in_(ids))
        .order_by(indications_RegimenLinks.parent_id, indications_RegimenLinks.position)
    ).mappings():
        regimens.setdefault(link.parent_id, []).append(
            RegimenLink(
                link.regimen,
                link.regimen_cui_raw,
                link.regimen_cui,
                link.with_field,
                link.position,
                link.aligned,
            )
        )

    child_values = _load_child_values(session, ids)

    sources = []
    for row in rows:
        slots = _biomarker_slots(row, mapped)
        raw = {
            column.name: (
                str(getattr(row[column.name], "value", row[column.name]))
                if row[column.name] is not None
                else None
            )
            for column in Indications.__table__.columns
        }
        for chain in Indications.chains:
            for column in chain["columns"]:
                if row[f"{column}_raw"] is not None:
                    raw[column] = row[f"{column}_raw"]
        sources.append(
            IndicationSource(
                row["id"],
                row["condition_cui"],
                row["condition"],
                row["component_cui"],
                row["component"],
                str(getattr(row["regulator"], "value", row["regulator"]))
                if row["regulator"] is not None
                else "",
                row["withdrawn"],
                tuple(slots),
                tuple(
                    link.code
                    for link in regimens.get(row.id, ())
                    if link.aligned and link.code is not None
                ),
                MappingProxyType(raw),
                raw.get("stage"),
                raw.get("status"),
                raw.get("stage_or_status"),
                raw.get("age"),
                raw.get("age_unit"),
                raw.get("prior_therapy"),
                raw.get("sex"),
                bool(row["accelerated"]),
                *(
                    tuple(child_values.get((row.id, attribute), ()))
                    for attribute in (
                        "context",
                        "demographics",
                        "prior_therapy_setting",
                        "prior_therapy_negation",
                        "response_contingency",
                        "risk_stratification",
                    )
                ),
                tuple(regimens.get(row.id, ())),
            )
        )
    return tuple(sources)
