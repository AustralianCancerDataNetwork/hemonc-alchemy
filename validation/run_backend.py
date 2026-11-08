"""Load a complete extract into an isolated backend and write aggregate evidence.

Run from the repository root with ``python -m validation.run_backend --help``.
The output directory is private: it also contains licensed rejection files and
the DuckDB database. Only report.json is designed for review/publication.
"""

from __future__ import annotations

import argparse
import json
import logging
import platform
import traceback
from collections import Counter
from contextlib import contextmanager
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

import sqlalchemy as sa
from oa_configurator import Resolver, StackConfig, load_stack_config
from oa_configurator.testing import isolated_test_database, isolated_test_schema
from orm_loader.loaders import LoadReport
from sqlalchemy.orm import Session

from hemonc_alchemy.bootstrap import _prepare_target, _source_models
from hemonc_alchemy.config import HemOncAlchemyConfig, create_hemonc_engine
from hemonc_alchemy.model import entities
from hemonc_alchemy.model.base import Base, concrete_entities
from hemonc_alchemy.toolkit.loading import load_all

from .parity import source_manifest, table_snapshot
from .queries import toolkit_queries
from .vocabulary import load_snapshot


class ConversionCounts(logging.Handler):
    def __init__(self):
        super().__init__()
        self.counts = Counter()

    def emit(self, record):
        if str(record.msg).startswith("CAST %s.%s: %d value(s) failed"):
            table, column, count = record.args
            action = "nullable_to_null" if "stored as NULL" in record.msg else "invalid_child_token"
            if column == "<row identity>":
                action = "identity_to_null"
            self.counts[f"{table}.{column}.{action}"] += count


@contextmanager
def target(backend: str, output: Path):
    if backend == "postgresql":
        resolver = Resolver(load_stack_config())
        package = resolver.resolve_package_config(HemOncAlchemyConfig)
        if package.test_hemonc_db is None:
            raise ValueError("Configure test_hemonc_db on a test_only PostgreSQL connection")
        resolved = resolver.resolve_database(package.test_hemonc_db)
        if not resolved.connection.test_only:
            raise ValueError("Parity imports require a test_only PostgreSQL connection")
        with (
            isolated_test_database(HemOncAlchemyConfig, "test_hemonc_db", dialect="postgresql") as database,
            isolated_test_schema(database.committing_engine, prefix="hemonc_parity") as schema,
        ):
            yield replace(database.resolved, schema_name=schema)
        return
    config = StackConfig.for_session(
        connections={"local": {"dialect": "duckdb", "database_name": str((output / "snapshot.duckdb").resolve())}},
        databases={"local": {"kind": "generic", "connection": "local", "schema_name": "hemonc"}},
    )
    yield Resolver(config).resolve_database("local")


def write_report(output: Path, report: dict) -> None:
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


def record_error(output: Path, report: dict, stage: str, error: Exception) -> None:
    report["errors"].append({"stage": stage, "type": type(error).__name__})
    with (output / "errors.private.log").open("a") as stream:
        traceback.print_exception(error, file=stream)
    write_report(output, report)
    print(f"FAILED {stage}: {type(error).__name__}", flush=True)


def load_sources(engine, resolved, models, data_dir, output, report):
    for model in models:
        observed = LoadReport()
        conversions = ConversionCounts()
        logger = logging.getLogger("hemonc_alchemy")
        logger.addHandler(conversions)
        start = perf_counter()
        try:
            with Session(engine) as session:
                counts = load_all(
                    session, model, data_dir, resolved=resolved, staging_schema_tag="primary",
                    chunksize=100_000, report=observed, rejects_dir=output / "rejects",
                )
                session.commit()
            report["loads"][model.__tablename__] = {
                "counts": counts, "rows_read": observed.rows_read,
                "rows_staged": observed.rows_loaded, "rows_rejected": observed.rows_rejected,
                "rows_deduplicated": observed.rows_deduplicated, "accounted": observed.accounted,
                "conversion_failures": dict(conversions.counts),
            }
            print(model.__tablename__, counts, flush=True)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError, sa.exc.SQLAlchemyError) as error:
            record_error(output, report, f"load.{model.__tablename__}", error)
        finally:
            logger.removeHandler(conversions)
            report["timings_seconds"][f"load.{model.__tablename__}"] = round(perf_counter() - start, 4)
            write_report(output, report)


def snapshot(engine, output, report):
    parent_ids = {}
    with engine.connect() as connection:
        for table in Base.metadata.sorted_tables:
            try:
                report["tables"][table.name] = table_snapshot(connection, table, parent_ids)
            except (ValueError, TypeError, KeyError, RuntimeError, sa.exc.SQLAlchemyError) as error:
                connection.rollback()
                record_error(output, report, f"snapshot.{table.name}", error)
    write_report(output, report)
    return parent_ids


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["duckdb", "postgresql"], required=True)
    parser.add_argument("--data-dir", type=Path, default=Path("data/Tables"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--table", action="append")
    parser.add_argument("--vocabulary-snapshot", type=Path)
    args = parser.parse_args(argv)
    names = args.table or [model.__tablename__ for model in concrete_entities(entities) if getattr(model, "filename", None)]
    models = _source_models(args.data_dir, names)
    manifest = source_manifest(args.data_dir, models, full_extract=args.table is None)
    args.output_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    logging.basicConfig(filename=args.output_dir / "run.private.log", level=logging.WARNING)
    report = {
        "backend": args.backend, "source": manifest, "status": "running", "errors": [],
        "loads": {}, "tables": {}, "queries": {}, "vocabulary": None, "timings_seconds": {},
        "versions": {package: version(package) for package in ["hemonc-alchemy", "oa-configurator", "orm-loader", "SQLAlchemy", "duckdb", "duckdb-sqlalchemy"]},
        "python": platform.python_version(),
    }
    write_report(args.output_dir, report)
    start = perf_counter()
    with target(args.backend, args.output_dir) as resolved:
        engine = create_hemonc_engine(resolved)
        try:
            _prepare_target(engine, rebuild=False)
            load_sources(engine, resolved, models, args.data_dir, args.output_dir, report)
            parent_ids = snapshot(engine, args.output_dir, report)
            if args.vocabulary_snapshot is not None:
                engine, report["vocabulary"] = load_snapshot(engine, args.vocabulary_snapshot)
            report["queries"], timings = toolkit_queries(
                engine, parent_ids, include_omop=args.vocabulary_snapshot is not None,
            )
            report["timings_seconds"].update({f"query.{key}": value for key, value in timings.items()})
        except (OSError, ValueError, TypeError, KeyError, RuntimeError, sa.exc.SQLAlchemyError) as error:
            record_error(args.output_dir, report, "validation", error)
        finally:
            engine.dispose()
    report["timings_seconds"]["total"] = round(perf_counter() - start, 4)
    report["status"] = "failed" if report["errors"] else "complete"
    write_report(args.output_dir, report)
    return int(bool(report["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
