"""Resolve the generated sex enum while preserving unknown source values."""

from collections import Counter
from dataclasses import dataclass

from .....model.enums import Indications_SexEnum
from ..loader import IndicationSource
from ..model import Criterion, RawCriterion, SexCriterion


@dataclass(frozen=True)
class SexNormaliser:
    name: str = "sex"
    columns: tuple[str, ...] = ("sex",)

    def normalise(self, source: IndicationSource) -> tuple[Criterion, ...]:
        raw = source.sex
        if raw is None:
            return ()
        try:
            sex = Indications_SexEnum(raw.casefold())
        except ValueError:
            return (RawCriterion("sex", "sex", raw),)
        return (SexCriterion("sex", "sex", raw, sex),)

    def lint(self, sources: tuple[IndicationSource, ...]) -> dict[str, int]:
        return dict(
            sorted(
                Counter(
                    source.sex
                    for source in sources
                    if source.sex is not None
                    and isinstance(self.normalise(source)[0], RawCriterion)
                ).items()
            )
        )


__all__ = ["SexNormaliser"]
