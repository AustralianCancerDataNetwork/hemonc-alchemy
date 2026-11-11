"""Type, enum and multi-value inference from the CSV extract, plus locating
each table's source file.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hemonc_alchemy.compiler.infer import (
    detect_numeric,
    infer_pipe_groups,
    looks_denormalised_text,
    parse_unique_key,
    resolve_source_csv,
)
from hemonc_alchemy.compiler.schema_model import _clean_identifier_placeholders


@pytest.mark.parametrize("value", [
    "GEICAM/2003-11; CIBOMA/2004-01",
    "(three times per week; increased as tolerated)",
])
def test_semicolons_in_names_and_notes_do_not_imply_a_collection(value):
    assert not looks_denormalised_text(pd.Series([None, value]))


def test_pipe_collections_are_detected_even_when_labels_contain_semicolons():
    assert looks_denormalised_text(pd.Series(["GEICAM/2003-11; CIBOMA/2004-01|APOLLO"]))


class TestParseUniqueKey:
    """Both of these appear in the real data dictionary."""

    def test_strips_parenthetical_annotation(self):
        assert parse_unique_key("study_id (see note)") == ["study_id"]

    def test_strips_parenthetical_alternatives(self):
        assert parse_unique_key("Date + Type + Affected Table + (Addition|Change|Deletion)") == [
            "date",
            "type",
            "affected",
            "table",
        ]

    def test_plain_key_unaffected(self):
        assert parse_unique_key("drug_cui") == ["drug_cui"]

    def test_or_becomes_alternate_candidates(self):
        assert parse_unique_key("name or person_cui") == ["name", "person_cui"]

    def test_normalises_python_keyword_column_names(self):
        assert parse_unique_key("component + with") == ["component", "with_field"]


class TestInferPipeGroups:
    def test_deterministic_column_order(self):
        df = pd.DataFrame(
            {
                "biomarker4": ["a|b", "c", "d|e|f"],
                "biomarker4_finding": ["x|y", "z", "w|v|u"],
            }
        )
        groups = infer_pipe_groups(df, ["biomarker4", "biomarker4_finding"])
        assert groups == [sorted(["biomarker4", "biomarker4_finding"])]
        # sorted(...), not set(...) -- must be identical every call, not
        # Must be identical across processes, not merely within one --
        # a set() here made the order depend on hash randomisation.
        assert infer_pipe_groups(df, ["biomarker4", "biomarker4_finding"]) == groups

    def test_missing_values_are_handled(self):
        df = pd.DataFrame(
            {
                "biomarker4": pd.array(["a|b", pd.NA, "c"], dtype="string"),
                "biomarker4_finding": pd.array(["x|y", pd.NA, "z"], dtype="string"),
            }
        )
        assert infer_pipe_groups(df, ["biomarker4", "biomarker4_finding"]) == [
            ["biomarker4", "biomarker4_finding"]
        ]


class TestDetectNumeric:
    """pandas upcasts an integer column to float the moment it has a missing
    value; the inferred type must still be Integer."""

    def test_integer_with_missing_values_is_integer_not_float(self):
        # pandas upcasts to float64 the moment an int column has any NaN --
        # Real cases: sigs.variant_cui, studies.condition_cui,
        # indications.component_cui.
        s = pd.Series([1.0, 2.0, None, 4.0])
        assert s.dtype == "float64"
        assert detect_numeric(s) == "Integer"

    def test_genuine_fractional_data_stays_float(self):
        s = pd.Series([1.5, 2.25, None, 4.0])
        assert detect_numeric(s) == "Float"

    def test_clean_integer_dtype_is_integer(self):
        assert detect_numeric(pd.Series([1, 2, 3])) == "Integer"


class TestCleanIdentifierPlaceholders:
    """Some identifier columns carry "not yet assigned" markers instead of a
    number -- `TBA` in variant_eligibility.variant_cui, `CBD` in
    indications.regimen_cui."""

    def test_tba_nulled_on_cui_column(self):
        s = pd.Series(["129497", "144834", "TBA"])
        cleaned = _clean_identifier_placeholders(s, "variant_cui")
        assert cleaned.dtype == "float64"
        assert cleaned.isna().sum() == 1
        assert detect_numeric(cleaned) == "Integer"

    def test_non_cui_column_untouched(self):
        # "TBD" is a real categorical value elsewhere (Authors_Site_typeEnum)
        # -- must not be treated as a placeholder outside _cui columns.
        s = pd.Series(["Academic Medical Center", "TBD", "Government"])
        cleaned = _clean_identifier_placeholders(s, "site_type")
        assert cleaned.equals(s)

    def test_cbd_nulled_on_cui_column(self):
        """indications.regimen_cui carries "CBD" 212 times and "TBA" 19
        times; both are "not yet assigned" markers, not real identifiers.
        """
        s = pd.Series(["12460", "CBD", "TBA", "47679"])
        cleaned = _clean_identifier_placeholders(s, "regimen_cui")
        assert cleaned.isna().sum() == 2
        assert detect_numeric(cleaned) == "Integer"

    def test_cbd_outside_a_cui_column_is_untouched(self):
        s = pd.Series(["CBD", "THC", "CBD"])
        assert _clean_identifier_placeholders(s, "compound").equals(s)

    def test_genuinely_alphanumeric_cui_column_stays_textual(self):
        # If a _cui column doesn't cleanly coerce even after removing
        # placeholders, it must NOT be forced to numeric (which would
        # silently drop real, non-numeric identifier data as NaN).
        s = pd.Series(["ABC123", "DEF456", "TBA"])
        cleaned = _clean_identifier_placeholders(s, "some_cui")
        assert detect_numeric(cleaned) is None  # not coerced to numeric
        assert cleaned.isna().sum() == 1  # only the placeholder, not the real values


class TestResolveSourceCsv:
    def test_excludes_beta_files(self, tmp_path: Path):
        (tmp_path / "study_eligibility beta.csv").write_text("a,b\n1,2\n")
        path, ambiguous = resolve_source_csv(tmp_path, "study_eligibility")
        assert path is None
        assert ambiguous == []

    def test_normalised_match_recovers_dotted_filename(self, tmp_path: Path):
        (tmp_path / "canonical.triples.csv").write_text("a,b\n1,2\n")
        path, ambiguous = resolve_source_csv(tmp_path, "canonicaltriples")
        assert path is not None
        assert path.name == "canonical.triples.csv"
        assert ambiguous == []

    def test_no_match_returns_none(self, tmp_path: Path):
        path, ambiguous = resolve_source_csv(tmp_path, "nonexistent_table")
        assert path is None
        assert ambiguous == []


class TestSeparatorInsensitiveResolution:
    """The 2026-08-17 regression: upstream re-spelled dotted extract
    filenames with underscores, which safe_identifier preserves, so
    `canonical_triples` no longer normalised onto `canonicaltriples`.
    """

    def test_underscored_filename_resolves_against_dotted_dictionary_name(self, tmp_path: Path):
        (tmp_path / "canonical_triples.csv").write_text("a,b\n1,2\n")
        path, ambiguous = resolve_source_csv(
            tmp_path, "canonicaltriples", source_name="canonical.triples"
        )
        assert path is not None
        assert path.name == "canonical_triples.csv"
        assert ambiguous == []

    def test_dotted_filename_still_resolves(self, tmp_path: Path):
        """The previous drop's convention must keep working."""
        (tmp_path / "variant.blob.csv").write_text("a,b\n1,2\n")
        path, _ = resolve_source_csv(tmp_path, "variantblob", source_name="variant.blob")
        assert path is not None and path.name == "variant.blob.csv"

    def test_collapse_does_not_reach_a_genuine_rename(self, tmp_path: Path):
        """`contexttable` -> `contexts` is a content decision, not a
        separator change; no heuristic should silently bridge it."""
        (tmp_path / "contexts.csv").write_text("a,b\n1,2\n")
        path, ambiguous = resolve_source_csv(
            tmp_path, "contexttable", source_name="context.table"
        )
        assert path is None
        assert ambiguous == []

    def test_declared_alias_resolves_a_genuine_rename(self, tmp_path: Path):
        (tmp_path / "contexts.csv").write_text("a,b\n1,2\n")
        path, _ = resolve_source_csv(
            tmp_path, "contexttable", source_name="context.table", alias="contexts"
        )
        assert path is not None and path.name == "contexts.csv"

    def test_ambiguous_collapse_is_reported_not_guessed(self, tmp_path: Path):
        # Neither stem matches at the tighter safe_identifier tier (which
        # preserves underscores), so both reach the collapse tier and tie.
        (tmp_path / "canonical_triples.csv").write_text("a,b\n1,2\n")
        (tmp_path / "canonical__triples.csv").write_text("a,b\n1,2\n")
        path, ambiguous = resolve_source_csv(
            tmp_path, "canonicaltriples", source_name="canonical.triples"
        )
        assert path is None
        assert sorted(ambiguous) == ["canonical__triples.csv", "canonical_triples.csv"]

    def test_a_tighter_tier_wins_over_an_ambiguous_looser_one(self, tmp_path: Path):
        """Precedence matters: an unambiguous dotted match must be taken
        rather than declaring a tie against an underscored sibling."""
        (tmp_path / "canonical.triples.csv").write_text("a,b\n1,2\n")
        (tmp_path / "canonical_triples.csv").write_text("a,b\n1,2\n")
        path, ambiguous = resolve_source_csv(
            tmp_path, "canonicaltriples", source_name="canonical.triples"
        )
        assert path is not None and path.name == "canonical.triples.csv"
        assert ambiguous == []

    def test_beta_exclusion_still_applies_to_the_collapse_tier(self, tmp_path: Path):
        (tmp_path / "variant_blob beta.csv").write_text("a,b\n1,2\n")
        path, ambiguous = resolve_source_csv(
            tmp_path, "variantblob", source_name="variant.blob"
        )
        assert path is None
        assert ambiguous == []


if __name__ == "__main__":
    pytest.main([__file__])
