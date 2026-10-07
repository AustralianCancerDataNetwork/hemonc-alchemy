"""Shared pytest fixtures.

Unmarked tests run on sqlite and need nothing external. Tests marked
`@pytest.mark.postgres` need a real Postgres and are skipped otherwise --
surrogate-key loading can't be exercised on sqlite.

To run those too, bring up the test database and configure it once:

    docker compose -p hemonc_alchemy_tests up -d   # from tests/, port 55433
    omop-config configure hemonc_alchemy           # set test_hemonc_db

The project name and port are deliberately distinct from orm-loader's own
test stack, which otherwise collides with this one.
"""

import time

import pytest
import sqlalchemy as sa


@pytest.fixture(scope="session")
def pg_engine():
    from oa_configurator.pytest_plugin import (  # type: ignore[import-untyped]  # no py.typed marker upstream
        ensure_test_db_exists,
        resolve_test_database,
    )

    from hemonc_alchemy.config import HemOncAlchemyConfig

    url = resolve_test_database(HemOncAlchemyConfig, "test_hemonc_db")

    try:
        ensure_test_db_exists(url)
    except Exception as exc:  # noqa: BLE001 -- best-effort setup, real connection attempt follows
        print(f"Could not ensure test DB exists, will try anyway: {exc}")

    last_err = None
    for i in range(20):
        engine: sa.Engine | None = None
        try:
            engine = sa.create_engine(url, future=True)
            with engine.connect() as conn:
                conn.execute(sa.text("SELECT 1"))
            yield engine
            engine.dispose()
            return
        except Exception as exc:  # noqa: BLE001 -- retry loop, any connection failure should retry
            if engine is not None:
                engine.dispose()
            last_err = exc
            print(f"[{i}] Postgres not ready:", repr(exc))
            time.sleep(1)

    pytest.skip(f"PostgreSQL never became available: {last_err}")


@pytest.fixture
def pg_session(pg_engine):
    import sqlalchemy.orm as so

    Session = so.sessionmaker(pg_engine, future=True)
    with Session() as session:
        yield session
        session.rollback()
