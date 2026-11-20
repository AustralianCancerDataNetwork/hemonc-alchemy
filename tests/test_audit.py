"""Regression tests for compiler/audit.py's review-follow-up fixes: null-safe
business-key duplicate detection and the hard-failure exit-status helper.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hemonc_alchemy.compiler.audit import audit_table, has_hard_failures


class TestNullSafeDuplicateDetection:
    """In the real sigs.csv, every one of 2422 rows flagged
    DUPLICATE_BUSINESS_KEYS had a null `variant_cui` (the natural key wasn't
    fully populated), and zero genuine duplicates exist among fully-keyed
    rows. Rows with a null key part must not be compared for uniqueness
    against each other (standard SQL UNIQUE-with-NULLS semantics) -- that's
    what SPARSE_KEY_ROWS is for.
    """

    def test_rows_with_shared_null_key_part_are_sparse_not_duplicate(
        self, tmp_path: Path
    ):
        csv = tmp_path / "sigs.csv"
        csv.write_text(
            "variant_cui,component_cui,doseminnum\n"
            ",162,50\n"
            ",162,50\n"  # same as row above but variant_cui is null in both
            "9,162,50\n"
        )
        result = audit_table(
            "content",
            "sigs",
            "prod",
            "variant_cui + component_cui + doseminnum",
            tmp_path,
        )
        assert result.status == "SPARSE_KEY_ROWS"
        assert result.duplicate_business_keys == 0

    def test_genuine_duplicate_among_fully_keyed_rows_still_flagged(
        self, tmp_path: Path
    ):
        csv = tmp_path / "contexttable.csv"
        csv.write_text(
            "contextraw\n"
            "Relapsed_or_refractory\n"
            "Relapsed_or_Refractory\n"  # case-only duplicate, no nulls involved
            "Newly_diagnosed\n"
        )
        result = audit_table("lookup", "contexttable", "prod", "contextRaw", tmp_path)
        assert result.status == "DUPLICATE_BUSINESS_KEYS"
        assert result.duplicate_business_keys == 1

    def test_null_key_part_alongside_genuine_duplicate_still_catches_the_duplicate(
        self, tmp_path: Path
    ):
        csv = tmp_path / "t.csv"
        csv.write_text("k,other\n,1\n,2\nsame,3\nsame,4\n")
        result = audit_table("content", "t", "prod", "k", tmp_path)
        assert result.status == "DUPLICATE_BUSINESS_KEYS"
        assert result.duplicate_business_keys == 1


class TestHasHardFailures:
    def test_true_when_any_result_is_a_hard_failure(self, tmp_path: Path):
        csv = tmp_path / "t.csv"
        csv.write_text("k,other\nsame,1\nsame,2\n")
        result = audit_table("content", "t", "prod", "k", tmp_path)
        assert has_hard_failures([result])

    def test_false_when_clean(self, tmp_path: Path):
        csv = tmp_path / "t.csv"
        csv.write_text("k\na\nb\n")
        result = audit_table("content", "t", "prod", "k", tmp_path)
        assert not has_hard_failures([result])


if __name__ == "__main__":
    pytest.main([__file__])
