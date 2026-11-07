"""Shared pytest fixtures for tests that need a real PostgreSQL database."""

import os

import pytest
import sqlalchemy as sa


@pytest.fixture
def pg_db(request):
    from oa_configurator import Resolver, load_stack_config
    from oa_configurator.testing import isolated_test_database

    from hemonc_alchemy.config import HemOncAlchemyConfig

    request.node.add_marker("db_dialect")
    resolver = Resolver(load_stack_config())
    package_config = resolver.resolve_package_config(HemOncAlchemyConfig)
    if package_config.test_hemonc_db is None:
        pytest.fail(
            "HemOncAlchemyConfig.test_hemonc_db must reference a configured test database"
        )
    resolver.resolve_database(package_config.test_hemonc_db)
    database_context = isolated_test_database(
        HemOncAlchemyConfig,
        "test_hemonc_db",
        dialect="postgresql",
        request=request,
    )
    try:
        database = database_context.__enter__()
    except (OSError, sa.exc.SQLAlchemyError) as exc:
        if os.getenv("HEMONC_REQUIRE_POSTGRES") == "1":
            pytest.fail(f"Required PostgreSQL validation target is unavailable: {exc}")
        pytest.skip(f"PostgreSQL test database is unavailable: {exc}")
    try:
        yield database
    finally:
        database_context.__exit__(None, None, None)


@pytest.fixture
def pg_engine(pg_db):
    return pg_db.committing_engine


@pytest.fixture
def pg_session(pg_db):
    yield pg_db.session


@pytest.fixture
def pg_load_engine(pg_db):
    """A committed disposable schema for loaders that commit their own session."""
    from oa_configurator.testing import isolated_test_schema

    engine = pg_db.committing_engine
    with isolated_test_schema(engine, prefix="hemonc_load") as schema:
        mapping = dict(engine.get_execution_options().get("schema_translate_map", {}))
        mapping["primary"] = schema
        yield engine.execution_options(schema_translate_map=mapping, compiled_cache={})


@pytest.fixture
def duckdb_db(request):
    """A disposable DuckDB file provisioned by oa-configurator."""
    from oa_configurator.testing import isolated_test_database

    from hemonc_alchemy.config import HemOncAlchemyConfig

    with isolated_test_database(
        HemOncAlchemyConfig, "test_hemonc_db_duckdb", dialect="duckdb", request=request
    ) as database:
        yield database
