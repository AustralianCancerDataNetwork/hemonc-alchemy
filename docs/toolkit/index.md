# Toolkit

The toolkit provides searches, treatment selection and schedule calculations over the imported HemOnc tables. Query functions accept a SQLAlchemy session; scheduling functions work with the selected variants and their sigs.

## Choose an operation

| Task | Functions and examples |
| --- | --- |
| Resolve condition names or search components | [Core queries](core.md) |
| Follow links between sigs, studies, conditions and variants | [Traversal helpers](../model/relationships.md#traversal-helpers) |
| Select variants by condition, component or category | [Treatment selection](treatment.md#select-variants) |
| Classify radiation, systemic or drug-ancestry groups | [Treatment classification](treatment.md) |
| Read dosing days, build administration frames or calculate timelines | [Scheduling](scheduling.md) |

## Run a query or build a statement

Execution helpers run a query using your session and return results:

```python
from hemonc_alchemy.toolkit.core.components import search_components

hits = search_components(session, "cisplatin")
```

Statement builders return a SQLAlchemy statement that you can extend before execution:

```python
from hemonc_alchemy.toolkit.core.components import component_search_statement

statement = component_search_statement("cisplatin").limit(20)
rows = session.execute(statement).mappings().all()
```

Return types vary by operation: searches can return result records, selection helpers return ORM entities, and schedule projections return pandas DataFrames. Each guide shows how to read its results.

Keep ORM entities attached to their session while accessing related rows. See [Configuration](../getting-started/configuration.md#open-a-session) for creating an engine and session.
