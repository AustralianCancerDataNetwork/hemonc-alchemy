# Installation

Install the package that matches the job you are doing. The base package contains the generated model, connection helpers, and toolkit APIs. PostgreSQL support is optional because the model itself does not require a particular driver.

## Use HemOnc from another project

```bash
uv add "hemonc-alchemy[postgres]"
```

With pip:

```bash
pip install "hemonc-alchemy[postgres]"
```

## Work on the repository

```bash
uv sync --extra dev
```

The `dev` extra adds model-generation tools, tests, linting, and documentation dependencies. It does not need to include Jupyter or plotting libraries.

## Run the notebooks

```bash
uv sync --extra exploration
```

The `exploration` extra adds the Python kernel, matplotlib, IPython, and the PostgreSQL driver used by `notebooks/`. For package development and notebooks together:

```bash
uv sync --extra dev --extra exploration
```

The repository devcontainers install the development, exploration, PostgreSQL, DuckDB, authoring, and OMOP extras together.

## Use DuckDB

```bash
uv add "hemonc-alchemy[duckdb]"
```

The extra installs the DuckDB engine and shared oa-configurator/orm-loader backend support. See [Local development](local-development.md) for the independent file-backed workflow and [Upgrading](upgrading.md) for existing applications.

## Use the OMOP bridge

`omop-alchemy` is intentionally not a runtime dependency. Install the optional extra only for code that resolves HemOnc identifiers against an OMOP vocabulary:

```bash
uv sync --extra omop
```

The bridge shares configuration and loading infrastructure with HemOnc Alchemy, but the two packages keep their models separate.

## What installation does not provide

Installation does not provide Docker, PostgreSQL, pgAdmin, a HemOnc source extract, or clinical data. Use the [development stack](local-development.md) for a disposable local database.
