"""Parse stage and status phrases into reusable scope tokens."""

import re
from collections import Counter
from dataclasses import dataclass

from ..loader import IndicationSource, _split
from ..model import ScopeCriterion, ScopeTerm, ScopeToken

_TOKEN_PHRASES = {token.value.replace("_", " "): token for token in ScopeToken}
_TOKEN_PHRASES["systemic therapy"] = ScopeToken.SYSTEMIC_THERAPY_REQUIRED
_PHRASE_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:"
    + "|".join(
        re.escape(item) for item in sorted(_TOKEN_PHRASES, key=len, reverse=True)
    )
    + r")(?![a-z0-9])"
)
_ALIASES = {
    "localled advanced": "locally advanced",
    "early stage": "early",
    "dukes' stage c": "stage c",
    "stage d2": "d2",
    "extensive-stage": "extensive stage",
    "node-positive": "node positive",
    "n+": "node positive",
    "m+": "metastatic",
}
_STAGE_SUFFIX = re.compile(r"\b(?:stage\s+)?(iv|iii|ii|i)[a-d]\b", re.IGNORECASE)


def _parse_term(raw: str) -> ScopeTerm | None:
    if raw.casefold() == "not applicable":
        return None
    qualifiers = re.findall(r"\(([^()]*)\)", raw)
    text = re.sub(r"\([^()]*\)", " ", raw).casefold()
    for alias, replacement in _ALIASES.items():
        text = re.sub(
            rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", replacement, text
        )
    text = _STAGE_SUFFIX.sub(lambda match: f"stage {match[1]}", text)
    text = re.sub(r"[-,/']", " ", text)
    tokens = []
    pieces = []
    start = 0
    for match in _PHRASE_PATTERN.finditer(text):
        phrase = match.group().casefold()
        tokens.append(_TOKEN_PHRASES[phrase])
        pieces.extend((text[start : match.start()], " "))
        start = match.end()
    pieces.append(text[start:])
    residue = re.sub(r"[^a-z0-9]+", " ", "".join(pieces))
    residue = " ".join(
        word for word in residue.split() if word not in {"and", "or", "to", "of"}
    )
    return ScopeTerm(raw, tuple(tokens), "; ".join(qualifiers) or None, not residue)


@dataclass(frozen=True)
class ScopeLint:
    unmapped_stage: dict[str, int]
    unmapped_status: dict[str, int]
    unmapped_stage_or_status: dict[str, int]


@dataclass(frozen=True)
class ScopeNormaliser:
    name: str = "scope"
    columns: tuple[str, ...] = ("stage", "status", "stage_or_status")

    def _criterion(self, source: str, raw: str | None) -> ScopeCriterion | None:
        if raw is None or not raw.strip():
            return None
        terms = tuple(filter(None, (_parse_term(value) for value in _split(raw))))
        if not terms:
            return None
        return ScopeCriterion(source, source, raw, terms)

    def normalise(self, source: IndicationSource) -> tuple[ScopeCriterion, ...]:
        return tuple(
            criterion
            for column in self.columns
            if (criterion := self._criterion(column, getattr(source, column)))
            is not None
        )

    def lint(self, sources: tuple[IndicationSource, ...]) -> ScopeLint:
        unmapped = {column: Counter() for column in self.columns}
        for source in sources:
            for criterion in self.normalise(source):
                unmapped[criterion.source].update(
                    term.raw for term in criterion.terms if not term.parsed
                )
        return ScopeLint(
            *(dict(sorted(unmapped[column].items())) for column in self.columns)
        )


__all__ = ["ScopeLint", "ScopeNormaliser"]
