"""`build_schedule_view`, against real in-memory rows and real imported variants."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
import sqlalchemy as sa
import sqlalchemy.orm as so

from hemonc_alchemy.model.base import Base
from hemonc_alchemy.model.entities import Drugs, Sigs, Variants
from hemonc_alchemy.model.enums import Sigs_Cycle_length_unitEnum, Sigs_PhaseEnum
from hemonc_alchemy.toolkit.analytics.treatment.scheduling.diagnostics import (
    DiagnosticCategory,
)
from hemonc_alchemy.toolkit.analytics.treatment.scheduling.views import (
    MAX_COMPARED_VARIANTS,
    SchedulePolicy,
    build_schedule_view,
    build_schedule_views,
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


def _variant(session, variant_cui: int, version: int = 1) -> Variants:
    variant = Variants(
        id=variant_cui, variant_cui=variant_cui, variant=f"v{variant_cui}",
        regimen_cui=1, regimen="R", version=version, cyclesigs=0, components=0, portions=0,
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


def _sig(session, *, sig_id, variant_cui, drug_cui, route, alldays, **overrides) -> Sigs:
    timing_sequence = overrides.pop("timing_sequence", None)
    cycle_length_lb = overrides.pop("cycle_length_lb", None)
    cycle_length_ub = overrides.pop("cycle_length_ub", None)
    cycle_length_unit = overrides.pop("cycle_length_unit", None)
    phase = overrides.pop("phase", None)
    phase_step = overrides.pop("phase_step", 1)
    component = overrides.pop("component", f"c{drug_cui}")
    assert not overrides
    sig = Sigs(
        id=sig_id, variant_cui=variant_cui, component_cui=drug_cui, component=component,
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


class TestBuildScheduleView:
    def test_every_event_carries_its_source_instruction(self, session):
        variant = _variant(session, 1)
        _drug(session, 1, "cisplatin")
        _sig(session, sig_id=1, variant_cui=1, drug_cui=1, route="INTRAVENOUS", alldays="1,8,15")
        session.expire_all()

        view = build_schedule_view(variant)
        assert not view.bounded
        assert len(view.events) == 3
        assert all(event.instruction.sig_id == 1 for event in view.events)
        assert view.coverage.total_instructions == 1
        assert view.coverage.represented_instructions == 1
        assert view.coverage.unplaced_instructions == 0
        assert view.unplaced_instructions == ()

    def test_a_sig_absent_from_the_rollout_becomes_unplaced_not_dropped(self, session):
        # Mirrors P0-A15/P0-A16: a source sig with no day expression at all
        # never appears in `roll_out_variant`'s frame.
        variant = _variant(session, 2)
        _drug(session, 1, "drug-a")
        _sig(session, sig_id=1, variant_cui=2, drug_cui=1, route="INTRAVENOUS", alldays="1")
        _sig(session, sig_id=2, variant_cui=2, drug_cui=1, route="NS", alldays=None)
        session.expire_all()

        view = build_schedule_view(variant)
        assert not view.bounded
        assert [event.instruction.sig_id for event in view.events] == [1]
        assert [u.instruction.sig_id for u in view.unplaced_instructions] == [2]
        assert view.coverage.total_instructions == 2
        assert view.coverage.represented_instructions == 1
        assert view.coverage.unplaced_instructions == 1
        assert any(
            d.category == DiagnosticCategory.UNSUPPORTED_ROUTE and d.sig_id == 2
            for d in view.diagnostics
        )

    def test_source_day_zero_is_preserved_and_elapsed_zero_displays_as_one(self, session):
        variant = _variant(session, 3)
        _drug(session, 1, "drug-a")
        _sig(
            session, sig_id=1, variant_cui=3, drug_cui=1, route="INTRAVENOUS",
            alldays="1", timing_sequence="1",
            cycle_length_lb="21", cycle_length_ub="21",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
        )
        session.expire_all()

        view = build_schedule_view(variant, SchedulePolicy(start_date=date(2020, 1, 1)))
        event = view.events[0]
        assert event.source_day == 1
        assert event.elapsed_day == 0
        assert event.display_day == 1

    def test_administration_setting_is_labelled_not_literal_iv(self, session):
        variant = _variant(session, 4)
        _drug(session, 1, "oral-drug")
        _drug(session, 2, "iv-drug")
        _sig(session, sig_id=1, variant_cui=4, drug_cui=1, route="ORAL", alldays="1")
        _sig(session, sig_id=2, variant_cui=4, drug_cui=2, route="INTRAVENOUS", alldays="1")
        session.expire_all()

        view = build_schedule_view(variant)
        settings = {event.instruction.sig_id: event.administration_setting for event in view.events}
        assert settings == {1: "home", 2: "clinic"}
        # The actual source route stays available too, not collapsed into the setting.
        assert view.events[0].instruction.route is not None

    def test_decay_days_is_forced_to_zero_regardless_of_the_toolkit_default(self, session):
        variant = _variant(session, 5)
        _drug(session, 1, "drug-a")
        _sig(
            session, sig_id=1, variant_cui=5, drug_cui=1, route="INTRAVENOUS",
            alldays="1", timing_sequence="1,2",
            cycle_length_lb="7", cycle_length_ub="7",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
        )
        session.expire_all()

        view = build_schedule_view(variant)
        # decay_days=2 (the toolkit's own default) would add decay rows after
        # each dose; forcing 0 keeps exactly one row per cycle.
        assert len(view.events) == 2
        assert all(event.intensity == 1.0 for event in view.events)

    def test_radiation_and_unclassified_sigs_are_preserved(self, session):
        variant = _variant(session, 6)
        _sig(
            session, sig_id=1, variant_cui=6, drug_cui=999, route="NS", alldays="1",
            component="radiotherapy",
        )
        session.flush()
        session.query(Sigs).filter_by(id=1).update({"class_field": "rad sig"})
        _drug(session, 1, "unclassified-drug")
        _sig(session, sig_id=2, variant_cui=6, drug_cui=1, route="INTRAVENOUS", alldays="1")
        session.query(Sigs).filter_by(id=2).update({"class_field": None})
        session.expire_all()

        view = build_schedule_view(variant)
        modalities = {event.instruction.sig_id: event.modality for event in view.events}
        assert modalities[1] == "radiation"
        assert modalities[2] is None

    def test_event_limit_overflow_returns_an_explicit_bounded_result(self, session, monkeypatch):
        import hemonc_alchemy.toolkit.analytics.treatment.scheduling.views as views_module

        variant = _variant(session, 7)
        _drug(session, 1, "drug-a")
        _sig(session, sig_id=1, variant_cui=7, drug_cui=1, route="INTRAVENOUS", alldays="1")
        session.expire_all()

        monkeypatch.setattr(views_module, "EVENT_LIMIT", 0)
        view = build_schedule_view(variant)
        assert view.bounded is True
        assert view.events == ()
        assert view.unplaced_instructions == ()
        assert view.coverage.total_instructions == 1
        assert view.coverage.represented_instructions is None
        assert any(
            d.category == DiagnosticCategory.LIMIT_EXCEEDED for d in view.diagnostics
        )

    def test_a_crashing_day_expression_returns_a_bounded_result_not_a_raise(self, session):
        # P0-A18's standalone regression sigs, here attached to a variant:
        # the shared parser's `parse_optional` raises a bare `ValueError`.
        variant = _variant(session, 8)
        _drug(session, 1, "drug-a")
        _sig(
            session, sig_id=1, variant_cui=8, drug_cui=1, route="INTRAVENOUS",
            alldays="(1),(2),(3),(4),(5),(6),(7)",
        )
        session.expire_all()

        view = build_schedule_view(variant)
        assert view.bounded is True
        assert view.coverage.total_instructions == 1
        assert any(
            d.category == DiagnosticCategory.PARSE_ERROR for d in view.diagnostics
        )

    def test_phase_and_variant_relative_offsets_are_both_kept(self, session):
        variant = _variant(session, 9)
        _drug(session, 1, "induction-drug")
        _drug(session, 2, "maintenance-drug")
        _sig(
            session, sig_id=1, variant_cui=9, drug_cui=1, route="INTRAVENOUS",
            alldays="1", timing_sequence="1,2",
            cycle_length_lb="14", cycle_length_ub="14",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
            phase=Sigs_PhaseEnum.INDUCTION, phase_step=1,
        )
        _sig(
            session, sig_id=2, variant_cui=9, drug_cui=2, route="INTRAVENOUS",
            alldays="1", timing_sequence="1",
            cycle_length_lb="21", cycle_length_ub="21",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
            phase=Sigs_PhaseEnum.MAINTENANCE, phase_step=2,
        )
        session.expire_all()

        view = build_schedule_view(variant)
        maintenance_event = next(
            e for e in view.events if e.instruction.sig_id == 2
        )
        assert maintenance_event.elapsed_day == 28
        assert maintenance_event.phase_elapsed_day == 0
        assert maintenance_event.phase_display_day == 1

    def test_policy_is_echoed_back(self, session):
        variant = _variant(session, 10)
        _drug(session, 1, "drug-a")
        _sig(session, sig_id=1, variant_cui=10, drug_cui=1, route="INTRAVENOUS", alldays="1")
        session.expire_all()

        policy = SchedulePolicy(cycle_length_selection="ub")
        view = build_schedule_view(variant, policy)
        assert view.policy == policy
        assert view.variant_cui == 10
        assert view.version == 1


class TestBuildScheduleViews:
    def test_more_than_the_comparison_limit_is_rejected(self, session):
        variants = []
        for cui in range(1, MAX_COMPARED_VARIANTS + 2):
            variant = _variant(session, cui)
            _drug(session, cui, f"drug-{cui}")
            _sig(session, sig_id=cui, variant_cui=cui, drug_cui=cui, route="INTRAVENOUS", alldays="1")
            variants.append(variant)
        session.expire_all()

        with pytest.raises(ValueError, match=str(MAX_COMPARED_VARIANTS)):
            build_schedule_views(variants)

    def test_up_to_the_limit_is_accepted(self, session):
        variants = []
        for cui in range(1, MAX_COMPARED_VARIANTS + 1):
            variant = _variant(session, cui)
            _drug(session, cui, f"drug-{cui}")
            _sig(session, sig_id=cui, variant_cui=cui, drug_cui=cui, route="INTRAVENOUS", alldays="1")
            variants.append(variant)
        session.expire_all()

        views = build_schedule_views(variants)
        assert len(views) == MAX_COMPARED_VARIANTS


class TestRealVariantReconciliation:
    """Source rows from the configured HemOnc database (see schedule-samples.json)."""

    _DEVCONTAINER_URL = "postgresql+psycopg://hemonc:hemonc@localhost:5432/hemonc_alchemy"

    def _load_latest_variant(self, cui: int):
        try:
            engine = sa.create_engine(self._DEVCONTAINER_URL, future=True)
            with engine.connect() as conn:
                conn.execute(sa.text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 -- any connection failure just skips
            pytest.skip(f"devcontainer PostgreSQL not reachable: {exc}")

        with so.Session(engine) as session:
            rows = session.execute(
                sa.select(Variants).where(Variants.variant_cui == cui)
            ).scalars().all()
            if not rows:
                pytest.skip(f"imported database has no variant_cui={cui}")
            latest = max(rows, key=lambda v: (v.version, v.id))
            session.expunge(latest)
            return latest

    @pytest.mark.postgres
    def test_variant_130784_surfaces_its_two_unrepresented_radiation_sigs(self):
        # P0-A15: six source sigs, only four represented; sigs 5505/5506 have
        # no day expression and must show up as unplaced, not vanish.
        variant = self._load_latest_variant(130784)
        view = build_schedule_view(variant)
        assert not view.bounded
        assert len(view.events) == 31
        assert {u.instruction.sig_id for u in view.unplaced_instructions} == {5505, 5506}
        assert view.coverage.total_instructions == 6
        assert view.coverage.represented_instructions == 4
        assert view.coverage.unplaced_instructions == 2

    @pytest.mark.postgres
    def test_variant_129553_surfaces_its_unrepresented_ns_route_sig(self):
        # P0-A16: sig 260 has route/day "NS"; only sig 259 reaches the projection.
        variant = self._load_latest_variant(129553)
        view = build_schedule_view(variant)
        assert not view.bounded
        assert len(view.events) == 728
        assert [u.instruction.sig_id for u in view.unplaced_instructions] == [260]
        assert any(
            d.category == DiagnosticCategory.UNSUPPORTED_ROUTE and d.sig_id == 260
            for d in view.diagnostics
        )

    @pytest.mark.postgres
    def test_variant_129505_decay_override_matches_the_captured_sample(self):
        # P0-A08: with decay_days=0 the sample recorded exactly 4 events for
        # sigs 35/36; the toolkit's own default (decay_days=2) gives 8.
        variant = self._load_latest_variant(129505)
        view = build_schedule_view(variant)
        assert len(view.events) == 4
        assert {e.instruction.sig_id for e in view.events} == {35, 36}
