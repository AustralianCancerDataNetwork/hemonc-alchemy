"""Reading a sig's dosing schedule.

`resolve_all_days` is the entry point; the `parse_*`/`tokenize_*` functions
below it handle one piece of the notation each. See tokens.py for the notation
itself.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from .tokens import TOKEN_RE, Choice, Day, Indefinite, Range

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedSchedule:
    """The days a drug is given on, as resolved from one `alldays` expression.

    `indefinite` is set when the schedule carries on past the days listed —
    until progression, say. When it is set, `days` is only the part that was
    written down explicitly, not the full course.
    """

    days: tuple[Day, ...] = ()
    indefinite: Indefinite | None = None

    def __iter__(self):
        return iter(self.days)

    def __len__(self) -> int:
        return len(self.days)

    def __bool__(self) -> bool:
        return bool(self.days) or self.indefinite is not None


def apply_sig_to_series(
    series: dict[int, float],
    days: list[Day],
    decay_days: int = 2,
    decay_factor: float = 0.5,
):
    """Mark `days` on a per-day intensity series, tapering off afterwards.

    Each dosing day is scored 1.0 (0.5 if optional) and the following
    `decay_days` are scored progressively lower, so a treatment day and its
    immediate aftermath both register. Used to build the administration
    matrices in properties.py. Mutates `series` in place.
    """
    for day in days:
        base = 0.5 if day.optional else 1.0
        d0 = day.value

        for offset in range(decay_days + 1):
            value = base * (decay_factor ** offset)
            series[d0 + offset] = max(series[d0 + offset], value)


def tokenize_all_days(value: str | None) -> list[str]:
    if not value:
        return []
    return [match.group(0).strip() for match in TOKEN_RE.finditer(value) if match.group(0).strip()]


def parse_choice(token: str) -> Choice:
    return Choice([int(part) for part in token.split("|") if part.strip()])


def parse_scalar_list(token: str):
    out = []
    for part in token.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("(") and part.endswith(")"):
            out.extend(parse_optional(part))
        elif "|" in part:
            out.append(parse_choice(part))
        else:
            try:
                out.append(Day(int(part)))
            except ValueError:
                logger.warning("Unparseable dosing token %r dropped", part)
    return out


def parse_range(token: str):
    body = token[1:-1]
    parts = [part.strip() for part in body.split(",")]
    if len(parts) != 3:
        logger.warning("Unparseable range token %r (expected 3 comma-separated parts)", token)
        return []

    start_text, end_text, step = parts
    start: int | str = int(start_text) if start_text.lstrip("-").isdigit() else start_text
    end: int | str = int(end_text) if end_text.lstrip("-").isdigit() else end_text
    return [Range(start, end, int(step))]


def parse_optional(token: str):
    inner = token[1:-1]

    if inner.startswith("+"):
        if match := re.fullmatch(r"\+([1-9][0-9]*)", inner):
            return [Indefinite("+k", interval=int(match.group(1)))]
        match = re.fullmatch(r"\+([a-zA-Z])(\d+)?", inner)
        if not match:
            logger.warning("Unparseable indefinite-dosing token %r", token)
            return []
        kind = f"+{match.group(1).lower()}"
        max_days = int(match.group(2)) if match.group(2) else None
        return [Indefinite(kind, max_days)]

    return [Day(int(inner), optional=True)]


def parse_token(token: str):
    token = token.replace("^", "").strip()
    if not token or token == "<NA>":
        return []
    if token.startswith("U"):
        logger.warning("Unspecified-dosing token %r dropped", token)
        return []
    if token.startswith("[") and token.endswith("]"):
        return parse_range(token)
    if token.startswith("(") and token.endswith(")"):
        return parse_optional(token)
    return parse_scalar_list(token)


def expand(parsed) -> ResolvedSchedule:
    days: list[Day] = []
    indefinite: Indefinite | None = None

    for item in parsed:
        if isinstance(item, Day):
            days.append(item)
        elif isinstance(item, Choice):
            days.extend(Day(day) for day in item.options)
        elif isinstance(item, Range):
            if isinstance(item.start, int) and isinstance(item.end, int):
                for day in range(item.start, item.end + 1, item.step):
                    days.append(Day(day, optional=item.optional))
        elif isinstance(item, Indefinite):
            if indefinite is not None:
                logger.warning(
                    "Multiple indefinite-dosing markers in one schedule; keeping the first (%r), dropping %r",
                    indefinite, item,
                )
            else:
                indefinite = item
                logger.debug(
                    "Indefinite-dosing marker %r found; explicit days list is not the complete schedule",
                    item,
                )

    return ResolvedSchedule(days=tuple(days), indefinite=indefinite)


def resolve_all_days(all_days: str | None) -> ResolvedSchedule:
    """Turn a sig's `alldays` expression into explicit cycle days.

        >>> resolve_all_days("1,8,15").days
        (Day(value=1, optional=False), Day(value=8, optional=False), Day(value=15, optional=False))

    See tokens.py for the notation. Check the result's `indefinite` before
    treating `days` as the whole schedule, and note that an unparseable or
    open-ended expression yields no days rather than raising -- anything
    dropped is logged.
    """
    parsed = []
    for token in tokenize_all_days(all_days):
        parsed.extend(parse_token(token))
    return expand(parsed)
