"""Grouping routes of administration by where treatment happens.

The distinction is whether a dose needs a clinic visit or can be taken at
home, since that is what drives appointment and infusion-chair demand rather
than the specific route.

This is useful for both planning and resource allocation, as well as for
scoring regimen matches. Typically in OMOP data, we see that full administration 
records (transfusions, infusions, injections) are captured for clinic-administered 
routes, while home-administered routes are often incompletely captured, with only 
the prescription record or dispensing record available. These need to be handled
differently in the scoring algorithms.

`NS` (not specified) and any route not listed below are left unclassified
rather than guessed at.
"""

from __future__ import annotations

from hemonc_alchemy.model.enums import Sigs_RouteEnum

_CLINIC_ADMINISTERED_ROUTES = frozenset(
    {
        Sigs_RouteEnum.INTRAVENOUS,
        Sigs_RouteEnum.SUBCUTANEOUS,
        Sigs_RouteEnum.INTRAMUSCULAR,
        Sigs_RouteEnum.INTRATHECAL,
        Sigs_RouteEnum.BY_SCARIFICATION,
        Sigs_RouteEnum.INTRAVESICAL,
        Sigs_RouteEnum.INTRACAVITARY,
        Sigs_RouteEnum.INTRA_TO_ARTERIAL,
    }
)

_HOME_ADMINISTRATION_ROUTES = frozenset(
    {
        Sigs_RouteEnum.ORAL,
        Sigs_RouteEnum.INHALATION,
        Sigs_RouteEnum.TOPICAL,
    }
)


def route_group(route: Sigs_RouteEnum | str | None) -> str | None:
    """Group a route as clinic- or home-administered.

    Returns `"IV"` for anything needing a clinic visit, `"PO"` for anything
    self-administered at home, or None if the route is unrecognised or not
    specified. Accepts either the enum or the raw string, case-insensitively.

    The two labels are historical shorthand for the groups, not literal
    routes: `"IV"` covers intramuscular, intrathecal and the rest, and `"PO"`
    covers inhaled and topical.
    """
    if route is None:
        return None

    if not isinstance(route, Sigs_RouteEnum):
        try:
            route = Sigs_RouteEnum(str(route).strip().lower())
        except ValueError:
            return None

    if route in _CLINIC_ADMINISTERED_ROUTES:
        return "IV"
    if route in _HOME_ADMINISTRATION_ROUTES:
        return "PO"
    return None
