"""Optional checks against the configured live HemOnc database."""

import os

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from hemonc_alchemy.toolkit.core.indications import (
    BiomarkerCriterion,
    load_indication_sources,
    resolve_indications,
)
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
    engine = sa.create_engine(database_url)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_live_snapshot_coverage_and_golden_indications(live_session):
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

    resolved = {item.indication_id: item for item in resolve_indications(live_session)}

    def signatures(indication_id):
        return [
            (
                criterion.slot,
                criterion.biomarker,
                tuple(finding.raw for finding in criterion.findings),
            )
            for criterion in resolved[indication_id].criteria
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
    assert resolved[803].withdrawn is True
    assert resolved[803].raw["withdrawn"] == "TRUE"
