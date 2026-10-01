"""Regression tests for compiler/schema_model.py's review-follow-up fixes:
denormalised-column dedup ordering, registry.json round-tripping of soft
relationships, and enum-collision detection.
"""

from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import pytest

from hemonc_alchemy.compiler.audit import (
    dictionary_only_column_warnings,
    enum_collision_warnings,
)
from hemonc_alchemy.compiler.generate import (
    parse_multival_overrides,
    parse_source_aliases,
)
from hemonc_alchemy.compiler.schema_model import (
    ColumnSpec,
    EnumSpec,
    ForeignLikeRef,
    NormalisedTable,
    Registry,
    SoftManyToManyRef,
    TableMeta,
    load_registry_json,
    save_registry_json,
)


class TestDenormalisedColumnDedup:
    """`finalise_from_data` must dedupe `denormalised_columns` before calling
    `infer_pipe_groups`, not after. Seen in the real generated
    entities.py: `Drugs.normalisation_groups` contained a malformed
    `['atc', 'atc']` self-pair even though `Drugs.denormalised_columns`
    itself came out clean (deduped too late to matter for inference).
    """

    def test_pre_existing_duplicate_does_not_produce_self_pair_group(self):
        meta = TableMeta(
            name="drugs",
            description="",
            kind="content",
            maturity="prod",
            pk_columns=["drug_cui"],
        )
        # Simulate the dictionary-driven pass (enrich_field_metadata) having
        # already appended 'atc' once before the data-driven pass runs.
        meta.denormalised_columns = ["atc"]

        df = pd.DataFrame(
            {
                "drug_cui": [1, 2, 3],
                "atc": ["A01|A02", "B01", "C01|C02|C03"],
            }
        )
        meta.finalise_from_data(df)

        assert meta.denormalised_columns == ["atc"]
        for group in meta.normalisation_groups:
            assert len(group.columns) == len(set(group.columns)), f"malformed self-pair: {group.columns}"

    def test_hard_multival_override_removes_map_but_keeps_scalar_column(self):
        meta = TableMeta(
            name="studies",
            description="",
            kind="content",
            maturity="prod",
            pk_columns=["id"],
            columns={"id": object(), "study": object(), "study_group": object()},
            denormalised_columns=["study", "study_group"],
        )
        meta.normalised_tables = [
            NormalisedTable(parent="studies", column="study"),
            NormalisedTable(parent="studies", column="study_group"),
        ]
        registry = Registry(tables={"studies": meta})

        registry.apply_multival_overrides({"studies": {"study"}})

        assert meta.denormalised_columns == ["study_group"]
        assert [table.column for table in meta.normalised_tables] == ["study_group"]
        assert "study" in meta.columns


class TestMultivalOverrides:
    def test_parses_case_insensitive_table_and_column_headers(self):
        df = pd.DataFrame(
            {
                "table": ["Studies", "study_results"],
                "COLUMN": ["study", "est_ci"],
                "Reason": ["scalar", "html"],
            }
        )

        assert parse_multival_overrides(df) == {
            "studies": {"study"},
            "study_results": {"est_ci"},
        }


class TestDictionaryFieldEnrichment:
    def test_footnote_variable_is_not_generated_as_a_column(self, capsys):
        meta = TableMeta(
            name="drugs", description="", kind="content", maturity="prod", pk_columns=[]
        )
        enriched = meta.enrich_field_metadata(
            pd.DataFrame(
                {
                    "Variable": [
                        "drug",
                        "(*) While we do not impose a limit, these are externally maintained vocabularies and have their own defined scopes",
                    ],
                    "Type": ["String", "String"],
                }
            )
        )

        assert enriched == {"drug"}
        assert set(meta.columns) == {"drug"}
        assert "ignoring prose" in capsys.readouterr().out

    def test_variable_note_header_still_enriches_the_sheet(self):
        meta = TableMeta(
            name="sigs", description="", kind="content", maturity="prod", pk_columns=[]
        )
        enriched = meta.enrich_field_metadata(
            pd.DataFrame(
                {
                    "Variable (note 1)": ["study", "regimen_cui"],
                    "Type": ["String", "Integer"],
                }
            )
        )

        assert enriched == {"study", "regimen_cui"}
        assert set(meta.columns) == {"study", "regimen_cui"}

    def test_dictionary_only_column_is_a_warning(self, tmp_path):
        meta = TableMeta(
            name="drugs",
            description="",
            kind="content",
            maturity="prod",
            pk_columns=[],
            columns={
                "drug": ColumnSpec(name="drug", type="String"),
                "declared_but_absent": ColumnSpec(
                    name="declared_but_absent", type="String"
                ),
            },
        )
        registry = Registry(tables={"drugs": meta})
        pd.DataFrame({"drug": ["cisplatin"]}).to_csv(tmp_path / "drugs.csv", index=False)
        registry.finalise_table_metadata_from_data(tmp_path)

        warnings = dictionary_only_column_warnings(registry)
        assert len(warnings) == 1
        assert "declared_but_absent" in warnings[0]


