# Upgrading HemOnc Alchemy

## Source-only cleanup and regenerated schema

The source-only release removes the unapproved indication vocabulary, patient-fit APIs, and local condition mapping corrections. It also includes the source loader fixes and regenerated scalar fields described in the [draft release notes](../maintainers/source-only-release-notes.md). These are breaking API and schema changes.

### Replace proposal-dependent calls

The `toolkit.core.indication_vocabulary` package and `toolkit.analytics.treatment.indication_fit` module are removed. The treatment package no longer exports `fits`, `fit_regimens`, `PatientState`, `BiomarkerMeasurement`, `FitPolicy`, or their fit-result types. Use source-facing indication/catalogue APIs for source browsing; patient eligibility matching requires a separately approved implementation.

Condition mapping APIs now read the imported source fields and standardise through official OMOP vocabulary. `load_patches`, `load_overrides`, `apply_patches`, the condition-target generator and `regen-condition-targets` command are removed. `accepted_codes()` accepts the source mappings only, without an overrides argument. Existing mapping, family and diagnosis results may change where they previously depended on local corrections. For example, CUI `168651` no longer receives the archived Acromegaly mapping gap-fill `74107003` automatically.

### Use a matching fresh source database

The following fields now remain scalar values on their source tables. Their former collection-map tables and relationships are removed.

| Source table | Scalar fields |
| --- | --- |
| `refs` | `reference`, `study`, `biblio`, `doi` |
| `sigs` | `cyclesigs_note`, `inparens`, `seqrelwhat`, `timing` |
| `contexts` | `context_pretty` |
| `inclusions` | `reason_note` |
| `sig_branch_types` | `description` |

For example, read `sig.cyclesigs_note` directly rather than loading `cyclesigs_note_items`, and query `Refs.study` rather than joining `refs_StudyMap`. The dosing toolkit continues to return its notes as a tuple. Semicolons in a study name or note are preserved as text; genuine pipe-delimited collections retain their child maps.

An older database may start successfully but fail when an ORM query selects one of the new scalar columns. Upgrade the package and use an artifact rebuilt with the same generated model. Alternatively, import the source extract into a new, separately configured database/file. Retain the previous asset until validation is complete; creating tables on top of it is not a schema migration.

Source snapshot imports assign local row IDs. Use old numeric record links with their original dataset, and label a candidate explicitly when browsing it. Preserve the source/build manifest alongside the external database artifact. Python distributions contain the model and loader code, while the source and official OMOP vocabulary assets are distributed separately.

### Update downstream applications

Explorer must use the cleaned Alchemy package and matching source asset together. Its source-only approval views replace the proposed vocabulary/fit pages and structured requirement filters. Update exact package pins and lockfiles once the chosen cleaned release is available; the local verification environment is not a replacement for a published dependency.

## DuckDB-capable dependency family

The new dependency family supports configured PostgreSQL and file-backed DuckDB imports. Models now carry a logical `primary` schema role, which is a breaking change for callers creating raw SQLAlchemy engines. Use a configured engine or the default-schema helper below. Existing database rows are not automatically moved or rebuilt.

## Install a consistent dependency family

| Package | Supported family |
| --- | --- |
| oa-configurator | `>=2.1.0,<3` |
| orm-loader | `>=3.0.0,<4` |
| omop-alchemy, optional | `>=3.0.0,<4` |

Install `hemonc-alchemy[postgres]`, `hemonc-alchemy[duckdb]`, or combine the chosen backend with `omop`. Remove application constraints that still require oa-configurator 1.x, orm-loader 1.x/2.x, or omop-alchemy 1.x/2.x before resolving the new lockfile. Explorer supports read-only DuckDB source and vocabulary assets as well as configured PostgreSQL access.

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
