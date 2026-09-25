"""Reading dosing schedules: route grouping and `alldays` resolution."""

from __future__ import annotations

import logging

from hemonc_alchemy.model.enums import Sigs_RouteEnum
from hemonc_alchemy.toolkit.analytics.treatment.scheduling import (
    Day,
    Indefinite,
    resolve_all_days,
    route_group,
)


class TestRouteGroup:
    """Cases confirmed against the real `route` column in the current
    data/Tables/sigs.csv (~23,300 rows).

    The 2026-08 drop normalised this column onto OMOP Route concept names and
    deduplicated it from 22 distinct values to 13: `IV`/`Intravenous`,
    `PO`/`Oral`, `SC`/`Subcutaneous`, `IT`/`Intrathecal`, `IM`/`Intramuscular`,
    `IA`/`Intra-arterial` and `intravesicularly`/`Intravesical` had all been
    recording the same route two ways, and `nebulized` + `inhaled` collapsed
    into `Inhalation`. The abbreviations no longer appear in the data or the
    generated enum, so they no longer classify -- see routes.py.
    """

    def test_concept_names_classify(self):
        assert route_group("Intravenous") == "IV"
        assert route_group("Oral") == "PO"
        assert route_group("Subcutaneous") == "IV"
        assert route_group(Sigs_RouteEnum.INTRAVENOUS) == "IV"

    def test_the_full_spellings_now_classify_at_all(self):
        """These were the silent data loss the old enum caused: 806 of 23,275
        rows carried a full concept name that the abbreviation-only enum had
        no member for, so they cast to None and never reached route_group.
        """
        for route in ("Intravenous", "Oral", "Subcutaneous", "Intracavitary",
                      "Intrathecal", "Intramuscular", "Intra-arterial",
                      "Intravesical", "Topical", "by scarification"):
            assert route_group(route) is not None, route

    def test_case_insensitive(self):
        assert route_group("intravenous") == "IV"
        assert route_group("inhalation") == "PO"

    def test_ns_and_none_are_unclassified(self):
        # "Not specified" became "NS" in this drop; both are ungrouped.
        assert route_group("NS") is None
        assert route_group(None) is None

    def test_retired_abbreviations_no_longer_classify(self):
        """Not a regression: these spellings are absent from the current data
        and from the generated enum, so an unclassified result is correct.
        """
        for retired in ("IV", "PO", "SC", "IT", "nebulized", "intravesicularly"):
            assert route_group(retired) is None, retired

    def test_unknown_route_is_unclassified(self):
        assert route_group("some future route nobody has seen yet") is None


class TestResolveAllDays:
    def test_simple_day_list(self):
        resolved = resolve_all_days("1,8,15")
        assert resolved.days == (Day(1), Day(8), Day(15))
        assert resolved.indefinite is None

    def test_range_expansion(self):
        resolved = resolve_all_days("[1,21,7]")
        assert resolved.days == (Day(1), Day(8), Day(15))

    def test_indefinite_marker_is_preserved_and_logged_at_debug(self, caplog):
        # Previously: expand() silently `continue`d past Indefinite tokens,
        # so a caller had no way to tell a maintenance regimen was truncated.
        with caplog.at_level(logging.DEBUG):
            resolved = resolve_all_days("1,8,15,(+n)")
        assert resolved.days == (Day(1), Day(8), Day(15))
        assert resolved.indefinite == Indefinite(kind="+n", max_days=None)
        assert bool(resolved) is True
        assert any("Indefinite-dosing marker" in record.message for record in caplog.records)
        assert all(record.levelno < logging.WARNING for record in caplog.records)

    def test_known_numeric_markers_do_not_warn(self, caplog):
        resolve_all_days("1,(+2)")
        resolve_all_days("1,(+2)")
        assert not caplog.records

    def test_unparseable_marker_still_warns(self, caplog):
        resolve_all_days("1,(+bogus)")
        assert any(record.levelno == logging.WARNING for record in caplog.records)

    def test_zero_continuation_interval_is_rejected(self, caplog):
        resolved = resolve_all_days("1,(+0)")
        assert resolved.days == (Day(1),)
        assert resolved.indefinite is None
        assert any("Unparseable indefinite-dosing token" in message for message in caplog.messages)

    def test_unspecified_scalar_is_dropped_with_warning(self, caplog):
        resolved = resolve_all_days("NS")
        assert resolved.days == ()
        assert resolved.indefinite is None
        assert any("NS" in message for message in caplog.messages)

    def test_bare_eoc_is_dropped_without_losing_valid_days(self, caplog):
        resolved = resolve_all_days("1,EOC")
        assert resolved.days == (Day(1),)
        assert any("EOC" in message for message in caplog.messages)

    def test_indefinite_only_schedule_is_still_truthy(self):
        resolved = resolve_all_days("(+c5)")
        assert resolved.days == ()
        assert resolved.indefinite == Indefinite(kind="+c", max_days=5)
        assert bool(resolved) is True

    def test_numeric_continuation_keeps_interval_without_expanding(self):
        resolved = resolve_all_days("1,(+2)")
        assert resolved.days == (Day(1),)
        assert resolved.indefinite == Indefinite(kind="+k", interval=2)

    def test_empty_input(self):
        resolved = resolve_all_days(None)
        assert resolved.days == ()
        assert resolved.indefinite is None
        assert bool(resolved) is False
