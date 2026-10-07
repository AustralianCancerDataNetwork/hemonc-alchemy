"""Summarising a variant as one cycle's worth of drug-by-day grids."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import pandas as pd  # type: ignore[import-untyped]

from ....core.links import variant_condition_objects
from ..classification import (
    ComponentRole,
    is_endocrine_block,
    is_endocrine_regimen,
    is_supportive_block,
    is_supportive_regimen,
)
from .properties import (
    DEFAULT_DECAY_FACTOR,
    ScheduleEvent,
    administration_frame,
    administration_matrix,
    cancer_services_drugs,
    home_administered_drugs,
    schedule_events,
)
from .rollout import CycleBlock, group_into_blocks, roll_out_phase

_CYCLE_UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}


@dataclass(frozen=True)
class ChoiceSchedule:
    """One source instruction allowing a dose on any one of several cycle days."""

    drugs: tuple[str, ...]
    route_group: str
    options: tuple[int, ...]


@dataclass(frozen=True)
class CycleTemplate:
    """One variant's cycle, as day x drug grids plus its identifying fields."""

    id: str
    common_name: str
    cycle_len: int
    diseases: set[str]
    iv_drug: list[str]
    po_drug: list[str]
    binary_iv: pd.DataFrame
    binary_po: pd.DataFrame
    binary_fuzzy: pd.DataFrame
    dose_iv: pd.DataFrame
    dose_po: pd.DataFrame
    endocrine_regimen: bool
    supportive_regimen: bool
    # Empty here -- needs a live OMOP session, so it's filled in afterward by
    # `integrations.omop.component_role.attach_component_roles`.
    drug_role: dict[str, ComponentRole]
    # Source day alternatives; they are deliberately not expanded into multiple doses.
    choices: tuple[ChoiceSchedule, ...] = ()


def _cycle_length_from_bound(lb: str, unit) -> int:
    """A cycle-length lower bound plus unit, converted to a day count."""
    unit_key = getattr(unit, "value", unit).lower()
    if unit_key not in _CYCLE_UNIT_DAYS:
        raise ValueError(f"unsupported cycle length unit {unit_key!r}")
    try:
        number = Decimal(str(lb))
    except InvalidOperation as exc:
        raise ValueError(f"cycle length bound {lb!r} is not numeric") from exc
    return int(number * _CYCLE_UNIT_DAYS[unit_key])


def _cycle_length_days(variant) -> int:
    """The variant's cycle length in days, from its sigs' shared cycle bound."""
    lengths = {
        (event.cycle_length_lb, event.cycle_length_unit)
        for event in schedule_events(variant)
        if event.cycle_length_lb is not None and event.cycle_length_unit is not None
    }
    if len(lengths) != 1:
        raise ValueError("variant has no single resolvable cycle length")
    (lb, unit), = lengths
    return _cycle_length_from_bound(lb, unit)


def _block_cycle_length_days(block: CycleBlock) -> int:
    """The block's cycle length in days, from its own cycle bound."""
    if block.cycle_length_lb is None or block.cycle_length_unit is None:
        raise ValueError("block has no resolvable cycle length")
    return _cycle_length_from_bound(block.cycle_length_lb, block.cycle_length_unit)


def _day_by_drug_grid(frame: pd.DataFrame, route: str, cycle_len: int, drugs: list[str]) -> pd.DataFrame:
    """0-indexed day x drug intensity grid, reindexed to a full cycle."""
    matrix = administration_matrix(frame, route)
    matrix = matrix.T if not matrix.empty else pd.DataFrame(index=[])
    matrix.index = matrix.index - 1
    return matrix.reindex(index=range(cycle_len), columns=drugs, fill_value=0.0)


def _binary_matrix(frame: pd.DataFrame, route: str, cycle_len: int, drugs: list[str]) -> pd.DataFrame:
    return (_day_by_drug_grid(frame, route, cycle_len, drugs) > 0).astype(int)


def _fuzzy_matrix(frame: pd.DataFrame, route: str, cycle_len: int, drugs: list[str]) -> pd.DataFrame:
    """Day x drug decay grid, from `frame`'s already-decayed `intensity` (see `administration_frame`)."""
    return _day_by_drug_grid(frame, route, cycle_len, drugs)


def _dose_matrix(events: Iterable[ScheduleEvent], route: str, drugs: list[str]) -> pd.DataFrame:
    records = []
    for event in events:
        if event.route_group != route or event.drug_object is None:
            continue
        dose = f"{event.dose_min};{event.dose_unit}" if event.dose_min is not None else ""
        for day in event.days:
            records.append({"day": day.value - 1, "drug": event.drug_object.drug, "dose": dose})
    if not records:
        return pd.DataFrame(columns=drugs)
    table = pd.DataFrame.from_records(records).pivot_table(
        index="day", columns="drug", values="dose", aggfunc="first", fill_value=""
    )
    return table.reindex(columns=drugs, fill_value="")


