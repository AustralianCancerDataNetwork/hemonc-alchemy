# Command-line reference

The `hemonc-alchemy` CLI is primarily a maintainer tool. End users normally install the package, configure a database, and query it through Python.

```bash
hemonc-alchemy --help
```

## `validate`

Check that the generated model and ORM-loader configuration are internally consistent:

```bash
hemonc-alchemy validate
```

## `audit`

Inspect a source directory for duplicate keys and enum risks before loading:

```bash
hemonc-alchemy audit --data-dir path/to/extract
```

## `diff`

Show schema-registry changes against the current Git revision:

```bash
hemonc-alchemy diff
```

## `regen`

Regenerate the model artifacts from a HemOnc data directory:

```bash
hemonc-alchemy regen --data-dir path/to/extract
```

Regeneration validates the result and reports schema changes for review. A missing source file for an existing generated table requires the explicit `--accept-source-loss` option. Use `--force` only after reviewing the reported changes.

## `lint-indications`

List indication values in a loaded database that the toolkit cannot parse, with occurrence counts, plus any normalizer invariant failures:

```bash
hemonc-alchemy lint-indications
hemonc-alchemy lint-indications --strict
```

The command reads the configured `hemonc_db` target. To use another database, pass `--database-url` or set `HEMONC_INDICATIONS_DATABASE_URL`. It exits non-zero when an invariant fails; `--strict` also exits non-zero when any value is unparsed.

`lint-biomarkers` is an alias for the same command.
