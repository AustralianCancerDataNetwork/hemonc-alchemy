"""Structured parse diagnostics, independent of `logging` output."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
import sqlalchemy.orm as so

from hemonc_alchemy.model.base import Base
from hemonc_alchemy.model.entities import Sigs, Variants
from hemonc_alchemy.model.enums import Sigs_Cycle_length_unitEnum, Sigs_RouteEnum
from hemonc_alchemy.toolkit.analytics.treatment.scheduling.diagnostics import (
    DiagnosticCategory,
    DiagnosticSeverity,
    diagnose_all_days,
    diagnose_calendar_unit,
    diagnose_route,
    diagnose_timing_status,
    diagnose_variant,
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


class TestDiagnoseAllDays:
    def test_clean_expression_has_no_diagnostics(self):
        assert diagnose_all_days("1,8,15", sig_id=1) == ()

    def test_none_expression_has_no_diagnostics(self):
        assert diagnose_all_days(None, sig_id=1) == ()

    def test_unspecified_u_token_is_a_parse_omission(self):
        diagnostics = diagnose_all_days("U", sig_id=7)
        assert len(diagnostics) == 1
        assert diagnostics[0].category == DiagnosticCategory.PARSE_OMISSION
        assert diagnostics[0].sig_id == 7
        assert diagnostics[0].raw_token == "U"

    def test_second_indefinite_marker_is_flagged_as_a_lost_qualifier(self):
        # P0-A17: "1,(+1),(+c60)" -- the parser keeps the first indefinite
        # marker and silently drops the second (here, the dose cap).
        diagnostics = diagnose_all_days("1,(+1),(+c60)", sig_id=695)
        lost = [d for d in diagnostics if d.category == DiagnosticCategory.LOST_QUALIFIER]
        assert len(lost) == 1
        assert lost[0].sig_id == 695
        # Token-level granularity: the whole comma-joined expression is one
        # `tokenize_all_days` token here, so `raw_token` carries the full
        # source string rather than just the dropped "(+c60)" fragment.
        assert "+c60" in lost[0].raw_token
        assert "dropped" in lost[0].message

    @pytest.mark.parametrize(
        "expression",
        ["(1),(2),(3),(4),(5),(6),(7)", "(3),(4)"],
    )
    def test_the_two_known_regression_expressions_never_raise(self, expression):
        # P0-A18: these crash the shared parser's `parse_optional` with a bare
        # ValueError; diagnostics must surface that structurally, not raise.
        diagnostics = diagnose_all_days(expression, sig_id=19566)
        assert len(diagnostics) == 1
        assert diagnostics[0].category == DiagnosticCategory.PARSE_ERROR
        assert diagnostics[0].severity == DiagnosticSeverity.ERROR
        assert diagnostics[0].raw_token == expression


class TestDiagnoseRoute:
    def test_unclassified_route_is_flagged(self):
        diagnostics = diagnose_route(Sigs_RouteEnum.NS, sig_id=260)
        assert len(diagnostics) == 1
        assert diagnostics[0].category == DiagnosticCategory.UNSUPPORTED_ROUTE
        assert diagnostics[0].sig_id == 260

    def test_classified_route_has_no_diagnostic(self):
        assert diagnose_route(Sigs_RouteEnum.INTRAVENOUS, sig_id=1) == ()

    def test_null_route_has_no_diagnostic(self):
        assert diagnose_route(None, sig_id=1) == ()


class TestDiagnoseCalendarUnit:
    def test_month_unit_without_a_start_date_is_an_approximation(self):
        diagnostics = diagnose_calendar_unit(
            Sigs_Cycle_length_unitEnum.MONTH, sig_id=1, calendar_anchored=False
        )
        assert len(diagnostics) == 1
        assert diagnostics[0].category == DiagnosticCategory.CALENDAR_APPROXIMATION

    def test_month_unit_with_a_start_date_is_not_flagged(self):
        assert diagnose_calendar_unit(
            Sigs_Cycle_length_unitEnum.MONTH, sig_id=1, calendar_anchored=True
        ) == ()

    def test_day_unit_is_never_flagged(self):
        assert diagnose_calendar_unit(
            Sigs_Cycle_length_unitEnum.DAY, sig_id=1, calendar_anchored=False
        ) == ()


class TestDiagnoseTimingStatus:
    def test_resolved_has_no_diagnostic(self):
        assert diagnose_timing_status("resolved", sig_id=1) == ()

    def test_optional_cycle_fallback_is_an_assumption_not_a_warning_category(self):
        diagnostics = diagnose_timing_status(
            "resolved_via_fallback: optional cycle 2 assumed given", sig_id=1
        )
        assert diagnostics[0].category == DiagnosticCategory.OPTIONAL_CYCLE_ASSUMPTION

    def test_choice_status_is_unresolved_choice(self):
        diagnostics = diagnose_timing_status(
            "unresolved: choice of days 7|8|9, not resolved", sig_id=9
        )
        assert diagnostics[0].category == DiagnosticCategory.UNRESOLVED_CHOICE

    def test_phase_step_gap_is_unresolved_phase(self):
        diagnostics = diagnose_timing_status(
            "unresolved: phase_step gap before step 3 (no sigs for step 2)", sig_id=1
        )
        assert diagnostics[0].category == DiagnosticCategory.UNRESOLVED_PHASE

    def test_other_unresolved_status_falls_back_to_generic_timing(self):
        diagnostics = diagnose_timing_status(
            "unresolved: missing cycle numbers", sig_id=1
        )
        assert diagnostics[0].category == DiagnosticCategory.UNRESOLVED_TIMING


class TestDiagnoseVariant:
    def test_never_raises_even_with_a_crashing_expression(self, session):
        # Mirrors the real standalone sigs 19566/23133 (P0-A18): diagnose_variant
        # reads `component_sigs` directly rather than `schedule_events`, so it
        # survives an `alldays` expression that crashes `resolve_all_days`.
        variant = Variants(
            id=1, variant_cui=1, variant="v", regimen_cui=1, regimen="R", version=1,
            cyclesigs=0, components=0, portions=0, routes=0, sigs=0, blob_version=0,
            fullyspecified=True, allsigshavecyclesigs=True, allsigshavedose=True,
            allsigshavedoseunit=True, allsigshaveduration=True, allsigshavedurationunit=True,
            allsigshavefrequency=True, allsigshaveroute=True, allsigshaveschedule=True,
            allsigshavesequence=True, date_added=_D,
        )
        session.add(variant)
        session.flush()
        session.add(Sigs(
            id=19566, variant_cui=1, component_cui=1, component="drug",
            component_role="primary systemic", portion="1", regimen="R",
            regimen_cui=1, step_number="1", divided=False, phase_step=1,
            variant="v", alldays="(1),(2),(3),(4),(5),(6),(7)", date_added=_D,
        ))
        session.flush()
        session.expire_all()

        diagnostics = diagnose_variant(variant)
        assert any(d.category == DiagnosticCategory.PARSE_ERROR for d in diagnostics)

    def test_collects_route_and_calendar_findings_across_sigs(self, session):
        variant = Variants(
            id=2, variant_cui=2, variant="v", regimen_cui=1, regimen="R", version=1,
            cyclesigs=0, components=0, portions=0, routes=0, sigs=0, blob_version=0,
            fullyspecified=True, allsigshavecyclesigs=True, allsigshavedose=True,
            allsigshavedoseunit=True, allsigshaveduration=True, allsigshavedurationunit=True,
            allsigshavefrequency=True, allsigshaveroute=True, allsigshaveschedule=True,
            allsigshavesequence=True, date_added=_D,
        )
        session.add(variant)
        session.flush()
        session.add(Sigs(
            id=1, variant_cui=2, component_cui=1, component="drug-a",
            component_role="primary systemic", portion="1", regimen="R",
            regimen_cui=1, step_number="1", divided=False, phase_step=1,
            variant="v", route=Sigs_RouteEnum.NS, alldays="1",
            cycle_length_lb="1", cycle_length_ub="1",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.MONTH, date_added=_D,
        ))
        session.flush()
        session.expire_all()

        diagnostics = diagnose_variant(variant, calendar_anchored=False)
        categories = {d.category for d in diagnostics}
        assert DiagnosticCategory.UNSUPPORTED_ROUTE in categories
        assert DiagnosticCategory.CALENDAR_APPROXIMATION in categories
