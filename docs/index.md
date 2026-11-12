# HemOnc Alchemy

HemOnc Alchemy provides Python tools for querying HemOnc.org treatment data. It includes SQLAlchemy models, condition and component searches, regimen selection, dosing schedules, and optional OMOP vocabulary queries.

Use a local DuckDB file or a PostgreSQL database containing the HemOnc tables. Install the driver for your chosen backend and configure the database before running queries. The package includes the model and loader; HemOnc source data and OMOP vocabulary data are supplied separately.

## Get started

1. [Install](getting-started/installation.md) with the DuckDB or PostgreSQL extra.
2. [Configure your database](getting-started/configuration.md).
3. Follow the [quickstart](getting-started/quickstart.md) to find treatment variants for a condition.

To create and load a development database, follow [Local development](getting-started/local-development.md).

## Find the right guide

| Task | Guide |
| --- | --- |
| Understand tables, identifiers and relationships | [The HemOnc model](model/index.md) |
| Find conditions, components and linked records | [Core queries](toolkit/core.md) |
| Select or classify treatment variants | [Treatment analytics](toolkit/treatment.md) |
| Read dosing days or build a treatment timeline | [Schedules and administration](toolkit/scheduling.md) |
| Resolve HemOnc identifiers through OMOP vocabulary | [OMOP integration](integrations/omop.md) |

When counting results, check what each row represents. For example, one regimen can have several variants, each with several dosing instructions. A study name can also occur in several condition-specific rows. See [Entities and generated models](model/entities.md) for identifiers and [Relationships](model/relationships.md) for study and version-selection rules.

## Project status

HemOnc Alchemy is pre-1.0. APIs and generated schemas may change without a compatibility layer or a migration path.
