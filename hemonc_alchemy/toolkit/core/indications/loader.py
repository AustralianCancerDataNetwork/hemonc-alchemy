"""Bounded-query loader for indication source records."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from sqlalchemy import select

from ....model import (
    Indications,
    indications_Biomarker2_findingMap,
    indications_Biomarker2Map,
    indications_Biomarker3_findingMap,
    indications_Biomarker3Map,
    indications_Biomarker4_findingMap,
    indications_Biomarker4Map,
    indications_ContextMap,
    indications_DemographicsMap,
    indications_Prior_therapy_negationMap,
    indications_Prior_therapy_settingMap,
    indications_Regimen_cuiMap,
    indications_Response_contingencyMap,
    indications_Risk_stratificationMap,
)
from ..catalogue.indications import indication_statement
from ..catalogue.specs import DEFAULT_INDICATION_SPEC, IndicationSpec


@dataclass(frozen=True)
class BiomarkerSource:
    slot: int
    biomarkers: tuple[str, ...]
    findings: tuple[str, ...]


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


def _split(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(
        dict.fromkeys(part.strip() for part in value.split("|") if part.strip())
    )


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
    tables = (
        (2, indications_Biomarker2Map, "biomarker2"),
        (2, indications_Biomarker2_findingMap, "biomarker2_finding"),
        (3, indications_Biomarker3Map, "biomarker3"),
        (3, indications_Biomarker3_findingMap, "biomarker3_finding"),
        (4, indications_Biomarker4Map, "biomarker4"),
        (4, indications_Biomarker4_findingMap, "biomarker4_finding"),
    )
    for slot, table, attribute in tables:
        column = getattr(table, attribute)
        for parent_id, value in session.execute(
            select(table.parent_id, column)
            .where(table.parent_id.in_(ids))
            .order_by(table.parent_id, column)
        ):
            mapped.setdefault((parent_id, slot, attribute), []).append(
                str(getattr(value, "value", value)) if value is not None else None
            )
    regimens = {}
    for parent_id, regimen_cui in session.execute(
        select(
            indications_Regimen_cuiMap.parent_id, indications_Regimen_cuiMap.regimen_cui
        )
        .where(indications_Regimen_cuiMap.parent_id.in_(ids))
        .order_by(
            indications_Regimen_cuiMap.parent_id, indications_Regimen_cuiMap.regimen_cui
        )
    ):
        regimens.setdefault(parent_id, []).append(regimen_cui)

    child_values = _load_child_values(session, ids)

    sources = []
    for row in rows:
        slots = [
            BiomarkerSource(
                1,
                _split(
                    str(getattr(row["biomarker"], "value", row["biomarker"]))
                    if row["biomarker"] is not None
                    else None
                ),
                _split(
                    str(
                        getattr(
                            row["biomarker_finding"],
                            "value",
                            row["biomarker_finding"],
                        )
                    )
                    if row["biomarker_finding"] is not None
                    else None
                ),
            )
        ]
        for slot in (2, 3, 4):
            name, finding = f"biomarker{slot}", f"biomarker{slot}_finding"
            slots.append(
                BiomarkerSource(
                    slot,
                    tuple(mapped.get((row.id, slot, name), ())),
                    tuple(mapped.get((row.id, slot, finding), ())),
                )
            )
        raw = {
            column.name: (
                str(getattr(row[column.name], "value", row[column.name]))
                if row[column.name] is not None
                else None
            )
            for column in Indications.__table__.columns
        }
        for slot in (2, 3, 4):
            raw[f"biomarker{slot}"] = "|".join(slots[slot - 1].biomarkers) or None
            raw[f"biomarker{slot}_finding"] = "|".join(slots[slot - 1].findings) or None
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
                tuple(regimens.get(row.id, ())),
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
            )
        )
    return tuple(sources)
