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
from hemonc_alchemy.model.enums import Sigs_Cycle_length_unitEnum, Sigs_PhaseEnum
from hemonc_alchemy.toolkit.analytics.treatment.scheduling import (
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
    assert not overrides
    sig = Sigs(
        id=sig_id, variant_cui=variant_cui, component_cui=drug_cui, component=f"c{drug_cui}",
        class_field="iv intermittent canonical sig", component_role="primary systemic",
        portion="1", regimen="R", regimen_cui=1, step_number="1", divided=False,
        phase=phase, phase_step=phase_step, variant=f"v{variant_cui}", route=route,
        alldays=alldays, timing_sequence=timing_sequence,
        cycle_length_lb=cycle_length_lb, cycle_length_ub=cycle_length_ub,
        cycle_length_unit=cycle_length_unit, date_added=_D,
    )
    session.add(sig)
    session.flush()
    return sig


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
            route="ORAL", alldays="1", timing_sequence="1,2",
            cycle_length_lb="14", cycle_length_ub="14",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
        )
        session.expire_all()

        anchored = anchor_blocks(group_into_blocks(schedule_events(variant)))
        assert [item.anchor_kind for item in anchored] == ["phase_start", "overlap"]

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

        frame = roll_out_variant(variant)
        assert frame["timing_status"].str.startswith("unresolved:").all()


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
            "day", "intensity", "optional", "indefinite", "elapsed_day", "timing_status",
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
