# Regenerating the model

The generated model is a build artifact of the HemOnc data dictionary. Regeneration is therefore a schema change to review, not an ordinary edit to Python files.

## Workflow

Install the development tools, then run:

```bash
uv sync --extra dev
hemonc-alchemy validate
hemonc-alchemy diff
hemonc-alchemy regen --data-dir path/to/extract
```

Review the generated diff before accepting it. If a source table has intentionally disappeared, use the command's explicit acceptance flag rather than allowing source loss to pass silently.

Run the checks before committing:

```bash
pytest
ruff check hemonc_alchemy tests
lint-imports
```

## Generated versus hand-written code

Do not hand-edit `model/entities.py`, `model/enums.py`, or `schema/registry.json`. Change the source data dictionary or compiler behavior, regenerate, and review the output. Hand-written relationships belong in `model/relationships.py`; reusable query and interpretation code belongs in the toolkit.

## Regenerating classification data

`toolkit/analytics/treatment/classification/generated.py` is also generated, not hand-written: `ENDOCRINE_MAIN_CLASSES` and `SUPPORTIVE_MAIN_CLASSES` are `Drugs.main_class` values resolved against the `Is a` hierarchy in the HemOnc extract's own `omop.RData` OMOP staging tables (see `compiler/classification_generation.py` for the algorithm). This needs no database and no `omop_alchemy` import -- `concept_stage`/`concept_relationship_stage` are read directly, the same way `entities.py` is generated from the data dictionary -- so it runs as an ordinary `hemonc-alchemy` subcommand:

```bash
uv sync --extra dev --extra author
hemonc-alchemy regen-classification --data-dir path/to/extract
```

Review the diff before committing. Re-run whenever HemOnc's extract or component-class hierarchy changes in a way that could move a `main_class` value's ancestry -- the generated module's own docstring records which `main_class` values had no resolvable ancestry or disagreed internally as of the last run, so a re-run's diff is easy to sanity-check against it.