def cycle_template(variant) -> CycleTemplate:
    """One cycle's drug-by-day grids and identifying fields for `variant`."""
    cycle_len = _cycle_length_days(variant)
    iv_drug = [drug.drug for drug in cancer_services_drugs(variant)]
    po_drug = [drug.drug for drug in home_administered_drugs(variant)]
    frame = administration_frame(variant, decay_days=0)
    # A dose on day 1 needs decay rows out to cycle_len-1 to cover the rest of the cycle.
    fuzzy_frame = administration_frame(variant, decay_days=max(cycle_len - 1, 0))
    diseases = {condition.condition for condition in variant_condition_objects(variant)}

    return CycleTemplate(
        id=f"{variant.regimen}{variant.variant_cui}",
        common_name=variant.regimen,
        cycle_len=cycle_len,
        diseases=diseases,
        iv_drug=iv_drug,
        po_drug=po_drug,
        binary_iv=_binary_matrix(frame, "IV", cycle_len, iv_drug),
        binary_po=_binary_matrix(frame, "PO", cycle_len, po_drug),
        # RG_uniq's own Binary_fuzzy is IV-only; decay models episodic dosing, not daily oral intake.
        binary_fuzzy=_fuzzy_matrix(fuzzy_frame, "IV", cycle_len, iv_drug),
        dose_iv=_dose_matrix(schedule_events(variant), "IV", iv_drug),
        dose_po=_dose_matrix(schedule_events(variant), "PO", po_drug),
        endocrine_regimen=is_endocrine_regimen(variant),
        supportive_regimen=is_supportive_regimen(variant),
        drug_role={},
        choices=tuple(
            ChoiceSchedule((event.drug_object.drug,), event.route_group, tuple(choice.options))
            for event in schedule_events(variant)
            if event.drug_object is not None and event.route_group in {"IV", "PO"} and event.choices
            for choice in event.choices
        ),
    )


@dataclass(frozen=True)
class CycleBlockTemplate:
    """One `CycleBlock`'s `CycleTemplate`, paired with how many cycles it repeats for."""

    template: CycleTemplate
    repeat_count: int


def _block_drugs(events: Iterable[ScheduleEvent], route: str) -> list:
    """Distinct drugs among `events` on `route`, in first-seen order."""
    drugs = {}
    for event in events:
        if event.route_group == route and event.drug_object is not None:
            drugs[event.drug_object.drug_cui] = event.drug_object
    return list(drugs.values())


def _block_frame(block: CycleBlock, *, decay_days: int, decay_factor: float = DEFAULT_DECAY_FACTOR) -> pd.DataFrame:
    """`administration_frame`'s per-day drug grid, rolled out from one block alone."""
    records = []
    for event in roll_out_phase([block], 0, decay_days=decay_days, decay_factor=decay_factor):
        source = event.schedule_event
        if source.route_group is None or source.drug_object is None:
            continue
        records.append({
            "route_group": source.route_group,
            "drug_cui": source.drug_object.drug_cui,
            "drug": source.drug_object.drug,
            "day": event.day,
            "intensity": event.intensity,
        })
    if not records:
        return pd.DataFrame(columns=["route_group", "drug_cui", "drug", "day", "intensity"])
    frame = pd.DataFrame.from_records(records)
    return frame.groupby(["route_group", "drug_cui", "drug", "day"], as_index=False).agg(
        intensity=("intensity", "max")
    )


def _block_template(variant, block: CycleBlock, *, diseases) -> CycleTemplate:
    """`cycle_template`'s per-variant logic, scoped to one `CycleBlock`'s own events.

    Modality (endocrine/supportive) is classified from this block's own drugs, not
    the parent variant's -- a block's `iv_drug`/`po_drug` are already block-scoped, and a
    mixed-modality variant (e.g. an endocrine-only block followed by a targeted-therapy one)
    would otherwise mislabel every block with the whole variant's, generally impure, mix.
    """
    cycle_len = _block_cycle_length_days(block)
    iv_drug = [drug.drug for drug in _block_drugs(block.events, "IV")]
    po_drug = [drug.drug for drug in _block_drugs(block.events, "PO")]
    frame = _block_frame(block, decay_days=0)
    # A dose on day 1 needs decay rows out to cycle_len-1 to cover the rest of the cycle.
    fuzzy_frame = _block_frame(block, decay_days=max(cycle_len - 1, 0))

    return CycleTemplate(
        id=f"{variant.regimen}{variant.variant_cui}",
        common_name=variant.regimen,
        cycle_len=cycle_len,
        diseases=diseases,
        iv_drug=iv_drug,
        po_drug=po_drug,
        binary_iv=_binary_matrix(frame, "IV", cycle_len, iv_drug),
        binary_po=_binary_matrix(frame, "PO", cycle_len, po_drug),
        binary_fuzzy=_fuzzy_matrix(fuzzy_frame, "IV", cycle_len, iv_drug),
        dose_iv=_dose_matrix(block.events, "IV", iv_drug),
        dose_po=_dose_matrix(block.events, "PO", po_drug),
        endocrine_regimen=is_endocrine_block(block.events),
        supportive_regimen=is_supportive_block(block.events),
        drug_role={},
        choices=tuple(
            ChoiceSchedule((event.drug_object.drug,), event.route_group, tuple(choice.options))
            for event in block.events
            if event.drug_object is not None and event.route_group in {"IV", "PO"} and event.choices
            for choice in event.choices
        ),
    )


def cycle_block_templates(variant) -> tuple[CycleBlockTemplate, ...]:
    """`variant`'s cycle blocks in order, each as a `CycleTemplate` paired with its repeat count."""
    blocks = group_into_blocks(schedule_events(variant))
    diseases = {condition.condition for condition in variant_condition_objects(variant)}

    return tuple(
        CycleBlockTemplate(
            template=_block_template(variant, block, diseases=diseases),
            repeat_count=len(block.cycle_numbers),
        )
        for block in blocks
    )
