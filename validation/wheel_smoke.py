"""Exercise only the installed package, including optional-dependency absence."""

import argparse
import importlib.util
import tempfile
from pathlib import Path

import sqlalchemy as sa
from oa_configurator import Resolver, StackConfig
from sqlalchemy.orm import Session

from hemonc_alchemy.bootstrap import bootstrap_database
from hemonc_alchemy.config import create_hemonc_engine
from hemonc_alchemy.integrations.omop import load_omop_binding
from hemonc_alchemy.model import Base
from hemonc_alchemy.model.entities import (
    HemoncClasses,
    hemonc_classes_Secondary_home_as_stringMap,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["sqlite", "duckdb"], required=True)
    args = parser.parse_args(argv)
    if args.backend == "sqlite":
        assert importlib.util.find_spec("duckdb") is None
        assert importlib.util.find_spec("omop_alchemy") is None
        assert load_omop_binding() is None
    else:
        assert load_omop_binding() is not None
    with tempfile.TemporaryDirectory(prefix="hemonc-wheel-") as directory:
        root = Path(directory)
        (root / "hemonc_classes.csv").write_text(
            "description,domain,class_type,primary_table,secondary_home_as_string,in_OHDSI\n"
            "Registry,clinical trial,ready for core,ready for core,studies$registry|studies$trial,FALSE\n"
        )
        config = StackConfig.for_session(
            connections={"local": {"dialect": args.backend, "database_name": str(root / "snapshot.db")}},
            databases={"local": {"kind": "generic", "connection": "local", "schema_name": "hemonc" if args.backend == "duckdb" else None}},
        )
        database = Resolver(config).resolve_database("local")
        counts = bootstrap_database(database, root)
        assert counts == {"hemonc_classes": {"hemonc_classes": 1, "secondary_home_as_string": 2}}
        assert bootstrap_database(database, root, rebuild=True) == counts
        engine = create_hemonc_engine(database)
        try:
            schema = engine.get_execution_options()["schema_translate_map"]["primary"]
            expected = {table.name for table in Base.metadata.tables.values()}
            assert len(expected) == 86  # 22 source tables and 64 collection maps.
            assert expected <= set(sa.inspect(engine).get_table_names(schema=schema))
            with Session(engine) as session:
                rows = session.execute(sa.select(
                    HemoncClasses.description, hemonc_classes_Secondary_home_as_stringMap.secondary_home_as_string,
                ).join(hemonc_classes_Secondary_home_as_stringMap,
                       HemoncClasses.id == hemonc_classes_Secondary_home_as_stringMap.parent_id)).all()
                assert set(rows) == {("Registry", "studies$registry"), ("Registry", "studies$trial")}
        finally:
            engine.dispose()
    print(f"PASS: installed wheel, {args.backend}, all {len(expected)} tables, import/rebuild and child linkage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
