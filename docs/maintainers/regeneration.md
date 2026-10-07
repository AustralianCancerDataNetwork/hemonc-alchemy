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
