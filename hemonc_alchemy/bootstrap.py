"""Import a source snapshot into the configured HemOnc development target."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, cast

import sqlalchemy as sa
from oa_configurator import ResolvedDatabase, physical_schema_of
from sqlalchemy.orm import Session

from .config import create_hemonc_engine, get_hemonc_context
from .model import entities
from .model.base import Base, concrete_entities
from .naming import resolve_source_csv
from .toolkit.loading import load_all


def _source_models(data_dir: Path, table_names: list[str] | None) -> list[Any]:
    generated = cast(list[Any], concrete_entities(entities))
    models = {model.__tablename__: model for model in generated if getattr(model, "filename", None)}
    selected = table_names if table_names is not None else sorted(models)
    unknown = set(selected) - models.keys()
    if unknown:
        raise ValueError(f"Unknown source tables: {', '.join(sorted(unknown))}")
    found = []
    for name in dict.fromkeys(selected):
        path, ambiguous = resolve_source_csv(data_dir, name)
        if ambiguous:
            raise ValueError(f"Ambiguous source CSVs for {name}: {ambiguous}")
        if path is not None:
            found.append(models[name])
        elif table_names is not None:
            raise FileNotFoundError(f"No source CSV for {name} under {data_dir}")
    if not found:
        raise FileNotFoundError(f"No HemOnc source CSVs found under {data_dir}")
    return found


def _prepare_target(engine: sa.Engine, *, rebuild: bool) -> None:
    schema = physical_schema_of(engine, schema_tag="primary")
    names = {table.name for table in Base.metadata.tables.values()}
    with engine.begin() as connection:
        if schema is not None and engine.dialect.name in {"duckdb", "postgresql"}:
            connection.execute(sa.schema.CreateSchema(schema, if_not_exists=True))
        present = set(sa.inspect(connection).get_table_names(schema=schema))
        if names.intersection(present) and not rebuild:
            raise ValueError("The target already contains HemOnc tables; use --rebuild only for a disposable target")
        if rebuild:
            for name in sorted({f"_staging_{name}" for name in names}.intersection(present)):
                table = sa.Table(name, sa.MetaData(), schema="primary")
                connection.execute(sa.schema.DropTable(table, if_exists=True))
                if engine.dialect.name == "duckdb":
                    sequence = sa.Sequence(f"{name}_rownum_seq", schema="primary")
                    connection.execute(sa.schema.DropSequence(sequence, if_exists=True))
    if rebuild:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def bootstrap_database(
    resolved: ResolvedDatabase, data_dir: Path, *, rebuild: bool = False,
    table_names: list[str] | None = None,
) -> dict[str, dict[str, int]]:
    """Load available sources; an explicit rebuild resets only HemOnc tables.

    Vocabulary and unrelated tables are retained. Each primary load can
    commit before its child loads complete.
    """
    models = _source_models(data_dir, table_names)
    engine = create_hemonc_engine(resolved)
    try:
        _prepare_target(engine, rebuild=rebuild)
        counts = {}
        with Session(engine) as session:
            for model in models:
                counts[model.__tablename__] = load_all(
                    session, model, data_dir, chunksize=100_000,
                    resolved=resolved, staging_schema_tag="primary",
                )
                session.commit()
        return counts
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(os.getenv("HEMONC_DATA_DIR", "data/Tables")))
    parser.add_argument("--table", action="append", dest="tables", help="Source table to import; repeat to select several")
    parser.add_argument("--rebuild", action="store_true", help="Reset HemOnc tables in the selected disposable target")
    args = parser.parse_args(argv)
    _, resolved = get_hemonc_context()
    print(f"HemOnc target: {resolved.name}")
    counts = bootstrap_database(resolved, args.data_dir, rebuild=args.rebuild, table_names=args.tables)
    for name, totals in counts.items():
        print(name, totals)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