class TestDenormalisedColumnRetyping:
    """A map table stores one exploded value per row, so the column's type
    must describe that value -- not the delimited cell it came from.
    `indications.regimen_cui` was typed String because `"12460|1354"` is not
    numeric, leaving the generated map column String against
    `Regimens.regimen_cui`'s BigInteger (`operator does not exist: bigint =
    character varying` on Postgres).
    """

    def _meta(self) -> TableMeta:
        return TableMeta(
            name="indications", description="", kind="content", maturity="prod",
            pk_columns=[], columns={},
        )

    def test_pipe_delimited_identifiers_become_numeric(self):
        meta = self._meta()
        meta.finalise_from_data(
            pd.DataFrame({"regimen_cui": ["12460|1354", "47679", "9212|8100"]})
        )
        assert "regimen_cui" in meta.denormalised_columns
        assert meta.columns["regimen_cui"].type == "Integer"

    def test_placeholder_tokens_do_not_block_the_numeric_inference(self):
        """CBD/TBA are "not yet assigned" markers on a _cui column."""
        meta = self._meta()
        meta.finalise_from_data(
            pd.DataFrame({"regimen_cui": ["12460|1354", "CBD", "TBA|47679"]})
        )
        assert meta.columns["regimen_cui"].type == "Integer"

    def test_genuinely_textual_denormalised_column_stays_a_string(self):
        meta = self._meta()
        meta.finalise_from_data(
            pd.DataFrame({"regimen": ["FOLFOX|FOLFIRI", "CHOP", "R-CHOP|CVP"]})
        )
        assert "regimen" in meta.denormalised_columns
        assert meta.columns["regimen"].type == "String"

    def test_a_scalar_column_is_not_retyped_by_splitting(self):
        """No pipes -> not denormalised -> left entirely alone."""
        meta = self._meta()
        meta.finalise_from_data(pd.DataFrame({"condition": ["a", "b", "c"]}))
        assert meta.denormalised_columns == []


class TestNaturalKeyPolicy:
    def test_sparse_lookup_uses_a_surrogate_key_everywhere(self):
        meta = TableMeta(
            name="lookup_values",
            description="",
            kind="lookup",
            maturity="prod",
            pk_columns=["lookup_id"],
        )
        meta.finalise_from_data(
            pd.DataFrame(
                {
                    "lookup_id": ["A", None],
                    "description": ["first", "second"],
                    "aliases": ["one|uno", "two|dos"],
                }
            )
        )

        assert meta.uses_surrogate_pk is True
        assert meta.natural_key_is_usable is False
        rendered = meta.table_class(Registry(tables={meta.name: meta}))
        child = meta.normalised_table_class(meta.normalised_tables[0])
        assert "id: Mapped[int]" in rendered
        assert "lookup_id: Mapped[Optional[str]]" in rendered
        assert "parent_id: Mapped[int]" in child
        assert "ForeignKey('lookup_values.id')" in child

    def test_duplicate_lookup_key_uses_a_surrogate_key(self):
        meta = TableMeta(
            name="lookup_values",
            description="",
            kind="lookup",
            maturity="prod",
            pk_columns=["lookup_id"],
        )
        meta.finalise_from_data(pd.DataFrame({"lookup_id": ["A", "A"]}))

        assert meta.natural_key_has_duplicates is True
        assert meta.uses_surrogate_pk is True

    def test_complete_lookup_key_remains_the_database_key(self):
        meta = TableMeta(
            name="lookup_values",
            description="",
            kind="lookup",
            maturity="prod",
            pk_columns=["lookup_id"],
            columns={"lookup_id": ColumnSpec(name="lookup_id", type="String", nullable=False)},
        )

        assert meta.natural_key_is_usable is True
        assert meta.uses_surrogate_pk is False


