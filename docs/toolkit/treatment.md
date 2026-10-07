# Treatment analytics

Treatment analytics are where HemOnc rows acquire reusable treatment meaning. The key discipline is to keep the policy explicit: HemOnc supplies source labels and relationships, while the selection spec or classification function states how your application interprets them.

## Classify a variant

```python
from hemonc_alchemy.toolkit.analytics.treatment.classification import (
    is_concurrent_chemort,
    is_rt_only,
)

if is_concurrent_chemort(variant):
    print("radiation and systemic sigs are both confidently classified")
elif is_rt_only(variant):
    print("all sigs are confidently classified as radiation")
```

An unknown or NULL `class_field` is unknown. It does not count as systemic treatment and prevents a confident radiation-only or concurrent-chemoradiotherapy classification. Treating “unclassified” as “not present” would turn missing source information into a clinical conclusion.

## Classify drug ancestry

Use `is_endocrine_regimen()` to identify variants whose drugs are all endocrine therapies, and `is_supportive_regimen()` to identify variants whose drugs are all growth-factor therapies. Here, “supportive” specifically means growth-factor ancestry. The same classifications are available for cycle blocks through `is_endocrine_block()` and `is_supportive_block()`.

### Query and apply the ancestry index

Install the [OMOP integration](../integrations/omop.md#installation-and-configuration) and configure the vocabulary connection's search path to expose its OMOP tables. Query an index from the source drug records and vocabulary relationships, then pass it to the classifiers or scheduling helpers:

```python
from hemonc_alchemy.integrations.omop import main_class_ancestry
from hemonc_alchemy.toolkit.analytics.treatment.classification import (
    is_endocrine_regimen,
    is_supportive_regimen,
)
from hemonc_alchemy.toolkit.analytics.treatment.scheduling import cycle_block_templates

index = main_class_ancestry(source_session, omop_session=vocabulary_session)
endocrine = is_endocrine_regimen(variant, ancestry=index)
supportive = is_supportive_regimen(variant, ancestry=index)
blocks = cycle_block_templates(variant, ancestry=index)
```

Omit `omop_session` when the source session can also access the vocabulary tables. Classifiers can infer the session from attached source objects; supplying an index also supports detached objects and separate databases.

### Interpret the classification

The predicates and `CycleTemplate.endocrine_regimen` / `supportive_regimen` flags have three possible results:

| Result | Meaning |
| --- | --- |
| `True` | Every identified drug belongs to a fully resolved group with the requested ancestry. |
| `False` | A known group excludes the requested ancestry, or there are no drug entries to classify. |
| `None` | The available evidence cannot establish the classification, for example because a group is unresolved or the vocabulary is unavailable. |

Drug ancestry uses active HemOnc `Is a` relationships beneath Endocrine therapeutic (`44970`) and Growth factor (`20221`). These are HemOnc concept codes. Classification applies to whole `Drugs.main_class` groups: every component in the group must have a usable Component Class edge. The polyhierarchical Steroid target (`45523`) is excluded. An incomplete group is unresolved; disagreement between fully resolved components is inconsistent.

A drug with NULL `main_class`, or a canonical drug instruction without a matching drug record, supplies unknown evidence. A known exclusion still yields `False`; otherwise unknown evidence yields `None`. Radiation and generic non-canonical component instructions without drug records are outside the drug ancestry scope.

### Investigate an unresolved result

Check `index.unavailable_reason` for a vocabulary availability problem. For individual groups, `index.resolutions` exposes the status, all component CUIs and the CUIs lacking usable classification edges:

```python
resolution = index.resolutions.get(drug.main_class)
if resolution is not None:
    print(resolution.status.value)
    print(resolution.component_cuis)
    print(resolution.unresolved_cuis)
```

The index is cached per source/vocabulary engine pair. After reloading either dataset, call `main_class_ancestry.cache_clear()` or restart the process so subsequent queries use the refreshed data.

## Query standalone radiation

```python
from hemonc_alchemy.toolkit.analytics.treatment.filters import (
    find_standalone_radiation_sigs,
)

sigs = find_standalone_radiation_sigs(session, [condition_cui])
```

“Standalone” is a precise query policy: a radiation-classified sig with regimen `Radiation therapy`, no `variant_cui`, and a normalized study link to one of the requested condition CUIs. It does not prove that the entire study contains no systemic treatment.

## Select variants

Describe the selection as a plain spec, then execute it:

```python
from hemonc_alchemy.toolkit.analytics.treatment.selection import (
    ComponentRequirement,
    TreatmentSelectionSpec,
    select_variants,
)

spec = TreatmentSelectionSpec.for_conditions(
    [condition_cui],
    component_requirements=(ComponentRequirement.from_terms("cisplatin"),),
    version_policy="latest",
)
variants = select_variants(session, spec)
```

Component terms within one requirement are alternatives; separate requirements are combined. Category requirements work the same way, but require an application-supplied mapping from a source field to the category names used by the spec:

```python
from hemonc_alchemy.toolkit.analytics.treatment.selection import CategoryRequirement

spec = TreatmentSelectionSpec.for_conditions(
    [condition_cui],
    category_requirements=(CategoryRequirement("cytotoxic", 1),),
)
variants = select_variants(
    session,
    spec,
    category_mapping={"main_class": {"Platinum agent": "cytotoxic"}},
)
```

The mapping is policy, not a hidden property of the model. Read source values before building a production mapping and decide how unmapped classes should be handled.

`build_variant_query_artifacts()` exposes the component projection, category projection, matching variant identities, and final statement. Use it when a selection needs auditability or returns an unexpected volume.
