# Installation

The package contains the SQLAlchemy model, connection helpers and toolkit. Choose an extra for the database you want to query.

## Use HemOnc from another project

| Backend | uv | pip |
| --- | --- | --- |
| DuckDB file | `uv add "hemonc-alchemy[duckdb]"` | `pip install "hemonc-alchemy[duckdb]"` |
| PostgreSQL server | `uv add "hemonc-alchemy[postgres]"` | `pip install "hemonc-alchemy[postgres]"` |

Then [configure the database](configuration.md) and run the [quickstart](quickstart.md).

## Work on the repository

```bash
uv sync --extra dev
```

Run this command from the repository root. The `dev` extra adds model-generation tools, tests, linting and documentation dependencies.

## Run the notebooks

```bash
uv sync --extra exploration
```

The `exploration` extra adds the Python kernel, matplotlib, IPython, and the PostgreSQL driver used by `notebooks/`. For package development and notebooks together:

```bash
uv sync --extra dev --extra exploration
```

The repository devcontainers install the development, exploration, PostgreSQL, DuckDB, authoring, and OMOP extras together.

## Use the OMOP bridge

Add `omop` when resolving HemOnc identifiers against an OMOP vocabulary. For example, with DuckDB:

```bash
uv add "hemonc-alchemy[duckdb,omop]"
```

When working in this repository, use `uv sync --extra dev --extra omop`. See [OMOP integration](../integrations/omop.md) for vocabulary configuration and query examples.

## What installation does not provide

Supply a populated HemOnc database or a source extract to import. OMOP queries also need a loaded vocabulary. The [local development guide](local-development.md) covers creating a DuckDB database or running the PostgreSQL Compose stack.
