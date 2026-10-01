"""Lossless per-sig dosing instructions, independent of any schedule rollout.

`cycle_template`'s dose matrices collapse a cycle to its minimum dose and
`aggfunc="first"`; they are a grid for display, not a source record. This
module instead keeps one `DosingInstruction` per sig, with every field read
straight off the source row and no parsing or aggregation applied.
"""

from __future__ import annotations

from dataclasses import dataclass

from ....model.enums import (
    Sigs_Cycle_length_unitEnum,
    Sigs_DosecapunitEnum,
    Sigs_DurationunitEnum,
    Sigs_FrequencyEnum,
    Sigs_PhaseEnum,
    Sigs_RouteEnum,
    Sigs_SequenceEnum,
    Sigs_SubcomponentEnum,
    Sigs_TargetleveltypeEnum,
    Sigs_TargetlevelunitEnum,
)

# Sigs are linked to a variant by `variant_cui` alone, not `(variant_cui, version)`;
# every historical version of a variant shares the same sig rows (see P0-A05).
MEMBERSHIP_PROVENANCE = "shared_by_variant_cui"


@dataclass(frozen=True)
class DosingInstruction:
    """One sig, losslessly: raw source strings, not display-formatted values."""

    sig_id: int
    variant_cui: int | None
    component_cui: int
    component: str
    subcomponent_cui: int | None
    subcomponent: Sigs_SubcomponentEnum | None
    phase: Sigs_PhaseEnum | None
    phase_step: int
    portion: str
    step_number: str
    dose_min: str | None
    dose_max: str | None
    dose_unit: str | None
    dose_cap: float | None
    dose_cap_unit: Sigs_DosecapunitEnum | None
    target_level: str | None
    target_level_type: Sigs_TargetleveltypeEnum | None
    target_level_unit: Sigs_TargetlevelunitEnum | None
    route: Sigs_RouteEnum | None
    frequency: Sigs_FrequencyEnum | None
    duration_min: str | None
    duration_max: str | None
    duration_unit: Sigs_DurationunitEnum | None
    raw_all_days: str | None
    raw_timing_sequence: str | None
    cycle_length_lb: str | None
    cycle_length_ub: str | None
    cycle_length_unit: Sigs_Cycle_length_unitEnum | None
    sequence: Sigs_SequenceEnum | None
    notes: tuple[str, ...]
    evidence_references: tuple[str, ...]
    membership_provenance: str = MEMBERSHIP_PROVENANCE


def _dosing_instruction(sig) -> DosingInstruction:
    return DosingInstruction(
        sig_id=sig.id,
        variant_cui=sig.variant_cui,
        component_cui=sig.component_cui,
        component=sig.component,
        subcomponent_cui=sig.subcomponent_cui,
        subcomponent=sig.subcomponent,
        phase=sig.phase,
        phase_step=sig.phase_step,
        portion=sig.portion,
        step_number=sig.step_number,
        dose_min=sig.doseminnum,
        dose_max=sig.dosemaxnum,
        dose_unit=sig.doseunit,
        dose_cap=sig.dosecapnum,
        dose_cap_unit=sig.dosecapunit,
        target_level=sig.targetlevel,
        target_level_type=sig.targetleveltype,
        target_level_unit=sig.targetlevelunit,
        route=sig.route,
        frequency=sig.frequency,
        duration_min=sig.durationminnum,
        duration_max=sig.durationmaxnum,
        duration_unit=sig.durationunit,
        raw_all_days=sig.alldays,
        raw_timing_sequence=sig.timing_sequence,
        cycle_length_lb=sig.cycle_length_lb,
        cycle_length_ub=sig.cycle_length_ub,
        cycle_length_unit=sig.cycle_length_unit,
        sequence=sig.sequence,
        notes=tuple(item.cyclesigs_note for item in sig.cyclesigs_note_items),
        evidence_references=tuple(item.study for item in sig.study_items),
    )


def dosing_instructions(variant) -> tuple[DosingInstruction, ...]:
    """Every sig on `variant` as a `DosingInstruction` -- one row per sig, in sig order.

    Never collapses or re-aggregates rows, and never parses `raw_all_days`/
    `raw_timing_sequence`; it does not depend on `resolve_all_days` and so
    cannot raise on a malformed expression (see diagnostics.py for parsing).
    """
    return tuple(_dosing_instruction(sig) for sig in variant.component_sigs)
