# OMOP integration

The OMOP bridge provides optional read-only queries between HemOnc source records and an OMOP vocabulary. Individual query helpers specify whether they use one database session or accept separate source and vocabulary sessions.

## The mental model

There are three identifiers in a typical mapping:

| Identifier | Meaning |
| --- | --- |
| HemOnc CUI | The source identity used by HemOnc tables, such as `condition_cui=614` |
| HemOnc OMOP `concept_id` | The surrogate ID for the corresponding row in the registered `HemOnc` vocabulary |
| Target OMOP `concept_id` | The concept in a target vocabulary such as SNOMED or RxNorm |

The bridge keeps all three distinct. A CUI is used as `concept_code` in the HemOnc OMOP vocabulary, but it is not an OMOP `concept_id`.

Mapping is one-to-many. `map_to_standard()` returns one object per active `Maps to` edge, with the relationship label and both concept references intact. It does not select the first target and it does not reinterpret treatment relationships such as `Has cytotox chemo Rx` as ordinary vocabulary mappings.

## Installation and configuration

Install the optional dependency when you need the integration package:

```bash
uv add "hemonc-alchemy[omop]"
```

The bridge lazily loads OMOP Alchemy's public CDM models and uses their validity semantics. The HemOnc package does not import the optional model tree during ordinary package imports. HemOnc-specific mapping joins remain local because OMOP Alchemy cannot know which HemOnc CUI or relationship policy a consumer intends.

The current devcontainer configuration puts both vocabularies in the same schema so the public OMOP models can be queried directly from the HemOnc session. This is configuration, not an invariant enforced by the integration; schema resolution will move to oa-configurator as that support lands:

```python
from hemonc_alchemy.integrations.omop import omop_available, map_to_standard

if omop_available(session):
    mappings = map_to_standard(session, [105], target_vocabulary="RxNorm")
```

If the configured OMOP tables or vocabulary are not present, the bridge returns an empty result rather than making HemOnc-only applications fail during startup.

## Common queries

```python
from hemonc_alchemy.integrations.omop import (
    condition_to_snomed,
    drug_to_rxnorm_ingredient,
    regimen_to_hemonc,
)

condition_rows = condition_to_snomed(session, [614])
drug_rows = drug_to_rxnorm_ingredient(session, [105])
regimen_rows = regimen_to_hemonc(session, [2204])
```

For the loaded development database, the first two examples resolve as follows:

```text
Classical Hodgkin lymphoma (CUI 614)
  → HemOnc concept_id 42542184
  → SNOMED code 118599009

Cisplatin (CUI 105)
  → HemOnc concept_id 35802958
  → RxNorm code 2555
```

## Diagnostics are part of the result

Use `coverage_report()` when a mapping is used as an analytical denominator. It reports requested, resolved, mapped, unmatched, and ambiguous CUIs and includes the advertised versions from `omop.vocabulary`. A missing mapping means “not present in this vocabulary release” unless the source and target data have been independently audited; it does not prove that the concept does not exist.

The `biomarker_qualifier_diagnostics()` helper is advisory. Molecularly qualified HemOnc conditions can map to an unqualified SNOMED disorder or fail to map. Keep the HemOnc condition CUI and qualifier fields when this distinction matters. `suspicious_condition_mappings()` surfaces condition edges to modifier/measurement concepts for vocabulary review; it does not automatically delete or rewrite them.

## Relationship taxonomy

OMOP contains useful HemOnc-native relationships in this deployment:

- `regimen_modalities()` reads `Has modality` links.
- `component_roles()` reads the directed component-role relationships and keeps their labels separate.
- `component_class_hierarchy()` reads direct `Is a` links to `Component Class` nodes.
- `main_class_ancestry()` combines source drug groups with the hierarchy to classify endocrine and growth-factor ancestry. See [Classify drug ancestry](../toolkit/treatment.md#classify-drug-ancestry) for querying, applying and inspecting the results.

These are curated HemOnc taxonomy edges, not a replacement for `public.indications`. Regulatory indication data in the HemOnc table is richer and has different semantics and coverage.

## Database boundary

The mapping and relationship query helpers perform same-database joins. If HemOnc and OMOP are in separate databases, query the source CUIs first and resolve them with a second OMOP session. `main_class_ancestry(source_session, omop_session=vocabulary_session)` handles this separation directly, combining the query results in Python. PostgreSQL being on the same server is not enough for an ordinary cross-database SQL join; other queries require an explicit application-level bridge, an FDW, or a materialized mapping subset.