class TestColumnSpecRoundTripTolerance:
    def test_a_registry_written_by_an_older_version_still_loads(self):
        """`cls(**raw)` pinned every registry.json to the exact field set that
        wrote it; compiler/diff.py loads the *previously committed* registry,
        so dropping a field broke the diff gate rather than just the reload.
        """
        spec = ColumnSpec.from_dict(
            {"name": "aff_no", "type": "String", "nullable": False,
             "enum": None, "length": None}       # `length` was removed
        )
        assert spec.name == "aff_no" and spec.nullable is False

    def test_current_shape_round_trips(self):
        original = ColumnSpec(name="route", type="Enum", nullable=True, enum="route")
        assert ColumnSpec.from_dict(asdict(original)) == original


class TestSoftRelationshipsSkipDenormalisedColumns:
    """`regimens` arrived as a new table in the
    2026-08 drop declaring `regimen_cui` as a source-defined key, so
    `infer_soft_relationships` emitted a scalar soft FK on
    `indications.regimen_cui` -- a column that is normalised into
    `indications_regimen_cui` and therefore never rendered as a
    mapped_column. SQLAlchemy failed with "Class Indications does not have a
    mapped column named 'regimen_cui'". The m2m relationship through the map
    table is the correct representation: one indication can cite several
    regimens.
    """

    def _registry(self) -> Registry:
        indications = TableMeta(
            name="indications", description="", kind="content", maturity="prod",
            pk_columns=[],
            columns={
                "condition": ColumnSpec(name="condition", type="String"),
                "regimen_cui": ColumnSpec(name="regimen_cui", type="String"),
            },
            denormalised_columns=["regimen_cui"],
        )
        indications.normalised_tables = [
            NormalisedTable(parent="indications", column="regimen_cui")
        ]
        regimens = TableMeta(
            name="regimens", description="", kind="content", maturity="prod",
            pk_columns=[], columns={"regimen_cui": ColumnSpec(name="regimen_cui", type="String")},
            source_defined_keys=["regimen_cui"],
        )
        return Registry(tables={"indications": indications, "regimens": regimens})

    def test_no_scalar_soft_fk_on_a_normalised_column(self):
        registry = self._registry()
        registry.infer_soft_relationships()
        locals_ = [r.local_column for r in registry.tables["indications"].soft_relationships]
        assert "regimen_cui" not in locals_

    def test_the_m2m_through_the_map_table_is_still_generated(self):
        registry = self._registry()
        registry.infer_soft_relationships()
        m2m = registry.tables["indications"].soft_m2m_relationships
        assert [(r.map_table, r.map_column, r.target_table) for r in m2m] == [
            ("indications_regimen_cui", "regimen_cui", "regimens")
        ]

    def test_a_scalar_column_still_gets_its_soft_fk(self):
        """The skip must be scoped to denormalised columns only."""
        registry = self._registry()
        conditions = TableMeta(
            name="conditions", description="", kind="content", maturity="prod",
            pk_columns=[], columns={"condition": object()},
            source_defined_keys=["condition"],
        )
        registry.tables["conditions"] = conditions
        registry.infer_soft_relationships()
        rels = registry.tables["indications"].soft_relationships
        assert ("condition", "conditions") in [(r.local_column, r.target_table) for r in rels]


class TestSourceAliases:
    def test_parses_case_insensitive_headers_and_strips_the_extension(self):
        df = pd.DataFrame(
            {
                "TABLE": ["context.table", "variant.blob"],
                "file": ["contexts.csv", "variant_blob"],
                "Reason": ["renamed upstream", "separator change"],
            }
        )

        assert parse_source_aliases(df) == {
            "contexttable": "contexts",
            "variantblob": "variant_blob",
        }

    def test_blank_rows_are_skipped(self):
        df = pd.DataFrame({"Table": ["context.table", None], "File": ["contexts.csv", None]})
        assert parse_source_aliases(df) == {"contexttable": "contexts"}

    def test_conflicting_declarations_for_one_table_are_rejected(self):
        df = pd.DataFrame(
            {"Table": ["context.table", "context.table"], "File": ["contexts.csv", "ctx.csv"]}
        )
        with pytest.raises(ValueError, match="conflicting files"):
            parse_source_aliases(df)

    def test_missing_required_headers_are_rejected(self):
        with pytest.raises(ValueError, match="must contain 'Table' and 'File'"):
            parse_source_aliases(pd.DataFrame({"Table": ["x"], "Notes": ["y"]}))


