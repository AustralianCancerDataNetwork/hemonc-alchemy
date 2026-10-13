"""Parse the single-valued age grammar used by indications."""

import re
from collections import Counter
from dataclasses import dataclass

from ..loader import IndicationSource
from ..model import AgeCriterion, Criterion

_INTEGER = re.compile(r"^\d+$")
_ABOVE = re.compile(r"^(\d+)\+$")
_BELOW = re.compile(r"^(\d+)-$")
_RANGE = re.compile(r"^(\d+)\s+to\s+(\d+|NUBp|NUBya)$", re.IGNORECASE)
_AGE_GROUPS = frozenset({"adult", "pediatric", "any"})
_AGE_GROUP_ALIASES = {"nubp": "pediatric", "nubya": "young_adult"}


def _group_age(text: str) -> tuple[str | None, int | None, int | None] | None:
    lower = text.casefold()
    if lower in _AGE_GROUPS:
        return lower, None, None
    if lower in _AGE_GROUP_ALIASES:
        return _AGE_GROUP_ALIASES[lower], None, None
    return None


def _numeric_age(text: str) -> tuple[str | None, int | None, int | None] | None:
    try:
        if _INTEGER.fullmatch(text):
            years = int(text)
            return None, years, years
        if match := _ABOVE.fullmatch(text):
            return None, int(match[1]), None
        if match := _BELOW.fullmatch(text):
            return None, None, int(match[1])
    except (ValueError, OverflowError):
        return None
    return None


def _range_age(text: str) -> tuple[str | None, int | None, int | None] | None:
    match = _RANGE.fullmatch(text)
    if not match:
        return None
    upper = match[2].casefold()
    group = (
        "pediatric" if upper == "nubp" else "young_adult" if upper == "nubya" else None
    )
    try:
        maximum = int(match[2]) if match[2].isdigit() else None
        return group, int(match[1]), maximum
    except (ValueError, OverflowError):
        return None


@dataclass(frozen=True)
class AgeNormaliser:
    name: str = "age"
    columns: tuple[str, ...] = ("age",)

    def normalise(self, source: IndicationSource) -> tuple[Criterion, ...]:
        raw = source.age
        if raw is None or not raw.strip():
            return ()
        text = raw.strip()
        parsed = _group_age(text) or _numeric_age(text) or _range_age(text)
        return (
            AgeCriterion(
                "age",
                "age",
                raw,
                *(parsed or (None, None, None)),
                source.age_unit,
                parsed is not None,
            ),
        )

    def lint(self, sources: tuple[IndicationSource, ...]) -> dict[str, int]:
        invalid = Counter(
            source.age
            for source in sources
            if source.age
            and source.age.strip()
            and not self.normalise(source)[0].parsed
        )
        return dict(sorted(invalid.items()))


__all__ = ["AgeNormaliser"]
