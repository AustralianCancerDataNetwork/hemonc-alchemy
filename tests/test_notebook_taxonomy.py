"""Tests for the notebooks' shared classification rules.

`notebooks/_taxonomy.py` is not part of the installed package -- it is a
helper the optional demonstration notebooks import. When the notebook bundle
is present locally, it is tested here because several notebooks depend on it
and their published figures change if it drifts. Package CI may not check out
the ignored notebook bundle, so the module-level import is intentionally
optional.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NOTEBOOKS = Path(__file__).resolve().parent.parent / "notebooks"
if str(NOTEBOOKS) not in sys.path:
    sys.path.insert(0, str(NOTEBOOKS))

taxonomy = pytest.importorskip(
    "_taxonomy",
    reason="notebook helpers are optional and are not included in package CI",
)


@pytest.mark.parametrize(
    ("main_class", "expected"),
    [
        # therapeutic monoclonals are targeted therapy, matching HemOnc-in-OMOP
        ("Anti-VEGFR antibody", "Targeted therapy"),
        ("Anti-CD20 antibody", "Targeted therapy"),
        ("EGFR inhibitor", "Targeted therapy"),
        # cytotoxics named "... inhibitor" must not fall through to targeted
        ("Topoisomerase II inhibitor", "Cytotoxic chemotherapy"),
        ("Microtubule inhibitor", "Cytotoxic chemotherapy"),
        ("Platinum agent", "Cytotoxic chemotherapy"),
        # checkpoint inhibitors are matched before the general antibody rule
        ("Anti-PD-1 antibody", "Immune checkpoint inhibitor"),
        ("Anti-CTLA-4 antibody", "Immune checkpoint inhibitor"),
        # deliberately finer than HemOnc's own taxonomy
        ("Anti-HER2 antibody-drug conjugate", "Antibody-drug conjugate"),
        ("Anti-EGFR-HGFR bispecific antibody", "Bispecific antibody"),
        ("External beam radiotherapy", "Radiotherapy"),
        # unmapped input is a visible gap, not a guess
        (None, None),
        ("", None),
        ("Something entirely new", None),
    ],
)
def test_modality(main_class, expected):
    assert taxonomy.modality(main_class) == expected


def test_modality_labels_are_declared():
    for _, label in taxonomy.MODALITY_RULES:
        assert label in taxonomy.MODALITIES


@pytest.mark.parametrize(
    ("cyclesigs", "expected"),
    [
        ("3-week cycles", (None, "open")),  # plural: repeats
        ("9-week cycle", (1, "single")),  # singular: one cycle
        ("3-week cycle for four cycles", (4, "fixed")),
        ("3-week cycle for 35 cycles", (35, "fixed")),
        ("3-week cycle for four to six cycles", (6, "range")),
        ("3-week cycle for at least six cycles", (6, "minimum")),
        ("3-week cycle for four or more cycles", (4, "minimum")),
        ("One 3-week course", (1, "single")),
        ("Three courses", (3, "fixed")),
        ("Continued indefinitely", (None, "open")),
        ("Duration of each cycle not specified", (None, "unspecified")),
        ("Evaluation occurs during week 30", (None, "other")),
        (None, (None, None)),
        (float("nan"), (None, None)),  # pandas missing value
    ],
)
def test_parse_course(cyclesigs, expected):
    assert taxonomy.parse_course(cyclesigs) == expected


def test_parse_course_caps_are_declared():
    for value in [
        "3-week cycles",
        "One course",
        "Three courses",
        "Evaluation during week 5",
        "Duration not specified",
    ]:
        _, cap = taxonomy.parse_course(value)
        assert cap in taxonomy.CAPS


@pytest.mark.parametrize(
    ("groups", "any_unknown", "expected"),
    [
        (["IV", "IV"], False, "parenteral only"),
        (["PO"], False, "oral only"),
        (["IV", "PO"], False, "mixed"),
        # a partially routed regimen must not be described by the known half
        (["PO"], True, "partially classified"),
        (["IV", "PO"], True, "partially classified"),
        ([None], True, "no usable route"),
        ([], True, "no usable route"),
    ],
)
def test_delivery_shape(groups, any_unknown, expected):
    assert taxonomy.delivery_shape(groups, any_unknown) == expected


@pytest.mark.parametrize(
    ("groups", "expected"),
    [
        ([float("nan"), float("nan")], "no usable route"),
        ([float("nan"), "IV"], "partially classified"),
    ],
)
def test_delivery_shape_handles_nan(groups, expected):
    """Routes arrive as a pandas Series, where a missing value is NaN.

    NaN is truthy, so a plain `if group` filter keeps it and an entirely
    unrouted regimen reads as partially classified instead of unusable.
    """
    assert taxonomy.delivery_shape(groups, any_unknown=True) == expected


def test_delivery_shape_accepts_a_pandas_series():
    pd = pytest.importorskip("pandas")
    series = pd.Series([None, None], dtype="object")
    assert taxonomy.delivery_shape(series, any_unknown=True) == "no usable route"
