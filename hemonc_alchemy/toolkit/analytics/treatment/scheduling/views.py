"""A transport-neutral timeline projection, reconciled against source dosing.

`build_schedule_view` composes `dosing_instructions`, `roll_out_variant` and
this module's own diagnostics into one `ScheduleView`. It never silently
drops a source sig: every sig id present on the variant is either an event's
`instruction`, an `UnplacedInstruction`, or the reason the whole view came
back `bounded`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

import pandas as pd  # type: ignore[import-untyped]

from .....model.enums import Sigs_PhaseEnum
from ..dosing import DosingInstruction, dosing_instructions
from .diagnostics import (
    Diagnostic,
    DiagnosticCategory,
    DiagnosticCode,
    DiagnosticSeverity,
    diagnose_timing_status,
    diagnose_variant,
)
from .handling import Indefinite, parse_token, tokenize_all_days
from .rollout import roll_out_variant
from .tokens import Choice, Day, Range

EVENT_LIMIT = 10_000
MAX_COMPARED_VARIANTS = 4

CycleLengthSelection = Literal["lb", "ub", "mean"]
AdministrationSetting = Literal["clinic", "home"]

_ADMINISTRATION_SETTING: dict[str, AdministrationSetting] = {"IV": "clinic", "PO": "home"}


@dataclass(frozen=True)
class SchedulePolicy:
    """The cycle-length/start-date policy a `ScheduleView` was built under, echoed back."""

    cycle_length_selection: CycleLengthSelection = "lb"
    start_date: date | datetime | None = None

    def __post_init__(self):
        if self.cycle_length_selection not in {"lb", "ub", "mean"}:
            raise ValueError("cycle_length_selection must be 'lb', 'ub', or 'mean'")


DEFAULT_SCHEDULE_POLICY = SchedulePolicy()


@dataclass(frozen=True)
class ScheduleEventView:
    """One rolled-out dosing event, keeping its source instruction and source-grain day.

    `source_day` is the raw, cycle-local source day (can be 0 or negative; see
    P0-A14) and is never shifted. `display_day`/`phase_display_day` are the
    presentation-only elapsed-offset-plus-one conversions; `elapsed_day`/
    `phase_elapsed_day` keep the real 0-based offsets.
    """

    instruction: DosingInstruction
    phase: Sigs_PhaseEnum | None
    phase_step: int | None
    cycle_number: int | None
    source_day: int | None
    elapsed_day: int | None
    display_day: int | None
    phase_elapsed_day: int | None
    phase_display_day: int | None
    calendar_date: date | None
    administration_setting: AdministrationSetting | None
    modality: str | None
    drug_cui: int | None
    drug: str | None
    intensity: float
    optional: bool
    day_indefinite: Indefinite | None
    cycle_indefinite: Indefinite | None
    timing_status: str

    @property
    def instruction_id(self) -> int:
        return self.instruction.sig_id


@dataclass(frozen=True)
class UnplacedInstruction:
    """A source instruction absent from the rolled-out event projection.

    Phase 0 found fully `resolved` projections with source sigs missing from
    them entirely (P0-A15); this is how that gap stays visible instead of
    making the variant look complete.
    """

    instruction: DosingInstruction
    reason: str


@dataclass(frozen=True)
class ScheduleCoverage:
    """Source-instruction accounting, counted by distinct sig id -- never by event row."""

    total_instructions: int
    represented_instructions: int | None
    unplaced_instructions: int | None


@dataclass(frozen=True)
class ScheduleView:
    """`events`, reconciled source coverage, diagnostics and the policy that produced them."""

    variant_cui: int
    version: int
    policy: SchedulePolicy
    events: tuple[ScheduleEventView, ...]
    unplaced_instructions: tuple[UnplacedInstruction, ...]
    diagnostics: tuple[Diagnostic, ...]
    assumptions: tuple[str, ...]
    coverage: ScheduleCoverage
    bounded: bool = False
    event_limit: int = EVENT_LIMIT


def _clean(value):
    return None if pd.isna(value) else value


def _clean_int(value) -> int | None:
    cleaned = _clean(value)
    return None if cleaned is None else int(cleaned)


def _event_view(row, by_id: dict[int, DosingInstruction]) -> ScheduleEventView:
    elapsed_day = _clean_int(row.elapsed_day)
    phase_elapsed_day = _clean_int(row.phase_elapsed_day)
    return ScheduleEventView(
        instruction=by_id[int(row.sig_id)],
        phase=_clean(row.phase),
        phase_step=_clean_int(row.phase_step),
        cycle_number=_clean_int(row.cycle_number),
        source_day=_clean_int(row.day),
        elapsed_day=elapsed_day,
        display_day=None if elapsed_day is None else elapsed_day + 1,
        phase_elapsed_day=phase_elapsed_day,
        phase_display_day=None if phase_elapsed_day is None else phase_elapsed_day + 1,
        calendar_date=_clean(row.calendar_date),
        administration_setting=_ADMINISTRATION_SETTING.get(row.route_group),
        modality=_clean(row.modality),
        drug_cui=_clean_int(row.drug_cui),
        drug=_clean(row.drug),
        intensity=float(row.intensity),
        optional=bool(row.optional),
        day_indefinite=_clean(row.day_indefinite),
        cycle_indefinite=_clean(row.cycle_indefinite),
        timing_status=row.timing_status,
    )


def _bounded_view(
    variant, policy: SchedulePolicy, total: int, diagnostics: list[Diagnostic]
) -> ScheduleView:
    return ScheduleView(
        variant_cui=variant.variant_cui,
        version=variant.version,
        policy=policy,
        events=(),
        unplaced_instructions=(),
        diagnostics=tuple(diagnostics),
        assumptions=(),
        coverage=ScheduleCoverage(
            total_instructions=total, represented_instructions=None, unplaced_instructions=None
        ),
        bounded=True,
    )


def _reconcile_unplaced(
    instructions: tuple[DosingInstruction, ...],
    represented_ids: set[int],
    by_id: dict[int, DosingInstruction],
) -> tuple[UnplacedInstruction, ...]:
    """Every source sig id absent from `represented_ids` -- never a silent drop."""
    return tuple(
        UnplacedInstruction(
            instruction=by_id[instr.sig_id],
            reason="source instruction not represented in the rolled-out projection",
        )
        for instr in instructions
        if instr.sig_id not in represented_ids
    )


def _timing_status_diagnostics(frame: pd.DataFrame) -> list[Diagnostic]:
    """One diagnostic per distinct (sig id, status) pair in `frame`, not per row."""
    diagnostics: list[Diagnostic] = []
    seen: set[tuple[int, str]] = set()
    for row in frame.itertuples(index=False):
        sig_id = _clean_int(row.sig_id)
        assert sig_id is not None  # every rollout row has a source sig id
        status = str(row.timing_status)
        key = (sig_id, status)
        if key in seen:
            continue
        seen.add(key)
        diagnostics.extend(diagnose_timing_status(status, sig_id=sig_id))
    return diagnostics


def _assumptions(diagnostics: list[Diagnostic]) -> tuple[str, ...]:
    return tuple(sorted(
        {
            diagnostic.message
            for diagnostic in diagnostics
            if diagnostic.category
            in (DiagnosticCategory.OPTIONAL_CYCLE_ASSUMPTION, DiagnosticCategory.CALENDAR_APPROXIMATION)
        }
    ))


def _roll_out_or_diagnose(variant, policy: SchedulePolicy) -> tuple[pd.DataFrame | None, Diagnostic | None]:
    try:
        if _exceeds_expansion_limit(variant):
            return None, Diagnostic(
                code=DiagnosticCode.EVENT_LIMIT_EXCEEDED,
                category=DiagnosticCategory.LIMIT_EXCEEDED,
                severity=DiagnosticSeverity.WARNING,
                message=(
                    f"source expansion may exceed {EVENT_LIMIT} events; "
                    "timeline withheld before expansion, source dosing remains available"
                ),
            )
        frame = roll_out_variant(
            variant,
            start_date=policy.start_date,
            cycle_length_selection=policy.cycle_length_selection,
            decay_days=0,
            systemic_only=False,
        )
    except ValueError as exc:
        return None, Diagnostic(
            code=DiagnosticCode.TOKEN_PARSE_ERROR,
            category=DiagnosticCategory.PARSE_ERROR,
            severity=DiagnosticSeverity.ERROR,
            message=f"rollout failed: {exc}; source dosing instructions remain available",
        )
    except OverflowError:
        return None, Diagnostic(
            code=DiagnosticCode.TIMING_UNRESOLVED,
            category=DiagnosticCategory.UNRESOLVED_TIMING,
            severity=DiagnosticSeverity.ERROR,
            message="timing exceeds the supported numeric/calendar range; source dosing remains available",
        )
    if len(frame) > EVENT_LIMIT:
        return None, Diagnostic(
            code=DiagnosticCode.EVENT_LIMIT_EXCEEDED,
            category=DiagnosticCategory.LIMIT_EXCEEDED,
            severity=DiagnosticSeverity.WARNING,
            message=(
                f"rollout produced {len(frame)} events, over the {EVENT_LIMIT} "
                "limit; timeline withheld, source dosing remains available"
            ),
        )
    return frame, None


def _expression_size(value: str | None) -> int:
    """Conservative size using the shared parser, without expanding numeric ranges.

    Duplicate days may overcount; rejecting that source is preferable to allocating
    an unbounded intermediate list. Choices cost one placeholder row each.
    """
    count = 0
    for token in tokenize_all_days(value):
        for item in parse_token(token):
            if isinstance(item, (Day, Choice)):
                count += 1
            elif isinstance(item, Range) and isinstance(item.start, int) and isinstance(item.end, int):
                # range raises for step=0, just as the normal expansion does.
                try:
                    count += len(range(item.start, item.end + 1, item.step))
                except OverflowError:
                    return EVENT_LIMIT + 1
            if count > EVENT_LIMIT:
                return count
    return count


def _exceeds_expansion_limit(variant) -> bool:
    """Bound both parsed lists and their cross-cycle product before rollout."""
    total = 0
    for sig in variant.component_sigs:
        days = _expression_size(sig.alldays)
        cycles = _expression_size(sig.timing_sequence)
        total += max(1, days) * max(1, cycles)
        if total > EVENT_LIMIT:
            return True
    return False


def build_schedule_view(variant, policy: SchedulePolicy = DEFAULT_SCHEDULE_POLICY) -> ScheduleView:
    """Roll `variant` out into one `ScheduleView`, reconciled against its source sigs.

    Always calls `roll_out_variant(..., decay_days=0, systemic_only=False)`:
    zero decay because this is an administration display, not an intensity
    model, and radiation/unclassified sigs are kept rather than dropped.
    """
    instructions = dosing_instructions(variant)
    by_id = {instruction.sig_id: instruction for instruction in instructions}
    diagnostics: list[Diagnostic] = list(
        diagnose_variant(variant, calendar_anchored=policy.start_date is not None)
    )

    frame, failure = _roll_out_or_diagnose(variant, policy)
    if failure is not None:
        diagnostics.append(failure)
        return _bounded_view(variant, policy, len(instructions), diagnostics)
    assert frame is not None

    events = tuple(_event_view(row, by_id) for row in frame.itertuples(index=False))
    represented_ids = {event.instruction_id for event in events}
    unplaced = _reconcile_unplaced(instructions, represented_ids, by_id)
    diagnostics.extend(_timing_status_diagnostics(frame))

    return ScheduleView(
        variant_cui=variant.variant_cui,
        version=variant.version,
        policy=policy,
        events=events,
        unplaced_instructions=unplaced,
        diagnostics=tuple(diagnostics),
        assumptions=_assumptions(diagnostics),
        coverage=ScheduleCoverage(
            total_instructions=len(instructions),
            represented_instructions=len(represented_ids),
            unplaced_instructions=len(unplaced),
        ),
        bounded=False,
    )


def build_schedule_views(
    variants, policy: SchedulePolicy = DEFAULT_SCHEDULE_POLICY
) -> tuple[ScheduleView, ...]:
    """`build_schedule_view` for each of up to `MAX_COMPARED_VARIANTS` variants.

    Raises rather than silently comparing a truncated subset, matching
    `CatalogueSpec`/`Pagination`'s own `__post_init__` validation style.
    """
    variants = list(variants)
    if len(variants) > MAX_COMPARED_VARIANTS:
        raise ValueError(
            f"cannot compare {len(variants)} variants; at most {MAX_COMPARED_VARIANTS} per request"
        )
    return tuple(build_schedule_view(variant, policy) for variant in variants)
