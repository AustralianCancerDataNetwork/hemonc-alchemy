"""Checks run over a regenerated model, at three levels.

`validate_registry` checks the schema before any code is written, so a bad
declaration is reported rather than turning into a confusing error from inside
the generator. `validate_generated_file` parses what was actually written,
catching a fault in the generator itself. `validate_source_regressions`
compares against the last committed schema, since a table quietly losing its
data is invisible to both of the others: a table with no columns has nothing
to check, and around a dozen tables have legitimately never had any.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ..errors import HemOncValidationError
from .schema_model import Registry


def validate_registry(registry: Registry) -> list[str]:
    """Structural checks against the Registry, before any code is rendered."""
    errors: list[str] = []

    dictionary_sheets: set[str] = getattr(registry, "_dictionary_sheets", set())
    enriched_columns: dict[str, set[str]] = getattr(registry, "_dictionary_enriched_columns", {})
    for table_name in sorted(dictionary_sheets):
        if not enriched_columns.get(table_name):
            errors.append(
                f"{table_name}: dictionary sheet exists but contributed no "
                "field enrichment; check its Variable column header"
            )

    for name, meta in registry.tables.items():
        if len(meta.columns) == 0:
            # No entity class is generated for this table (e.g. no backing
            # CSV was found) -- nothing to check.
            continue

        uses_surrogate = meta.uses_surrogate_pk
        effective_pk = ["id"] if uses_surrogate else meta.pk_columns

        for pk in effective_pk:
            if pk == "id" and uses_surrogate:
                continue
            if pk not in meta.columns:
                errors.append(f"{name}: declared pk_column '{pk}' does not exist among its generated columns")

        if not uses_surrogate and not meta.natural_key_is_usable:
            errors.append(
                f"{name}: natural key {meta.pk_columns!r} is sparse or duplicated; "
                "enable surrogate primary-key generation"
            )

        for col_name in meta.enums:
            if col_name not in meta.columns:
                errors.append(f"{name}: enum declared for column '{col_name}' but no such column exists")

        for rel in meta.soft_relationships:
            if rel.target_table not in registry.tables:
                errors.append(f"{name}: soft relationship targets unknown table '{rel.target_table}'")

        for m2m_rel in meta.soft_m2m_relationships:
            if m2m_rel.target_table not in registry.tables:
                errors.append(f"{name}: soft m2m relationship targets unknown table '{m2m_rel.target_table}'")

        # A column repeated within a group, or spread across two, would
        # generate a malformed or ambiguous child table. Has happened.
        seen_in_group: dict[str, int] = {}
        for group in meta.normalisation_groups:
            if len(group.columns) != len(set(group.columns)):
                errors.append(f"{name}: normalisation group {group.columns!r} repeats a column")
            for col in group.columns:
                seen_in_group[col] = seen_in_group.get(col, 0) + 1
        for col, count in seen_in_group.items():
            if count > 1:
                errors.append(f"{name}.{col}: appears in {count} normalisation groups, expected at most 1")

    return errors


def validate_generated_file(path: Path) -> list[str]:
    """Confirm a generated Python file is at least syntactically valid."""
    source = path.read_text(encoding="utf-8")
    try:
        ast.parse(source)
    except SyntaxError as exc:
        return [f"{path}: syntax error at line {exc.lineno}: {exc.msg}"]
    return []


def validate_source_regressions(
    registry: Registry, previous: Registry | None
) -> list[str]:
    """Report tables that used to produce an entity class and no longer do.

    Filename and header conventions upstream aren't ours to control, so a
    future failure to locate a table's data is a matter of when. This is what
    stops that producing a quietly smaller model. Returns nothing on a first
    generation, having no baseline to compare against.
    """
    if previous is None:
        return []

    errors: list[str] = []
    for name, previous_meta in sorted(previous.tables.items()):
        if not previous_meta.columns:
            continue
        current = registry.tables.get(name)
        if current is None:
            # An outright removed table is a schema change the diff gate
            # already reports by name; not a silent source-resolution loss.
            continue
        if current.columns:
            continue
        errors.append(
            f"{name}: had {len(previous_meta.columns)} column(s) backed by "
            f"'{previous_meta.source_filename or 'an unrecorded file'}' and now resolves to no "
            f"source file, so it no longer generates an entity class. If the extract was "
            f"renamed upstream, declare it on the dictionary's SourceAliases sheet; if the "
            f"table is genuinely gone, remove it from the dictionary."
        )
    return errors


def validate_all(
    registry: Registry,
    entities_path: Path,
    enums_path: Path,
    previous: Registry | None = None,
) -> list[str]:
    """Run every check; return all failures (does not raise)."""
    errors = validate_registry(registry)
    errors += validate_generated_file(entities_path)
    errors += validate_generated_file(enums_path)
    errors += validate_source_regressions(registry, previous)
    return errors


def validate_or_raise(registry: Registry, entities_path: Path, enums_path: Path) -> None:
    """Raise HemOncValidationError with every failure listed, if any."""
    errors = validate_all(registry, entities_path, enums_path)
    if errors:
        joined = "\n".join(f"  - {e}" for e in errors)
        raise HemOncValidationError(f"Generated model failed validation:\n{joined}")
