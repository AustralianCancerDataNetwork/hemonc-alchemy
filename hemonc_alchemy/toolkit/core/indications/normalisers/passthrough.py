"""Retain unparsed indication text as raw criteria."""

from dataclasses import dataclass

from ..loader import IndicationSource
from ..model import Criterion, RawCriterion


@dataclass(frozen=True)
class PassthroughNormaliser:
    name: str = "passthrough"
    columns: tuple[str, ...] = (
        "ineligibility",
        "with_field",
        "prior_biomarker",
        "accelerated",
        "demographics",
        "prior_therapy_setting",
        "prior_therapy_negation",
        "response_contingency",
        "risk_stratification",
    )

    def normalise(self, source: IndicationSource) -> tuple[Criterion, ...]:
        values = []
        for column in self.columns:
            if column == "accelerated":
                raw = "true" if source.accelerated else None
            elif column in {
                "demographics",
                "prior_therapy_setting",
                "prior_therapy_negation",
                "response_contingency",
                "risk_stratification",
            }:
                raw = "|".join(getattr(source, column)) or None
            else:
                raw = source.raw.get(column)
            if (
                column == "prior_therapy_negation"
                and raw is not None
                and raw.strip().casefold() == "false"
            ):
                raw = None
            if raw is not None:
                values.append(RawCriterion(column, column, raw))
        return tuple(values)


__all__ = ["PassthroughNormaliser"]
