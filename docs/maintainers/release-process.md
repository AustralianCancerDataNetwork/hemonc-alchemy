# Release and repository workflow

HemOnc Alchemy uses the shared [cava-devops](https://github.com/AustralianCancerDataNetwork/cava-devops) workflows. The package repository keeps the small amount of configuration that is inherently repository-specific; the CI, label gate, release drafting, documentation deployment, and distribution build logic remains reusable and centralised.

## Pull requests

The `CI` workflow runs on pull requests targeting `main`:

- `label-gate / check` requires exactly one release label: `breaking`, `feature`, `fix`, `dependencies`, or `chore`.
- `default / test` runs the default dialect-independent suite without a database service.
- `duckdb / test` explicitly selects `duckdb` tests through CAVA's shared DuckDB workflow.
- `postgres / test` runs the shared PostgreSQL service workflow with `PYTEST_ADDOPTS=-m postgres`. The required-connection flag makes unavailable PostgreSQL fixtures fail instead of silently skipping the dialect job.
- `installed-wheel / wheel (core)` and `installed-wheel / wheel (duckdb-omop)` install built wheels in clean environments and exercise them outside the checkout.

`build-test / test` retains the organization-required check name and passes only when all four validation jobs succeed. It runs even after a failed, cancelled or skipped dependency, so a skipped job cannot bypass the merge gate.

The project default excludes both `db_dialect` and legacy `postgres` markers. The PostgreSQL override and DuckDB workflow command explicitly replace that selection. Licensed full-extract parity is a separate local release gate; public CI uses synthetic fixtures and skips real-extract checks when their inputs are absent. See the repository's [validation instructions](https://github.com/AustralianCancerDataNetwork/hemonc-alchemy/tree/main/validation).

The label controls release intent, not test selection. Use `chore` for documentation, refactoring, generated maintenance, and CI changes that should not create a release-note entry. Use the highest applicable bump label when a change affects the public package.

The PR title becomes the release-note entry. The description is reviewer context, so explain design decisions, data-model consequences, and how the change was verified there. Before merging, confirm that the title is suitable for someone reading the release history months later.

## Versioning and release drafting

The version is derived from Git tags by `hatch-vcs`. The repository does not maintain a manually edited version string or a generated `CHANGELOG.md`.

When a labelled PR is squash-merged, `merge.yml` updates the standing draft release. The draft's next version is resolved from the highest-priority label it contains:

| Label | Version impact |
|---|---|
| `breaking` | Major |
| `feature` | Minor |
| `fix` or `dependencies` | Patch |
| `chore` | No release-note entry and no version bump |

A maintainer reviews and publishes the draft from GitHub's Releases page. Publishing creates a `vX.Y.Z` tag on `main`; that tag is the only event that starts package publication.

Before publishing the DuckDB-capable release, require the recorded full-extract parity gate, installed-wheel checks, and downstream PostgreSQL smoke results. Schema-role adoption is a breaking public contract for raw-engine callers, so the `breaking` label applies under the version policy above. Link the [upgrade guide](../getting-started/upgrading.md) from the release notes. Update downstream exact pins only after the distribution is available from PyPI.

## Package publication

`publish.yml` delegates building to CAVA, which verifies that the tag is reachable from `main` and produces the wheel and source distribution. The final PyPI upload stays in this repository because PyPI trusted publishing binds its OIDC identity to the calling repository's workflow file.

The repository needs a GitHub environment named `pypi` and a PyPI trusted publisher with these values:

| Field | Value |
|---|---|
| Owner | `AustralianCancerDataNetwork` |
| Repository | `hemonc-alchemy` |
| Workflow | `publish.yml` |
| Environment | `pypi` |

## Documentation deployment

`docs.yml` deploys the MkDocs site after changes land on `main` and can also be run manually. The documentation dependencies live in the `dev` extra so the reusable deployment workflow can recreate the same build environment.

## Repository settings

The existing organization rules require pull requests, at least one approval, and these status checks on `main`:

- `label-gate / check`
- `build-test / test`

The aggregate `build-test / test` requires the default, DuckDB, PostgreSQL, and installed-wheel jobs. This protects every validation axis without changing a shared organization ruleset to include repository-specific check names.

Use squash merging as the normal merge strategy and prevent force pushes to `main`. The initial history migration or other exceptional administrative operation should be handled separately from ordinary package changes.
