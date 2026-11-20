"""Parse source date cells without inventing missing precision."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DateParts:
    """Date components present in a source cell and its precision."""

    year: int
    month: int | None
    day: int | None
    precision: str


_HTML_DATETIME = re.compile(
    r'<time\b[^>]*\bdatetime=["\']([^"\']+)["\']', re.IGNORECASE
)
_DATE = re.compile(r"(?<!\d)(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?(?!\d)")
_MONTHS = (
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def parse_source_date(raw: object) -> DateParts | None:
    """Read a date cell's supplied precision, returning None for free text."""
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None

    wrapped = _HTML_DATETIME.search(value)
    if wrapped:
        value = wrapped.group(1).strip()
    elif value.casefold().startswith("withdrawn on "):
        value = value[len("withdrawn on ") :].strip()

    iso_datetime = re.fullmatch(r"(\d{4}-\d{1,2}-\d{1,2})(?:[T ][^ ]+)?", value)
    if iso_datetime:
        value = iso_datetime.group(1)

    compact = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", value)
    if compact:
        year, month, day = map(int, compact.groups())
        return _validated_date(year, month, day)

    named = re.fullmatch(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", value)
    if named:
        try:
            month = next(
                index
                for index, name in enumerate(_MONTHS)
                if name.casefold() == named.group(2).casefold()
            )
            return _validated_date(int(named.group(3)), month, int(named.group(1)))
        except (StopIteration, ValueError):
            return None

    match = _DATE.fullmatch(value)
    if not match:
        return None
    year, month, day = match.groups()
    if month is None:
        return DateParts(int(year), None, None, "year")
    if day is None:
        month_value = int(month)
        return (
            DateParts(int(year), month_value, None, "month")
            if 1 <= month_value <= 12
            else None
        )
    return _validated_date(int(year), int(month), int(day))


def complete_source_date(raw: object) -> date | None:
    """Return a full date only when the cell itself is that date."""
    if raw is not None and str(raw).strip().casefold().startswith("withdrawn on "):
        return None
    parsed = parse_source_date(raw)
    if parsed is None or parsed.precision != "day":
        return None
    return date(parsed.year, parsed.month, parsed.day)


def _validated_date(year: int, month: int, day: int) -> DateParts | None:
    try:
        date(year, month, day)
    except ValueError:
        return None
    return DateParts(year, month, day, "day")
