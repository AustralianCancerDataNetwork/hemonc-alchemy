"""Summarising when a regimen variant's drugs are actually given.

`schedule_events` flattens a variant's sigs into one dosing event per sig.
`administration_frame` turns those into a per-drug, per-day picture of a cycle,
which is what you want for comparing regimens by the demand they place on
clinic time versus what a patient takes at home.

    frame = administration_frame(variant)
    frame[frame.route_group == "IV"]

One row per drug per day, so it composes: pivot it for the grid view, group it
to compare variants, join it to anything else keyed on `drug_cui`.

    frame.pivot_table(index="drug", columns="day", values="intensity")

Passing many variants at once gets you one frame to compare across rather than
a frame each. It costs no fewer queries than a loop would -- sigs and drugs are
already batch-loaded when the variants are, so these functions issue none of
their own.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from .....model.enums import (
    Sigs_Cycle_length_unitEnum,
    Sigs_FrequencyEnum,
    Sigs_PhaseEnum,
)
from .handling import Day, Indefinite, resolve_all_days
from .routes import route_group

DEFAULT_DECAY_DAYS = 2
DEFAULT_DECAY_FACTOR = 0.5

_FRAME_COLUMNS = [
    "variant_cui",
    "variant",
    "route_group",
    "drug_cui",
    "drug",
    "day",
    "intensity",
    "optional",
    "indefinite",
    "elapsed_day",
    "timing_status",
]


@dataclass(frozen=True)
class ScheduleEvent:
    """One sig's dosing instruction, with its schedule resolved."""

    sig: Any
    drug_object: Any | None
    route_group: str | None
    days: tuple[Day, ...]
    indefinite: Indefinite | None
    phase: Sigs_PhaseEnum | None
    phase_step: int | None
    portion: str | None
    timing_sequence: str | None
    step_number: str | None
    dose_min: str | None
    dose_max: str | None
    dose_unit: str | None
    frequency: Sigs_FrequencyEnum | None
    cycle_length_lb: str | None
    cycle_length_ub: str | None
    cycle_length_unit: Sigs_Cycle_length_unitEnum | None
    raw_all_days: str | None


def schedule_events(variant) -> list[ScheduleEvent]:
    """One `ScheduleEvent` per sig in `variant`, in the order the sigs come."""
    events = []
    for sig in variant.component_sigs:
        resolved = resolve_all_days(sig.alldays)
        events.append(
            ScheduleEvent(
                sig=sig,
                drug_object=sig.drug_object,
                route_group=route_group(sig.route),
                days=resolved.days,
                indefinite=resolved.indefinite,
                phase=sig.phase,
                phase_step=sig.phase_step,
                portion=sig.portion,
                timing_sequence=sig.timing_sequence,
                step_number=sig.step_number,
                dose_min=sig.doseminnum,
                dose_max=sig.dosemaxnum,
                dose_unit=sig.doseunit,
                frequency=sig.frequency,
                cycle_length_lb=sig.cycle_length_lb,
                cycle_length_ub=sig.cycle_length_ub,
                cycle_length_unit=sig.cycle_length_unit,
                raw_all_days=sig.alldays,
            )
        )
    return events


def _drugs_where(variant, group: str) -> list:
    drugs = {}
    for event in schedule_events(variant):
        drug = event.drug_object
        if event.route_group == group and drug is not None:
            drugs[drug.drug_cui] = drug
    return list(drugs.values())


def _sigs_by_drug_where(variant, group: str) -> dict:
    out = defaultdict(list)
    for event in schedule_events(variant):
        drug = event.drug_object
        if event.route_group == group and drug is not None:
            out[drug].append(event.sig)
    return dict(out)


def cancer_services_drugs(variant) -> list:
    """The distinct drugs in `variant` that need a clinic visit."""
    return _drugs_where(variant, "IV")


def home_administered_drugs(variant) -> list:
    """The distinct drugs in `variant` a patient takes at home."""
    return _drugs_where(variant, "PO")


def cancer_services_sigs_by_drug(variant) -> dict:
    """`{drug: [sigs]}` for the clinic-administered part of `variant`."""
    return _sigs_by_drug_where(variant, "IV")


