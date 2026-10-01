"""Regression tests for compiler/diff.py's review-follow-up fixes: invalid
git refs must fail loudly instead of being treated as "first generation",
and generated-code-affecting metadata (enums, normalisation groups, soft
relationships) must actually be diffed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from hemonc_alchemy.compiler.diff import (
    diff_registries,
    load_previous_registry_from_git,
)
from hemonc_alchemy.compiler.schema_model import (
    EnumSpec,
    ForeignLikeRef,
    NormalisationGroup,
    Registry,
    TableMeta,
    save_registry_json,
)


def _git_repo_with_committed_registry(tmp_path: Path, registry: Registry) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    save_registry_json(registry, schema_dir / "registry.json")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=tmp_path, check=True)
    return schema_dir / "registry.json"


@pytest.fixture
def committed_registry_path(tmp_path: Path) -> Path:
    registry = Registry(tables={"drugs": TableMeta(name="drugs", description="d", kind="content", maturity="prod", pk_columns=["drug_cui"])})
    return _git_repo_with_committed_registry(tmp_path, registry)


class TestLoadPreviousRegistryFromGit:
    def test_invalid_ref_raises(self, committed_registry_path: Path):
        with pytest.raises(ValueError, match="not a valid git ref"):
            load_previous_registry_from_git(committed_registry_path, ref="definitely-not-a-ref")

    def test_valid_ref_loads_committed_registry(self, committed_registry_path: Path):
        registry = load_previous_registry_from_git(committed_registry_path, ref="HEAD")
        assert registry is not None
        assert "drugs" in registry.tables

    def test_valid_ref_missing_file_returns_none(self, tmp_path: Path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
        (tmp_path / "README.md").write_text("x")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=tmp_path, check=True)

        never_committed = tmp_path / "schema" / "registry.json"
        assert load_previous_registry_from_git(never_committed, ref="HEAD") is None


class TestDiffRegistriesMetadataCoverage:
    """A synthetic enum-member change, denormalisation change, or soft-
    relationship change must not produce an empty diff. In practice the
    original column-presence/type/nullability-only comparison missed all
    three.
    """

    def _table(self, **overrides: Any) -> TableMeta:
        base: dict[str, Any] = {
            "name": "indications", "description": "d", "kind": "content", "maturity": "prod", "pk_columns": [],
        }
        base.update(overrides)
        return TableMeta(**base)

    def test_enum_member_change_is_detected(self):
        old = self._table()
        old.enums = {"finding": EnumSpec(name="finding", tablename="indications", values=["positive", "negative"])}
        new = self._table()
        new.enums = {"finding": EnumSpec(name="finding", tablename="indications", values=["positive", "negative", "equivocal"])}

        changes = diff_registries(Registry(tables={"indications": old}), Registry(tables={"indications": new}))
        assert any("enum values changed" in c for c in changes)

    def test_normalisation_group_change_is_detected(self):
        old = self._table()
        old.normalisation_groups = [NormalisationGroup(columns=["biomarker4", "biomarker4_finding"])]
        new = self._table()
        new.normalisation_groups = []

        changes = diff_registries(Registry(tables={"indications": old}), Registry(tables={"indications": new}))
        assert any("normalisation groups changed" in c for c in changes)

    def test_soft_relationship_change_is_detected(self):
        old = self._table()
        new = self._table()
        new.soft_relationships = [ForeignLikeRef(local_column="drug_cui", target_table="drugs", target_column="drug_cui")]

        changes = diff_registries(Registry(tables={"indications": old}), Registry(tables={"indications": new}))
        assert any("soft relationships changed" in c for c in changes)

    def test_no_change_is_empty(self):
        old = self._table()
        new = self._table()
        assert diff_registries(Registry(tables={"indications": old}), Registry(tables={"indications": new})) == []


if __name__ == "__main__":
    pytest.main([__file__])
