"""Shared pytest fixtures for tests that need a real PostgreSQL database."""

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
