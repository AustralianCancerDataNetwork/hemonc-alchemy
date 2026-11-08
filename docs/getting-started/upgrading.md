# Upgrade to the DuckDB-capable release

The new dependency family supports configured PostgreSQL and file-backed DuckDB imports. Models now carry a logical `primary` schema role, which is a breaking change for callers creating raw SQLAlchemy engines. Use a configured engine or the default-schema helper below. Existing database rows are not automatically moved or rebuilt.

## Install a consistent dependency family

| Package | Supported family |
| --- | --- |
| oa-configurator | `>=2.1.0,<3` |
| orm-loader | `>=3.0.0,<4` |
| omop-alchemy, optional | `>=3.0.0,<4` |

Install `hemonc-alchemy[postgres]`, `hemonc-alchemy[duckdb]`, or combine the chosen backend with `omop`. Remove application constraints that still require oa-configurator 1.x, orm-loader 1.x/2.x, or omop-alchemy 1.x/2.x before resolving the new lockfile. DuckDB support does not change Explorer's PostgreSQL deployment requirement.

## Update engine construction

For configured databases:

```python
from hemonc_alchemy import create_hemonc_engine, get_hemonc_context

_, database = get_hemonc_context()
engine = create_hemonc_engine(database)
```

For tables in a URL connection's default schema:

```python
from hemonc_alchemy import create_default_hemonc_engine

engine = create_default_hemonc_engine("sqlite:///:memory:")
```

An existing SQLAlchemy engine needs `schema_translate_map={"primary": None}` for its default schema or `{"primary": "your_schema"}` for a named schema. Preserve any additional routes already attached to it. This applies to test fixtures as well as applications. Model metadata keys are now qualified, for example `Base.metadata.tables["primary.variants"]`. Raw SQL text still uses physical schema names.

Existing PostgreSQL tables in `public` remain queryable when `primary` maps to `public` or the connection default. This release does not alter existing tables or constraints. The corrected composite foreign-key definitions apply when creating a fresh schema. Generated enum members and stored labels are preserved; DuckDB enforces labels with string `CHECK` constraints instead of native named enum types.

## Update copied configuration

Existing TOML files are preserved. Apply the [copied-config upgrade steps](configuration.md#update-an-existing-copied-config), including `test_cdm_db_pg`, the optional HemOnc `omop_db`, and distinct explicit HemOnc/CDM primary-schema ownership. Editing schema routes does not migrate clinical tables. Use a separate config file when selecting the [independent DuckDB development environment](local-development.md#duckdb-no-postgresql-service-required).

Same-database OMOP queries can use separate physical schemas. Routing adds the vocabulary role while retaining HemOnc's primary role. Separate physical vocabulary databases require helpers accepting separate sessions; there is no automatic attach. See [OMOP integration](../integrations/omop.md).

## Update loading calls and retries

Use `Entity.load_file(session, path, ...)`. The deprecated `load_csv()` alias remains available, and `register_enum_casts()` is now a deprecated no-op. Package-level `load_entity()`, `load_denormalised()`, and `load_all()` retain their count return shapes.

Pass the resolved database to loaders as `resolved=database`, especially for DuckDB. Conversion is local to each load: malformed nullable values become NULL, while malformed required values reject their rows. Nullable conversions remain compatible with child-parent identity matching. Rejection reports distinguish rejected parents from dropped invalid child tokens.

ID-less surrogate-key extracts are snapshots for empty parent tables. Native PostgreSQL/DuckDB sequences reserve their generated IDs; a second ID-less import is refused. There is no incremental identity reconciliation. Explicit-ID inputs remain responsible for native sequence synchronization before later inserts that omit IDs.

Primary merges and intermediate batches can commit before a later child or entity fails. A session rollback does not undo those earlier commits. For a disposable development target, correct the problem and use `python -m hemonc_alchemy.bootstrap --rebuild`. The default bootstrap refuses existing HemOnc tables. Rebuild resets all generated HemOnc tables and recognized staging objects in the selected schema, even when `--table` restricts imported files; unrelated and vocabulary tables are retained. See [Loading data](../model/loading.md).

Use one writer process per DuckDB file. For separate reader processes, stop the writer and create read-only engines with `database.create_engine(register_claims=False, connect_args={"read_only": True})`.
