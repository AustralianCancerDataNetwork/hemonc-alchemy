"""Acceptance checks of the packaged vocabulary against the live HemOnc database.

Run with:
    HEMONC_INDICATIONS_DATABASE_URL=postgresql+psycopg://hemonc:hemonc@localhost:5432/hemonc_alchemy \
        uv run pytest -q tests/test_indication_vocabulary_live.py
"""

import os

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from hemonc_alchemy.toolkit.core.indication_vocabulary import load_vocabulary
from hemonc_alchemy.toolkit.core.indication_vocabulary.loader import (
    normalise_source_value,
)
from hemonc_alchemy.toolkit.core.indications import load_indication_sources

GAP_ANALYTES = {"17p", "5q", "CCR4", "iobenguane scan", "MIBG", "PML-RARA", "t(15;17)"}


# TPS 60% is a numeric threshold case, not a vocabulary-closure golden.
M2_CLOSURE_GOLDENS = {
    ("ALK", "negative"): ("negative",),
    ("ALK", "positive"): ("positive",),
    ("ALK", "wild-type"): ("wild-type",),
    ("BRAF", "mutated"): ("mutated",),
    ("BRAF", "p.V600"): ("mutated", "p.V600"),
    ("BRAF", "p.V600E"): ("mutated", "p.V600", "p.V600E"),
    ("EGFR", "exon 19 deletion"): (
        "activating mutation",
        "exon 19 deletion",
        "mutated",
        "sensitizing mutation",
    ),
    ("EGFR", "exon 20 insertion"): ("exon 20 insertion", "mutated"),
    ("EGFR", "mutated"): ("mutated",),
    ("EGFR", "negative"): ("negative",),
    ("EGFR", "non-resistant mutation"): ("mutated", "non-resistant mutation"),
    ("EGFR", "p.L858R"): (
        "activating mutation",
        "mutated",
        "p.L858",
        "p.L858R",
        "sensitizing mutation",
    ),
    ("EGFR", "p.T790M"): ("mutated", "p.T790", "p.T790M"),
    ("EGFR", "wild-type"): ("wild-type",),
    ("HER2", "TKD activating mutation"): ("TKD activating mutation", "mutated"),
    ("HER2", "mutated"): ("mutated",),
    ("HER2", "positive"): ("positive",),
    ("KRAS", "p.G12C"): ("mutated", "p.G12", "p.G12C"),
    ("MET", "exon 14 skipping alteration"): (
        "exon 14 skipping alteration",
        "mutated",
    ),
    ("NRG1", "fusion"): ("fusion",),
    ("PD-L1", "TPS at least 1%"): ("TPS at least 1%",),
    ("PD-L1", "TPS at least 50%"): ("TPS at least 1%", "TPS at least 50%"),
    ("PD-L1", "at least 1%"): ("at least 1%",),
    ("PD-L1", "high"): ("high",),
    ("PD-L1", "positive"): ("positive",),
    ("RET", "fusion"): ("fusion",),
    ("ROS1", "fusion"): ("fusion", "rearrangement"),
    ("ROS1", "rearrangement"): ("fusion", "rearrangement"),
    ("ROS1", "wild-type"): ("wild-type",),
    ("c-Met", ">50% of tumor cells with strong (3+ IHC) staining"): (
        ">50% of tumor cells with strong (3+ IHC) staining",
    ),
}


@pytest.fixture(scope="module")
def live_session():
    database_url = os.getenv("HEMONC_INDICATIONS_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "Set HEMONC_INDICATIONS_DATABASE_URL to run live HemOnc indication checks."
        )
    engine = sa.create_engine(
        database_url, connect_args={"options": "-csearch_path=public,omop"}
    )
    try:
        with Session(engine) as session:
            try:
                session.connection()
            except OperationalError as exc:
                pytest.skip(
                    f"Live HemOnc database is unreachable ({type(exc).__name__})."
                )
            yield session
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def sources(live_session):
    return load_indication_sources(live_session)


@pytest.fixture(scope="module")
def vocab():
    return load_vocabulary()


def _observed_findings(sources):
    observed = {}
    for source in sources:
        for slot in source.biomarkers:
            for gene in slot.biomarkers:
                observed.setdefault(gene, set()).update(
                    normalise_source_value(finding) for finding in slot.findings
                )
    return observed


def _missing_golden_targets(observed, vocab):
    missing = []
    for (gene, finding), expected in M2_CLOSURE_GOLDENS.items():
        state = vocab.concept_for("biomarker_finding", finding, gene)
        if state is None:
            continue
        reached = {state, *vocab.implied(state)}
        for token in expected:
            normalized = normalise_source_value(token)
            if normalized not in observed.get(gene, set()):
                continue
            target = vocab.concept_for("biomarker_finding", token, gene)
            if target is not None and target not in reached:
                missing.append((gene, finding, token))
    return missing


@pytest.mark.postgres
def test_every_biomarker_criterion_of_the_861_indications_resolves(sources, vocab):
    bearing = [s for s in sources if s.biomarkers[0].biomarkers]
    assert len(bearing) == 861
    unresolved = []
    for source in bearing:
        for slot in source.biomarkers:
            if not slot.biomarkers:
                continue
            for gene in slot.biomarkers:
                match = vocab.lookup("biomarker", gene)
                if match is None or (
                    match.target_concept_id is None and gene not in GAP_ANALYTES
                ):
                    unresolved.append((source.indication_id, gene))
            for finding in slot.findings:
                if not any(
                    vocab.concept_for("biomarker_finding", finding, gene)
                    for gene in slot.biomarkers
                ):
                    unresolved.append((source.indication_id, finding))
    assert unresolved == []


@pytest.mark.postgres
def test_anchored_biomarker_indications_carry_biomarker_criteria(sources, vocab):
    unanchored = {
        int(r["indication_id"]) for r in vocab.table("unanchored_indications")
    }
    by_code = {c.concept_code: c.concept_id for c in vocab.concepts("Indication")}
    checked = 0
    for source in sources:
        if not source.biomarkers[0].biomarkers or source.indication_id in unanchored:
            continue
        criteria = vocab.criteria(by_code[f"HOL-IND-{source.indication_id}"])
        assert any(c.dimension == "biomarker" for c in criteria), source.indication_id
        checked += 1
    assert checked > 700


@pytest.mark.postgres
def test_vocabulary_closure_covers_static_m2_goldens(sources, vocab):
    assert _missing_golden_targets(_observed_findings(sources), vocab) == []
