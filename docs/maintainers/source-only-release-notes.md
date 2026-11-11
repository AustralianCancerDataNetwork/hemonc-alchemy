# Source-only release notes — draft

This release removes the unapproved indication-vocabulary proposal from the runtime package and includes the completed source-loader and generated-schema corrections. The scope is source loading, source catalogue access, official OMOP integration, and ordinary treatment/dosing/scheduling functionality.

The local stabilization build uses `0.5.0rc1` as a verification label through a build-time version override. No tag or published release is created by that build. The final version remains a maintainer decision. The repository's automatic `breaking` label selects a major bump; a planned pre-1.0 minor release needs an explicitly chosen version rather than assuming that label produces it.

## Removed APIs and bundled data

- The `toolkit.core.indication_vocabulary` package, including its loader, identity, hierarchy, lint and CLI APIs, and all bundled vocabulary/evidence tables.
- The proposed `toolkit.analytics.treatment.indication_fit` implementation and associated treatment exports, including `fits`, `fit_regimens`, `PatientState`, `BiomarkerMeasurement` and `FitPolicy`.
- Bundled condition mapping patches/overrides and their runtime readers/application hooks. Condition targets now use source mappings and official OMOP standardisation.
- The condition-target patch generator and `regen-condition-targets` command, which formerly wrote corrections into the package.

The proposal material is preserved outside the Alchemy project under the workspace's `_design/vocab_proposal` folder for historical review. It is not a runtime provider or an approved specification. Wheel and source-distribution checks prevent it from being shipped again.

## Source loading and schema corrections

ID-less snapshot loading retains each source occurrence's assigned parent ID through child loading. Records with equal scalar values and differing study lists, and complete duplicate records, retain their own child associations. Rejected parents contribute no child rows. Changed source files/CSV reading options and ambiguous fallback parent matches raise explicit errors.

Automatic collection inference uses the loader's supported pipe delimiter. A semicolon in a label or prose field no longer changes the storage shape of an entire column. The regenerated model contains **22 source tables and 64 collection maps, totaling 86 tables**. Eleven former collection fields are now scalars; see the [upgrade guide](../getting-started/upgrading.md#use-a-matching-fresh-source-database) for the full list.

Existing source database files need a fresh import into the new schema. The package does not automatically migrate an old asset. Dosing still exposes notes as a tuple, with the underlying note now read from its scalar field. Explicit source CUIs retain their meaning; generated row IDs remain local to a dataset.

## Consumer migration

Upgrade the Alchemy package and its source database artifact together. Review downstream imports for removed APIs and collection-map classes. Ordinary catalogue, source indication, condition mapping, dosing and scheduling APIs remain available. Source-only Explorer needs this package/model family; its existing `0.4.0` pin must change after the cleaned release is published.

Partial source dates and unresolved source identifiers retain the existing conversion behavior. Withdrawal lifecycle interpretation, durable approval identity and a future approved indication vocabulary are separate design work. Their prototype assumptions are not reinstated by this release.

## Validation for the release candidate

Validate a built wheel outside the checkout, including a core install with no optional backends and an install with DuckDB/OMOP support. Run source, DuckDB and PostgreSQL regression checks; compare complete source content; and smoke-test Explorer's source approvals, condition/regimen pages, variant details, dosing and timelines with matching external assets. The installed-wheel check expects the current 86-table schema.

The local stabilization receipt records artifact hashes, exact package versions, source fingerprints, tests and real-asset page results. Keep that receipt and the source-build manifest with the candidate assets. Publishing, tags, package uploads, repository commits and downstream pin updates are separate authorized actions.
