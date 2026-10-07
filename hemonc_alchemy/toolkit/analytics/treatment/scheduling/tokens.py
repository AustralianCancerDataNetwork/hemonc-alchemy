"""The pieces a dosing schedule is made of.

A sig's `alldays` field expresses which days of a cycle a drug is given on, in
a compact notation:

| notation | meaning | becomes |
|---|---|---|
| `1,8,15` | given on those days | three `Day`s |
| `[1,5,1]` | every day from 1 to 5, step 1 | a `Range` |
| `(4)` | optional day | `Day(4, optional=True)` |
| `1\\|2` | one of these days, unspecified which | a `Choice` |
| `(+c)`, `(+n21)` | continues beyond the explicit days, optionally capped | an `Indefinite` |
| `(+2)` | continues every two days in `alldays` or every two cycles in `timing_sequence` | an `Indefinite(interval=2)` |

Day numbers can be negative (`-14`), meaning that many days before day 1 —
conditioning or lead-in dosing.

Two markers are dropped rather than represented: a leading `U` means the
schedule is unspecified, and `^` is stripped. Both are logged when they occur.

A `Range` bound may be a word instead of a number — `EOC` for end of cycle —
and such a range yields no explicit days at all, because its length isn't known
from the sig alone. Roughly 79 sigs are written this way, so an empty day list
does not by itself mean a drug is never given.

`resolve_all_days` in handling.py turns the notation into these objects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Day:
    value: int
    optional: bool = False


@dataclass(frozen=True)
class Choice:
    options: list[int]


@dataclass(frozen=True)
class Range:
    start: int | str  # int or "EOC"
    end: int | str
    step: int
    optional: bool = False


@dataclass(frozen=True)
class Indefinite:
    kind: str  # "+n", "+c", or "+k"
    max_days: int | None = None
    interval: int | None = None  # cycles in timing_sequence, days in alldays


TOKEN_RE = re.compile(
    r"""
    (\[[^\]]*\])        |  # [ ... ] blocks
    ([^[]+)                # everything else (outside brackets)
    """,
    re.VERBOSE,
)
