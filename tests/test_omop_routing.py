"""Explicit and configured vocabulary targets must preserve HemOnc's route."""

from contextlib import ExitStack
from dataclasses import replace

import pytest
import sqlalchemy as sa
from oa_configurator import ResolvedCDMDatabase, Resolver, StackConfig
from oa_configurator.testing import isolated_test_schema
from sqlalchemy.orm import Session

from hemonc_alchemy.config import create_hemonc_engine
from hemonc_alchemy.integrations.omop import (
    load_omop_binding,
    omop_availability,
    schema_aware_bind,
)
from hemonc_alchemy.integrations.omop.schema import OmopSchemaConfigurationError
from hemonc_alchemy.model.entities import Units


@pytest.fixture(params=[
    "sqlite",
    pytest.param("duckdb", marks=[pytest.mark.duckdb, pytest.mark.db_dialect]),
    pytest.param("duckdb-default", marks=[pytest.mark.duckdb, pytest.mark.db_dialect]),
    pytest.param("postgresql", marks=[pytest.mark.postgres, pytest.mark.db_dialect]),
])
def routed_database(request, tmp_path):
    if load_omop_binding() is None:
        pytest.skip("the optional omop extra is not installed")
    with ExitStack() as stack:
        if request.param == "postgresql":
            db = request.getfixturevalue("pg_db")
            source_schema = stack.enter_context(isolated_test_schema(db.committing_engine, prefix="hemonc_route"))
            vocabulary_schema = stack.enter_context(isolated_test_schema(db.committing_engine, prefix="omop_route"))
            resolved = replace(db.resolved, schema_name=source_schema)
            target = ResolvedCDMDatabase(
                name="vocabulary", connection=resolved.connection, schema_name="clinical_elsewhere",
                vocab_connection=resolved.connection, vocab_schema=vocabulary_schema, results_schema=None,
            )
            resolver = None
        else:
            named = request.param == "duckdb"
            dialect = "duckdb" if request.param.startswith("duckdb") else request.param
            config = StackConfig.for_session(
                connections={"local": {"dialect": dialect, "database_name": str(tmp_path / "routing.db")}},
                databases={
                    "hemonc": {"kind": "generic", "connection": "local", "schema_name": "hemonc" if named else None},
                    "vocabulary": {"kind": "cdm", "connection": "local", "cdm_schema": "clinical" if named else None,
                                   "vocab_schema": "omop" if named else None},
                },
                tools={"hemonc_alchemy": {"hemonc_db": "hemonc", "omop_db": "vocabulary"}},
            )
            resolver = Resolver(config)
            resolved = resolver.resolve_database("hemonc")
            target = resolver.resolve_database("vocabulary")
        engine = create_hemonc_engine(resolved)
        stack.callback(engine.dispose)
        mapping = dict(engine.get_execution_options()["schema_translate_map"])
        mapping["vocab"] = target.vocab_schema
        seeded = engine.execution_options(schema_translate_map=mapping)
        with seeded.begin() as connection:
            if request.param != "sqlite":
                for schema in {mapping["primary"], mapping["vocab"]}:
                    if schema is not None:
                        connection.execute(sa.schema.CreateSchema(schema, if_not_exists=True))
        Units.__table__.create(seeded)
        binding = load_omop_binding()
        metadata = sa.MetaData()
        for model in [binding.concept, binding.concept_relationship]:
            # Keep the real query shape without requiring an entire Athena release.
            sa.Table(model.__tablename__, metadata, *[
                sa.Column(column.name, column.type.copy(), primary_key=column.primary_key, nullable=True, autoincrement=False)
                for column in model.__table__.c
            ], schema="vocab")
        metadata.create_all(seeded)
        with seeded.begin() as connection:
            connection.execute(sa.insert(Units.__table__), {
                "unit": "mg", "unit_type": "mass", "concept_code": 101,
                "date_added": "2026-11-07", "fixed": True, "parameterbased": False, "timebased": False,
            })
            connection.execute(metadata.tables["vocab.concept"].insert(), {
                "concept_id": 101, "concept_name": "Example unit", "concept_code": "101", "vocabulary_id": "HemOnc",
            })
        yield engine, target, resolver


