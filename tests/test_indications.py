"""Unit coverage for the lossless indication biomarker normaliser."""

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from hemonc_alchemy.model import (
    Indications,
    indications_Biomarker2_findingMap,
    indications_Biomarker2Map,
    indications_Biomarker3_findingMap,
    indications_Biomarker3Map,
    indications_Biomarker4_findingMap,
    indications_Biomarker4Map,
    indications_Regimen_cuiMap,
)
from hemonc_alchemy.toolkit.core.indications import resolve_indications
from hemonc_alchemy.toolkit.core.indications.loader import (
    BiomarkerSource,
    IndicationSource,
)
from hemonc_alchemy.toolkit.core.indications.model import (
    BiomarkerCriterion,
    Kind,
    Origin,
    Presence,
)
from hemonc_alchemy.toolkit.core.indications.normalisers.biomarker import (
    BiomarkerNormaliser,
)


def source(*slots: BiomarkerSource, indication_id: int = 1) -> IndicationSource:
    return IndicationSource(
        indication_id, 1, "Condition", 2, "Drug", "FDA", "FALSE", tuple(slots), (), {}
    )


def test_names_and_findings_in_a_slot_are_independent_or_alternatives():
    normaliser = BiomarkerNormaliser()
    resolved = normaliser.normalise(
        source(BiomarkerSource(1, ("MMR", "MSI"), ("deficient", "high")))
    )

    assert len(resolved) == 2
    assert all(isinstance(item, BiomarkerCriterion) for item in resolved)
    assert [item.biomarker for item in resolved] == ["MMR", "MSI"]
    assert resolved[0].group == resolved[1].group == "1:1"
    assert [[finding.raw for finding in item.findings] for item in resolved] == [
        ["deficient", "high"],
        ["deficient", "high"],
    ]
    assert [finding.detail for finding in resolved[0].findings] == ["deficient", "high"]


def test_duplicate_names_collapse_but_unknown_finding_remains_unknown():
    (criterion,) = BiomarkerNormaliser().normalise(
        source(BiomarkerSource(1, ("ER", "ER"), ("positive", "unknown")))
    )

    assert criterion.biomarker == "ER"
    assert criterion.group is None
    assert [finding.presence for finding in criterion.findings] == [
        Presence.PRESENT,
        Presence.UNKNOWN,
    ]
    assert [finding.raw for finding in criterion.findings] == ["positive", "unknown"]


def test_finding_forms_keep_the_raw_text_and_fields():
    normaliser = BiomarkerNormaliser()
    expectations = {
        "p.L858R": (Kind.VARIANT, "p.L858R"),
        "p.V600": (Kind.VARIANT, "p.V600"),
        "exon 19 deletion": (Kind.EXON_ALTERATION, "exon 19 deletion"),
        "TPS at least 50%": (Kind.EXPRESSION, "TPS"),
        ">= 10 mutations/Mb": (Kind.EXPRESSION, None),
        "at least 400 ng/mL": (Kind.EXPRESSION, None),
    }
    for raw, (kind, detail) in expectations.items():
        finding = normaliser.parse_finding(raw)
        assert finding.raw == raw and finding.parsed
        assert (finding.kind, finding.detail) == (kind, detail)
    assert normaliser.parse_finding("TPS at least 50%").comparator == ">="
    assert normaliser.parse_finding(">= 10 mutations/Mb").unit == "mut/Mb"
    assert normaliser.parse_finding("at least 400 ng/mL").unit == "ng/mL"


def test_presence_distinguishes_unknown_from_unstated_expression():
    normaliser = BiomarkerNormaliser()
    level_and_threshold_findings = [
        normaliser.parse_finding(raw)
        for raw in (
            "high",
            "low",
            "not high",
            "high (IHC 3+)",
            "TPS at least 1%",
            "CPS at least 1%",
            ">= 10 mutations/Mb",
            "at least 400 ng/mL",
        )
    ]
    assert all(finding.presence is not Presence.UNKNOWN for finding in level_and_threshold_findings)
    assert all(
        finding.presence is Presence.NOT_STATED
        for finding in level_and_threshold_findings
    )
    assert all(
        (finding.comparator is None and finding.value is None)
        or finding.presence is not Presence.UNKNOWN
        for finding in level_and_threshold_findings
    )

    deficient = normaliser.parse_finding("deficient")
    proficient = normaliser.parse_finding("proficient")
    assert deficient.presence is Presence.PRESENT and deficient.detail == "deficient"
    assert proficient.presence is Presence.ABSENT and proficient.detail == "proficient"
    assert normaliser.parse_finding("unknown").presence is Presence.UNKNOWN


