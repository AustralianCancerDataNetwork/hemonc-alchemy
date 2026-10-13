"""Unit coverage for finding implication data and closure."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from hemonc_alchemy.toolkit.core.indications.implications import (
    clear_implication_cache,
    implied_findings,
    lint_finding_implications,
    load_implication_data,
    parse_implication_data,
)
from hemonc_alchemy.toolkit.core.indications.loader import (
    BiomarkerSource,
    IndicationSource,
)
from hemonc_alchemy.toolkit.core.indications.model import Kind, Presence


def entry(biomarker, finding, satisfies):
    return {
        "biomarker": biomarker,
        "finding": finding,
        "satisfies": satisfies,
    }


def data(implications=(), no_implication=()):
    return parse_implication_data(
        {
            "implications": list(implications),
            "no_implication": [
                {"biomarker": biomarker, "finding": finding}
                for biomarker, finding in no_implication
            ],
        }
    )


def source(biomarker, findings, condition="Other cancer"):
    return IndicationSource(
        1,
        None,
        condition,
        None,
        "Drug",
        "FDA",
        "FALSE",
        (BiomarkerSource(1, (biomarker,), tuple(findings)),),
        (),
        {},
    )


def test_implication_closure_follows_chains_and_stops_cycles(monkeypatch):
    implication_data = data(
        (
            entry("ROS1", "fusion", ["rearrangement"]),
            entry("ROS1", "rearrangement", ["translocation"]),
            entry("ROS1", "translocation", ["fusion"]),
        )
    )
    monkeypatch.setattr(
        "hemonc_alchemy.toolkit.core.indications.implications.load_implication_data",
        lambda: implication_data,
    )

    findings = implied_findings("ros1", "FUSION")

    assert [finding.raw for finding in findings] == [
        "FUSION",
        "rearrangement",
        "translocation",
    ]


def test_unknown_input_returns_only_itself_without_loading_data(monkeypatch):
    def fail():
        raise AssertionError("unknown findings must not load implication data")

    monkeypatch.setattr(
        "hemonc_alchemy.toolkit.core.indications.implications.load_implication_data",
        fail,
    )

    (finding,) = implied_findings("EGFR", "ITD")

    assert finding.raw == "ITD"
    assert finding.parsed is False
    assert finding.presence is Presence.UNKNOWN


def test_structural_implications_include_hgvs_partial_and_mutated(monkeypatch):
    monkeypatch.setattr(
        "hemonc_alchemy.toolkit.core.indications.implications.load_implication_data",
        lambda: data(),
    )

    findings = implied_findings("BRAF", "p.V600E")

    assert [finding.raw for finding in findings] == ["p.V600E", "mutated", "p.V600"]
    assert findings[1].kind is Kind.MUTATION_CLASS


def test_threshold_closure_checks_assay_unit_and_direction(monkeypatch):
    implication_data = data(
        no_implication=(
            ("PD-L1", "TPS at least 1%"),
            ("PD-L1", "TPS at least 50%"),
            ("PD-L1", "at least 1%"),
            ("PD-L1", "at least 50%"),
            ("PD-L1", "CPS at least 50%"),
            ("PD-L1", "TPS at least 50 mut/Mb"),
            ("PD-L1", "TPS at most 20%"),
            ("PD-L1", "TPS at most 50%"),
        )
    )
    monkeypatch.setattr(
        "hemonc_alchemy.toolkit.core.indications.implications.load_implication_data",
        lambda: implication_data,
    )

    upward = {finding.raw for finding in implied_findings("PD-L1", "TPS at least 60%")}
    downward = {finding.raw for finding in implied_findings("PD-L1", "TPS at most 40%")}

    assert {"TPS at least 1%", "TPS at least 50%"} <= upward
    assert not {"at least 1%", "CPS at least 50%", "TPS at least 50 mut/Mb"} & upward
    unspecified_assay = {
        finding.raw for finding in implied_findings("PD-L1", "at least 60%")
    }
    assert "at least 50%" not in unspecified_assay
    assert {"TPS at most 50%"} <= downward
    assert "TPS at most 20%" not in downward


def test_implication_data_rejects_invalid_schema():
    with pytest.raises(ValueError, match="must contain exactly"):
        parse_implication_data(
            {
                "implications": [
                    entry("EGFR", "p.L858R", ["mutated"]) | {"status": "draft"}
                ],
                "no_implication": [],
            }
        )


def test_yaml_is_loaded_lazily_and_cache_can_be_cleared(monkeypatch):
    calls = 0
    packaged = {
        "implications": [],
        "no_implication": [{"biomarker": "EGFR", "finding": "p.L858R"}],
    }

    def read_data():
        nonlocal calls
        calls += 1
        return packaged

    import hemonc_alchemy.toolkit.core.indications.implications as module

    clear_implication_cache()
    monkeypatch.setattr(module, "_read_yaml", read_data)
    first = load_implication_data()
    assert load_implication_data() is first
    assert calls == 1
    clear_implication_cache()
    load_implication_data()
    assert calls == 2
    clear_implication_cache()


def test_importing_module_does_not_read_yaml():
    repository = Path(__file__).resolve().parents[1]
    script = (
        "import importlib.resources; "
        "importlib.resources.files = lambda *args, **kwargs: "
        "(_ for _ in ()).throw(AssertionError('resource read during import')); "
        "import hemonc_alchemy.toolkit.core.indications.implications"
    )
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        cwd=repository,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )


def test_implication_lint_checks_tokens_and_lung_pair_coverage():
    implication_data = data((entry("EGFR", "p.L858R", ["activating mutation"]),))
    sources = (
        source("EGFR", ("p.L858R", "activating mutation", "p.T790M"), "Lung cancer"),
        source("EGFR", ("p.L858R", "activating mutation")),
    )

    report = lint_finding_implications(sources, implication_data)

    assert report.failures == ("unaccounted lung finding pair: egfr: p.t790m",)
