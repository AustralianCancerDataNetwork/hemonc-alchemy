"""
Checks whether HemOnc's declared identity (sourced from data dictionary)
for a table holds up in the real data, plus a couple of small enumerator
health checks.

A "natural key" (or business key) is the column(s) that the data dictionary
says is enough to uniquely identify a row of a table.

This is different from the surrogate `id` a content table gets in the
generated model: the surrogate id is just a database convenience, but the
natural key is the stated claim about what makes a row distinct.

This module re-derives the declared key for every table in the dictionary,
then checks whether it's actually unique in the current CSV snapshot. When
it isn't, it may be a sign the real data doesn't behave the way its own
declared key implies.

A "sparse key" means one or more of the composite key columns is blank for
some real rows. This is fine in principle, but doesn't meet sqlalchemy's
strict uniqueness requirement, so the audit flags it as a warning.

There are some already-understood edge case (see `TABLE_DECISIONS` below
for the ones already reviewed and accepted).

`enum_threshold_warnings` flags enum columns getting close to the point
where they'd stop being treated as an enum at all, and `enum_collision_warnings`
flags enum values that look distinct but collapse to same generated member name.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pandas as pd

from .infer import (
    CONTENT_COL,
    DICTIONARY_FILENAME,
    LOOKUP_COL,
    MATURITY_COL,
    MAX_ENUM_UNIQUE,
    UNIQUE_COL,
    parse_unique_key,
    resolve_source_csv,
    safe_enum_key,
    safe_identifier,
)
from .schema_model import Registry

# these table-specific decisions are reviewed and accepted exceptions to the
# audit's default "hard failure" rules.

# TODO: review at source to confirm these are still valid, and remove them if
# they are no longer needed.

TABLE_DECISIONS: dict[str, dict[str, str]] = {
    "studies": {"SPARSE_KEY_ROWS": "ACCEPTED_SPARSE_KEY"},
    "refs": {"SPARSE_KEY_ROWS": "ACCEPTED_SPARSE_KEY"},
    "study_results": {"SPARSE_KEY_ROWS": "ACCEPTED_SPARSE_KEY"},
    "sig_branch_types": {"SPARSE_KEY_ROWS": "IGNORE_ON_LOAD"},
    "hemonc_classes": {"DUPLICATE_BUSINESS_KEYS": "IGNORE_ON_LOAD"},
    "indications": {"DUPLICATE_BUSINESS_KEYS": "IGNORE_ON_LOAD"},
    "pointers": {"DUPLICATE_BUSINESS_KEYS": "IGNORE_ON_LOAD"},
    "contexttable": {"DUPLICATE_BUSINESS_KEYS": "IGNORE_ON_LOAD"},
}

STATUS_NOTES: dict[str, str] = {
    "ACCEPTED_SPARSE_KEY": "Reviewed and accepted as a sparse business-key table.",
    "IGNORE_ON_LOAD": "Reviewed and treated as a source-data issue safe to ignore or dedupe on load.",
}

HARD_FAILURE_STATUSES: frozenset[str] = frozenset(
    {
        "AMBIGUOUS_CSV_MATCH",
        "MISSING_KEY_COLUMNS",
        "DUPLICATE_BUSINESS_KEYS",
    }
)


def has_hard_failures(results: list[AuditResult]) -> bool:
    return any(r.status in HARD_FAILURE_STATUSES for r in results)


@dataclass
class AuditResult:
    kind: str
    raw_table_name: str
    table_name: str
    maturity: str
    unique_key_raw: str
    key_columns: list[str]
    csv_name: str | None
    source_row_count: int | None
    row_count: int | None
    exact_duplicate_rows_removed: int | None
    duplicate_business_keys: int | None
    rows_with_null_key_parts: int | None
    missing_key_columns: list[str]
    status: str
    notes: list[str]
    duplicate_examples: list[dict[str, Any]]


def canonical_key_value(value: Any) -> str:
    """
    Canonicalise a business-key cell the same way the runtime column
    caster does, so the audit can't pass on data that will actually
    collide once loaded.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "__NULL_KEY__"

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    text = str(value).strip()
    if text.isdigit():
        text = str(int(text))
    else:
        try:
            f = float(text)
            if f.is_integer():
                text = str(int(f))
        except ValueError:
            pass

    return text.casefold()


