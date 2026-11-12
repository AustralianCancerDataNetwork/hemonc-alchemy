# Quickstart

Find treatment variants by looking up a condition's HemOnc CUI and passing it to a selection query.

This example works with a configured DuckDB or PostgreSQL database containing the HemOnc tables. See [Configuration](configuration.md) to set up the connection.

```python
from sqlalchemy.orm import Session

from hemonc_alchemy import create_hemonc_engine, get_hemonc_context
from hemonc_alchemy.toolkit.core.conditions import condition_cuis_by_names
from hemonc_alchemy.toolkit.analytics.treatment.selection import (
    TreatmentSelectionSpec,
    select_variants,
)

_, database = get_hemonc_context()
engine = create_hemonc_engine(database)

with Session(engine) as session:
    condition_cuis = condition_cuis_by_names(session, "Acute myeloid leukemia")
    if not condition_cuis:
        raise LookupError("Condition was not found")

    spec = TreatmentSelectionSpec.for_conditions(
        condition_cuis,
        version_policy="latest",
    )
    variants = select_variants(session, spec)

    for variant in variants[:5]:
        print(variant.variant_cui, variant.version, variant.regimen)
```

`version_policy="latest"` selects the highest imported `(version, id)` per `variant_cui` before applying condition filters. Use `version_policy="all"` to query imported versions together. See [Variant versions and sigs](../model/relationships.md#variant-versions-and-sigs) for how this differs from the source-defined current version.

## Inspect a selected variant

```python
from hemonc_alchemy.toolkit.analytics.treatment.bundles import VariantBundle

with Session(engine) as session:
    variants = select_variants(session, spec)
    if variants:
        bundle = VariantBundle.from_variant(variants[0])
        for sig in bundle.sigs:
            print(sig.component, sig.doseminnum, sig.doseunit, sig.alldays)
```

Keep the session open while reading related records. Sigs link through `variant_cui` without a version, so these instructions are shared across imported versions with that CUI.

## Inspect or extend the SQL

Use a statement builder to add filters or limits before running a query:

```python
from hemonc_alchemy.toolkit.core.components import component_search_statement

statement = component_search_statement("cisplatin").limit(20)
with Session(engine) as session:
    rows = session.execute(statement).mappings().all()
```

For treatment selection, `build_variant_query_artifacts()` exposes the intermediate projections as well as the final statement. This is useful when a selection returns an unexpected number of variants.
