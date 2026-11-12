# Getting started

You need the Python package and a populated HemOnc database. Choose the backend that suits your environment:

| Backend | Use it when | Install |
| --- | --- | --- |
| DuckDB | You want to query a local database file without a database server. | `hemonc-alchemy[duckdb]` |
| PostgreSQL | You have a PostgreSQL database or need shared server access. | `hemonc-alchemy[postgres]` |

1. [Install the package](installation.md) with your backend extra.
2. [Configure a database](configuration.md) containing the HemOnc tables.
3. Run the [quickstart](quickstart.md) to find treatment variants for a condition.

If you need to create a database from a source extract, use the [local development guide](local-development.md) for DuckDB or PostgreSQL, then follow [Loading data](../model/loading.md).

The [model guide](../model/index.md) explains what each row represents and how identifiers and relationships work. Read it before combining tables or counting records.
