"""Lossless positional alignment shared by the compiler and runtime loaders."""

from dataclasses import dataclass


def split_positions(raw: str | None) -> tuple[str | None, ...]:
    """Keep empty positions; a completely blank side has no values."""
    if raw is None or not raw.strip():
        return ()
    return tuple(part.strip() or None for part in raw.split("|"))


def _nested_pipe(raw: str) -> bool:
    depth = 0
    for char in raw:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "|" and depth > 0:
            return True
    return False


@dataclass(frozen=True)
class Alignment:
    status: str
    rows: tuple[tuple[str | None, ...], ...] = ()
    repeats_kept: int = 0


def align_values(raw: tuple[str | None, ...]) -> Alignment:
    """Align pipe lists while keeping nested-pipe expressions opaque.

    Opaque members contribute nulls at aligned positions; conflicting list
    lengths remain unaligned.
    """
    opaque = tuple(_nested_pipe(value or "") for value in raw)
    parts = tuple(
        () if is_opaque else split_positions(value)
        for value, is_opaque in zip(raw, opaque)
    )
    width = max(map(len, parts), default=0)
    if not width:
        return Alignment("unaligned" if any(opaque) else "empty")
    if any(len(values) not in (0, 1, width) for values in parts):
        return Alignment("unaligned")
    repeats = sum(len(values) - len(set(values)) for values in parts)
    rows = tuple(
        tuple(
            values[0 if len(values) == 1 else index] if values else None
            for values in parts
        )
        for index in range(width)
    )
    status = (
        "opaque_member"
        if any(opaque)
        else (
            "broadcast"
            if width > 1 and any(len(values) == 1 for values in parts)
            else "paired"
        )
    )
    return Alignment(status, rows, repeats)
