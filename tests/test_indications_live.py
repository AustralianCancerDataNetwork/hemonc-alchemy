"""Optional checks against the configured live HemOnc database.

Run with:
    HEMONC_INDICATIONS_DATABASE_URL=postgresql+psycopg://hemonc:hemonc@localhost:5432/hemonc_alchemy \
        uv run pytest -q tests/test_indications_live.py

The engine connects with ``-csearch_path=public,omop``. See
``docs/getting-started/local-development.md`` for devcontainer database startup.
"""

import os

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from hemonc_alchemy.toolkit.core.indications import (
    BiomarkerCriterion,
    load_indication_sources,
    resolve_indications,
)
from hemonc_alchemy.toolkit.core.indications.model import Presence
from hemonc_alchemy.toolkit.core.indications.normalisers.biomarker import (
    BiomarkerNormaliser,
)


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
            yield session
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def resolved_indications(live_session):
    return {item.indication_id: item for item in resolve_indications(live_session)}


@pytest.mark.postgres
def test_live_snapshot_coverage_and_golden_indications(
    live_session, resolved_indications
):
    sources = load_indication_sources(live_session)
    assert len(sources) == 3093
    assert sum(bool(source.biomarkers[0].biomarkers) for source in sources) == 861

    normaliser = BiomarkerNormaliser()
    report = normaliser.lint(sources)
    assert report.unknown_names == {}
    assert report.unparsed_findings == {"ITD": 5}
    name_tokens = sum(
        len(slot.biomarkers) for source in sources for slot in source.biomarkers
    )
    finding_tokens = sum(
        len(slot.findings) for source in sources for slot in source.biomarkers
    )
    recognised_names = name_tokens - sum(report.unknown_names.values())
    recognised_findings = finding_tokens - sum(report.unparsed_findings.values())
    assert (recognised_names + recognised_findings) / (
        name_tokens + finding_tokens
    ) >= 0.99

    def signatures(indication_id):
        return [
            (
                criterion.slot,
                criterion.biomarker,
                tuple(finding.raw for finding in criterion.findings),
            )
            for criterion in resolved_indications[indication_id].criteria
            if isinstance(criterion, BiomarkerCriterion)
        ]

    assert signatures(180)[:3] == [
        (1, "ER", ("negative",)),
        (2, "PR", ("negative",)),
        (3, "HER2", ("negative",)),
    ]
    assert signatures(44) == [(1, "EGFR", ("exon 19 deletion", "p.L858R"))]
    assert signatures(964) == [
        (1, "MMR", ("deficient", "high")),
        (1, "MSI", ("deficient", "high")),
    ]
    assert signatures(2830) == [(1, "ER", ("positive", "unknown"))]
    assert signatures(2991) == [(1, "BRAF", ("p.V600E",))]
    assert signatures(2994) == [(1, "BRAF", ("p.V600",))]
    assert signatures(203) == [(1, "PD-L1", ("TPS at least 50%",))]
    assert signatures(1533) == [(1, "HER2", ("positive",))]
    assert resolved_indications[803].withdrawn is True
    assert resolved_indications[803].raw["withdrawn"] == "TRUE"


@pytest.mark.postgres
def test_live_presence_classification(resolved_indications):
    findings = [
        finding
        for item in resolved_indications.values()
        for criterion in item.criteria
        if isinstance(criterion, BiomarkerCriterion)
        for finding in criterion.findings
    ]
    level_words = {"high", "low", "not high", "deficient", "proficient"}
    assert all(
        finding.presence is not Presence.UNKNOWN
        for finding in findings
        if finding.comparator is not None
        or finding.value is not None
        or (finding.detail or "").casefold() in level_words
    )
    assert all(
        not finding.parsed or (finding.detail or "").casefold() == "unknown"
        for finding in findings
        if finding.presence is Presence.UNKNOWN
    )


@pytest.mark.postgres
def test_live_golden_presence_states(resolved_indications):
    assert [c.findings[0].presence for c in resolved_indications[180].criteria[:3]] == [
        Presence.ABSENT,
        Presence.ABSENT,
        Presence.ABSENT,
    ]
    assert [f.presence for f in resolved_indications[44].criteria[0].findings] == [
        Presence.PRESENT,
        Presence.PRESENT,
    ]
    mmr_msi = resolved_indications[964].criteria
    assert len(mmr_msi) == 2 and mmr_msi[0].group == mmr_msi[1].group
    assert [f.presence for f in mmr_msi[0].findings] == [
        Presence.PRESENT,
        Presence.NOT_STATED,
    ]
    assert [f.presence for f in resolved_indications[2830].criteria[0].findings] == [
        Presence.PRESENT,
        Presence.UNKNOWN,
    ]
    assert all(
        resolved_indications[indication_id].criteria[0].findings[0].presence
        is Presence.PRESENT
        for indication_id in (2991, 2994)
    )
    pd_l1 = resolved_indications[203].criteria[0].findings[0]
    assert pd_l1.presence is Presence.NOT_STATED
    assert (pd_l1.comparator, pd_l1.value, pd_l1.unit) == (">=", 50, "%")