def extract_duplicate_examples(
    df: pd.DataFrame, key_columns: list[str], limit: int = 5
) -> list[dict[str, Any]]:
    if df.empty:
        return []

    counts = (
        df.groupby(key_columns, dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values(
            ["count", *key_columns], ascending=[False, *([True] * len(key_columns))]
        )
    )
    examples: list[dict[str, Any]] = []
    for _, row in counts.head(limit).iterrows():
        example = {col: row[col] for col in key_columns}
        example["count"] = int(row["count"])
        examples.append(example)
    return examples


def canonical_key_frame(df: pd.DataFrame, key_columns: list[str]) -> pd.DataFrame:
    keyed = df[key_columns].copy()
    for col in key_columns:
        keyed[col] = keyed[col].map(canonical_key_value)
    return keyed


def audit_table(
    kind: str, raw_table_name: str, maturity: str, unique_key_raw: str, data_dir: Path
) -> AuditResult:
    table_name = safe_identifier(raw_table_name)
    key_columns = parse_unique_key(unique_key_raw)
    csv_path, ambiguous_matches = resolve_source_csv(data_dir, table_name)

    base = AuditResult(
        kind=kind,
        raw_table_name=raw_table_name,
        table_name=table_name,
        maturity=maturity,
        unique_key_raw=unique_key_raw,
        key_columns=key_columns,
        csv_name=None,
        source_row_count=None,
        row_count=None,
        exact_duplicate_rows_removed=None,
        duplicate_business_keys=None,
        rows_with_null_key_parts=None,
        missing_key_columns=[],
        status="",
        notes=[],
        duplicate_examples=[],
    )

    if ambiguous_matches:
        return replace(
            base,
            status="AMBIGUOUS_CSV_MATCH",
            notes=[f"Ambiguous CSV matches: {', '.join(ambiguous_matches)}"],
        )

    if not key_columns:
        return replace(
            base,
            csv_name=csv_path.name if csv_path else None,
            status="NO_DECLARED_NATURAL_KEY",
            notes=["Overview row has no parseable natural key."],
        )

    if csv_path is None:
        return replace(
            base,
            status="NO_CURRENT_CSV",
            notes=["No matching current CSV found in the data directory."],
        )

    df = pd.read_csv(csv_path)
    normalized_df = df.rename(columns=lambda c: safe_identifier(c).lower())
    source_row_count = len(normalized_df)
    missing_key_columns = [
        col for col in key_columns if col not in normalized_df.columns
    ]

    if missing_key_columns:
        return replace(
            base,
            csv_name=csv_path.name,
            source_row_count=source_row_count,
            row_count=source_row_count,
            exact_duplicate_rows_removed=0,
            missing_key_columns=missing_key_columns,
            status="MISSING_KEY_COLUMNS",
            notes=[
                f"Declared key columns missing from CSV: {', '.join(missing_key_columns)}"
            ],
        )

    notes: list[str] = []
    exact_duplicate_rows_removed = int(normalized_df.duplicated(keep="first").sum())
    audit_df = normalized_df.drop_duplicates(ignore_index=True)
    if exact_duplicate_rows_removed > 0:
        notes.append(
            f"Removed {exact_duplicate_rows_removed} exact full-row duplicate"
            f"{'' if exact_duplicate_rows_removed == 1 else 's'} before key audit."
        )

    key_df = audit_df[key_columns]
    has_null_key_part = key_df.isna().any(axis=1)
    rows_with_null_key_parts = int(has_null_key_part.sum())

    # Rows with a null key part are excluded from the duplicate check
    # because a business key that's partly unassigned (e.g. `sigs.variant_cui`
    # before it is linked to its eventual variant) isn't comparable to another
    # row with the same gap, matching standard SQL UNIQUE-constraint semantics
    # where NULLs never collide

    # Keying only the fully-populated rows reclassifies partial nulls as
    # SPARSE_KEY_ROWS instead of false DUPLICATE_BUSINESS_KEYS.

    keyed_df = audit_df.loc[~has_null_key_part]
    canonical_df = canonical_key_frame(keyed_df, key_columns)
    duplicate_mask = canonical_df.duplicated(subset=key_columns, keep=False)
    duplicate_business_keys = int(canonical_df.duplicated(subset=key_columns).sum())

    if duplicate_business_keys > 0:
        status = "DUPLICATE_BUSINESS_KEYS"
        notes.append(
            "Declared business keys are not unique under case/numeric-canonical comparison."
        )
    elif rows_with_null_key_parts > 0:
        status = "SPARSE_KEY_ROWS"
        notes.append(
            "Declared business key includes nullable dimensions in current data."
        )
    else:
        status = "OK"

    duplicate_examples = extract_duplicate_examples(
        keyed_df.loc[duplicate_mask, key_columns], key_columns
    )

    return replace(
        base,
        csv_name=csv_path.name,
        source_row_count=source_row_count,
        row_count=len(audit_df),
        exact_duplicate_rows_removed=exact_duplicate_rows_removed,
        duplicate_business_keys=duplicate_business_keys,
        rows_with_null_key_parts=rows_with_null_key_parts,
        status=status,
        notes=notes,
        duplicate_examples=duplicate_examples,
    )


def apply_review_decisions(results: list[AuditResult]) -> list[AuditResult]:
    updated: list[AuditResult] = []
    for result in results:
        reviewed_status = TABLE_DECISIONS.get(result.table_name, {}).get(result.status)
        if reviewed_status is None:
            updated.append(result)
            continue

        notes = list(result.notes)
        note = STATUS_NOTES.get(reviewed_status)
        if note and note not in notes:
            notes.append(note)

        updated.append(replace(result, status=reviewed_status, notes=notes))
    return updated


def load_overview_rows(dictionary_path: Path) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    overview_overrides: dict[str, tuple[str, str]] = {}
    overview_ambiguous: set[str] = set()

    overview_df = pd.read_excel(dictionary_path, sheet_name="Overview")
    for _, row in overview_df.iterrows():
        raw_name_value = row.get(CONTENT_COL)
        if pd.isna(raw_name_value):
            continue

        raw_name = str(raw_name_value).strip()
        if not raw_name:
            continue

        normalized_name = safe_identifier(raw_name)
        if not normalized_name:
            continue

        maturity = (
            "" if pd.isna(row.get(MATURITY_COL)) else str(row[MATURITY_COL]).strip()
        )
        unique_key_raw = (
            "" if pd.isna(row.get(UNIQUE_COL)) else str(row[UNIQUE_COL]).strip()
        )

        if normalized_name in overview_overrides:
            overview_ambiguous.add(normalized_name)
            continue

        overview_overrides[normalized_name] = (maturity, unique_key_raw)

    for normalized_name in overview_ambiguous:
        overview_overrides.pop(normalized_name, None)

    overview_sheets = [
        ("content", "Content", CONTENT_COL),
        ("lookup", "Lookup", LOOKUP_COL),
    ]

    for kind, sheet_name, name_col in overview_sheets:
        df = pd.read_excel(dictionary_path, sheet_name=sheet_name)
        for _, row in df.iterrows():
            if pd.isna(row.get(name_col)):
                continue

            raw_name = str(row[name_col]).strip()
            maturity = (
                ""
                if pd.isna(row.get(MATURITY_COL))
                else str(row.get(MATURITY_COL)).strip()
            )
            unique_key_raw = (
                "" if pd.isna(row.get(UNIQUE_COL)) else str(row.get(UNIQUE_COL)).strip()
            )
            override = overview_overrides.get(safe_identifier(raw_name))
            if override is not None:
                maturity, unique_key_raw = override
            rows.append((kind, raw_name, maturity, unique_key_raw))

    return rows


def run_audit(data_dir: Path) -> list[AuditResult]:
    overview_rows = load_overview_rows(data_dir / DICTIONARY_FILENAME)
    results = [
        audit_table(kind, raw_name, maturity, unique_key_raw, data_dir)
        for kind, raw_name, maturity, unique_key_raw in overview_rows
    ]
    results = apply_review_decisions(results)
    return sorted(results, key=lambda r: (r.kind, r.table_name))


def enum_collision_warnings(registry: Registry) -> list[str]:
    """
    Flag enum columns where two distinct display values collapse onto the
    same generated member name.
    """
    warnings: list[str] = []
    for table_name, meta in registry.tables.items():
        for col_name, enum_spec in meta.enums.items():
            values = [v.strip().lower() for v in enum_spec.values]
            by_key: dict[str, set[str]] = {}
            for v in dict.fromkeys(values):
                by_key.setdefault(safe_enum_key(v), set()).add(v)
            for key, members in by_key.items():
                if len(members) > 1:
                    collapsed = ", ".join(repr(m) for m in sorted(members))
                    warnings.append(
                        f"{table_name}.{col_name}: {collapsed} all normalise to enum member "
                        f"'{key}' -- only one survives generation"
                    )
    return warnings


def enum_threshold_warnings(registry: Registry, within: int = 3) -> list[str]:
    """
    Flag enum columns close to the MAX_ENUM_UNIQUE threshold
    """
    warnings: list[str] = []
    for table_name, meta in registry.tables.items():
        for col_name, enum_spec in meta.enums.items():
            n = len(enum_spec.values)
            if MAX_ENUM_UNIQUE - within <= n <= MAX_ENUM_UNIQUE:
                warnings.append(
                    f"{table_name}.{col_name}: {n}/{MAX_ENUM_UNIQUE} distinct values - close to max threshold"
                )
    return warnings


def dictionary_only_column_warnings(registry: Registry) -> list[str]:
    """Report dictionary fields not present in the current table extract.

    These are intentionally warnings rather than automatic column removals:
    a reviewed computed field could be absent from a particular CSV release.
    Footnotes are filtered earlier by ``enrich_field_metadata``.
    """
    warnings: list[str] = []
    dictionary_only = getattr(registry, "_dictionary_only_columns", {})
    for table_name, columns in sorted(dictionary_only.items()):
        if columns:
            warnings.append(
                f"{table_name}: dictionary-only column(s) not found in the current "
                f"CSV header: {', '.join(columns)}"
            )
    return warnings


def build_report(results: list[AuditResult], data_dir: Path) -> str:
    status_counts = Counter(result.status for result in results)

    hard_failures = HARD_FAILURE_STATUSES
    reviewed_statuses = {"ACCEPTED_SPARSE_KEY", "IGNORE_ON_LOAD"}
    warning_statuses = {"SPARSE_KEY_ROWS", "NO_CURRENT_CSV", "NO_DECLARED_NATURAL_KEY"}

    lines: list[str] = ["# Natural Key Audit Report", ""]
    lines.append(f"- Dictionary: `{data_dir / DICTIONARY_FILENAME}`")
    lines.append(f"- Data directory: `{data_dir}`")
    lines.append(f"- Overview tables scanned: `{len(results)}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- `OK`: {status_counts['OK']}")
    for status in sorted(
        (hard_failures | reviewed_statuses | warning_statuses) - {"OK"}
    ):
        if status_counts[status]:
            lines.append(f"- `{status}`: {status_counts[status]}")
    lines.append("")

    lines.append("## Hard Mismatches")
    lines.append("")
    hard_rows = [r for r in results if r.status in hard_failures]
    if not hard_rows:
        lines.append("- None.")
    else:
        for result in hard_rows:
            lines.append(f"### `{result.table_name}`")
            lines.append(f"- Status: `{result.status}`")
            for note in result.notes:
                lines.append(f"- Note: {note}")
            lines.append("")

    lines.append("## Warnings")
    lines.append("")
    warning_rows = [r for r in results if r.status in warning_statuses]
    if not warning_rows:
        lines.append("- None.")
    else:
        for result in warning_rows:
            lines.append(f"- `{result.table_name}`: status=`{result.status}`")
    lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit overview-declared natural keys against current CSV data."
    )
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    results = run_audit(args.data_dir)
    report = build_report(results, args.data_dir)

    if args.output is None:
        print(report)
        return

    args.output.write_text(report, encoding="utf-8")
    print(f"Wrote report to {args.output}")


if __name__ == "__main__":
    main()