class TestTableMetaRoundTrip:
    """TableMeta.from_dict must round-trip everything save_registry_json
    writes. The checked-in registry.json had 18 soft
    relationships that silently became 0 after a load_registry_json
    round-trip, which is what compiler/diff.py and compiler/audit.py both
    operate on.
    """

    def test_soft_relationships_and_use_surrogate_pk_survive_round_trip(self, tmp_path):
        table = TableMeta(
            name="sigs",
            description="d",
            kind="content",
            maturity="prod",
            pk_columns=["sig_cui"],
            use_surrogate_pk=False,
        )
        table.soft_relationships = [ForeignLikeRef(local_column="drug_cui", target_table="drugs", target_column="drug_cui")]
        table.soft_m2m_relationships = [
            SoftManyToManyRef(
                local_table="sigs", map_table="sigs_route", map_column="route_cui",
                target_table="routes", target_column="route_cui",
            )
        ]
        registry = Registry(tables={"sigs": table})

        path = tmp_path / "registry.json"
        save_registry_json(registry, path)
        loaded = load_registry_json(path)

        loaded_table = loaded.tables["sigs"]
        assert loaded_table.use_surrogate_pk is False
        assert len(loaded_table.soft_relationships) == 1
        assert loaded_table.soft_relationships[0].target_table == "drugs"
        assert len(loaded_table.soft_m2m_relationships) == 1
        assert loaded_table.soft_m2m_relationships[0].map_table == "sigs_route"

    def test_defaults_when_fields_absent_from_older_snapshot(self):
        # A registry.json written before these fields existed shouldn't fail
        # to load.
        raw = {
            "name": "drugs", "description": "d", "kind": "content", "maturity": "prod",
            "pk_columns": ["drug_cui"], "columns": {},
        }
        table = TableMeta.from_dict(raw)
        assert table.soft_relationships == []
        assert table.soft_m2m_relationships == []
        assert table.use_surrogate_pk is True


class TestEnumCollisionWarnings:
    """sigs/indications' `targetleveltype`-style
    columns have both 'CPS at least 10%' and 'CPS at least 10', which both
    normalise to the same `safe_enum_key`. Should warn, not fail (the two
    values are the same real-world category here) -- and stay silent when
    there's no collision.
    """

    def test_warns_on_colliding_enum_values(self):
        table = TableMeta(
            name="indications", description="", kind="content", maturity="prod", pk_columns=[],
        )
        table.enums = {
            "biomarker4_finding": EnumSpec(
                name="biomarker4_finding", tablename="indications",
                values=["CPS at least 10%", "CPS at least 10"],
            )
        }
        registry = Registry(tables={"indications": table})
        warnings = enum_collision_warnings(registry)
        assert len(warnings) == 1
        assert "indications.biomarker4_finding" in warnings[0]

    def test_no_warning_without_collision(self):
        table = TableMeta(
            name="indications", description="", kind="content", maturity="prod", pk_columns=[],
        )
        table.enums = {
            "biomarker4_finding": EnumSpec(
                name="biomarker4_finding", tablename="indications",
                values=["Positive", "Negative"],
            )
        }
        registry = Registry(tables={"indications": table})
        assert enum_collision_warnings(registry) == []


def test_enum_rendering_escapes_multiline_values():
    table = TableMeta(
        name="study_results", description="", kind="content", maturity="prod", pk_columns=[],
    )
    enum = EnumSpec(
        name="comparator_code",
        tablename="study_results",
        values=["not applicable\n333: a multiline description"],
    )

    rendered = enum.enum_class(table)

    compile(rendered, "<generated-enum>", "exec")


if __name__ == "__main__":
    pytest.main([__file__])
