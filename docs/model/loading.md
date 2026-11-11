# Loading data

Loading is an environment or maintainer operation. Analysis code should normally connect to an already imported database and use the model or toolkit.

## Load one entity

```python
from pathlib import Path

from hemonc_alchemy.model import Variants
from hemonc_alchemy.toolkit.loading import load_all

counts = load_all(session, Variants, Path("data/Tables"))
session.commit()
print(counts)
```

`load_all()` loads primary rows and their denormalized child tables. It resolves source filenames and headers, applies an explicit HemOnc conversion policy, and maps child rows back to accepted parents. Its return value remains a dictionary of counts; `load_entity()` returns the primary count and `load_denormalised()` returns child counts.

## Loader 3 compatibility

HemOnc uses `orm-loader` 3, `oa-configurator` 2.1, and optional `omop-alchemy` 3. Install the DuckDB driver with `uv sync --extra duckdb`; PostgreSQL remains available with `--extra postgres`. Both backends support the [configured devcontainer workflow](../getting-started/local-development.md). Use a configured engine or `create_default_hemonc_engine()` so the generated `primary` schema role is mapped before creating tables or loading rows.

Entity classes now provide `load_file(session, path, ...)`. `load_csv()` remains a deprecated compatibility alias. `register_enum_casts()` remains callable but is unnecessary: conversion is local to each load and does not modify an upstream global cast registry.

An ID-less CSV for a surrogate-key entity requires an **empty parent table**. PostgreSQL and DuckDB reserve IDs from the table's native sequence; subsequent ORM inserts continue from that sequence. SQLite uses the public loader ID allocator for these BIGINT columns. This snapshot path assumes a single writer. A second ID-less import raises before staging; use a fresh disposable target or a source with stable, explicit IDs. Incremental identity reconciliation is not implemented.

PostgreSQL reserves sequence values on an additional connection because later file batches are read while `COPY` is active on the loader connection. Its pool must allow that additional connection. Create and commit the schema before beginning the snapshot import.

Files supplying IDs use the upstream merge strategies. Callers supplying explicit IDs are responsible for synchronizing native sequences before later inserts that omit IDs. Child loading uses plain inserts and is not an idempotent reload operation.

For ID-less snapshots, the loader retains each parsed source occurrence's assigned ID until its child load completes. Rejected parent IDs are excluded. Thus two sig rows with the same scalar values can keep different study lists, and two exact duplicate occurrences can each retain their children. This association uses the assigned IDs, not the order returned by a database query.

When calling `load_entity()` and `load_denormalised()` separately, use the **same Session, unchanged source file, and matching CSV reading options**. A commit between stages is supported; a rollback discards the retained association. Supplied IDs and unambiguous scalar identities support independent child loads, but ambiguous fallback matches raise an error rather than silently omit children. A changed file or reading options also raises before child insertion. Custom readers must preserve the source record order and parsing rules used by child loading; splitting batches is supported.

Only `|` is automatically inferred and split as a collection delimiter. Semicolons remain part of names or prose: for example, `GEICAM/2003-11; CIBOMA/2004-01` is one study name with CUI `25246`. The updated dictionary overrides preserve reference names, study names, sig notes, and parenthetical expressions as scalar fields. Regenerate and rebuild the source database to adopt these schema changes; existing assets are not migrated by running the loader code.

## Conversion and rejection reports

The default HemOnc policy preserves case-insensitive enum values and the compiler's normalized-member fallback. Malformed nullable fields are logged and become NULL. Malformed required values reject their rows rather than introducing a sentinel. Rejected parents cannot contribute child rows, including when an accepted parent has the same natural key.

The policy treats `NULL`, `None`, `N/A`, `NaN`, `nan`, `null`, `NA`, and `n/a` as text null markers. Dates use the upstream declared formats (`yyyymmdd`, `dd-mon-yyyy`, and `yyyy-mm-dd`); unrecognized nullable date values become NULL. Source markers stored in string columns remain strings unless they are one of the configured null markers. Ambiguous date formats require an explicit handler.

```python
from orm_loader.loaders import LoadReport

report = LoadReport()
counts = load_all(session, Variants, Path("data/Tables"), report=report, resolved=database)
print(report.rows_read, report.rows_rejected, report.accounted)
print(report.rejects_path)
```

Here `database` is the resolved target from `get_hemonc_context()`. Pass it through as `resolved=`; DuckDB requires it to classify foreign-key enforcement. The report describes the primary file, while the returned dictionary includes child counts. `load_entity()` keeps rejection CSVs under `data_dir/rejects` even when it normalizes a source through a temporary file. Treat these reports as source data when storing or sharing them.

To raise on malformed values, including nullable ones, pass an explicit policy. `load_all()` passes it to both primary and child conversion:

```python
from dataclasses import replace
from orm_loader.conversion import ErrorPolicy
from hemonc_alchemy.model.ingestion import conversion_policy

strict = replace(conversion_policy(), errors=ErrorPolicy(on_error="raise"))
counts = load_all(session, Variants, Path("data/Tables"), policy=strict, resolved=database)
```

## Transaction boundaries

The upstream file loader commits primary merges internally and can commit intermediate batches. A later child-load failure does not roll back those committed parents; `session.rollback()` only rolls back work still in the current transaction. Use a disposable target for snapshot imports and rebuild it after a partial failure. Complete schema rebuilding is a separate bootstrap operation.

## Bootstrap the development database

```bash
uv run python -m hemonc_alchemy.bootstrap --data-dir data/Tables
```

Bootstrap resolves the active `hemonc_db` with `get_hemonc_context()`, uses `create_hemonc_engine()`, and passes the resolved target and `primary` staging role through to `load_all()`. It ignores the legacy `DATABASE_URL` variable. `.devcontainer/bootstrap.py` remains a thin wrapper for the same entry point.

The default operation creates all generated tables and loads the source files present. It refuses a target already containing any HemOnc table. Repeat `--table`, for example `--table units --table hemonc_classes`, to select source tables explicitly. Unknown, missing selected, ambiguous, or entirely absent source files fail before opening the engine or rebuilding anything.

For an existing **disposable target**, explicitly pass `--rebuild`. This drops generated HemOnc tables and recognized `_staging_<hemonc_table>` objects only in the configured HemOnc schema, then recreates the metadata before importing. It retains unrelated tables, unrelated staging objects, and OMOP vocabulary tables. It does not drop the schema or use cascading drops. External foreign keys referencing HemOnc can therefore block a rebuild. Selecting `--table` limits imported files, not the set of tables reset by `--rebuild`.

Rebuilds destroy the selected target's HemOnc data. Use only a disposable development target and stop other DuckDB processes using the file first. Each entity can commit before later entities or children fail; retry a partial snapshot with an explicit rebuild after fixing the failure. Programmatic callers can use `bootstrap_database(resolved, data_dir, rebuild=False, table_names=None)` from `hemonc_alchemy.bootstrap` and receive per-entity count dictionaries.

## Preserve source-shaped values

The loader does not force uncertain source values into invented types. A field may remain nullable, string-valued, or contain a source marker such as `Uncertain date`. Convert it only at the analysis boundary where your application can state what happens to values that do not parse.