def test_importing_resolver_does_not_load_biomarker_vocabulary(monkeypatch):
    import importlib

    from hemonc_alchemy.toolkit.core.indications.normalisers import biomarker

    def fail_if_loaded():
        raise AssertionError("CSV vocabulary read during resolver module import")

    monkeypatch.setattr(biomarker, "_name_table", fail_if_loaded)
    resolver_module = importlib.import_module(
        "hemonc_alchemy.toolkit.core.indications.resolver"
    )
    importlib.reload(resolver_module)


def test_finding_parser_is_total_and_keeps_opaque_values():
    normaliser = BiomarkerNormaliser()
    opaque = normaliser.parse_finding("ITD")
    assert not opaque.parsed and opaque.raw == "ITD"
    assert opaque.presence is Presence.UNKNOWN
    assert normaliser.parse_finding(None).raw == "None"


def test_name_vocabulary_is_case_insensitive_and_uses_her2_canonical_name():
    normaliser = BiomarkerNormaliser()
    assert normaliser.canonical_name("erbb2") == "HER2"
    assert normaliser.canonical_name("hEr2") == "HER2"
    assert normaliser.canonical_name("unknown marker") is None


def test_origin_qualifier_and_composite_expression_forms():
    normaliser = BiomarkerNormaliser()
    germline = normaliser.parse_finding("germline mutation")
    fusion = normaliser.parse_finding(
        "fusion without a known acquired resistance mutation"
    )
    expression = normaliser.parse_finding(
        "low (IHC 1+ or IHC 2+/ISH-) or ultralow (IHC 0 with membrane staining)"
    )
    assert germline.origin is Origin.GERMLINE
    assert (
        fusion.kind is Kind.FUSION
        and fusion.qualifier == "without a known acquired resistance mutation"
    )
    assert expression.parsed and expression.detail == "low"


def test_sqlite_loader_reads_four_slots_and_regimen_links_in_fixed_queries():
    engine = sa.create_engine("sqlite://")
    tables = (
        Indications.__table__,
        indications_Biomarker2Map.__table__,
        indications_Biomarker2_findingMap.__table__,
        indications_Biomarker3Map.__table__,
        indications_Biomarker3_findingMap.__table__,
        indications_Biomarker4Map.__table__,
        indications_Biomarker4_findingMap.__table__,
        indications_Regimen_cuiMap.__table__,
    )
    for table in tables:
        table.create(engine)
    with engine.begin() as connection:
        connection.execute(
            Indications.__table__.insert().values(
                id=1,
                accelerated=False,
                component="Drug",
                condition="Condition",
                date_added=datetime(2026, 1, 1, tzinfo=UTC),
                first_in_class=False,
                regulator="FDA",
                withdrawn="2025-01-01",
                biomarker="ER",
                biomarker_finding="negative",
            )
        )
        for table, column, value in (
            (indications_Biomarker2Map, "biomarker2", "PR"),
            (indications_Biomarker2_findingMap, "biomarker2_finding", "NEGATIVE"),
            (indications_Biomarker3Map, "biomarker3", "HER2"),
            (indications_Biomarker3_findingMap, "biomarker3_finding", "NEGATIVE"),
            (indications_Biomarker4Map, "biomarker4", "ROS1"),
            (indications_Biomarker4_findingMap, "biomarker4_finding", "POSITIVE"),
        ):
            connection.execute(
                table.__table__.insert().values(parent_id=1, **{column: value})
            )
        connection.execute(
            indications_Regimen_cuiMap.__table__.insert().values(
                parent_id=1, regimen_cui=77
            )
        )

    calls = []

    def count_query(*_):
        calls.append(None)

    sa.event.listen(engine, "before_cursor_execute", count_query)
    try:
        with Session(engine) as session:
            (indication,) = resolve_indications(session)
    finally:
        sa.event.remove(engine, "before_cursor_execute", count_query)
        engine.dispose()

    assert len(calls) == 8
    assert indication.regimen_cuis == (77,)
    assert indication.withdrawn and indication.raw["withdrawn"] == "2025-01-01"
    assert [(item.slot, item.biomarker) for item in indication.criteria] == [
        (1, "ER"),
        (2, "PR"),
        (3, "HER2"),
        (4, "ROS1"),
    ]
