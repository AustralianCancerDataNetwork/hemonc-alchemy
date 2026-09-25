"""Schedule summaries, against real rows in a real database.

These went unexercised for long enough to silently break -- the module read a
`sigs.branch` column that had been dropped upstream -- so they are tested
through real inserts and real relationship traversal rather than stubs.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
import sqlalchemy as sa
import sqlalchemy.event
import sqlalchemy.orm as so

from hemonc_alchemy.model.base import Base
from hemonc_alchemy.model.entities import Drugs, Sigs, Variants
from hemonc_alchemy.model.enums import (
    Sigs_Class_fieldEnum,
    Sigs_Cycle_length_unitEnum,
    Sigs_PhaseEnum,
)
from hemonc_alchemy.toolkit.analytics.treatment.scheduling import (
    Indefinite,
    UnresolvedTiming,
    administration_frame,
    administration_matrix,
    anchor_blocks,
    cancer_services_drugs,
    cancer_services_sigs_by_drug,
    group_into_blocks,
    home_administered_drugs,
    roll_out_variant,
    schedule_events,
)

pytestmark = pytest.mark.skipif(
    len(Base.metadata.tables) == 0,
    reason="model/entities.py has no generated classes yet -- run `hemonc-alchemy regen` first",
)

_D = datetime(2020, 1, 1, tzinfo=UTC)
_IV_SIG = "IV_INTERMITTENT_CANONICAL_SIG"
_NONIV_SIG = "NON_TO_IV_CANONICAL_SIG"
_IV_CONT_SIG = "IV_CONTINUOUS_CANONICAL_SIG"


@pytest.fixture
def session():
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with so.Session(engine) as s:
        yield s


def _variant(session, variant_cui: int) -> Variants:
    variant = Variants(
        id=variant_cui, variant_cui=variant_cui, variant=f"v{variant_cui}",
        regimen_cui=1, regimen="R", version=1, cyclesigs=0, components=0, portions=0,
        routes=0, sigs=0, blob_version=0, fullyspecified=True,
        allsigshavecyclesigs=True, allsigshavedose=True, allsigshavedoseunit=True,
        allsigshaveduration=True, allsigshavedurationunit=True, allsigshavefrequency=True,
        allsigshaveroute=True, allsigshaveschedule=True, allsigshavesequence=True,
        date_added=_D,
    )
    session.add(variant)
    session.flush()
    return variant


def _drug(session, drug_cui: int, name: str) -> Drugs:
    drug = Drugs(
        id=drug_cui, drug_cui=drug_cui, drug=name,
        investigational=False, multiagent=False, date_added=_D,
    )
    session.add(drug)
    session.flush()
    return drug


def _sig(
    session,
    *,
    sig_id: int,
    variant_cui: int,
    drug_cui: int,
    route: str,
    alldays: str,
    **overrides,
) -> Sigs:
    timing_sequence = overrides.pop("timing_sequence", None)
    cycle_length_lb = overrides.pop("cycle_length_lb", None)
    cycle_length_ub = overrides.pop("cycle_length_ub", None)
    cycle_length_unit = overrides.pop("cycle_length_unit", None)
    phase = overrides.pop("phase", None)
    phase_step = overrides.pop("phase_step", 1)
    class_field = overrides.pop("class_field", "iv intermittent canonical sig")
    component = overrides.pop("component", f"c{drug_cui}")
    assert not overrides
    sig = Sigs(
        id=sig_id, variant_cui=variant_cui, component_cui=drug_cui, component=component,
        class_field=class_field, component_role="primary systemic",
        portion="1", regimen="R", regimen_cui=1, step_number="1", divided=False,
        phase=phase, phase_step=phase_step, variant=f"v{variant_cui}", route=route,
        alldays=alldays, timing_sequence=timing_sequence,
        cycle_length_lb=cycle_length_lb, cycle_length_ub=cycle_length_ub,
        cycle_length_unit=cycle_length_unit, date_added=_D,
    )
    session.add(sig)
    session.flush()
    return sig


def _source_variant(session, variant_cui, rows):
    """Mirror selected development database sigs in sqlite."""
    variant = _variant(session, variant_cui)
    for component_cui, component in dict.fromkeys((row[1], row[0]) for row in rows):
        _drug(session, component_cui, component)
    for sig_id, (
        component, component_cui, alldays, timing_sequence, length,
        unit, route, sig_class, phase, phase_step,
    ) in enumerate(rows, start=1):
        _sig(
            session, sig_id=sig_id, variant_cui=variant_cui, drug_cui=component_cui,
            route=route, alldays=alldays, timing_sequence=timing_sequence,
            cycle_length_lb=length, cycle_length_ub=length,
            cycle_length_unit=Sigs_Cycle_length_unitEnum[unit],
            class_field=Sigs_Class_fieldEnum[sig_class], component=component,
            phase=Sigs_PhaseEnum[phase] if phase is not None else None,
            phase_step=phase_step,
        )
    session.expire_all()
    return variant


class TestScheduleEvents:
    def test_one_event_per_sig_with_its_days_resolved(self, session):
        variant = _variant(session, 1)
        _drug(session, 1, "cisplatin")
        _sig(session, sig_id=1, variant_cui=1, drug_cui=1, route="INTRAVENOUS", alldays="1,8,15")
        session.expire_all()

        events = schedule_events(variant)
        assert len(events) == 1
        assert [day.value for day in events[0].days] == [1, 8, 15]
        assert events[0].route_group == "IV"
        assert events[0].drug_object.drug == "cisplatin"

    def test_an_indefinite_schedule_is_flagged_not_dropped(self, session):
        variant = _variant(session, 2)
        _drug(session, 1, "capecitabine")
        _sig(session, sig_id=1, variant_cui=2, drug_cui=1, route="ORAL", alldays="1,(+c)")
        session.expire_all()

        event = schedule_events(variant)[0]
        assert event.indefinite is not None
        assert [day.value for day in event.days] == [1]


class TestRollout:
    def _two_block_variant(self, session, variant_cui=90):
        variant = _variant(session, variant_cui)
        _drug(session, 1, "docetaxel")
        _drug(session, 2, "trastuzumab")
        _sig(
            session, sig_id=1, variant_cui=variant_cui, drug_cui=1,
            route="INTRAVENOUS", alldays="1",
            timing_sequence="1,2,3,4,5,6,7,8",
            cycle_length_lb="2", cycle_length_ub="2",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.WEEK,
        )
        _sig(
            session, sig_id=2, variant_cui=variant_cui, drug_cui=2,
            route="INTRAVENOUS", alldays="1",
            timing_sequence="9,10,11,12,13,14,15,16,17,18,19,20",
            cycle_length_lb="3", cycle_length_ub="3",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.WEEK,
        )
        session.expire_all()
        return variant

    def test_groups_by_cycle_length_and_cycle_numbers(self, session):
        variant = self._two_block_variant(session)

        blocks = group_into_blocks(schedule_events(variant))

        assert len(blocks) == 2
        assert [block.cycle_numbers for block in blocks] == [
            frozenset(range(1, 9)), frozenset(range(9, 21)),
        ]

    def test_sequential_and_unresolved_anchors(self, session):
        variant = self._two_block_variant(session, variant_cui=91)
        blocks = group_into_blocks(schedule_events(variant))

        anchored = anchor_blocks(blocks)
        assert [item.anchor_kind for item in anchored] == ["phase_start", "after"]

        variant_gap = _variant(session, 92)
        _drug(session, 3, "cyclophosphamide")
        _sig(
            session, sig_id=3, variant_cui=92, drug_cui=3,
            route="INTRAVENOUS", alldays="1", timing_sequence="1,2",
            cycle_length_lb="14", cycle_length_ub="14",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
        )
        _sig(
            session, sig_id=4, variant_cui=92, drug_cui=3,
            route="INTRAVENOUS", alldays="1", timing_sequence="4,5",
            cycle_length_lb="14", cycle_length_ub="14",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
        )
        session.expire_all()
        gap = anchor_blocks(group_into_blocks(schedule_events(variant_gap)))
        assert isinstance(gap[-1].unresolved, UnresolvedTiming)

    def test_first_block_after_cycle_one_has_no_variant_start_date(self, session):
        variant = _variant(session, 109)
        _drug(session, 1, "cycle-three-drug")
        _drug(session, 2, "cycle-four-drug")
        for sig_id, drug_cui, cycles in ((1, 1, "3"), (2, 2, "4")):
            _sig(
                session, sig_id=sig_id, variant_cui=109, drug_cui=drug_cui,
                route="INTRAVENOUS", alldays="1", timing_sequence=cycles,
                cycle_length_lb="21", cycle_length_ub="21",
                cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
            )
        session.expire_all()

        anchored = anchor_blocks(group_into_blocks(schedule_events(variant)))
        assert anchored[0].unresolved is not None
        frame = roll_out_variant(variant, start_date=date(2020, 1, 1), decay_days=0)
        assert set(frame["cycle_number"]) == {3, 4}
        assert frame["elapsed_day"].isna().all()
        assert frame["calendar_date"].isna().all()
        assert frame["timing_status"].str.startswith("unresolved:").all()

    def test_phase_cycle_numbers_can_continue_from_previous_phase(self, session):
        # LVP Sandwich Variant #01 carries cycle numbers across its phases.
        variant = _variant(session, 111)
        for cui in (1, 2, 3):
            _drug(session, cui, f"drug-{cui}")
        for sig_id, drug_cui, cycles, phase, step in (
            (1, 1, "1,2", Sigs_PhaseEnum.INDUCTION, 1),
            (2, 2, "3", Sigs_PhaseEnum.DEFINITIVE, 2),
            (3, 3, "4,5", Sigs_PhaseEnum.CONSOLIDATION, 3),
        ):
            _sig(
                session, sig_id=sig_id, variant_cui=111, drug_cui=drug_cui,
                route="INTRAVENOUS", alldays="1", timing_sequence=cycles,
                cycle_length_lb="21", cycle_length_ub="21",
                cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
                phase=phase, phase_step=step,
            )
        session.expire_all()

        frame = roll_out_variant(variant, decay_days=0)
        assert frame.loc[frame["phase"] == Sigs_PhaseEnum.DEFINITIVE, "elapsed_day"].iloc[0] == 42
        assert frame.loc[frame["phase"] == Sigs_PhaseEnum.CONSOLIDATION, "elapsed_day"].min() == 63
        assert set(frame["timing_status"]) == {"resolved"}

    def test_phase_cycle_number_jump_remains_unresolved(self, session):
        variant = _variant(session, 112)
        _drug(session, 1, "induction-drug")
        _drug(session, 2, "consolidation-drug")
        for sig_id, drug_cui, cycles, phase, step in (
            (1, 1, "1,2", Sigs_PhaseEnum.INDUCTION, 1),
            (2, 2, "4", Sigs_PhaseEnum.CONSOLIDATION, 2),
        ):
            _sig(
                session, sig_id=sig_id, variant_cui=112, drug_cui=drug_cui,
                route="INTRAVENOUS", alldays="1", timing_sequence=cycles,
                cycle_length_lb="21", cycle_length_ub="21",
                cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
                phase=phase, phase_step=step,
            )
        session.expire_all()

        frame = roll_out_variant(variant, decay_days=0)
        later = frame[frame["phase"] == Sigs_PhaseEnum.CONSOLIDATION]
        assert later["elapsed_day"].isna().all()
        assert later["timing_status"].str.startswith("unresolved:").all()

    def test_overlapping_blocks_share_an_anchor(self, session):
        variant = _variant(session, 93)
        _drug(session, 1, "carfilzomib")
        _drug(session, 2, "lenalidomide")
        _sig(
            session, sig_id=1, variant_cui=93, drug_cui=1,
            route="INTRAVENOUS", alldays="1", timing_sequence="1,2,3",
            cycle_length_lb="28", cycle_length_ub="28",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
        )
        _sig(
            session, sig_id=2, variant_cui=93, drug_cui=2,
            route="ORAL", alldays="1", timing_sequence="1",
            cycle_length_lb="14", cycle_length_ub="14",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
        )
        session.expire_all()

        anchored = anchor_blocks(group_into_blocks(schedule_events(variant)))
        assert [item.anchor_kind for item in anchored] == ["phase_start", "overlap"]

    def test_three_overlaps_reject_conflicting_cycle_starts(self, session):
        variant = _variant(session, 119)
        for cui in (1, 2, 3):
            _drug(session, cui, f"drug-{cui}")
        for sig_id, start, stop, length in ((1, 1, 5, 7), (2, 3, 7, 14), (3, 5, 9, 21)):
            _sig(
                session, sig_id=sig_id, variant_cui=119, drug_cui=sig_id,
                route="INTRAVENOUS", alldays="1",
                timing_sequence=",".join(map(str, range(start, stop + 1))),
                cycle_length_lb=str(length), cycle_length_ub=str(length),
                cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
            )
        session.expire_all()

        frame = roll_out_variant(variant, decay_days=0)
        first = frame[frame["drug"] == "drug-1"]
        second = frame[frame["drug"] == "drug-2"]
        third = frame[frame["drug"] == "drug-3"]
        assert first.loc[first["cycle_number"] == 5, "elapsed_day"].iloc[0] == 28
        assert set(first["timing_status"]) == {"resolved"}
        assert second["elapsed_day"].isna().all()
        assert set(second["timing_status"]) == {
            "unresolved: cycle lengths differ across shared cycles 3-5"
        }
        assert third["elapsed_day"].isna().all()
        assert set(third["timing_status"]) == {
            "unresolved: cycle lengths differ across shared cycles 5-7"
        }

    @pytest.mark.parametrize(
        ("later_cycles", "expected_status"),
        [
            ("2,3,4", "unresolved: cycle lengths differ across shared cycles 2-3"),
            ("3,4,5", "resolved"),
        ],
    )
    def test_different_length_overlap_needs_multiple_shared_cycles(
        self, session, later_cycles, expected_status
    ):
        variant = _variant(session, 120)
        _drug(session, 1, "earlier-drug")
        _drug(session, 2, "later-drug")
        for sig_id, drug_cui, cycles, length in (
            (1, 1, "1,2,3", 7),
            (2, 2, later_cycles, 14),
        ):
            _sig(
                session, sig_id=sig_id, variant_cui=120, drug_cui=drug_cui,
                route="INTRAVENOUS", alldays="1", timing_sequence=cycles,
                cycle_length_lb=str(length), cycle_length_ub=str(length),
                cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
            )
        session.expire_all()

        frame = roll_out_variant(variant, decay_days=0)
        later = frame[frame["drug"] == "later-drug"]
        assert set(later["timing_status"]) == {expected_status}
        if expected_status == "resolved":
            assert later.loc[later["cycle_number"] == 3, "elapsed_day"].iloc[0] == 14
        else:
            assert later["elapsed_day"].isna().all()

    def test_single_shared_cycle_with_two_prior_blocks_stays_resolved(self, session):
        variant = _variant(session, 125)
        for cui, name in ((1, "carboplatin"), (2, "paclitaxel"), (3, "ipilimumab")):
            _drug(session, cui, name)
        for sig_id, cycles, length in (
            (1, "1,2,3,4", 3),
            (2, "1,2,3,4,5,6", 3),
            (3, "3", 12),
        ):
            _sig(
                session, sig_id=sig_id, variant_cui=125, drug_cui=sig_id,
                route="INTRAVENOUS", alldays="1", timing_sequence=cycles,
                cycle_length_lb=str(length), cycle_length_ub=str(length),
                cycle_length_unit=Sigs_Cycle_length_unitEnum.WEEK,
            )
        session.expire_all()

        frame = roll_out_variant(variant, decay_days=0)
        ipilimumab = frame[frame["drug"] == "ipilimumab"]
        assert ipilimumab["elapsed_day"].iloc[0] == 42
        assert set(ipilimumab["timing_status"]) == {"resolved"}

    @pytest.mark.parametrize(
        ("predecessor_lengths", "expected_day", "expected_status"),
        [
            ((4, 3, 1), None, "unresolved: blocks ending cycle 1 differ in cycle length"),
            ((4, 4, 4), 28, "resolved"),
        ],
    )
    def test_following_cycle_checks_all_predecessor_lengths(
        self, session, predecessor_lengths, expected_day, expected_status
    ):
        # Variant 131178 has three cycle-1 blocks; sort order puts the one-week
        # block last, but cycle 2 cannot be anchored to that block alone.
        variant = _variant(session, 127)
        for cui, name in (
            (1, "cobimetinib"),
            (2, "vemurafenib-early"),
            (3, "vemurafenib-late"),
            (4, "atezolizumab"),
        ):
            _drug(session, cui, name)
        for sig_id, cycles, length in (
            (1, "1,(+1)", predecessor_lengths[0]),
            (2, "1", predecessor_lengths[1]),
            (3, "1", predecessor_lengths[2]),
            (4, "2,(+1)", 4),
        ):
            _sig(
                session, sig_id=sig_id, variant_cui=127, drug_cui=sig_id,
                route="ORAL", alldays="1", timing_sequence=cycles,
                cycle_length_lb=str(length), cycle_length_ub=str(length),
                cycle_length_unit=Sigs_Cycle_length_unitEnum.WEEK,
            )
        session.expire_all()

        frame = roll_out_variant(variant, decay_days=0)
        cycle_two = frame[frame["drug"] == "atezolizumab"]
        if expected_day is None:
            assert cycle_two["elapsed_day"].isna().all()
        else:
            assert cycle_two["elapsed_day"].iloc[0] == expected_day
        assert set(cycle_two["timing_status"]) == {expected_status}

    def test_three_blocks_sharing_only_cycle_five_stay_resolved(self, session):
        variant = _variant(session, 126)
        for cui in (1, 2, 3):
            _drug(session, cui, f"drug-{cui}")
        for sig_id, cycles, length in (
            (1, "1,2,3,4,5", 7),
            (2, "5", 14),
            (3, "5,6,7,8,9", 21),
        ):
            _sig(
                session, sig_id=sig_id, variant_cui=126, drug_cui=sig_id,
                route="INTRAVENOUS", alldays="1", timing_sequence=cycles,
                cycle_length_lb=str(length), cycle_length_ub=str(length),
                cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
            )
        session.expire_all()

        frame = roll_out_variant(variant, decay_days=0)
        cycle_five = frame[frame["cycle_number"] == 5]
        assert set(cycle_five["elapsed_day"]) == {28}
        assert set(cycle_five["timing_status"]) == {"resolved"}

    def test_same_cycle_length_pattern_change_forms_two_blocks(self, session):
        variant = _variant(session, 99)
        _drug(session, 1, "carfilzomib")
        _drug(session, 2, "dexamethasone")
        _sig(
            session, sig_id=1, variant_cui=99, drug_cui=1,
            route="INTRAVENOUS", alldays="1,2,8,9,15,16",
            timing_sequence="2,3,4,5,6,7,8,9,10,11,12",
            cycle_length_lb="4", cycle_length_ub="4",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.WEEK,
        )
        _sig(
            session, sig_id=2, variant_cui=99, drug_cui=2,
            route="ORAL", alldays="1,15",
            timing_sequence="13,14,15,16,17,18",
            cycle_length_lb="4", cycle_length_ub="4",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.WEEK,
        )
        session.expire_all()

        blocks = group_into_blocks(schedule_events(variant))

        assert len(blocks) == 2
        assert {block.cycle_length_lb for block in blocks} == {"4"}

    def test_rollout_uses_previous_block_duration(self, session):
        variant = self._two_block_variant(session, variant_cui=94)

        frame = roll_out_variant(variant)

        first = frame[(frame["drug"] == "docetaxel") & (frame["cycle_number"] == 8)]
        second = frame[(frame["drug"] == "trastuzumab") & (frame["cycle_number"] == 9)]
        assert first["elapsed_day"].iloc[0] == 98
        assert second["elapsed_day"].iloc[0] == 112
        assert set(frame["timing_status"]) == {"resolved"}

    def test_rollout_can_return_calendar_dates(self, session):
        variant = self._two_block_variant(session, variant_cui=95)

        frame = roll_out_variant(variant, start_date=date(2020, 1, 1))

        second = frame[(frame["drug"] == "trastuzumab") & (frame["cycle_number"] == 9)]
        assert second["calendar_date"].iloc[0] == date(2020, 4, 22)
        assert second["elapsed_day"].iloc[0] == 112

    def test_phase_rollout_chains_at_full_cycle_end(self, session):
        variant = _variant(session, 96)
        _drug(session, 1, "induction-drug")
        _drug(session, 2, "maintenance-drug")
        _sig(
            session, sig_id=1, variant_cui=96, drug_cui=1,
            route="INTRAVENOUS", alldays="1", timing_sequence="1,2",
            cycle_length_lb="14", cycle_length_ub="14",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
            phase=Sigs_PhaseEnum.INDUCTION, phase_step=1,
        )
        _sig(
            session, sig_id=2, variant_cui=96, drug_cui=2,
            route="INTRAVENOUS", alldays="1", timing_sequence="1,2",
            cycle_length_lb="21", cycle_length_ub="21",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
            phase=Sigs_PhaseEnum.MAINTENANCE, phase_step=2,
        )
        session.expire_all()

        frame = roll_out_variant(variant)
        maintenance = frame[frame["phase"] == Sigs_PhaseEnum.MAINTENANCE]
        assert maintenance["elapsed_day"].min() == 28
        assert set(frame["timing_status"]) == {"resolved"}

    def test_phase_step_gap_nulls_later_phases(self, session):
        variant = _variant(session, 113)
        for cui in (1, 2, 3):
            _drug(session, cui, f"drug-{cui}")
        for sig_id, drug_cui, phase, step in (
            (1, 1, Sigs_PhaseEnum.NEOADJUVANT, 1),
            (2, 2, Sigs_PhaseEnum.ADJUVANT, 3),
            (3, 3, Sigs_PhaseEnum.MAINTENANCE, 5),
        ):
            _sig(
                session, sig_id=sig_id, variant_cui=113, drug_cui=drug_cui,
                route="INTRAVENOUS", alldays="1", timing_sequence="1",
                cycle_length_lb="21", cycle_length_ub="21",
                cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
                phase=phase, phase_step=step,
            )
        session.expire_all()

        frame = roll_out_variant(variant, decay_days=0)
        assert frame.loc[frame["phase"] == Sigs_PhaseEnum.NEOADJUVANT, "elapsed_day"].iloc[0] == 0
        later = frame[frame["phase"] != Sigs_PhaseEnum.NEOADJUVANT]
        assert later["elapsed_day"].isna().all()
        assert set(later["timing_status"]) == {
            "unresolved: phase_step gap before step 3 (no sigs for step 2)"
        }

    def test_phase_step_gap_with_fallback_order_nulls_later_phase(self, session):
        variant = _variant(session, 122)
        _drug(session, 1, "perioperative-drug")
        _drug(session, 2, "adjuvant-drug")
        for sig_id, drug_cui, phase, step in (
            (1, 1, Sigs_PhaseEnum.PERIOPERATIVE, 1),
            (2, 2, Sigs_PhaseEnum.ADJUVANT, 3),
        ):
            _sig(
                session, sig_id=sig_id, variant_cui=122, drug_cui=drug_cui,
                route="INTRAVENOUS", alldays="1", timing_sequence="1,2",
                cycle_length_lb="21", cycle_length_ub="21",
                cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
                phase=phase, phase_step=step,
            )
        session.expire_all()

        frame = roll_out_variant(variant, decay_days=0)
        perioperative = frame[frame["phase"] == Sigs_PhaseEnum.PERIOPERATIVE]
        adjuvant = frame[frame["phase"] == Sigs_PhaseEnum.ADJUVANT]
        assert set(perioperative["elapsed_day"]) == {0, 21}
        assert adjuvant["elapsed_day"].isna().all()
        assert set(adjuvant["timing_status"]) == {
            "unresolved: phase_step gap before step 3 (no sigs for step 2)"
        }

    def test_fallback_gap_checks_step_span_not_loop_neighbours(self, session):
        variant = _variant(session, 123)
        _drug(session, 1, "perioperative-drug")
        _drug(session, 2, "adjuvant-drug")
        for sig_id, drug_cui, phase, step in (
            (1, 1, Sigs_PhaseEnum.PERIOPERATIVE, 4),
            (2, 2, Sigs_PhaseEnum.ADJUVANT, 2),
        ):
            _sig(
                session, sig_id=sig_id, variant_cui=123, drug_cui=drug_cui,
                route="INTRAVENOUS", alldays="1", timing_sequence="1",
                cycle_length_lb="21", cycle_length_ub="21",
                cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
                phase=phase, phase_step=step,
            )
        session.expire_all()

        frame = roll_out_variant(variant, decay_days=0)
        assert frame["elapsed_day"].isna().all()
        assert set(frame["timing_status"]) == {
            "unresolved: phase_step gap before step 4 (no sigs for step 3)"
        }

    def test_optional_cycle_marks_rows_and_following_phase(self, session):
        variant = _variant(session, 114)
        _drug(session, 1, "induction-drug")
        _drug(session, 2, "maintenance-drug")
        for sig_id, drug_cui, cycles, phase, step in (
            (1, 1, "1,2,(3),(4)", Sigs_PhaseEnum.INDUCTION, 1),
            (2, 2, "1", Sigs_PhaseEnum.MAINTENANCE, 2),
        ):
            _sig(
                session, sig_id=sig_id, variant_cui=114, drug_cui=drug_cui,
                route="INTRAVENOUS", alldays="1", timing_sequence=cycles,
                cycle_length_lb="14", cycle_length_ub="14",
                cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
                phase=phase, phase_step=step,
            )
        session.expire_all()

        frame = roll_out_variant(variant, decay_days=0)
        induction = frame[frame["phase"] == Sigs_PhaseEnum.INDUCTION]
        assert induction.loc[induction["cycle_number"] == 3, "optional"].all()
        assert set(induction.loc[induction["cycle_number"] < 3, "timing_status"]) == {"resolved"}
        assert set(induction.loc[induction["cycle_number"] == 3, "timing_status"]) == {
            "resolved_via_fallback: optional cycles 3, 4 assumed given"
        }
        assert set(induction.loc[induction["cycle_number"] == 4, "timing_status"]) == {
            "resolved_via_fallback: optional cycles 3, 4 assumed given"
        }
        maintenance = frame[frame["phase"] == Sigs_PhaseEnum.MAINTENANCE]
        assert maintenance["elapsed_day"].iloc[0] == 56
        assert set(maintenance["timing_status"]) == {
            "resolved_via_fallback: optional cycles 3, 4 assumed given"
        }

    def test_later_block_in_same_phase_inherits_optional_cycle_assumption(self, session):
        variant = _variant(session, 115)
        _drug(session, 1, "optional-drug")
        _drug(session, 2, "later-drug")
        for sig_id, drug_cui, cycles in ((1, 1, "1,(2)"), (2, 2, "3")):
            _sig(
                session, sig_id=sig_id, variant_cui=115, drug_cui=drug_cui,
                route="INTRAVENOUS", alldays="1", timing_sequence=cycles,
                cycle_length_lb="14", cycle_length_ub="14",
                cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
            )
        session.expire_all()

        frame = roll_out_variant(variant, decay_days=0)
        assert frame.loc[frame["cycle_number"] == 1, "timing_status"].iloc[0] == "resolved"
        assert set(frame.loc[frame["cycle_number"] >= 2, "timing_status"]) == {
            "resolved_via_fallback: optional cycle 2 assumed given"
        }

    def test_optional_cycle_and_phase_order_keep_both_fallback_reasons(self, session):
        variant = _variant(session, 116)
        _drug(session, 1, "perioperative-drug")
        _drug(session, 2, "later-drug")
        for sig_id, drug_cui, cycles, phase, step in (
            (1, 1, "1,(2)", Sigs_PhaseEnum.PERIOPERATIVE, 1),
            (2, 2, "1", Sigs_PhaseEnum.MAINTENANCE, 2),
        ):
            _sig(
                session, sig_id=sig_id, variant_cui=116, drug_cui=drug_cui,
                route="INTRAVENOUS", alldays="1", timing_sequence=cycles,
                cycle_length_lb="14", cycle_length_ub="14",
                cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
                phase=phase, phase_step=step,
            )
        session.expire_all()

        frame = roll_out_variant(variant, decay_days=0)
        assert set(frame.loc[frame["phase"] == Sigs_PhaseEnum.MAINTENANCE, "timing_status"]) == {
            "resolved_via_fallback: perioperative ordered by documented convention, not phase_step; optional cycle 2 assumed given"
        }

    def test_numeric_continuation_prevents_later_phase_chaining(self, session):
        variant = _variant(session, 117)
        _drug(session, 1, "continuing-drug")
        _drug(session, 2, "later-drug")
        for sig_id, drug_cui, cycles, phase, step in (
            (1, 1, "1,(+2)", Sigs_PhaseEnum.INDUCTION, 1),
            (2, 2, "1", Sigs_PhaseEnum.MAINTENANCE, 2),
        ):
            _sig(
                session, sig_id=sig_id, variant_cui=117, drug_cui=drug_cui,
                route="INTRAVENOUS", alldays="1", timing_sequence=cycles,
                cycle_length_lb="21", cycle_length_ub="21",
                cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
                phase=phase, phase_step=step,
            )
        session.expire_all()

        frame = roll_out_variant(variant, decay_days=0)
        induction = frame[frame["phase"] == Sigs_PhaseEnum.INDUCTION]
        maintenance = frame[frame["phase"] == Sigs_PhaseEnum.MAINTENANCE]
        assert induction["elapsed_day"].iloc[0] == 0
        assert induction["cycle_indefinite"].iloc[0] == Indefinite(kind="+k", interval=2)
        assert maintenance["elapsed_day"].isna().all()
        assert set(maintenance["timing_status"]) == {
            "unresolved: previous phase continues (every 2 cycles)"
        }

    @pytest.mark.parametrize(
        ("length", "unit"),
        [("21", None), ("NS", Sigs_Cycle_length_unitEnum.DAY)],
    )
    def test_indefinite_block_with_bad_cycle_length_is_unresolved(self, session, length, unit):
        variant = _variant(session, 124)
        _drug(session, 1, "continuing-drug")
        _sig(
            session, sig_id=1, variant_cui=124, drug_cui=1,
            route="INTRAVENOUS", alldays="1", timing_sequence="1,(+1)",
            cycle_length_lb=length, cycle_length_ub=length,
            cycle_length_unit=unit,
        )
        session.expire_all()

        for frame in (
            roll_out_variant(variant, decay_days=0),
            administration_frame(variant, decay_days=0),
        ):
            assert len(frame) == 1
            assert frame["elapsed_day"].isna().all()
            assert frame["timing_status"].str.startswith("unresolved:").all()

    def test_numeric_day_continuation_is_preserved(self, session):
        variant = _variant(session, 118)
        _drug(session, 1, "continuing-days-drug")
        _sig(
            session, sig_id=1, variant_cui=118, drug_cui=1,
            route="INTRAVENOUS", alldays="1,(+30)", timing_sequence="1",
            cycle_length_lb="30", cycle_length_ub="30",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
        )
        session.expire_all()

        frame = roll_out_variant(variant, decay_days=0)
        assert frame["day_indefinite"].iloc[0] == Indefinite(kind="+k", interval=30)
        assert set(frame["day"]) == {1}

    def test_phase_end_uses_longest_overlapping_block(self, session):
        variant = _variant(session, 101)
        _drug(session, 1, "long-course")
        _drug(session, 2, "cycle-three")
        _drug(session, 3, "next-phase")
        for sig_id, drug_cui, cycles, phase, step in (
            (1, 1, "1,2,3,4,5,6", Sigs_PhaseEnum.INDUCTION, 1),
            (2, 2, "3", Sigs_PhaseEnum.INDUCTION, 1),
            (3, 3, "1", Sigs_PhaseEnum.MAINTENANCE, 2),
        ):
            _sig(
                session, sig_id=sig_id, variant_cui=101, drug_cui=drug_cui,
                route="INTRAVENOUS", alldays="1", timing_sequence=cycles,
                cycle_length_lb="21", cycle_length_ub="21",
                cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
                phase=phase, phase_step=step,
            )
        session.expire_all()

        frame = roll_out_variant(variant, decay_days=0)
        assert frame.loc[frame["drug"] == "next-phase", "elapsed_day"].iloc[0] == 126

    def test_unresolved_block_end_prevents_phase_chaining(self, session):
        variant = _variant(session, 107)
        for cui in (1, 2, 3):
            _drug(session, cui, f"drug-{cui}")
        for sig_id, drug_cui, cycles, length, phase, step in (
            (1, 1, "1,2,3", "21", Sigs_PhaseEnum.INDUCTION, 1),
            (2, 2, "2", "not-a-number", Sigs_PhaseEnum.INDUCTION, 1),
            (3, 3, "1", "21", Sigs_PhaseEnum.MAINTENANCE, 2),
        ):
            _sig(
                session, sig_id=sig_id, variant_cui=107, drug_cui=drug_cui,
                route="INTRAVENOUS", alldays="1", timing_sequence=cycles,
                cycle_length_lb=length, cycle_length_ub=length,
                cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
                phase=phase, phase_step=step,
            )
        session.expire_all()

        frame = roll_out_variant(variant, decay_days=0)
        next_phase = frame[frame["phase"] == Sigs_PhaseEnum.MAINTENANCE]
        assert set(next_phase["timing_status"]) == {
            "unresolved: previous phase end is unresolved"
        }
        assert next_phase["elapsed_day"].isna().all()

    def test_fallback_ordered_phases_chain(self, session):
        variant = _variant(session, 102)
        _drug(session, 1, "perioperative-drug")
        _drug(session, 2, "adjuvant-drug")
        for sig_id, drug_cui, phase, step in (
            (1, 1, Sigs_PhaseEnum.PERIOPERATIVE, 1),
            (2, 2, Sigs_PhaseEnum.ADJUVANT, 2),
        ):
            _sig(
                session, sig_id=sig_id, variant_cui=102, drug_cui=drug_cui,
                route="INTRAVENOUS", alldays="1", timing_sequence="1,2",
                cycle_length_lb="14", cycle_length_ub="14",
                cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
                phase=phase, phase_step=step,
            )
        session.expire_all()

        frame = roll_out_variant(variant, decay_days=0)
        adjuvant = frame[frame["phase"] == Sigs_PhaseEnum.ADJUVANT]
        assert adjuvant["elapsed_day"].min() == 28
        assert adjuvant["timing_status"].str.startswith("resolved_via_fallback:").all()

    def test_empty_rollout_keeps_prefixed_order_status(self, session):
        variant = _variant(session, 103)
        _drug(session, 1, "perioperative-drug")
        _drug(session, 2, "adjuvant-drug")
        for sig_id, drug_cui, phase, step in (
            (1, 1, Sigs_PhaseEnum.PERIOPERATIVE, 1),
            (2, 2, Sigs_PhaseEnum.ADJUVANT, 2),
        ):
            _sig(
                session, sig_id=sig_id, variant_cui=103, drug_cui=drug_cui,
                route="INTRAVENOUS", alldays="[1,EOC,7]", timing_sequence="1",
                cycle_length_lb="14", cycle_length_ub="14",
                cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
                phase=phase, phase_step=step,
            )
        session.expire_all()

        frame = roll_out_variant(variant)
        assert frame.empty
        assert frame.attrs["timing_status"].startswith("resolved_via_fallback:")

    @pytest.mark.parametrize(
        ("variant_cui", "alldays", "timing_sequence", "day_indefinite", "cycle_indefinite"),
        [
            (104, "1,(+c)", "1", True, False),
            (105, "1", "1,(+n)", False, True),
        ],
    )
    def test_indefinite_markers_identify_their_scope(
        self, session, variant_cui, alldays, timing_sequence,
        day_indefinite, cycle_indefinite,
    ):
        variant = _variant(session, variant_cui)
        _drug(session, 1, "continuing-drug")
        _sig(
            session, sig_id=1, variant_cui=variant_cui, drug_cui=1,
            route="ORAL", alldays=alldays, timing_sequence=timing_sequence,
            cycle_length_lb="21", cycle_length_ub="21",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
        )
        session.expire_all()

        rolled = roll_out_variant(variant, decay_days=0)
        administered = administration_frame(variant, decay_days=0)
        assert (rolled["day_indefinite"].notna().all()) == day_indefinite
        assert (rolled["cycle_indefinite"].notna().all()) == cycle_indefinite
        assert (administered["indefinite"].notna().all()) == day_indefinite
        assert (administered["cycle_indefinite"].notna().all()) == cycle_indefinite

    def test_radiation_rows_are_labeled_and_anchor_later_phases(self, session):
        variant = _variant(session, 106)
        _drug(session, 1, "adjuvant-drug")
        _sig(
            session, sig_id=1, variant_cui=106, drug_cui=999,
            route="NS", alldays="1", timing_sequence="1,2",
            cycle_length_lb="14", cycle_length_ub="14",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
            phase=Sigs_PhaseEnum.DEFINITIVE, phase_step=1,
            class_field=Sigs_Class_fieldEnum.RAD_SIG, component="radiotherapy",
        )
        _sig(
            session, sig_id=2, variant_cui=106, drug_cui=1,
            route="INTRAVENOUS", alldays="1", timing_sequence="1",
            cycle_length_lb="21", cycle_length_ub="21",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
            phase=Sigs_PhaseEnum.ADJUVANT, phase_step=2,
            component="adjuvant-drug",
        )
        session.expire_all()

        frame = roll_out_variant(variant, decay_days=0)
        radiation = frame[frame["modality"] == "radiation"]
        assert len(radiation) == 2
        assert radiation["drug"].isna().all()
        assert set(radiation["component"]) == {"radiotherapy"}
        assert set(radiation["component_cui"]) == {999}
        assert frame.loc[frame["modality"] == "systemic", "elapsed_day"].iloc[0] == 28

        systemic = roll_out_variant(variant, decay_days=0, systemic_only=True)
        assert set(systemic["modality"]) == {"systemic"}
        assert systemic["elapsed_day"].iloc[0] == 28

    def test_unclassified_sig_keeps_unknown_modality(self, session):
        variant = _variant(session, 108)
        _drug(session, 1, "unknown-class-drug")
        _sig(
            session, sig_id=1, variant_cui=108, drug_cui=1,
            route="INTRAVENOUS", alldays="1", timing_sequence="1",
            cycle_length_lb="21", cycle_length_ub="21",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
            class_field=None,
        )
        session.expire_all()

        assert roll_out_variant(variant, systemic_only=True)["modality"].isna().all()

    def test_phase_step_tie_is_unresolved(self, session):
        variant = _variant(session, 97)
        _drug(session, 1, "induction-drug")
        _drug(session, 2, "consolidation-drug")
        for sig_id, drug_cui, phase in (
            (1, 1, Sigs_PhaseEnum.INDUCTION),
            (2, 2, Sigs_PhaseEnum.CONSOLIDATION),
        ):
            _sig(
                session, sig_id=sig_id, variant_cui=97, drug_cui=drug_cui,
                route="INTRAVENOUS", alldays="1", timing_sequence="1",
                cycle_length_lb="14", cycle_length_ub="14",
                cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
                phase=phase, phase_step=1,
            )
        session.expire_all()

        frame = roll_out_variant(variant, start_date=date(2020, 1, 1))
        assert frame["timing_status"].str.startswith("unresolved:").all()
        assert frame["elapsed_day"].isna().all()
        assert frame["calendar_date"].isna().all()


class TestRealVariantSnapshots:
    """Source rows from the development HemOnc database on 2026-09-24."""

    def test_ddfec_ddth_cycle_length_change(self, session):
        variant = _source_variant(session, 131576, [
            ("Cyclophosphamide", 122, "1", "1,2,3,4", "2", "WEEK", "INTRAVENOUS", _IV_SIG, None, 1),
            ("Docetaxel", 164, "1", "5,6,7,8", "2", "WEEK", "INTRAVENOUS", _IV_SIG, None, 1),
            ("Epirubicin", 191, "1", "1,2,3,4", "2", "WEEK", "INTRAVENOUS", _IV_SIG, None, 1),
            ("Filgrastim", 220, "[3,10,1]", "1,2,3,4,5,6,7,8", "2", "WEEK", "SUBCUTANEOUS", _NONIV_SIG, None, 1),
            ("Fluorouracil", 225, "1", "1,2,3,4", "2", "WEEK", "INTRAVENOUS", _IV_SIG, None, 1),
            ("Trastuzumab", 512, "1", "5", "2", "WEEK", "INTRAVENOUS", _IV_SIG, None, 1),
            ("Trastuzumab", 512, "1", "6,7,8", "2", "WEEK", "INTRAVENOUS", _IV_SIG, None, 1),
            ("Trastuzumab", 512, "1", "9,10,11,12,13,14,15,16,17,18,19,20", "3", "WEEK", "INTRAVENOUS", _IV_SIG, None, 1),
        ])
        frame = roll_out_variant(variant, start_date=date(2020, 1, 1), decay_days=0)
        cycle_nine = frame[(frame["component"] == "Trastuzumab") & (frame["cycle_number"] == 9)]
        # Eight two-week cycles end 112 days after 2020-01-01.
        assert cycle_nine["elapsed_day"].iloc[0] == 112
        assert cycle_nine["calendar_date"].iloc[0] == date(2020, 4, 22)
        assert set(frame["timing_status"]) == {"resolved"}

    def test_dara_krd_pattern_changes_within_four_week_cycles(self, session):
        variant = _source_variant(session, 131485, [
            ("Carfilzomib", 89, "[8,15,7]", "1", "4", "WEEK", "INTRAVENOUS", _IV_SIG, None, 1),
            ("Carfilzomib", 89, "1", "1", "4", "WEEK", "INTRAVENOUS", _IV_SIG, None, 1),
            ("Carfilzomib", 89, "[1,15,7]", "2,3,4,5,6,7,8", "4", "WEEK", "INTRAVENOUS", _IV_SIG, None, 1),
            ("Daratumumab", 139, "[1,22,7]", "1,2", "4", "WEEK", "INTRAVENOUS", _IV_SIG, None, 1),
            ("Daratumumab", 139, "[1,15,14]", "3,4,5,6", "4", "WEEK", "INTRAVENOUS", _IV_SIG, None, 1),
            ("Daratumumab", 139, "1", "7,8", "4", "WEEK", "INTRAVENOUS", _IV_SIG, None, 1),
            ("Dexamethasone", 156, "[1,22,7]", "1,2,3,4", "4", "WEEK", "INTRAVENOUS", _IV_SIG, None, 1),
            ("Dexamethasone", 156, "[1,22,7]", "5,6,7,8", "4", "WEEK", "ORAL", _NONIV_SIG, None, 1),
            ("Lenalidomide", 299, "[1,21,1]", "1,2,3,4,5,6,7,8", "4", "WEEK", "ORAL", _NONIV_SIG, None, 1),
        ])
        frame = roll_out_variant(variant, decay_days=0)
        daratumumab = frame[frame["component"] == "Daratumumab"]
        # Cycle 3 starts at 2 × 28 = 56 days; day 15 is day 70.
        assert set(daratumumab[daratumumab["cycle_number"] == 3]["elapsed_day"]) == {56, 70}
        # Cycle 7 starts at 6 × 28 = 168 days and has only day 1.
        assert set(daratumumab[daratumumab["cycle_number"] == 7]["elapsed_day"]) == {168}
        assert set(frame["timing_status"]) == {"resolved"}

    def test_five_plus_two_day_control(self, session):
        variant = _source_variant(session, 129498, [
            ("Cytarabine", 126, "1", "1", "5", "DAY", "INTRAVENOUS", _IV_CONT_SIG, None, 1),
            ("Daunorubicin", 143, "[1,2,1]", "1", "5", "DAY", "INTRAVENOUS", _IV_SIG, None, 1),
        ])
        frame = roll_out_variant(variant, decay_days=0)
        # A single five-day block begins at day 0; its explicit days are 1 and 2.
        assert set(frame["elapsed_day"]) == {0, 1}
        assert set(frame["timing_status"]) == {"resolved"}

    def test_tislelizumab_neoadjuvant_to_adjuvant(self, session):
        variant = _source_variant(session, 150930, [
            ("Carboplatin", 88, "1", "1,2,3,(4)", "3", "WEEK", "INTRAVENOUS", _IV_SIG, "NEOADJUVANT", 1),
            ("Paclitaxel", 379, "1", "1,2,3,(4)", "3", "WEEK", "INTRAVENOUS", _IV_SIG, "NEOADJUVANT", 1),
            ("Tislelizumab", 64463, "1", "1,2,3,(4)", "3", "WEEK", "INTRAVENOUS", _IV_SIG, "NEOADJUVANT", 1),
            ("Tislelizumab", 64463, "1", "1,2,3,4,5,6,7,8", "6", "WEEK", "INTRAVENOUS", _IV_SIG, "ADJUVANT", 3),
        ])
        frame = roll_out_variant(variant, decay_days=0)
        neoadjuvant = frame[frame["phase"] == Sigs_PhaseEnum.NEOADJUVANT]
        adjuvant = frame[frame["phase"] == Sigs_PhaseEnum.ADJUVANT]
        # Optional cycle 4 begins after three 21-day cycles.
        assert neoadjuvant.loc[neoadjuvant["cycle_number"] == 4, "elapsed_day"].iloc[0] == 63
        assert neoadjuvant.loc[neoadjuvant["cycle_number"] == 4, "optional"].all()
        assert set(neoadjuvant.loc[neoadjuvant["cycle_number"] < 4, "timing_status"]) == {"resolved"}
        assert set(neoadjuvant.loc[neoadjuvant["cycle_number"] == 4, "timing_status"]) == {
            "resolved_via_fallback: optional cycle 4 assumed given"
        }
        # Step 2 has no sig, so adjuvant dates are unknown.
        assert adjuvant["elapsed_day"].isna().all()
        assert set(adjuvant["timing_status"]) == {
            "unresolved: phase_step gap before step 3 (no sigs for step 2)"
        }

    def test_osimertinib_compact_daily_days(self, session):
        variant = _source_variant(session, 136672, [
            ("Carboplatin", 88, "1", "1,2,3,4", "3", "WEEK", "INTRAVENOUS", _IV_SIG, None, 1),
            ("Osimertinib", 375, "[1,21,1]", "1,(+1)", "3", "WEEK", "ORAL", _NONIV_SIG, None, 1),
            ("Pemetrexed", 395, "1", "1,(+1)", "3", "WEEK", "INTRAVENOUS", _IV_SIG, None, 1),
        ])
        frame = roll_out_variant(variant, decay_days=0)
        oral = frame[frame["component"] == "Osimertinib"]
        # The source's explicit range covers days 1 through 21 in cycle 1.
        assert set(oral["elapsed_day"]) == set(range(21))
        # Carboplatin cycle 4 begins after 3 × 21 = 63 days.
        assert frame[(frame["component"] == "Carboplatin") & (frame["cycle_number"] == 4)]["elapsed_day"].iloc[0] == 63
        assert set(frame["timing_status"]) == {"resolved"}
        assert set(oral["cycle_indefinite"]) == {Indefinite(kind="+k", interval=1)}

    def test_ipilimumab_cycle_three_overlaps_six_cycle_cp(self, session):
        variant = _source_variant(session, 130411, [
            ("Carboplatin", 88, "1", "1,2,3,4,5,6", "3", "WEEK", "INTRAVENOUS", _IV_SIG, None, 1),
            ("Ipilimumab", 279, "1", "3,(+1)", "12", "WEEK", "INTRAVENOUS", _IV_SIG, None, 1),
            ("Paclitaxel", 379, "1", "1,2,3,4,5,6", "3", "WEEK", "INTRAVENOUS", _IV_SIG, None, 1),
        ])
        frame = roll_out_variant(variant, decay_days=0)
        # Ipilimumab cycle 3 starts after two three-week CP cycles: 42 days.
        assert frame.loc[frame["component"] == "Ipilimumab", "elapsed_day"].iloc[0] == 42
        # CP cycle 6 begins after five three-week cycles: 105 days.
        assert frame[(frame["component"] == "Paclitaxel") & (frame["cycle_number"] == 6)]["elapsed_day"].iloc[0] == 105
        assert set(frame["timing_status"]) == {"resolved"}
        assert frame.loc[frame["component"] == "Ipilimumab", "cycle_indefinite"].iloc[0] == Indefinite(kind="+k", interval=1)


class TestAdministrationFrame:
    def _nsclc_ish(self, session):
        variant = _variant(session, 10)
        _drug(session, 1, "carboplatin")
        _drug(session, 2, "etoposide")
        _sig(session, sig_id=1, variant_cui=10, drug_cui=1, route="INTRAVENOUS", alldays="1")
        _sig(session, sig_id=2, variant_cui=10, drug_cui=2, route="ORAL", alldays="1,2,3")
        session.expire_all()
        return variant

    def test_one_row_per_drug_per_day(self, session):
        frame = administration_frame(self._nsclc_ish(session), decay_days=0)
        assert list(frame.columns) == [
            "variant_cui", "variant", "route_group", "drug_cui", "drug",
            "day", "intensity", "optional", "indefinite", "cycle_indefinite",
            "elapsed_day", "timing_status",
        ]
        assert len(frame) == 4  # carboplatin d1, etoposide d1-3
        assert set(frame["route_group"]) == {"IV", "PO"}
        assert (frame["intensity"] == 1.0).all()

    def test_a_single_variant_is_not_iterated_into_its_columns(self, session):
        """Entities inherit __iter__ from orm-loader's serialisation
        interface, so a naive Iterable check treats one variant as a
        collection of its own column values."""
        frame = administration_frame(self._nsclc_ish(session))
        assert set(frame["variant_cui"]) == {10}

    def test_decay_tapers_after_each_dosing_day(self, session):
        frame = administration_frame(self._nsclc_ish(session), decay_days=2, decay_factor=0.5)
        carbo = frame[frame["drug"] == "carboplatin"].set_index("day")["intensity"]
        assert carbo.loc[1] == 1.0
        assert carbo.loc[2] == 0.5
        assert carbo.loc[3] == 0.25

    def test_carries_both_drug_identifier_and_name(self, session):
        """The original keyed its grid by display name, so two distinct drugs
        sharing one name merged into a single row."""
        frame = administration_frame(self._nsclc_ish(session))
        assert set(zip(frame["drug_cui"], frame["drug"])) == {
            (1, "carboplatin"), (2, "etoposide"),
        }

    def test_unclassified_route_is_excluded(self, session):
        variant = _variant(session, 20)
        _drug(session, 1, "something")
        _sig(session, sig_id=1, variant_cui=20, drug_cui=1, route="NS", alldays="1")
        session.expire_all()
        assert administration_frame(variant).empty

    def test_a_variant_with_no_resolvable_days_gives_an_empty_frame(self, session):
        """An `EOC` range has no known length, so it yields no explicit days --
        an empty frame, not an error."""
        variant = _variant(session, 30)
        _drug(session, 1, "something")
        _sig(session, sig_id=1, variant_cui=30, drug_cui=1, route="INTRAVENOUS", alldays="[1,EOC,7]")
        session.expire_all()

        frame = administration_frame(variant)
        assert frame.empty
        assert list(frame.columns)[:3] == ["variant_cui", "variant", "route_group"]

    def test_overlapping_sigs_for_one_drug_keep_the_strongest_day(self, session):
        """Two sigs can dose the same drug in one variant and their decay
        tails land on the same day."""
        variant = _variant(session, 40)
        _drug(session, 1, "fluorouracil")
        _sig(session, sig_id=1, variant_cui=40, drug_cui=1, route="INTRAVENOUS", alldays="1")
        _sig(session, sig_id=2, variant_cui=40, drug_cui=1, route="INTRAVENOUS", alldays="2")
        session.expire_all()

        frame = administration_frame(variant)
        day_2 = frame[frame["day"] == 2]
        assert len(day_2) == 1                 # not one row per sig
        assert day_2["intensity"].iloc[0] == 1.0   # dosing day beats the other's tail

    @pytest.mark.parametrize("indefinite_first", [False, True])
    def test_collapsed_sigs_preserve_cycle_indefinite(self, session, indefinite_first):
        variant = _variant(session, 110)
        _drug(session, 1, "continuing-drug")
        sequences = ("1,(+n)", "1") if indefinite_first else ("1", "1,(+n)")
        for sig_id, sequence in enumerate(sequences, start=1):
            _sig(
                session, sig_id=sig_id, variant_cui=110, drug_cui=1,
                route="INTRAVENOUS", alldays="1", timing_sequence=sequence,
                cycle_length_lb="21", cycle_length_ub="21",
                cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
            )
        session.expire_all()

        frame = administration_frame(variant, decay_days=0)
        assert len(frame) == 1
        assert frame["cycle_indefinite"].iloc[0] is not None

    def test_many_variants_come_back_in_one_frame(self, session):
        _drug(session, 1, "cisplatin")
        for cui in (51, 52):
            _variant(session, cui)
            _sig(session, sig_id=cui, variant_cui=cui, drug_cui=1,
                 route="INTRAVENOUS", alldays="1")
        session.expire_all()

        variants = session.execute(sa.select(Variants)).scalars().all()
        frame = administration_frame(variants)
        assert set(frame["variant_cui"]) == {51, 52}
        assert len(frame.groupby("variant_cui")) == 2

    def test_the_functions_issue_no_queries_of_their_own(self, session):
        """Sigs and drugs are batch-loaded with the variants, so summarising
        them costs nothing further -- looping is no worse than batching."""
        _drug(session, 1, "cisplatin")
        for cui in (61, 62, 63):
            _variant(session, cui)
            _sig(session, sig_id=cui, variant_cui=cui, drug_cui=1,
                 route="INTRAVENOUS", alldays="1,8")
        session.commit()
        session.expire_all()

        seen: list[str] = []
        engine = session.get_bind()

        def record(conn, cursor, statement, parameters, context, executemany):
            seen.append(statement)

        sa.event.listen(engine, "before_cursor_execute", record)
        try:
            variants = session.execute(sa.select(Variants)).scalars().all()
            after_load = len(seen)
            administration_frame(variants)
            assert len(seen) == after_load
        finally:
            sa.event.remove(engine, "before_cursor_execute", record)

    def test_elapsed_day_exposes_cross_block_timing(self, session):
        variant = TestRollout()._two_block_variant(session, variant_cui=98)

        frame = administration_frame(variant, decay_days=0)
        first_block = frame[frame["drug"] == "docetaxel"]
        second_block = frame[frame["drug"] == "trastuzumab"]

        assert first_block["elapsed_day"].min() == 0
        assert second_block["elapsed_day"].min() == 112
        assert set(frame["day"]) == {1}
        assert set(frame["timing_status"]) == {"resolved"}


class TestAdministrationMatrix:
    def test_pivots_to_the_drug_by_day_grid(self, session):
        variant = _variant(session, 70)
        _drug(session, 1, "carboplatin")
        _sig(session, sig_id=1, variant_cui=70, drug_cui=1, route="INTRAVENOUS", alldays="1,8")
        session.expire_all()

        grid = administration_matrix(administration_frame(variant, decay_days=0))
        assert list(grid.index) == ["carboplatin"]
        assert list(grid.columns) == [1, 8]
        assert grid.loc["carboplatin", 8] == 1.0

    def test_a_route_with_no_rows_gives_an_empty_grid(self, session):
        variant = _variant(session, 80)
        _drug(session, 1, "capecitabine")
        _sig(session, sig_id=1, variant_cui=80, drug_cui=1, route="ORAL", alldays="1")
        session.expire_all()

        frame = administration_frame(variant)
        assert administration_matrix(frame, route="IV").empty
        assert not administration_matrix(frame, route="PO").empty


class TestRouteGroupedHelpers:
    def test_splits_drugs_by_where_they_are_given(self, session):
        variant = _variant(session, 90)
        _drug(session, 1, "carboplatin")
        _drug(session, 2, "etoposide")
        _sig(session, sig_id=1, variant_cui=90, drug_cui=1, route="INTRAVENOUS", alldays="1")
        _sig(session, sig_id=2, variant_cui=90, drug_cui=2, route="ORAL", alldays="1,2,3")
        session.expire_all()

        assert [d.drug for d in cancer_services_drugs(variant)] == ["carboplatin"]
        assert [d.drug for d in home_administered_drugs(variant)] == ["etoposide"]

    def test_sigs_grouped_by_drug(self, session):
        variant = _variant(session, 100)
        drug = _drug(session, 1, "cisplatin")
        _sig(session, sig_id=1, variant_cui=100, drug_cui=1, route="INTRAVENOUS", alldays="1")
        _sig(session, sig_id=2, variant_cui=100, drug_cui=1, route="INTRAVENOUS", alldays="8")
        session.expire_all()

        by_drug = cancer_services_sigs_by_drug(variant)
        assert list(by_drug) == [drug]
        assert len(by_drug[drug]) == 2


if __name__ == "__main__":
    pytest.main([__file__])
