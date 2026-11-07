# Local development stack

Choose the DuckDB path for a local file or the PostgreSQL path for the shared development stack. Neither starts an import automatically. Both install the frozen project environment and seed configuration only when the selected config file does not exist.

## DuckDB: no PostgreSQL service required

From the repository root:

```bash
docker compose -f .devcontainer/compose.duckdb.yaml up -d --build
```

First startup installs the frozen development dependencies before seeding configuration. Wait until the service logs report that the stack config was installed or retained. Follow them with `docker compose -f .devcontainer/compose.duckdb.yaml logs -f python-hemonc-alchemy-duckdb`; press Ctrl-C after setup completes to stop following logs. The service keeps running.

Place licensed source CSVs under `data/Tables`, then import:

```bash
docker compose -f .devcontainer/compose.duckdb.yaml exec \
  python-hemonc-alchemy-duckdb uv run python -m hemonc_alchemy.bootstrap
```

This Compose file runs only a Python service: it needs no PostgreSQL service, shared network, or database port. In VS Code, choose the **HemOnc Alchemy — DuckDB** development configuration under `.devcontainer/duckdb/devcontainer.json`. The interpreter is `/opt/venv/bin/python`.

The seed is `.devcontainer/config.duckdb.toml`. Its active copy is `/home/vscode/.config/omop/hemonc-duckdb.toml`; its database is `/workspace/hemonc-alchemy/data/hemonc-alchemy.duckdb`. The repository mount persists the database on the host at `data/hemonc-alchemy.duckdb`. Keep this directory writable by the container user. HemOnc uses schema `hemonc`; optional vocabulary tables use `omop`, with CDM tables assigned `cdm` in the same file. Bootstrap imports HemOnc only; it does not supply an OMOP vocabulary.

Use one process to write a DuckDB file. Stop other processes using the file before a bootstrap or rebuild; multiple writer processes are unsupported. Multiple processes can read with `database.create_engine(register_claims=False, connect_args={"read_only": True})` when no writer is running. Sessions within one process can share an engine. Do not commit the database or licensed extracts.

Stop this independent stack with:

```bash
docker compose -f .devcontainer/compose.duckdb.yaml down
```

## PostgreSQL: existing shared development stack

The default `.devcontainer/devcontainer.json` starts PostgreSQL 18 with pgvector, the Python service, and pgAdmin. Create the network shared with SCOOP before starting:

```bash
docker network inspect hemonc-alchemy_default >/dev/null 2>&1 || \
  docker network create hemonc-alchemy_default
docker compose -f .devcontainer/compose.yaml up -d --build
```

Wait for initial Python service setup and config seeding to finish. Open the repository in VS Code's default Dev Container, or import from the Python service:

```bash
docker compose -f .devcontainer/compose.yaml exec \
  python-hemonc-alchemy uv run python -m hemonc_alchemy.bootstrap
```

The seed `.devcontainer/config.toml` targets the Compose `postgres` service. HemOnc uses `public`, CDM uses `cdm`, and vocabulary uses `omop`. A separate test database keeps PostgreSQL tests away from the loaded development database. See [Configuration](configuration.md#update-an-existing-copied-config) before using an older copied seed.

pgAdmin is available at [http://localhost:5050](http://localhost:5050). Set login values in `.devcontainer/.env` before using a shared machine. Connect to host `postgres`, port `5432`, database `hemonc_alchemy`, user `hemonc`. Inside pgAdmin, `localhost` refers to its own container.

## Import and rebuild behavior

Bootstrap selects the active oa-configurator `hemonc_db` target. It creates all generated HemOnc tables and imports the source files it finds. `--data-dir` selects another extract directory; repeat `--table` to select specific source tables. Missing or ambiguous selected files fail before database changes.

An existing HemOnc table makes the default import fail. For a **disposable target**, add `--rebuild` to reset all HemOnc tables and recognized HemOnc staging objects in the selected schema. Unrelated and vocabulary tables are retained. This is not an incremental reload. A failed import may leave committed parent rows; fix the source and explicitly rebuild the disposable target. See [Loading data](../model/loading.md).

Existing active config files are retained on restart and rebuild. Set `OA_CONFIG_PATH` before launching Python to choose a different file; `OA_CONFIG_SEED` selects a create-time seed. Switching seeds does not overwrite an existing file.

## Notebooks and tests

Both development paths install the development, authoring, exploration, PostgreSQL, DuckDB, and OMOP extras. Open notebooks with `/opt/venv/bin/python`. `_setup.open_session()` reports whether it connected to the configured database or used the small demo dataset.

Run these commands inside the chosen Python service:

```bash
uv run pytest
uv run pytest -m duckdb -o addopts=''
```

Run PostgreSQL tests in the PostgreSQL path with `uv run pytest -m postgres -o addopts=''`. The default pytest selection excludes database-dialect tests, so run the selected backend suite explicitly.