def home_administered_sigs_by_drug(variant) -> dict:
    """`{drug: [sigs]}` for the home-administered part of `variant`."""
    return _sigs_by_drug_where(variant, "PO")


def _rollout_frame_records(
    variant,
    *,
    decay_days: int,
    decay_factor: float,
) -> list[dict]:
    from .rollout import roll_out_variant

    rolled = roll_out_variant(
        variant,
        decay_days=decay_days,
        decay_factor=decay_factor,
    )
    records = []
    for row in rolled.itertuples(index=False):
        if row.route_group is None or row.drug_cui is None:
            continue
        records.append(
            {
                "variant_cui": row.variant_cui,
                "variant": row.variant,
                "route_group": row.route_group,
                "drug_cui": row.drug_cui,
                "drug": row.drug,
                "day": row.day,
                "intensity": row.intensity,
                "optional": row.optional,
                "indefinite": row.indefinite,
                "elapsed_day": row.elapsed_day,
                "timing_status": row.timing_status,
            }
        )
    return records


def administration_frame(
    variants,
    *,
    decay_days: int = DEFAULT_DECAY_DAYS,
    decay_factor: float = DEFAULT_DECAY_FACTOR,
) -> pd.DataFrame:
    """When each drug is given across a cycle, one row per drug per day.

    Accepts a single variant or any iterable of them. Columns:

    | column | |
    |---|---|
    | `variant_cui`, `variant` | which variant the row belongs to |
    | `route_group` | `"IV"` (clinic) or `"PO"` (home) |
    | `drug_cui`, `drug` | the drug, by identifier and by name |
    | `day` | day of cycle; can be negative for lead-in dosing |
    | `elapsed_day` | variant-relative day when cross-cycle timing resolves |
    | `intensity` | 1.0 on a dosing day, tapering over `decay_days` after |
    | `optional` | whether the dosing day itself was marked optional |
    | `indefinite` | set when the sig continues past its stated days |
    | `timing_status` | whether the rollout is resolved or needs review |

    `intensity` tapers after each dose by `decay_factor` per day for
    `decay_days`, so a treatment day and the days it encroaches on both
    register. Set `decay_days=0` for dosing days alone.

    Rows whose route is unrecognised or not specified are excluded, as are
    sigs with no resolvable days -- including open-ended `EOC` ranges, so a
    variant can legitimately produce no rows. Where `indefinite` is set, the
    days present are only the part that was written down.
    """
    # Duck-typed rather than `isinstance(variants, Iterable)`: entities inherit
    # __iter__ from orm-loader's serialisation interface, so a single variant
    # passes an Iterable check and gets iterated into its own columns.
    if hasattr(variants, "component_sigs"):
        variants = [variants]

    records: list[dict] = []

    for variant in variants:
        records.extend(_rollout_frame_records(
            variant,
            decay_days=decay_days,
            decay_factor=decay_factor,
        ))

    if not records:
        return pd.DataFrame(columns=_FRAME_COLUMNS)

    frame = pd.DataFrame.from_records(records, columns=_FRAME_COLUMNS)

    # One drug can be dosed by several sigs in the same variant, and their
    # decay tails can land on the same day; keep the strongest.
    grouped = (
        frame.groupby(
            [
                "variant_cui", "variant", "route_group", "drug_cui", "drug",
                "day", "elapsed_day",
            ],
            as_index=False,
            dropna=False,
        )
        .agg(intensity=("intensity", "max"), optional=("optional", "all"),
             indefinite=("indefinite", "first"), timing_status=("timing_status", "first"))
    )
    return grouped[_FRAME_COLUMNS].sort_values(
        ["variant_cui", "route_group", "drug", "elapsed_day", "day"], ignore_index=True
    )


def administration_matrix(frame: pd.DataFrame, route: str = "IV") -> pd.DataFrame:
    """A drug-by-day grid for one route group, from `administration_frame`.

    The grid view: drugs down the side, cycle days across the top, zero where
    a drug isn't given. Days with no dosing at all are still omitted -- pass a
    reindexed frame if you need a contiguous calendar.
    """
    subset = frame[frame["route_group"] == route]
    if subset.empty:
        return pd.DataFrame()
    return subset.pivot_table(
        index="drug", columns="day", values="intensity", aggfunc="max", fill_value=0.0
    )
