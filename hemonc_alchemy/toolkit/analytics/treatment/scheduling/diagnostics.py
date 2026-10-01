"""Structured parse/interpretation diagnostics, independent of log text.

Companion to `resolve_all_days`/`roll_out_variant`: it reuses their own
token/status objects rather than re-parsing the notation or depending on
`logging` output, and it never raises -- a malformed expression becomes a
diagnostic, the same way an unresolved timing status does.

`diagnose_variant` reads straight off `variant.component_sigs`, not
`schedule_events`/`resolve_all_days`, because some real source expressions
raise `ValueError` inside the shared parser (see `test_diagnostics.py`'s
`test_parser_exception_becomes_a_diagnostic_not_a_crash`); diagnostics must
stay available even then.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .....model.enums import Sigs_Cycle_length_unitEnum
from .handling import Indefinite, parse_token, tokenize_all_days
from .routes import route_group

_MONTH_YEAR_UNITS = frozenset(
    {Sigs_Cycle_length_unitEnum.MONTH, Sigs_Cycle_length_unitEnum.YEAR}
)


class DiagnosticSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DiagnosticCategory(str, Enum):
    PARSE_OMISSION = "parse_omission"
    PARSE_ERROR = "parse_error"
    LOST_QUALIFIER = "lost_qualifier"
    UNSUPPORTED_ROUTE = "unsupported_route"
    UNRESOLVED_PHASE = "unresolved_phase"
    UNRESOLVED_CHOICE = "unresolved_choice"
    OPTIONAL_CYCLE_ASSUMPTION = "optional_cycle_assumption"
    CALENDAR_APPROXIMATION = "calendar_approximation"
    UNRESOLVED_TIMING = "unresolved_timing"
    LIMIT_EXCEEDED = "limit_exceeded"


class DiagnosticCode(str, Enum):
    TOKEN_UNPARSEABLE = "token_unparseable"
    TOKEN_PARSE_ERROR = "token_parse_error"
    INDEFINITE_MARKER_DROPPED = "indefinite_marker_dropped"
    ROUTE_NOT_CLASSIFIED = "route_not_classified"
    PHASE_TIMING_UNRESOLVED = "phase_timing_unresolved"
    CHOICE_UNRESOLVED = "choice_unresolved"
    OPTIONAL_CYCLE_ASSUMED = "optional_cycle_assumed"
    CALENDAR_UNIT_APPROXIMATED = "calendar_unit_approximated"
    TIMING_UNRESOLVED = "timing_unresolved"
    EVENT_LIMIT_EXCEEDED = "event_limit_exceeded"


@dataclass(frozen=True)
class Diagnostic:
    """One structured parse/interpretation finding tied to a source sig."""

    code: DiagnosticCode
    category: DiagnosticCategory
    severity: DiagnosticSeverity
    message: str
    sig_id: int | None = None
    raw_token: str | None = None


def diagnose_all_days(all_days: str | None, *, sig_id: int | None = None) -> tuple[Diagnostic, ...]:
    """Findings for one `alldays`/`timing_sequence` expression, from its own tokens.

    Reuses `tokenize_all_days`/`parse_token`; never raises -- a token that
    fails to parse (including the known `parse_optional` crash on consecutive
    parenthesised groups outside brackets, see P0-A18) becomes a `PARSE_ERROR`
    diagnostic instead of propagating.
    """
    diagnostics: list[Diagnostic] = []
    indefinite_items: list[tuple[str, Indefinite]] = []
    for token in tokenize_all_days(all_days):
        cleaned = token.replace("^", "").strip()
        if not cleaned or cleaned == "<NA>":
            continue
        try:
            parsed = parse_token(token)
        except ValueError as exc:
            diagnostics.append(
                Diagnostic(
                    code=DiagnosticCode.TOKEN_PARSE_ERROR,
                    category=DiagnosticCategory.PARSE_ERROR,
                    severity=DiagnosticSeverity.ERROR,
                    message=f"token {token!r} raised while parsing: {exc}",
                    sig_id=sig_id,
                    raw_token=token,
                )
            )
            continue
        if not parsed:
            kind = "unspecified-dosing" if cleaned.startswith("U") else "unparseable"
            diagnostics.append(
                Diagnostic(
                    code=DiagnosticCode.TOKEN_UNPARSEABLE,
                    category=DiagnosticCategory.PARSE_OMISSION,
                    severity=DiagnosticSeverity.WARNING,
                    message=f"{kind} token {token!r} dropped from the resolved schedule",
                    sig_id=sig_id,
                    raw_token=token,
                )
            )
            continue
        indefinite_items.extend(
            (token, item) for item in parsed if isinstance(item, Indefinite)
        )

    if len(indefinite_items) > 1:
        kept_token, _ = indefinite_items[0]
        for dropped_token, _ in indefinite_items[1:]:
            diagnostics.append(
                Diagnostic(
                    code=DiagnosticCode.INDEFINITE_MARKER_DROPPED,
                    category=DiagnosticCategory.LOST_QUALIFIER,
                    severity=DiagnosticSeverity.WARNING,
                    message=f"indefinite marker {dropped_token!r} dropped; only {kept_token!r} is kept",
                    sig_id=sig_id,
                    raw_token=dropped_token,
                )
            )
    return tuple(diagnostics)


def diagnose_route(route, *, sig_id: int | None = None) -> tuple[Diagnostic, ...]:
    """Flag a route that `route_group` cannot place as clinic- or home-administered."""
    if route is None or route_group(route) is not None:
        return ()
    value = getattr(route, "value", route)
    return (
        Diagnostic(
            code=DiagnosticCode.ROUTE_NOT_CLASSIFIED,
            category=DiagnosticCategory.UNSUPPORTED_ROUTE,
            severity=DiagnosticSeverity.INFO,
            message=f"route {value!r} is not grouped as clinic- or home-administered",
            sig_id=sig_id,
        ),
    )


def diagnose_calendar_unit(
    cycle_length_unit, *, sig_id: int | None = None, calendar_anchored: bool
) -> tuple[Diagnostic, ...]:
    """Flag a month/year cycle length rolled out without an illustrative start date.

    With no start date, rollout approximates a month as 30 days and a year as
    365; with a start date it uses the real calendar month/year length instead.
    """
    if calendar_anchored or cycle_length_unit not in _MONTH_YEAR_UNITS:
        return ()
    return (
        Diagnostic(
            code=DiagnosticCode.CALENDAR_UNIT_APPROXIMATED,
            category=DiagnosticCategory.CALENDAR_APPROXIMATION,
            severity=DiagnosticSeverity.INFO,
            message=(
                f"{cycle_length_unit.value} cycle length is approximated as a fixed "
                "day count without an illustrative start date"
            ),
            sig_id=sig_id,
        ),
    )


def diagnose_timing_status(status: str, *, sig_id: int | None = None) -> tuple[Diagnostic, ...]:
    """One finding from a rolled-out event's own `timing_status`.

    A "resolved" status needs no diagnostic; every other documented prefix
    (see rollout.py's `UnresolvedTiming`/`_combine_status`/`_choice_status`)
    is surfaced even though the row itself may still carry day/cycle values.
    """
    if status == "resolved":
        return ()
    if status.startswith("resolved_via_fallback: optional"):
        return (
            Diagnostic(
                code=DiagnosticCode.OPTIONAL_CYCLE_ASSUMED,
                category=DiagnosticCategory.OPTIONAL_CYCLE_ASSUMPTION,
                severity=DiagnosticSeverity.INFO,
                message=status,
                sig_id=sig_id,
            ),
        )
    if "choice of days" in status:
        return (
            Diagnostic(
                code=DiagnosticCode.CHOICE_UNRESOLVED,
                category=DiagnosticCategory.UNRESOLVED_CHOICE,
                severity=DiagnosticSeverity.WARNING,
                message=status,
                sig_id=sig_id,
            ),
        )
    if "phase_step" in status or "previous phase" in status:
        return (
            Diagnostic(
                code=DiagnosticCode.PHASE_TIMING_UNRESOLVED,
                category=DiagnosticCategory.UNRESOLVED_PHASE,
                severity=DiagnosticSeverity.WARNING,
                message=status,
                sig_id=sig_id,
            ),
        )
    return (
        Diagnostic(
            code=DiagnosticCode.TIMING_UNRESOLVED,
            category=DiagnosticCategory.UNRESOLVED_TIMING,
            severity=DiagnosticSeverity.WARNING,
            message=status,
            sig_id=sig_id,
        ),
    )


def diagnose_variant(variant, *, calendar_anchored: bool = False) -> tuple[Diagnostic, ...]:
    """Every per-sig structured diagnostic for `variant`, independent of rollout.

    Reads `variant.component_sigs` directly rather than `schedule_events`, so
    it stays available even for a sig whose `alldays` crashes the shared parser.
    """
    diagnostics: list[Diagnostic] = []
    for sig in variant.component_sigs:
        diagnostics.extend(diagnose_all_days(sig.alldays, sig_id=sig.id))
        diagnostics.extend(diagnose_all_days(sig.timing_sequence, sig_id=sig.id))
        diagnostics.extend(diagnose_route(sig.route, sig_id=sig.id))
        diagnostics.extend(
            diagnose_calendar_unit(
                sig.cycle_length_unit, sig_id=sig.id, calendar_anchored=calendar_anchored
            )
        )
    return tuple(diagnostics)
