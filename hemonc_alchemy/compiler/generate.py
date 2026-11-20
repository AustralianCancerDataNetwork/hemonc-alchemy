"""
Build a Registry from the HemOnc data dictionary and render the model.

This is the path from data dictionary to generated code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ..errors import HemOncValidationError
from .infer import (
    CONTENT_COL,
    DICTIONARY_FILENAME,
    LOOKUP_COL,
    MATURITY_COL,
    UNIQUE_COL,
    parse_unique_key,
    safe_identifier,
)
from .schema_model import Registry, TableMeta, save_registry_json
from .validate import validate_registry

MULTIVAL_OVERRIDES_SHEET = "MultivalOverrides"
SOURCE_ALIASES_SHEET = "SourceAliases"


def parse_multival_overrides(df: pd.DataFrame) -> dict[str, set[str]]:
    """Return hard ``Table -> Column`` multivalue exclusions from a sheet."""
    columns = {str(column).strip().casefold(): column for column in df.columns}
    try:
        table_col = columns["table"]
        column_col = columns["column"]
    except KeyError as exc:
        raise ValueError(
            f"{MULTIVAL_OVERRIDES_SHEET} must contain 'Table' and 'Column' columns"
        ) from exc

    overrides: dict[str, set[str]] = {}
    for _, row in df.iterrows():
        if pd.isna(row[table_col]) or pd.isna(row[column_col]):
            continue
        table = safe_identifier(str(row[table_col]).strip())
        column = safe_identifier(str(row[column_col]).strip())
        overrides.setdefault(table, set()).add(column)
    return overrides


def load_multival_overrides(dictionary_path: Path) -> dict[str, set[str]]:
    """Load optional hard multivalue exclusions from the data dictionary."""
    try:
        overrides_df = pd.read_excel(
            dictionary_path, sheet_name=MULTIVAL_OVERRIDES_SHEET
        )
    except ValueError:
        return {}
    return parse_multival_overrides(overrides_df)


def parse_source_aliases(df: pd.DataFrame) -> dict[str, str]:
    """Return declared ``Table -> Filename stem`` source-file aliases."""
    columns = {str(column).strip().casefold(): column for column in df.columns}
    try:
        table_col = columns["table"]
        file_col = columns["file"]
    except KeyError as exc:
        raise ValueError(
            f"{SOURCE_ALIASES_SHEET} must contain 'Table' and 'File' columns"
        ) from exc

    aliases: dict[str, str] = {}
    for _, row in df.iterrows():
        if pd.isna(row[table_col]) or pd.isna(row[file_col]):
            continue
        table = safe_identifier(str(row[table_col]).strip())
        stem = Path(str(row[file_col]).strip()).stem
        if table in aliases and aliases[table] != stem:
            raise ValueError(
                f"{SOURCE_ALIASES_SHEET} declares conflicting files for table "
                f"'{table}': '{aliases[table]}' and '{stem}'"
            )
        aliases[table] = stem
    return aliases


def load_source_aliases(dictionary_path: Path) -> dict[str, str]:
    """
    Load optional explicit source-file aliases from the data dictionary.

    An alias is how a genuine upstream table rename gets recorded as authored,
    reviewed content rather than inferred by a filename heuristic
    """
    try:
        aliases_df = pd.read_excel(dictionary_path, sheet_name=SOURCE_ALIASES_SHEET)
    except ValueError:
        return {}
    return parse_source_aliases(aliases_df)


def build_registry(dictionary_path: Path) -> Registry:
    """Build a `Registry` from the workbook's `Content` and `Lookup` sheets."""
    content_df = pd.read_excel(dictionary_path, sheet_name="Content")
    lookup_df = pd.read_excel(dictionary_path, sheet_name="Lookup")

    tables = []
    for content_col, df in {CONTENT_COL: content_df, LOOKUP_COL: lookup_df}.items():
        name_map = {
            content_col: "name",
            MATURITY_COL: "maturity",
            "Description": "description",
            UNIQUE_COL: "unique_key",
        }
        if "Identity Key" in df.columns:
            name_map["Identity Key"] = "identity_key"

        columns = df.rename(columns=name_map)[list(name_map.values())].to_dict(
            orient="records"
        )
        for col in columns:
            c = {k: v.strip() if isinstance(v, str) else v for k, v in col.items()}
            c["source_name"] = c["name"] if isinstance(c["name"], str) else None
            c["name"] = safe_identifier(c["name"])
            c["pk_columns"] = parse_unique_key(
                "" if pd.isna(c.get("unique_key")) else str(c["unique_key"])
            )
            c["identity_keys"] = parse_unique_key(
                "" if pd.isna(c.get("identity_key")) else str(c["identity_key"])
            )
            c["kind"] = "content" if content_col == CONTENT_COL else "lookup"
            kwargs: dict[str, Any] = {
                str(k): v
                for k, v in c.items()
                if isinstance(k, str) and k in TableMeta.__annotations__
            }
            tables.append(TableMeta(**kwargs))
    return Registry(tables={t.name: t for t in tables})


def regenerate(
    data_dir: Path,
    output_dir: Path,
) -> Registry:
    """
    Regenerate model/entities.py, model/enums.py, and the interim JSON
    registry snapshot. Does NOT validate or diff.
    """
    dictionary_path = data_dir / DICTIONARY_FILENAME
    registry = build_registry(dictionary_path)
    registry.enrich_table_metadata(dictionary_path)
    registry.finalise_table_metadata_from_data(
        data_dir, source_aliases=load_source_aliases(dictionary_path)
    )
    raw_dates = [
        f"{table}.{column}"
        for table, meta in registry.tables.items()
        for column in meta.raw_date_columns
    ]
    print(
        "DateTime columns with raw fields: "
        + (", ".join(raw_dates) if raw_dates else "none")
    )
    registry.apply_multival_overrides(load_multival_overrides(dictionary_path))

    # Structural checks belong *before* rendering, which is what
    # validate_registry's own docstring describes. Running them only after
    # meant a bad declaration surfaced as a KeyError from inside the code
    # generator instead of a named error: a stale `Unique Key` in the
    # dictionary (`contextRaw` after the extract renamed the column to
    # `context_raw`) crashed normalised_table_class with `KeyError:
    # 'contextraw'` and no indication of the cause.
    errors = validate_registry(registry)
    if errors:
        joined = "\n".join(f"  - {e}" for e in errors)
        raise HemOncValidationError(
            f"Registry failed structural validation before rendering:\n{joined}"
        )

    entities_code, enums_code = registry.render_sa_models()

    (output_dir / "entities.py").write_text(entities_code, encoding="utf-8")
    (output_dir / "enums.py").write_text(enums_code, encoding="utf-8")
    save_registry_json(registry, output_dir.parent / "schema" / "registry.json")

    return registry
