# Local development stack

The repository's `.devcontainer` is a disposable environment for exploring the model, running notebooks, and testing loaders. It is not a production deployment and its bootstrap process recreates the database.

## What runs

- PostgreSQL 18 with pgvector, containing the HemOnc database and the optional `omop` schema.
- A Python development container with the repository mounted at `/workspace/hemonc-alchemy`.
- pgAdmin for inspecting the database through a browser.

## Start the stack

From the repository root:

```bash
docker network inspect hemonc-alchemy_default >/dev/null 2>&1 || \
  docker network create hemonc-alchemy_default
docker compose -f .devcontainer/compose.yaml up -d
```

The network is shared with SCOOP and must exist before Compose starts.

Open the repository in VS Code's Dev Container. The project interpreter inside the Python service is `/opt/venv/bin/python`; the notebook kernel should use that environment.

## Inspect the database with pgAdmin

Open [http://localhost:5050](http://localhost:5050). The default development login is defined by `.devcontainer/.env`; set your own values before using the stack on a shared machine.

Inside pgAdmin, connect to the Compose service rather than the host:

```text
Host:     postgres
Port:     5432
Database: hemonc_alchemy
User:     hemonc
```

`postgres` is resolvable from the Compose network. `localhost` would refer to the pgAdmin container itself.

## Load an extract

Place source files under `data/Tables`, then run the bootstrap from the Python service:

```bash
docker compose -f .devcontainer/compose.yaml exec \
  python-hemonc-alchemy uv run python .devcontainer/bootstrap.py
```

Bootstrap drops and recreates the target schema before loading. Use it only with the disposable development database; it will destroy data already in that schema. For a controlled application load, use [Loading data](../model/loading.md).

## Run notebooks and tests

The devcontainer installs the exploration and development extras. Open a notebook from `notebooks/` with the project interpreter, or execute it from the Python service with Jupyter. The notebooks use `_setup.open_session()` and will report whether they connected to `hemonc_db` or fell back to their small demo dataset.

Run the package checks with:

```bash
docker compose -f .devcontainer/compose.yaml exec \
  python-hemonc-alchemy uv run pytest
```

The Compose configuration also defines a separate test database so PostgreSQL tests do not write to the loaded development database.
