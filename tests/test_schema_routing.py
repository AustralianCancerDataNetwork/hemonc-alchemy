"""Generated schema roles, composite FK enforcement, and dialect DDL lifecycle."""

from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from oa_configurator import ResolvedDatabase, Resolver, StackConfig
from oa_configurator.testing import isolated_test_schema

from hemonc_alchemy.compiler.schema_model import load_registry_json
from hemonc_alchemy.config import create_default_hemonc_engine, create_hemonc_engine
from hemonc_alchemy.model.base import Base
from hemonc_alchemy.model.entities import HemoncClasses


@pytest.fixture(params=[
    "sqlite",
    pytest.param("duckdb_default", marks=[pytest.mark.duckdb, pytest.mark.db_dialect]),
    pytest.param("duckdb_named", marks=[pytest.mark.duckdb, pytest.mark.db_dialect]),
    pytest.param("postgresql_default", marks=[pytest.mark.postgres, pytest.mark.db_dialect]),
    pytest.param("postgresql_named", marks=[pytest.mark.postgres, pytest.mark.db_dialect]),
])
def schema_target(request):
    with ExitStack() as stack:
        if request.param == "sqlite":
            config = StackConfig.for_session(
                connections={"local": {"dialect": "sqlite", "database_name": ":memory:"}},
                databases={"local": {"kind": "generic", "connection": "local"}},
            )
            resolved = Resolver(config).resolve_database("local")
            physical = "main"
        else:
            db = request.getfixturevalue("pg_db" if request.param.startswith("postgresql") else "duckdb_db")
            physical = stack.enter_context(isolated_test_schema(db.committing_engine, prefix="hemonc_schema"))
            resolved = ResolvedDatabase(name="hemonc_schema_test", connection=db.resolved.connection, schema_name=physical)
        if request.param == "postgresql_default":
            # The connection's default schema is itself isolated from other tests.
            resolved = replace(resolved, schema_name=None)
            engine = resolved.create_engine(connect_args={"options": f"-csearch_path={physical}"})
        elif request.param == "duckdb_default":
            resolved = replace(resolved, schema_name=None)
            physical = "main"
            engine = create_hemonc_engine(resolved)
        else:
            engine = create_hemonc_engine(resolved)
        stack.callback(engine.dispose)
        if request.param == "sqlite":
            @sa.event.listens_for(engine, "connect")
            def enable_foreign_keys(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
        yield engine, physical


def test_all_generated_tables_and_enums_use_the_primary_role():
    # 22 source tables plus 64 genuine collection maps after scalar corrections.
    assert len(Base.metadata.tables) == 86
    assert {table.schema for table in Base.metadata.tables.values()} == {"primary"}
    for table in Base.metadata.tables.values():
        for column in table.c:
            if isinstance(column.type, sa.Enum):
                assert column.type.schema == "primary"
        for fk in table.foreign_key_constraints:
            assert fk.referred_table.schema == "primary"
            assert [element.column.name for element in fk.elements] == [column.name for column in fk.referred_table.primary_key]


def test_url_engine_keeps_explicit_schema_routes_and_execution_options():
    engine = create_default_hemonc_engine("sqlite://", execution_options={
        "schema_translate_map": {"primary": "temp", "vocab": "omop"}, "stream_results": True,
    })
    try:
        options = engine.get_execution_options()
        assert options["schema_translate_map"] == {"primary": "temp", "vocab": "omop"}
        assert options["stream_results"] is True
    finally:
        engine.dispose()


def test_model_regeneration_is_reproducible():
    package = Path(__file__).parents[1] / "hemonc_alchemy"
    registry = load_registry_json(package / "schema" / "registry.json")
    entities, enums = registry.render_sa_models()
    assert entities == (package / "model" / "entities.py").read_text()
    assert enums == (package / "model" / "enums.py").read_text()
    registry.tables = dict(reversed(registry.tables.items()))
    for table in registry.tables.values():
        table.columns = dict(reversed(table.columns.items()))
        table.enums = dict(reversed(table.enums.items()))
        table.normalised_tables.reverse()
    assert registry.render_sa_models() == (entities, enums)


def test_full_schema_creates_drops_and_recreates_in_the_selected_schema(schema_target):
    engine, schema = schema_target
    expected = {table.name for table in Base.metadata.tables.values()}
    Base.metadata.create_all(engine)
    assert expected <= set(sa.inspect(engine).get_table_names(schema=schema))
    if engine.dialect.name == "postgresql":
        enum_names = {column.type.name for table in Base.metadata.tables.values() for column in table.c if isinstance(column.type, sa.Enum)}
        assert enum_names <= {enum["name"] for enum in sa.inspect(engine).get_enums(schema=schema)}
    Base.metadata.drop_all(engine)
    assert not expected.intersection(sa.inspect(engine).get_table_names(schema=schema))
    Base.metadata.create_all(engine)
    assert expected <= set(sa.inspect(engine).get_table_names(schema=schema))


def test_composite_child_foreign_keys_are_enforced(schema_target):
    engine, _ = schema_target
    Base.metadata.create_all(engine)
    canonical_key = {"class_1": "REGIMEN", "class_2": "Context", "relationship": "is_a"}
    affiliation_key = {"aff_no": 1, "pmid": 2, "sequence": 3}
    cases = [
        ("canonicaltriples_class_1_provenance", canonical_key, "class_1_provenance"),
        ("canonicaltriples_class_2_provenance", canonical_key, "class_2_provenance"),
        ("affiliations_affiliation_europmc", affiliation_key, "affiliation_europmc"),
        ("affiliations_affiliation_journal", affiliation_key, "affiliation_journal"),
    ]
    with engine.begin() as connection:
        connection.execute(sa.insert(Base.metadata.tables["primary.canonicaltriples"]), {
            **canonical_key, "date_added": "2026-11-07", "in_ohdsi": False, "internal": False, "used_in": "test",
        })
        connection.execute(sa.insert(Base.metadata.tables["primary.affiliations"]), {
            **affiliation_key, "affiliation_hemonc": "test", "date_added": datetime(2026, 11, 7), "full_name_hemonc": "test",  # column is timezone-naive
        })
        for name, key, value_column in cases:
            connection.execute(sa.insert(Base.metadata.tables[f"primary.{name}"]), {**key, value_column: "valid"})
    for name, key, value_column in cases:
        table = Base.metadata.tables[f"primary.{name}"]
        column = next(column for column in next(iter(table.foreign_key_constraints)).columns if not isinstance(column.type, sa.Enum))
        missing = 999999 if isinstance(column.type, sa.Integer) else "missing parent"
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
            connection.execute(sa.insert(table), {**key, column.name: missing, value_column: "invalid"})


def test_generated_id_inserts_and_queries_use_the_selected_schema(schema_target):
    engine, schema = schema_target
    HemoncClasses.__table__.create(engine)
    record = {"class_type": "READY_FOR_CORE", "description": "schema route", "primary_table": "test", "in_ohdsi": False}
    if engine.dialect.name == "sqlite":
        record["id"] = 1
    with engine.begin() as connection:
        connection.execute(sa.insert(HemoncClasses.__table__), record)
        assert connection.scalar(sa.select(HemoncClasses.id)) == 1
    assert "hemonc_classes" in sa.inspect(engine).get_table_names(schema=schema)
    if engine.dialect.name != "sqlite":
        # These are valid strings but invalid labels; the database must reject them.
        with pytest.raises((sa.exc.IntegrityError, sa.exc.DataError)), engine.begin() as connection:
            connection.execute(sa.insert(HemoncClasses.__table__), {**record, "class_type": "NOT_A_MEMBER"})
