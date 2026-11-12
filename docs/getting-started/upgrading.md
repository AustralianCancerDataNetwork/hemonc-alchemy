# Updating an existing setup

HemOnc Alchemy is currently a beta release only. APIs and generated schemas may change without a compatibility layer or a migration path. When updating, check the package, configuration, database schema and application calls together.

## Install the backend you use

In an application managed with uv, update the package with your backend extra:

```bash
uv add --upgrade "hemonc-alchemy[duckdb]"
```

For PostgreSQL, use `hemonc-alchemy[postgres]`. Add `omop` to the extras if your application uses the vocabulary integration, for example `hemonc-alchemy[duckdb,omop]`. See [Installation](installation.md) for repository development environments.

## Check your configuration

The application uses the named `hemonc_db` target. An optional `omop_db` selects the vocabulary target. Configuration files are retained across environment rebuilds, so compare an existing file with the [current configuration examples](configuration.md). The [copied-config checklist](configuration.md#update-an-existing-copied-config) covers older repository seeds.

Use `create_hemonc_engine()` for a configured target or `create_default_hemonc_engine()` for tables in a URL connection's default schema. Both map the model's logical `primary` schema role. See [Engine configuration](configuration.md#bring-your-own-engine) for custom SQLAlchemy engines.

## Use a database built for the model

An existing database must have the columns and tables expected by the installed model. If the schema differs, import the source into a fresh target. Running table creation against an existing database does not update its tables.

Follow [Loading data](../model/loading.md) for imports and rejection reports. For a disposable development target, the [bootstrap command](../model/loading.md#bootstrap-the-development-database) can rebuild and reload HemOnc tables. Rebuilding deletes the target's HemOnc data; select the target carefully.

Generated row IDs belong to their imported dataset. Record links using those IDs must refer to the database they came from.

## Check application queries

Use the [model guide](../model/index.md) to check entity fields and the [toolkit guides](../toolkit/index.md) for current query examples. Verify the pages or analyses that depend on those queries against the rebuilt database.

If the application uses OMOP, check vocabulary availability and routing separately. Some helpers require HemOnc and vocabulary tables in the same physical database; others accept separate sessions. See [OMOP integration](../integrations/omop.md#database-boundary).
