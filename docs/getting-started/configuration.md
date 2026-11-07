# Configuration

HemOnc Alchemy uses `oa-configurator` so several Australian Cancer Data Network packages can refer to the same named databases without putting credentials in Python or source control.

The configuration has three levels:

- A **connection** contains driver, host, credentials, and database name.
- A **database** gives that connection a logical name and schema.
- A **tool target** selects `hemonc_db` and an optional CDM target, `omop_db`, for vocabulary queries.

That indirection is useful when the same application moves between a local database, a shared server, and a test database. It also makes it possible for a HemOnc target and an OMOP target to share a PostgreSQL server while remaining different schemas or databases.

## Configure a database

Run the interactive configurator:

```bash
omop-config configure hemonc_alchemy
```

A minimal configuration has this shape:

```toml
[connections.hemonc]
dialect       = "postgresql+psycopg"
host          = "localhost"
port          = 5432
user          = "hemonc"
password      = "change-me"
database_name = "hemonc_alchemy"

[databases.hemonc_db]
kind        = "generic"
connection  = "hemonc"
schema_name = "public"

[tools.hemonc_alchemy]
hemonc_db = "hemonc_db"
```

Let the configurator create the real file so its current conventions are preserved. Never commit passwords. If you need separate test or OMOP targets, configure them as additional named databases rather than changing application code.

## Open a session

Resolve the logical target once, keep the engine for the lifetime of the application, and create sessions for units of work:

```python
from sqlalchemy.orm import Session

from hemonc_alchemy import create_hemonc_engine, get_hemonc_context

_, database = get_hemonc_context()
engine = create_hemonc_engine(database)

with Session(engine) as session:
    ...
```

Toolkit functions do not own your session or transaction. This keeps connection lifetime, transaction boundaries, and error handling under application control.

## The devcontainer configuration

When the repository devcontainer is created, `.devcontainer/config.toml` is copied to `~/.config/omop/config.toml` with mode 600. Its `hemonc_db` target points at the Compose PostgreSQL service; its test target points at a separate `hemonc_alchemy_test` database. HemOnc's generated tables and foreign keys carry the logical `primary` role. `create_hemonc_engine()` uses oa-configurator to map that role to the target's configured `schema_name`, or the connection's default schema when no override is configured.

The checked-in file is a seed, not the active configuration. An existing copy is never overwritten. To keep configuration elsewhere, set `OA_CONFIG_PATH` **before starting Python**. `OA_CONFIG_SEED` chooses the seed used by `post-create.sh` when that file is absent. Back up a customized config before editing it.

### DuckDB configuration

Install `hemonc-alchemy[duckdb]` and use a persistent, writable file. Keep the file stem distinct from the configured schema name: DuckDB uses that stem as its catalog name, and identical names make two-part table references ambiguous.

```toml
[connections.local]
dialect = "duckdb"
database_name = "/absolute/writable/path/hemonc-alchemy.duckdb"

[databases.hemonc_db]
kind = "generic"
connection = "local"
schema_name = "hemonc"

[databases.cdm_db]
kind = "cdm"
connection = "local"
cdm_schema = "cdm"
vocab_schema = "omop"

[tools.hemonc_alchemy]
hemonc_db = "hemonc_db"
omop_db = "cdm_db"
```

Omit the CDM database and `omop_db` if no vocabulary is needed. Bootstrap creates HemOnc tables; load vocabulary tables separately. A vocabulary join requires the vocabulary role to use the same physical database as HemOnc. Merely sharing a PostgreSQL server is insufficient. A separate schema in the same PostgreSQL database or DuckDB file is supported. See [OMOP integration](../integrations/omop.md).

The independent DuckDB devcontainer uses `.devcontainer/config.duckdb.toml`, a separate active config filename, and a database persisted under the repository's `data` mount. See [Local development](local-development.md).

### Update an existing copied config

Startup preserves an existing file, so dependency upgrades do not apply seed changes to it. Back up the active TOML and apply these changes where applicable:

1. In `[tools.omop_alchemy]`, rename `test_cdm_db` to `test_cdm_db_pg`. Keep its existing database reference; the `[databases.test_cdm_db]` entry need not be renamed.
2. In `[tools.hemonc_alchemy]`, add `omop_db = "cdm_db"` using the intended CDM database's actual name. This makes vocabulary selection explicit when several CDM targets exist.
3. For copies of the old repository seed, change `cdm_schema = "public"` to `"cdm"` in `[databases.cdm_db]` and `[databases.test_cdm_db]`. Leave HemOnc's `schema_name = "public"` and `vocab_schema = "omop"` intact. oa-configurator 2.1 rejects overlapping explicit primary-schema ownership. These settings route future CDM operations; they do not move existing CDM tables. Adapt this layout to any existing clinical tables before using CDM tooling.

HemOnc-only configs do not need an OMOP target. Existing generic HemOnc targets remain valid. To switch to DuckDB, select a separate config file instead of replacing the PostgreSQL connection in place.

## Check the connection

```bash
python - <<'PY'
from sqlalchemy import text
from sqlalchemy.orm import Session

from hemonc_alchemy import create_hemonc_engine, get_hemonc_context

_, database = get_hemonc_context()
engine = create_hemonc_engine(database)
with Session(engine) as session:
    print(session.execute(text("SELECT 1")).scalar_one())
PY
```

If the target is missing, configure it with `omop-config configure hemonc_alchemy` rather than embedding a connection string in analysis code.

## Bring your own engine

For a URL-based connection to HemOnc tables in the database's default schema:

```python
from hemonc_alchemy import create_default_hemonc_engine

engine = create_default_hemonc_engine("sqlite:///:memory:")
```

This helper accepts the usual SQLAlchemy engine keyword arguments and adds `schema_translate_map={"primary": None}`. Explicit execution options and schema routes take precedence. Existing SQLAlchemy engines can receive that same execution option before creating tables or sessions. For an isolated physical schema, map `primary` to its name or use the configured target shown above. Mapping does not create the physical schema; provision it before creating the tables.

Raw SQL text is not rewritten by schema translation. SQLAlchemy model and table expressions carry the logical schema role. The role is also part of metadata keys, for example `Base.metadata.tables["primary.variants"]`.

Named PostgreSQL enum types use the same role as their tables. DuckDB uses string columns with label `CHECK` constraints, avoiding the current driver's untranslated schema references for named enum types while retaining label validation.
