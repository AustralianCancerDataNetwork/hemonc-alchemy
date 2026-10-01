"""Roll sig schedules out onto a variant-relative treatment timeline.

The source ``day`` value is local to one cycle.  This module adds the missing
context: cycle numbers, cycle lengths, block anchors, and phase boundaries.
It deliberately keeps the rollout deterministic.  An indefinite source
marker is retained as metadata; it is never sampled here.

Phases are ordered by each sig's own ``phase_step``, the same rule for every
phase label. A missing, tied, or internally inconsistent step is unresolved
rather than guessed.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, cast

import pandas as pd  # type: ignore[import-untyped]

from .....model.enums import Sigs_Cycle_length_unitEnum, Sigs_PhaseEnum
from ..classification import RAD_SIG_CLASS_VALUE, sig_class_value
from .handling import Indefinite, apply_sig_to_series, resolve_all_days
from .properties import ScheduleEvent, schedule_events


@dataclass(frozen=True)
class UnresolvedTiming:
    """A source-timing problem that must remain visible to callers."""

    reason: str

    @property
    def status(self) -> str:
        return f"unresolved: {self.reason}"


@dataclass(frozen=True)
class CycleBlock:
    """Events sharing a cycle length and a contiguous cycle-number set."""

    events: tuple[ScheduleEvent, ...]
    cycle_numbers: frozenset[int]
    cycle_length_lb: str | None
    cycle_length_ub: str | None
    cycle_length_unit: Sigs_Cycle_length_unitEnum | None
    timing_indefinite: Indefinite | None = None
    optional_cycles: frozenset[int] = frozenset()

    @property
    def first_cycle(self) -> int | None:
        return min(self.cycle_numbers) if self.cycle_numbers else None

    @property
    def last_cycle(self) -> int | None:
        return max(self.cycle_numbers) if self.cycle_numbers else None

    @property
    def is_contiguous(self) -> bool:
        if not self.cycle_numbers:
            return False
        first_cycle = cast(int, self.first_cycle)
        last_cycle = cast(int, self.last_cycle)
        return len(self.cycle_numbers) == last_cycle - first_cycle + 1


@dataclass(frozen=True)
class AnchoredBlock:
    """A block plus the relationship that determines its start point."""

    block: CycleBlock
    anchor_kind: str
    anchor_block: CycleBlock | None = None
    anchor_cycle: int | None = None
    unresolved: UnresolvedTiming | None = None
    overlap_candidates: tuple[CycleBlock, ...] = ()

    @property
    def timing_status(self) -> str:
        if self.unresolved is not None:
            return self.unresolved.status
        return "resolved"


@dataclass(frozen=True)
class TimedEvent:
    """One event/day result from a rolled-out block."""

    schedule_event: ScheduleEvent
    phase: Sigs_PhaseEnum | None
    phase_step: int | None
    cycle_number: int | None
    day: int | None
    elapsed_day: int | None
    calendar_date: date | None
    intensity: float
    optional: bool
    cycle_indefinite: Indefinite | None
    timing_status: str


def _event_series(
    event: ScheduleEvent,
    *,
    decay_days: int,
    decay_factor: float,
) -> dict[int, float]:
    series: dict[int, float] = defaultdict(float)
    apply_sig_to_series(
        series,
        list(event.days),
        decay_days=decay_days,
        decay_factor=decay_factor,
    )
    return series


def _timing_numbers(
    value: str | None,
) -> tuple[frozenset[int], Indefinite | None, frozenset[int]]:
    try:
        resolved = resolve_all_days(value)
    except (TypeError, ValueError):
        return frozenset(), None, frozenset()
    return (
        frozenset(day.value for day in resolved.days),
        resolved.indefinite,
        frozenset(day.value for day in resolved.days if day.optional),
    )


def group_into_blocks(events: Iterable[ScheduleEvent]) -> list[CycleBlock]:
    """Group schedule events by cycle length and parsed cycle numbers."""

    grouped: dict[tuple[Any, ...], list[ScheduleEvent]] = {}
    for event in events:
        cycle_numbers, indefinite, optional_cycles = _timing_numbers(event.timing_sequence)
        key = (
            event.cycle_length_lb,
            event.cycle_length_ub,
            event.cycle_length_unit,
            cycle_numbers,
            indefinite,
            optional_cycles,
        )
        grouped.setdefault(key, []).append(event)

    blocks = []
    for key, block_events in grouped.items():
        cycle_numbers, indefinite, optional_cycles = key[3:]
        blocks.append(
            CycleBlock(
                events=tuple(block_events),
                cycle_numbers=cycle_numbers,
                cycle_length_lb=key[0],
                cycle_length_ub=key[1],
                cycle_length_unit=key[2],
                timing_indefinite=indefinite,
                optional_cycles=optional_cycles,
            )
        )
    return sorted(
        blocks,
        key=lambda block: (
            block.first_cycle is None,
            block.first_cycle if block.first_cycle is not None else 0,
            block.last_cycle if block.last_cycle is not None else 0,
        ),
    )


def _overlap_conflict(block: CycleBlock, overlaps: list[AnchoredBlock]) -> UnresolvedTiming | None:
    length = (block.cycle_length_lb, block.cycle_length_ub, block.cycle_length_unit)
    shared = set().union(*(
        prior.block.cycle_numbers & block.cycle_numbers for prior in overlaps
    ))
    if len(shared) > 1 and any(
        (prior.block.cycle_length_lb, prior.block.cycle_length_ub, prior.block.cycle_length_unit)
        != length for prior in overlaps
    ):
        return UnresolvedTiming(
            f"cycle lengths differ across shared cycles {min(shared)}-{max(shared)}"
        )
    return None


def anchor_blocks(
    blocks: Iterable[CycleBlock], *, preceding_cycle: int | None = None
) -> list[AnchoredBlock]:
    """Assign sequential, overlapping, or unresolved block anchors."""

    ordered = sorted(
        blocks,
        key=lambda block: (
            block.first_cycle is None,
            block.first_cycle if block.first_cycle is not None else 0,
            block.last_cycle if block.last_cycle is not None else 0,
        ),
    )
    anchored: list[AnchoredBlock] = []

    for index, block in enumerate(ordered):
        if not block.cycle_numbers:
            anchored.append(
                AnchoredBlock(
                    block=block,
                    anchor_kind="unresolved",
                    unresolved=UnresolvedTiming("missing cycle numbers"),
                )
            )
            continue
        if not block.is_contiguous:
            anchored.append(
                AnchoredBlock(
                    block=block,
                    anchor_kind="unresolved",
                    unresolved=UnresolvedTiming(
                        f"non-contiguous cycle numbers {sorted(block.cycle_numbers)}"
                    ),
                )
            )
            continue
        if index == 0:
            first_cycle = cast(int, block.first_cycle)
            # Cycle numbers may continue when the preceding phase ends immediately before.
            if first_cycle > 1 and preceding_cycle != first_cycle - 1:
                anchored.append(
                    AnchoredBlock(
                        block=block,
                        anchor_kind="unresolved",
                        unresolved=UnresolvedTiming(
                            f"missing preceding cycles before cycle {block.first_cycle}"
                        ),
                    )
                )
                continue
            anchored.append(
                AnchoredBlock(
                    block=block,
                    anchor_kind="phase_start",
                    anchor_cycle=block.first_cycle,
                )
            )
            continue

        overlaps = [
            prior
            for prior in anchored
            if prior.block.cycle_numbers & block.cycle_numbers
        ]
        if overlaps:
            if conflict := _overlap_conflict(block, overlaps):
                anchored.append(
                    AnchoredBlock(
                        block=block,
                        anchor_kind="unresolved",
                        unresolved=conflict,
                    )
                )
                continue
            shared = set().union(*(
                prior.block.cycle_numbers & block.cycle_numbers for prior in overlaps
            ))
            anchored.append(
                AnchoredBlock(
                    block=block,
                    anchor_kind="overlap",
                    anchor_block=overlaps[-1].block,
                    anchor_cycle=min(shared),
                    overlap_candidates=tuple(prior.block for prior in overlaps),
                )
            )
            continue

        previous = ordered[index - 1]
        if previous.last_cycle is not None and block.first_cycle == previous.last_cycle + 1:
            predecessors = [
                prior.block for prior in anchored
                if prior.block.last_cycle == previous.last_cycle
            ]
            lengths = {
                (prior.cycle_length_lb, prior.cycle_length_ub, prior.cycle_length_unit)
                for prior in predecessors
            }
            if len(lengths) > 1:
                anchored.append(
                    AnchoredBlock(
                        block=block,
                        anchor_kind="unresolved",
                        unresolved=UnresolvedTiming(
                            f"blocks ending cycle {previous.last_cycle} differ in cycle length"
                        ),
                    )
                )
                continue
            anchored.append(
                AnchoredBlock(
                    block=block,
                    anchor_kind="after",
                    anchor_block=previous,
                    anchor_cycle=block.first_cycle,
                )
            )
            continue

        anchored.append(
            AnchoredBlock(
                block=block,
                anchor_kind="unresolved",
                unresolved=UnresolvedTiming(
                    f"cycle gap or contradiction before cycles {sorted(block.cycle_numbers)}"
                ),
            )
        )

    return anchored


def _day_offset(day: int) -> int:
    """0-based offset from cycle day 1; a negative lead-in day keeps its value."""
    return day - 1 if day >= 1 else day


def _unit_value(unit: Sigs_Cycle_length_unitEnum | str | None) -> str | None:
    if unit is None:
        return None
    return getattr(unit, "value", unit).lower()


def _parse_bound(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None


def _length_number(block: CycleBlock, selection: str) -> Decimal:
    if selection not in {"lb", "ub", "mean"}:
        raise ValueError("cycle_length_selection must be 'lb', 'ub', or 'mean'")
    lower = _parse_bound(block.cycle_length_lb)
    upper = _parse_bound(block.cycle_length_ub)
    # One bound fills in for the other when only one is numeric, so a sig
    # missing just lb or just ub still resolves under any selection.
    if selection == "lb":
        value = lower if lower is not None else upper
    elif selection == "ub":
        value = upper if upper is not None else lower
    elif lower is not None and upper is not None:
        value = (lower + upper) / 2
    else:
        value = lower if lower is not None else upper
    if value is None:
        raise ValueError("cycle length is not numeric")
    return value


def _calendar_add(value: date, number: int, unit: str) -> date:
    if unit == "day":
        return value + timedelta(days=number)
    if unit == "week":
        return value + timedelta(days=number * 7)
    if unit == "month":
        month_index = value.month - 1 + number
        year, month_index = divmod(value.year * 12 + month_index, 12)
        month = month_index + 1
        day = min(value.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)
    if unit == "year":
        year = value.year + number
        day = min(value.day, calendar.monthrange(year, value.month)[1])
        return date(year, value.month, day)
    raise ValueError(f"unsupported calendar cycle unit {unit!r}")


def _advance(
    start: int | date,
    block: CycleBlock,
    cycles: int,
    *,
    selection: str,
) -> int | date:
    unit = _unit_value(block.cycle_length_unit)
    if unit not in {"day", "week", "month", "year"}:
        raise ValueError("cycle length has no resolvable unit")
    number = _length_number(block, selection)

    if isinstance(start, date):
        if number != number.to_integral_value():
            raise ValueError("calendar cycle length is not a whole number")
        if unit in {"month", "year"}:
            units = int(number) * cycles
            return _calendar_add(start, units, unit)
        days = int(number) * (7 if unit == "week" else 1) * cycles
        return start + timedelta(days=days)

    if unit == "month":
        number *= 30
    elif unit == "week":
        number *= 7
    elif unit == "year":
        number *= 365
    if number != number.to_integral_value():
        raise ValueError("elapsed cycle length is not a whole number of days")
    return start + int(number) * cycles


def _block_start(
    anchored: AnchoredBlock,
    starts: dict[int, int | date],
    ends: dict[int, int | date],
    phase_start: int | date,
    *,
    selection: str,
) -> int | date | None:
    if anchored.unresolved is not None:
        return None
    if anchored.anchor_kind == "phase_start":
        return phase_start
    if anchored.anchor_kind == "overlap":
        # Every overlapping prior must imply the same start; picking just one
        # (as if the others didn't exist) would hide a real disagreement.
        anchor_cycle = cast(int, anchored.anchor_cycle)
        implied: set[int | date] = set()
        for candidate in anchored.overlap_candidates:
            candidate_start = starts.get(id(candidate))
            if candidate_start is None:
                continue
            try:
                cycle_delta = anchor_cycle - min(candidate.cycle_numbers)
                implied.add(
                    _advance(candidate_start, candidate, cycle_delta, selection=selection)
                )
            except ValueError:
                continue
        if len(implied) != 1:
            return None
        return next(iter(implied))
    if anchored.anchor_block is None:
        return None
    parent_start = starts.get(id(anchored.anchor_block))
    if parent_start is None:
        return None
    if anchored.anchor_kind == "after":
        return ends.get(id(anchored.anchor_block))
    return None


def _phase_end(
    anchored_blocks: list[AnchoredBlock],
    phase_start: int | date,
    *,
    selection: str,
) -> int | date | None:
    starts: dict[int, int | date] = {}
    ends: dict[int, int | date] = {}
    for anchored in anchored_blocks:
        start = _block_start(anchored, starts, ends, phase_start, selection=selection)
        if start is None:
            continue
        starts[id(anchored.block)] = start
        if anchored.block.timing_indefinite is not None:
            continue
        last_cycle = cast(int, anchored.block.last_cycle)
        anchor_cycle = cast(int, anchored.anchor_cycle)
        try:
            end = _advance(
                start,
                anchored.block,
                last_cycle - anchor_cycle + 1,
                selection=selection,
            )
        except (TypeError, ValueError):
            continue
        ends[id(anchored.block)] = end
    if not anchored_blocks or any(
        block.unresolved is not None or block.block.timing_indefinite is not None
        for block in anchored_blocks
    ):
        return None
    if len(ends) != len(anchored_blocks):
        return None
    return max(ends.values())


def _optional_for_day(
    event: ScheduleEvent, day: int, block: CycleBlock, cycle_number: int | None
) -> bool:
    return cycle_number in block.optional_cycles or any(
        source_day.value == day and source_day.optional for source_day in event.days
    )


def _choice_status(event: ScheduleEvent) -> str:
    options = ", ".join("|".join(map(str, choice.options)) for choice in event.choices)
    return f"unresolved: choice of days {options}, not resolved"


def _choice_placeholder_events(
    event: ScheduleEvent,
    cycle_numbers: Iterable[int | None],
    base_status: str,
    cycle_indefinite: Indefinite | None,
) -> list[TimedEvent]:
    """A row for a component whose only timing is an unresolved Choice.
    """
    status = _combine_status(base_status, _choice_status(event))
    return [
        TimedEvent(
            schedule_event=event,
            phase=event.phase,
            phase_step=event.phase_step,
            cycle_number=cycle_number,
            day=None,
            elapsed_day=None,
            calendar_date=None,
            intensity=1.0,
            optional=False,
            cycle_indefinite=cycle_indefinite,
            timing_status=status,
        )
        for cycle_number in cycle_numbers
    ]


def _unresolved_block_events(
    block: CycleBlock,
    status: UnresolvedTiming,
    *,
    decay_days: int,
    decay_factor: float,
) -> list[TimedEvent]:
    output = []
    cycle_numbers: list[int | None] = cast(list[int | None], sorted(block.cycle_numbers)) or [None]
    for event in block.events:
        series = _event_series(event, decay_days=decay_days, decay_factor=decay_factor)
        if not series and event.choices:
            output.extend(
                _choice_placeholder_events(
                    event, cycle_numbers, status.status, block.timing_indefinite
                )
            )
            continue
        for cycle_number in cycle_numbers:
            for day, intensity in series.items():
                output.append(
                    TimedEvent(
                        schedule_event=event,
                        phase=event.phase,
                        phase_step=event.phase_step,
                        cycle_number=cycle_number,
                        day=day,
                        elapsed_day=None,
                        calendar_date=None,
                        intensity=intensity,
                        optional=_optional_for_day(event, day, block, cycle_number),
                        cycle_indefinite=block.timing_indefinite,
                        timing_status=status.status,
                    )
                )
    return output


def _resolved_block_events(
    anchored: AnchoredBlock,
    start: int | date,
    *,
    selection: str,
    decay_days: int,
    decay_factor: float,
) -> list[TimedEvent]:
    output = []
    block = anchored.block
    anchor_cycle = cast(int, anchored.anchor_cycle)
    for event in block.events:
        series = _event_series(event, decay_days=decay_days, decay_factor=decay_factor)
        if not series and event.choices:
            output.extend(
                _choice_placeholder_events(
                    event,
                    sorted(block.cycle_numbers),
                    anchored.timing_status,
                    block.timing_indefinite,
                )
            )
            continue
        for cycle_number in sorted(block.cycle_numbers):
            cycle_start = _advance(
                start,
                block,
                cycle_number - anchor_cycle,
                selection=selection,
            )
            for day, intensity in series.items():
                offset = _day_offset(day)
                if isinstance(cycle_start, date):
                    calendar_date = cycle_start + timedelta(days=offset)
                    elapsed_day = None
                else:
                    calendar_date = None
                    elapsed_day = cycle_start + offset
                output.append(
                    TimedEvent(
                        schedule_event=event,
                        phase=event.phase,
                        phase_step=event.phase_step,
                        cycle_number=cycle_number,
                        day=day,
                        elapsed_day=elapsed_day,
                        calendar_date=calendar_date,
                        intensity=intensity,
                        optional=_optional_for_day(event, day, block, cycle_number),
                        cycle_indefinite=block.timing_indefinite,
                        timing_status=anchored.timing_status,
                    )
                )
    return output


def roll_out_phase(
    blocks: Iterable[CycleBlock] | Iterable[AnchoredBlock],
    phase_start: int | date,
    *,
    cycle_length_selection: str = "lb",
    decay_days: int = 2,
    decay_factor: float = 0.5,
) -> list[TimedEvent]:
    """Roll one phase out from its own start point.

    ``phase_start`` is an integer elapsed-day offset or a ``date``.  Unresolved
    blocks still produce rows with null timeline values and an explicit status.
    """

    block_list: list[CycleBlock | AnchoredBlock] = list(blocks)
    anchored: list[AnchoredBlock]
    if all(isinstance(block, AnchoredBlock) for block in block_list):
        anchored = cast(list[AnchoredBlock], block_list)
    else:
        anchored = anchor_blocks(cast(list[CycleBlock], block_list))
    starts: dict[int, int | date] = {}
    ends: dict[int, int | date] = {}
    output: list[TimedEvent] = []

    for anchored_block in anchored:
        block = anchored_block.block
        start = _block_start(
            anchored_block,
            starts,
            ends,
            phase_start,
            selection=cycle_length_selection,
        )
        if start is not None:
            try:
                end = _advance(
                    start,
                    block,
                    1 if block.timing_indefinite is not None
                    else cast(int, block.last_cycle) - cast(int, anchored_block.anchor_cycle) + 1,
                    selection=cycle_length_selection,
                )
            except (TypeError, ValueError):
                start = None
            else:
                starts[id(block)] = start
                if block.timing_indefinite is None:
                    ends[id(block)] = end

        if start is None:
            status = anchored_block.unresolved or UnresolvedTiming(
                "anchor depends on unresolved timing"
            )
            output.extend(
                _unresolved_block_events(
                    block,
                    status,
                    decay_days=decay_days,
                    decay_factor=decay_factor,
                )
            )
            continue

        output.extend(
            _resolved_block_events(
                anchored_block,
                start,
                selection=cycle_length_selection,
                decay_days=decay_days,
                decay_factor=decay_factor,
            )
        )
    return output


def _phase_groups(events: list[ScheduleEvent]) -> list[tuple[Any, list[ScheduleEvent]]]:
    groups: dict[Any, list[ScheduleEvent]] = {}
    for event in events:
        groups.setdefault(event.phase, []).append(event)
    return list(groups.items())


def _phase_order(
    groups: list[tuple[Any, list[ScheduleEvent]]],
) -> tuple[list[tuple[Any, list[ScheduleEvent], str]], str]:
    if len(groups) <= 1:
        return [(phase, events, "resolved") for phase, events in groups], "resolved"

    phase_steps: dict[Any, int | None] = {}
    inconsistent: list[Any] = []
    for phase, events in groups:
        steps = {event.phase_step for event in events}
        if len(steps) != 1:
            inconsistent.append(phase)
            phase_steps[phase] = None
        else:
            phase_steps[phase] = next(iter(steps))

    if inconsistent:
        reason = "phase_step inconsistent within " + ", ".join(map(str, inconsistent))
        status = f"unresolved: {reason}"
        return [(phase, events, status) for phase, events in groups], status

    missing = [phase for phase, step in phase_steps.items() if step is None]
    if missing:
        reason = "no phase_step for " + ", ".join(str(phase) for phase in missing)
        status = f"unresolved: {reason}"
        return [(phase, events, status) for phase, events in groups], status

    if len(set(phase_steps.values())) != len(phase_steps):
        tied = [str(phase) for phase, step in phase_steps.items() if list(phase_steps.values()).count(step) > 1]
        reason = "phase_step tie between " + ", ".join(tied)
        status = f"unresolved: {reason}"
        return [(phase, events, status) for phase, events in groups], status

    resolved_steps: dict[Any, int] = {
        phase: step for phase, step in phase_steps.items() if step is not None
    }
    ordered = sorted(groups, key=lambda item: resolved_steps[item[0]])
    return [(phase, events, "resolved") for phase, events in ordered], "resolved"


def _combine_status(*statuses: str) -> str:
    if any(status.startswith("unresolved:") for status in statuses):
        reasons = [
            reason
            for status in statuses if status.startswith("unresolved:")
            for reason in status.removeprefix("unresolved: ").split("; ")
        ]
        return "unresolved: " + "; ".join(dict.fromkeys(reasons))
    fallbacks = [
        reason
        for status in statuses if status.startswith("resolved_via_fallback:")
        for reason in status.removeprefix("resolved_via_fallback: ").split("; ")
    ]
    if fallbacks:
        return "resolved_via_fallback: " + "; ".join(dict.fromkeys(fallbacks))
    return "resolved"


def _optional_cycle_status(cycles: Iterable[int]) -> str:
    numbers = sorted(set(cycles))
    if not numbers:
        return "resolved"
    label = "cycle" if len(numbers) == 1 else "cycles"
    values = ", ".join(map(str, numbers))
    return f"resolved_via_fallback: optional {label} {values} assumed given"


def _phase_end_failure(blocks: Iterable[CycleBlock]) -> str:
    continuing = next(
        (block.timing_indefinite for block in blocks if block.timing_indefinite is not None),
        None,
    )
    if continuing is None:
        return "unresolved: previous phase end is unresolved"
    if continuing.interval is None:
        return "unresolved: previous phase continues indefinitely"
    unit = "cycle" if continuing.interval == 1 else "cycles"
    return f"unresolved: previous phase continues (every {continuing.interval} {unit})"


def _as_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def _phase_relative_day(
    event: TimedEvent, phase_start: int | date, *, calendar_start_known: bool
) -> int | None:
    if isinstance(phase_start, date):
        if not calendar_start_known or event.calendar_date is None:
            return None
        return (event.calendar_date - phase_start).days
    if event.elapsed_day is None:
        return None
    return event.elapsed_day - phase_start


def roll_out_variant(
    variant,
    *,
    start_date: date | datetime | None = None,
    cycle_length_selection: str = "lb",
    decay_days: int = 2,
    decay_factor: float = 0.5,
    systemic_only: bool = False,
) -> pd.DataFrame:
    """Compose all phases of ``variant`` into one deterministic timeline.

    Radiation sigs are included by default: an RT phase still anchors the
    phases after it (e.g. chemoradiation followed by adjuvant). Pass
    ``systemic_only=True`` to drop radiation rows after chaining, not before.
    """

    events = schedule_events(variant)
    groups = _phase_groups(events)
    ordered, order_status = _phase_order(groups)
    phase_start: int | date = _as_date(start_date) if start_date is not None else 0
    all_timed: list[tuple[TimedEvent, int | None]] = []
    timeline_failure = order_status if order_status.startswith("unresolved:") else None
    optional_assumptions: list[str] = []
    previous_last_cycle: int | None = None
    phase_steps = {phase_events[0].phase_step for _, phase_events, _ in ordered}
    known_steps = sorted(step for step in phase_steps if step is not None)
    missing_steps = (
        sorted(set(range(known_steps[0], known_steps[-1] + 1)) - phase_steps)
        if known_steps else []
    )

    for phase, phase_events, phase_status in ordered:
        current_step = phase_events[0].phase_step
        missing_before = [
            step for step in missing_steps if step < current_step
        ] if current_step is not None else []
        if timeline_failure is None and missing_before:
            missing = ", ".join(map(str, missing_before))
            timeline_failure = (
                f"unresolved: phase_step gap before step {current_step} "
                f"(no sigs for step {missing})"
            )
        blocks = group_into_blocks(phase_events)
        optional_cycles = sorted({
            cycle for block in blocks for cycle in block.optional_cycles
        })
        phase_anchored = anchor_blocks(blocks, preceding_cycle=previous_last_cycle)
        timed = roll_out_phase(
            phase_anchored,
            phase_start,
            cycle_length_selection=cycle_length_selection,
            decay_days=decay_days,
            decay_factor=decay_factor,
        )
        calendar_start_known = timeline_failure is None or all(
            _unit_value(block.cycle_length_unit) not in {"month", "year"}
            for block in blocks
        )
        phase_optional_status = _optional_cycle_status(optional_cycles)
        for event in timed:
            row_optional_status = (
                phase_optional_status
                if optional_cycles
                and event.cycle_number is not None
                and event.cycle_number >= optional_cycles[0]
                else "resolved"
            )
            status = _combine_status(
                event.timing_status,
                phase_status,
                timeline_failure or "resolved",
                *optional_assumptions,
                row_optional_status,
            )
            calendar_date = event.calendar_date if timeline_failure is None else None
            elapsed_day = event.elapsed_day if timeline_failure is None else None
            phase_elapsed_day = _phase_relative_day(
                event, phase_start, calendar_start_known=calendar_start_known
            )
            if start_date is not None and calendar_date is not None:
                elapsed_day = (calendar_date - _as_date(start_date)).days
            all_timed.append(
                (
                    TimedEvent(
                        schedule_event=event.schedule_event,
                        phase=phase,
                        phase_step=event.phase_step,
                        cycle_number=event.cycle_number,
                        day=event.day,
                        elapsed_day=elapsed_day,
                        calendar_date=calendar_date,
                        intensity=event.intensity,
                        optional=event.optional,
                        cycle_indefinite=event.cycle_indefinite,
                        timing_status=status,
                    ),
                    phase_elapsed_day,
                )
            )

        phase_end = _phase_end(phase_anchored, phase_start, selection=cycle_length_selection)
        if phase_end is None and timeline_failure is None:
            timeline_failure = _phase_end_failure(blocks)
        if phase_end is not None and timeline_failure is None:
            phase_start = phase_end
            previous_last_cycle = max(cast(int, block.last_cycle) for block in blocks)
        else:
            previous_last_cycle = None
        if optional_cycles:
            optional_assumptions.append(phase_optional_status)

    records = []
    for timed_event, phase_elapsed_day in all_timed:
        schedule_event = timed_event.schedule_event
        sig_class = sig_class_value(schedule_event.sig)
        modality = (
            "radiation" if sig_class == RAD_SIG_CLASS_VALUE
            else "systemic" if sig_class is not None else None
        )
        if systemic_only and modality == "radiation":
            continue
        drug = schedule_event.drug_object
        records.append(
            {
                "variant_cui": variant.variant_cui,
                "variant": variant.variant,
                "phase": timed_event.phase,
                "phase_step": timed_event.phase_step,
                "cycle_number": timed_event.cycle_number,
                "sig_id": schedule_event.sig.id,
                "timing_sequence": schedule_event.timing_sequence,
                "cycle_length_lb": schedule_event.cycle_length_lb,
                "cycle_length_ub": schedule_event.cycle_length_ub,
                "cycle_length_unit": schedule_event.cycle_length_unit,
                "cycle_length_selection": cycle_length_selection,
                "route_group": schedule_event.route_group,
                "modality": modality,
                "component_cui": schedule_event.sig.component_cui,
                "component": schedule_event.sig.component,
                "drug_cui": drug.drug_cui if drug is not None else None,
                "drug": drug.drug if drug is not None else None,
                "day": timed_event.day,
                "elapsed_day": timed_event.elapsed_day,
                "phase_elapsed_day": phase_elapsed_day,
                "calendar_date": timed_event.calendar_date,
                "intensity": timed_event.intensity,
                "optional": timed_event.optional,
                "day_indefinite": schedule_event.indefinite,
                "cycle_indefinite": timed_event.cycle_indefinite,
                "timing_status": timed_event.timing_status,
            }
        )
    columns = [
        "variant_cui", "variant", "phase", "phase_step", "cycle_number",
        "sig_id", "timing_sequence", "cycle_length_lb", "cycle_length_ub",
        "cycle_length_unit", "cycle_length_selection",
        "route_group", "modality", "component_cui", "component",
        "drug_cui", "drug", "day", "elapsed_day", "phase_elapsed_day",
        "calendar_date", "intensity", "optional", "day_indefinite",
        "cycle_indefinite", "timing_status",
    ]
    frame = pd.DataFrame.from_records(records, columns=columns)
    if order_status != "resolved" and frame.empty:
        frame.attrs["timing_status"] = order_status
    return frame
