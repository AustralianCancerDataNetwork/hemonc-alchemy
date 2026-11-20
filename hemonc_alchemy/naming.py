"""
Identifier normalisation and source-file resolution shared across tiers.
"""

from __future__ import annotations

import keyword
import re
from pathlib import Path

PY_KEYWORDS = set(keyword.kwlist)


def safe_identifier(name: str) -> str:
    """Return a normalised lowercase identifier safe for code and model fields."""
    if name == "":
        return "_"

    ident = re.sub(r"[^0-9a-zA-Z_]", "", str(name))

    if ident and ident[0].isdigit():
        ident = "_" + ident

    if not ident:
        ident = "_"

    if ident in PY_KEYWORDS:
        ident = ident + "_field"

    return ident.lower()


def safe_enum_key(raw: str) -> str:
    """Convert an arbitrary display value into a safe enum member name."""
    s = raw.strip()

    s = s.replace("<", "LT_")
    s = s.replace(">", "GT_")
    s = s.replace("≤", "LE_")
    s = s.replace("≥", "GE_")

    s = s.replace(" to ", "_TO_")
    s = s.replace("-", "_TO_")
    s = s.replace("–", "_TO_")
    s = s.replace("/", "_")

    if re.match(r"^\d", s):
        s = "I_" + s

    s = re.sub(r"[^0-9a-zA-Z_]", "_", s)
    s = re.sub(r"_+", "_", s)
    s = s.upper()[:60]

    if s == "":
        s = "VALUE"

    return s.strip("_")


def collapse_separators(name: str) -> str:
    """
    Return `name` reduced to its alphanumeric characters, lowercased.

    Unlike `safe_identifier`, this drops underscores as well as dots, so it
    compares two spellings of the same name independently of the separator
    convention used. `safe_identifier` cannot do this: it produces Python
    identifiers, where `_` is legal and meaningful, so `canonical.triples`
    normalises to `canonicaltriples` while `canonical_triples` stays as-is.
    That asymmetry is why a purely cosmetic upstream rename from dotted to
    underscored extract filenames silently unbacked three tables.
    """
    return re.sub(r"[^0-9a-z]", "", str(name).lower())


def resolve_source_csv(
    data_dir: Path,
    table_name: str,
    source_name: str | None = None,
    alias: str | None = None,
) -> tuple[Path | None, list[str]]:
    """
    Find the real CSV backing `table_name` in `data_dir`.
    This tries progressively looser matches until exactly one file wins,
    excluding filenames containing "beta".

    `source_name` is the table's raw spelling in the data dictionary (e.g.
    `canonical.triples` for the `canonicaltriples` table). When given, it is
    matched alongside `table_name`, so the dictionary's own spelling is
    compared against the file rather than only a lossy derivative of it.

    `alias` is an explicitly declared filename stem for this table, from the
    dictionary's `SourceAliases` sheet. It wins outright when it matches a
    file, because a genuine upstream rename (as opposed to a separator
    change) is a content decision no heuristic should be guessing at.

    Returns (path, ambiguous_matches). `path` is None if nothing resolved;
    `ambiguous_matches` is non-empty only when multiple candidates tied and
    the caller should treat that as an error rather than guess.
    """
    csvs = [p for p in sorted(data_dir.glob("*.csv")) if "beta" not in p.stem.lower()]

    if alias:
        declared = [
            p for p in csvs if collapse_separators(p.stem) == collapse_separators(alias)
        ]
        if len(declared) == 1:
            return declared[0], []
        if len(declared) > 1:
            return None, [p.name for p in declared]

    exact = [p for p in csvs if p.stem == table_name]
    if len(exact) == 1:
        return exact[0], []
    if len(exact) > 1:
        return None, [p.name for p in exact]

    normalised = [p for p in csvs if safe_identifier(p.stem) == table_name]
    if len(normalised) == 1:
        return normalised[0], []
    if len(normalised) > 1:
        return None, [p.name for p in normalised]

    # Separator-insensitive on both sides, against the dictionary's own
    # spelling as well as the derived identifier. Verified collision-free
    # across both the current and previous HemOnc extract drops.
    wanted = {collapse_separators(table_name)}
    if source_name:
        wanted.add(collapse_separators(source_name))
    collapsed = [p for p in csvs if collapse_separators(p.stem) in wanted]
    if len(collapsed) == 1:
        return collapsed[0], []
    if len(collapsed) > 1:
        return None, [p.name for p in collapsed]

    prefixed = [p for p in csvs if p.stem.lower().startswith(table_name.lower())]
    if len(prefixed) == 1:
        return prefixed[0], []
    if len(prefixed) > 1:
        return None, [p.name for p in prefixed]

    return None, []
