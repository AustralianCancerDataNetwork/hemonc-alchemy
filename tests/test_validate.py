"""Regression test for compiler/validate.py's normalisation-group invariant
(review follow-up): a repeated column within a group, or a column spread
across more than one group, means table_class() would render malformed or
ambiguous child tables. Seen for real in the generated
entities.py as `['atc', 'atc']` before schema_model.py's dedup-ordering fix.
"""

from __future__ import annotations

from typing import Any

import pytest

from hemonc_alchemy.compiler.schema_model import (
    ColumnSpec,
    NormalisationGroup,
    Registry,
    TableMeta,
)
from hemonc_alchemy.compiler.validate import (
    validate_all,
    validate_registry,
    validate_source_regressions,
)


def _table(**overrides: Any) -> TableMeta:
    base: dict[str, Any] = {
        "name": "drugs", "description": "d", "kind": "content", "maturity": "prod",
        "pk_columns": [], "columns": {"atc": ColumnSpec(name="atc", type="string")},
    }
    base.update(overrides)
    return TableMeta(**base)


class TestNormalisationGroupInvariant:
    def test_self_pair_group_is_rejected(self):
        table = _table()
        table.normalisation_groups = [NormalisationGroup(columns=["atc", "atc"])]
        errors = validate_registry(Registry(tables={"drugs": table}))
        assert any("repeats a column" in e for e in errors)

    def test_column_in_two_groups_is_rejected(self):
        table = _table()
        table.normalisation_groups = [
            NormalisationGroup(columns=["atc", "atc_class"]),
            NormalisationGroup(columns=["atc", "atc_code"]),
        ]
        errors = validate_registry(Registry(tables={"drugs": table}))
        assert any("appears in 2 normalisation groups" in e for e in errors)

    def test_clean_groups_pass(self):
        table = _table()
        table.normalisation_groups = [NormalisationGroup(columns=["atc_class", "atc_code"])]
        assert validate_registry(Registry(tables={"drugs": table})) == []

    def test_dictionary_sheet_without_enrichment_is_rejected(self):
        registry = Registry(tables={"sigs": _table(name="sigs")})
        registry._dictionary_sheets = {"sigs"}
        registry._dictionary_enriched_columns = {"sigs": set()}

        errors = validate_registry(registry)

        assert any("dictionary sheet exists but contributed no" in error for error in errors)


class TestSourceRegressions:
    """The silent half of the 2026-08-17 regression: three tables stopped
    resolving to a CSV, dropped to zero columns, and generated no entity
    class -- and validate_registry skips column-less tables by design, so
    nothing failed.
    """

    def test_losing_all_columns_since_the_last_run_is_an_error(self):
        previous = Registry(tables={"canonicaltriples": _table(
            name="canonicaltriples", columns={"class_1": ColumnSpec(name="class_1", type="string")},
            source_filename="canonical.triples.csv",
        )})
        current = Registry(tables={"canonicaltriples": _table(
            name="canonicaltriples", columns={},
        )})
        errors = validate_source_regressions(current, previous)
        assert len(errors) == 1
        assert "canonicaltriples" in errors[0]
        assert "canonical.triples.csv" in errors[0]
        assert "SourceAliases" in errors[0]

    def test_table_that_never_had_columns_is_not_an_error(self):
        """A dozen dictionary-declared tables have no CSV extract in any
        drop; that is the long-standing state, not a regression."""
        previous = Registry(tables={"cities": _table(name="cities", columns={})})
        current = Registry(tables={"cities": _table(name="cities", columns={})})
        assert validate_source_regressions(current, previous) == []

    def test_still_backed_table_is_not_an_error(self):
        previous = Registry(tables={"drugs": _table()})
        current = Registry(tables={"drugs": _table()})
        assert validate_source_regressions(current, previous) == []

    def test_outright_removed_table_is_left_to_the_diff_gate(self):
        """`pointers` left the dictionary entirely in the new drop. The diff
        reports that by name; double-reporting it here would be noise."""
        previous = Registry(tables={"pointers": _table(name="pointers")})
        assert validate_source_regressions(Registry(tables={}), previous) == []

    def test_first_generation_has_no_baseline_to_compare(self):
        current = Registry(tables={"drugs": _table(columns={})})
        assert validate_source_regressions(current, None) == []

    def test_validate_all_surfaces_it(self, tmp_path):
        entities = tmp_path / "entities.py"
        enums = tmp_path / "enums.py"
        entities.write_text("x = 1\n")
        enums.write_text("y = 2\n")
        previous = Registry(tables={"variantblob": _table(
            name="variantblob", columns={"blob": ColumnSpec(name="blob", type="string")},
        )})
        current = Registry(tables={"variantblob": _table(name="variantblob", columns={})})
        errors = validate_all(current, entities, enums, previous=previous)
        assert any("variantblob" in e for e in errors)

    def test_validate_all_without_a_baseline_is_unchanged(self, tmp_path):
        entities = tmp_path / "entities.py"
        enums = tmp_path / "enums.py"
        entities.write_text("x = 1\n")
        enums.write_text("y = 2\n")
        current = Registry(tables={"variantblob": _table(name="variantblob", columns={})})
        assert validate_all(current, entities, enums) == []


if __name__ == "__main__":
    pytest.main([__file__])
