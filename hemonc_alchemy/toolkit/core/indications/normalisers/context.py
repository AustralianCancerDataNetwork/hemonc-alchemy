"""Normalise indication context labels into line and treatment settings."""

from collections import Counter
from dataclasses import dataclass

from ..loader import IndicationSource, _split
from ..model import ContextCriterion, ContextTerm, Setting

_CANONICAL_SETTINGS = {
    setting.value.replace("_", " "): setting
    for setting in Setting
    if setting is not Setting.UNPARSED
}
_SETTING_ALIASES = {
    "1l": Setting.FIRST_LINE,
    "2l": Setting.SECOND_LINE,
    "2l+": Setting.LATER_LINE,
    "3l": Setting.LATER_LINE,
    "3l+": Setting.LATER_LINE,
    "1l maintenance": Setting.FIRST_LINE_MAINTENANCE,
}


def _context_term(raw: str) -> ContextTerm:
    normalized = raw.casefold()
    setting: Setting | None = _CANONICAL_SETTINGS.get(normalized.replace("-", " "))
    if setting is None:
        setting = _SETTING_ALIASES.get(normalized, Setting.UNPARSED)
    return ContextTerm(raw, setting, setting is not Setting.UNPARSED)


@dataclass(frozen=True)
class ContextNormaliser:
    name: str = "context"
    columns: tuple[str, ...] = ("context",)

    def normalise(self, source: IndicationSource) -> tuple[ContextCriterion, ...]:
        values = tuple(
            part.strip()
            for raw in source.context
            for value in _split(raw)
            for part in value.split("&")
            if part.strip() and part.strip().casefold() != "not applicable"
        )
        if not values:
            return ()
        terms = tuple(_context_term(raw) for raw in dict.fromkeys(values))
        raw = "|".join(dict.fromkeys(source.context))
        return (ContextCriterion("context", "context", raw, terms),)

    def lint(self, sources: tuple[IndicationSource, ...]) -> dict[str, int]:
        values = Counter(
            term.raw
            for source in sources
            for criterion in self.normalise(source)
            for term in criterion.terms
            if not term.parsed
        )
        return dict(sorted(values.items()))


__all__ = ["ContextNormaliser"]
