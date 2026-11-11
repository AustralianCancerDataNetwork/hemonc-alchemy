# Backend release validation

These maintainer tools compare one complete generated-model extract on disposable PostgreSQL and DuckDB targets. They are not part of the installed runtime API. Run them from the repository root after `uv sync --frozen --all-extras`.

## Reproduce a full comparison

1. Select an authorized local extract. All 22 currently loadable entities must have source files. Auxiliary and beta CSVs outside the generated loader contract are listed as unmodeled inputs. The manifest hashes every selected source file; it does not assume an upstream release date from a directory name.
2. Export an authorized vocabulary snapshot from a configured source database. This selects vocabulary tables only, in one read-only repeatable-read transaction: HemOnc concepts, outgoing `Is a` and `Maps to` edges and their targets, plus vocabulary metadata. The resulting file contains vocabulary records and is private, with mode 600.

   ```bash
   OA_CONFIG_PATH=/path/to/source-config.toml uv run --frozen python -m validation.vocabulary \
     --schema omop --output /tmp/hemonc-vocabulary.json.gz
   ```

3. Import both targets. Each output directory must be new. PostgreSQL requires `test_hemonc_db` on a `test_only` connection and creates an isolated schema which is removed on exit. Vocabulary tables use that same isolated schema. DuckDB creates a new file with a named schema inside its private output directory.

   ```bash
   uv run --frozen python -m validation.run_backend --backend duckdb \
     --data-dir data/Tables --output-dir /tmp/hemonc-duckdb-check \
     --vocabulary-snapshot /tmp/hemonc-vocabulary.json.gz
   OA_CONFIG_PATH=/path/to/test-config.toml uv run --frozen python -m validation.run_backend \
     --backend postgresql --data-dir data/Tables --output-dir /tmp/hemonc-postgres-check \
     --vocabulary-snapshot /tmp/hemonc-vocabulary.json.gz
   ```

4. Compare the aggregate receipts. A failed or incomplete run, missing source reports/tables/queries, unaccounted rows, orphan children, or different data fails the release gate.

   ```bash
   uv run --frozen python -m validation.compare \
     /tmp/hemonc-postgres-check/report.json /tmp/hemonc-duckdb-check/report.json \
     --output /tmp/hemonc-comparison.json
   ```

Only `report.json` and the comparison summary are intended for sharing. They contain source hashes, package versions, aggregate counts, null/conversion profiles, semantic hashes and timings. The private output directories also contain the database, licensed rejection files and detailed failure logs; do not copy those into Git. `validation/private/` is ignored for users choosing an in-repository private working directory.

## What equality means

All 86 current generated tables are compared as multisets, including duplicates and per-column NULL counts. Generated parent IDs are replaced with their complete scalar row semantics before hashing; child foreign keys are replaced with the corresponding parent's semantic hash. Different sequence allocation or SQL row order therefore does not create a false difference. A child attached to a different semantic parent does change the fingerprint. Missing parents fail independently of hash equality.

Per-entity loader reports include accepted/staged, rejected and deduplicated rows, returned child counts, and conversion diagnostics. Identity values normalized to NULL are distinguished from invalid child tokens. Representative queries compare complete regimen and indication catalogues, condition families, and known HemOnc/SNOMED/RxNorm mappings. They must return rows. This vocabulary slice is sufficient for these checks; it is not a full-ontology validation.

`--table` permits focused troubleshooting, but the release comparator rejects partial-extract receipts. A run without `--vocabulary-snapshot` executes only source catalogue checks and cannot pass the full release gate.

## Recorded local result

[7 November 2026 receipts](results/20261107/comparison.json) compare 22 source entities, all 97 tables and **2,111,833 rows** with zero differences or orphan children. The same private vocabulary snapshot supplied 14,144 concepts, 72,109 relationships and 54 vocabulary metadata rows to both targets. All six representative query fingerprints agree.

Timings are single-run local baselines under uncontrolled host load. The receipts separate per-entity loading, query execution and total validation time. Total time also includes table fingerprinting and vocabulary copying. No performance improvement is inferred.

[Downstream candidate checks](results/20261107/downstream-candidate.json) use a locally built `1.0.0` wheel, not a published release. Ten Explorer PostgreSQL HTTP checks pass with server-enforced read-only connections. Crucible's existing lifecycle creates all 97 tables twice without errors and passes `omop-config verify` in a fresh disposable database, which is removed afterward. Explorer's unchanged locked baseline and candidate both have the same seven HTML assertion failures (49 passed, 7 failed, 3 browser skips); no new failures were introduced by the candidate. Exact downstream registry pins and lockfiles remain gated on package publication.

A temporary snapshot of the current Explorer working tree also passes **63 tests**, with four browser skips, against the installed candidate. Only schema-aware test engine construction is applied to that snapshot; the original uncommitted application/UI work is untouched.

## Installed-wheel checks

Build the wheel, install it into separate clean environments with no extras and with `duckdb,omop`, then run `wheel_smoke.py` from outside the checkout. The core environment must have neither optional package installed. Both environments create all 86 current tables (22 source tables and 64 collection maps) and verify snapshot import, explicit rebuild, and parent-child linkage. CI runs this matrix independently of the source-tree test jobs. The dated 7 November receipts above describe the earlier 97-table schema.

## Full-extract PostgreSQL regression tests

The live-data tests do not use the active HemOnc database. Set `HEMONC_IMPORTED_TEST_DB` to a configured database alias containing a fresh complete source import and the official OMOP test slice in the same disposable schema, alongside the ordinary `test_hemonc_db` configuration used for disposable synthetic tests. The imported alias must resolve to a `test_only=true` PostgreSQL connection. Test reads are server-enforced read-only, and an explicitly selected incompatible schema fails rather than silently skipping.

```bash
OA_CONFIG_PATH=/path/to/test-config.toml HEMONC_IMPORTED_TEST_DB=imported_test_dataset \
  uv run --frozen pytest -m postgres -o addopts=
```

Without that explicit alias the full-extract tests skip; synthetic PostgreSQL tests continue to use their disposable schemas. Provision and clean up the imported schema through the existing isolated test-database lifecycle.