def joined_unit(session):
    binding = load_omop_binding()
    return session.execute(sa.select(Units.unit, binding.concept.concept_name).join(
        binding.concept, Units.concept_code == binding.concept.concept_id
    )).one()


def test_explicit_target_preserves_primary_for_same_database_joins(routed_database):
    engine, target, _ = routed_database
    primary = engine.get_execution_options()["schema_translate_map"]["primary"]
    with Session(engine) as session:
        assert omop_availability(session, omop_database=target, require_relationships=True).available
        assert session.info["schema_translate_map"]["primary"] == primary
        assert joined_unit(session) == ("mg", "Example unit")
        session.commit()
        assert joined_unit(session) == ("mg", "Example unit")


def test_configured_target_adds_vocab_to_a_generic_engine(routed_database, monkeypatch):
    engine, target, resolver = routed_database
    if resolver is None:
        pytest.skip("configured selection is tested with file-backed local stacks")
    monkeypatch.setattr(Resolver, "from_active_config", staticmethod(lambda: resolver))
    with Session(engine) as session:
        assert omop_availability(session).available
        assert session.info["schema_translate_map"]["vocab"] == target.vocab_schema
        assert joined_unit(session) == ("mg", "Example unit")


def test_missing_vocabulary_schema_is_reported_without_hiding_the_route(routed_database):
    engine, target, _ = routed_database
    with Session(engine) as session:
        availability = omop_availability(session, omop_database=replace(target, vocab_schema="missing_vocabulary"))
        assert not availability.available
        assert "missing_vocabulary" in availability.reason


def test_separate_vocabulary_database_is_rejected_before_opening_it(routed_database, tmp_path):
    engine, target, _ = routed_database
    config = StackConfig.for_session(
        connections={"other": {"dialect": "duckdb", "database_name": str(tmp_path / "unopened.duckdb")}},
        databases={"other": {"kind": "generic", "connection": "other"}},
    )
    other = Resolver(config).resolve_database("other").connection
    with pytest.raises(OmopSchemaConfigurationError, match="same database"):
        schema_aware_bind(engine, omop_database=replace(target, vocab_connection=other))
    assert not (tmp_path / "unopened.duckdb").exists()
    # A remote clinical primary is fine when the vocabulary itself is local.
    with Session(engine) as session:
        schema_aware_bind(session, omop_database=replace(target, connection=other))
        assert joined_unit(session) == ("mg", "Example unit")


def test_explicit_map_wins_over_unusable_config(routed_database, monkeypatch):
    engine, target, _ = routed_database
    def unavailable():
        raise AssertionError("explicit vocabulary mapping must not read active configuration")
    monkeypatch.setattr(Resolver, "from_active_config", staticmethod(unavailable))
    with Session(engine) as session:
        schema_aware_bind(session, {"vocab": target.vocab_schema})
        assert joined_unit(session) == ("mg", "Example unit")


def test_ambiguous_discovery_requires_a_selected_target(tmp_path, monkeypatch):
    config = StackConfig.for_session(
        connections={name: {"dialect": "sqlite", "database_name": str(tmp_path / f"{name}.db")}
                     for name in ["local", "clinical_a", "clinical_b"]},
        databases={"hemonc": {"kind": "generic", "connection": "local"},
                   "a": {"kind": "cdm", "connection": "clinical_a", "vocab_connection": "local"},
                   "b": {"kind": "cdm", "connection": "clinical_b", "vocab_connection": "local"}},
        tools={"hemonc_alchemy": {"hemonc_db": "hemonc"}},
    )
    resolver = Resolver(config)
    monkeypatch.setattr(Resolver, "from_active_config", staticmethod(lambda: resolver))
    engine = create_hemonc_engine(resolver.resolve_database("hemonc"))
    try:
        with pytest.raises(OmopSchemaConfigurationError, match="Multiple OMOP targets"):
            schema_aware_bind(engine)
        config.tools["hemonc_alchemy"]["omop_db"] = "a"
        selected = schema_aware_bind(engine)
        mapping = selected.get_execution_options()["schema_translate_map"]
        assert mapping["primary"] is None
        assert mapping["vocab"] is None
    finally:
        engine.dispose()
