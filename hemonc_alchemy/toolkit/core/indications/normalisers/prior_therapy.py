"""Classify only the explicit minimal prior-therapy states."""

from dataclasses import dataclass

from ..loader import IndicationSource
from ..model import Criterion, PriorTherapy, PriorTherapyCriterion


@dataclass(frozen=True)
class PriorTherapyNormaliser:
    name: str = "prior_therapy"
    columns: tuple[str, ...] = ("prior_therapy",)

    def normalise(self, source: IndicationSource) -> tuple[Criterion, ...]:
        raw = source.prior_therapy
        if raw is None:
            return ()
        value = raw.strip()
        requirement = (
            PriorTherapy.NONE_REQUIRED
            if not value or value.casefold() == "not applicable"
            else PriorTherapy.UNTREATED
            if value == "0"
            else PriorTherapy.REQUIRES_PRIOR
        )
        return (
            PriorTherapyCriterion("prior_therapy", "prior_therapy", raw, requirement),
        )


__all__ = ["PriorTherapyNormaliser"]
