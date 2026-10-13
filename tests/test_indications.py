"""Unit coverage for the lossless indication biomarker normaliser."""

import importlib.resources
import shutil
import subprocess
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

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
    indications_ContextMap,
    indications_DemographicsMap,
    indications_Prior_therapy_negationMap,
    indications_Prior_therapy_settingMap,
    indications_Regimen_cuiMap,
    indications_Response_contingencyMap,
    indications_Risk_stratificationMap,
)
from hemonc_alchemy.toolkit.core.indications import resolve_indications
from hemonc_alchemy.toolkit.core.indications.loader import (
    BiomarkerSource,
    IndicationSource,
)
from hemonc_alchemy.toolkit.core.indications.model import (
    AgeCriterion,
    BiomarkerCriterion,
    ContextCriterion,
    Kind,
    Origin,
    Presence,
    PriorTherapy,
    PriorTherapyCriterion,
    RawCriterion,
    ScopeCriterion,
    ScopeToken,
    Setting,
    SexCriterion,
)
from hemonc_alchemy.toolkit.core.indications.normalisers.age import AgeNormaliser
from hemonc_alchemy.toolkit.core.indications.normalisers.biomarker import (
    BiomarkerNormaliser,
)
from hemonc_alchemy.toolkit.core.indications.normalisers.context import (
    ContextNormaliser,
)
from hemonc_alchemy.toolkit.core.indications.normalisers.lint import lint_indications
from hemonc_alchemy.toolkit.core.indications.normalisers.passthrough import (
    PassthroughNormaliser,
)
from hemonc_alchemy.toolkit.core.indications.normalisers.prior_therapy import (
    PriorTherapyNormaliser,
)
from hemonc_alchemy.toolkit.core.indications.normalisers.scope import ScopeNormaliser
from hemonc_alchemy.toolkit.core.indications.normalisers.sex import SexNormaliser


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
    assert all(
        finding.presence is not Presence.UNKNOWN
        for finding in level_and_threshold_findings
    )
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


def test_importing_resolver_does_not_read_package_resources(monkeypatch):
    import importlib

    def fail_if_loaded(*_args, **_kwargs):
        raise AssertionError("Package resource read during resolver import")

    monkeypatch.setattr(importlib.resources, "files", fail_if_loaded)
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


def test_scope_values_split_pipes_and_retain_unmapped_terms():
    normaliser = ScopeNormaliser()
    result = normaliser.normalise(
        source(
            indication_id=17,
        )
    )
    assert result == ()

    row = source()
    row = replace(row, stage="Locally advanced|Metastatic", status="chronic phase")
    stage, status = normaliser.normalise(row)
    assert isinstance(stage, ScopeCriterion)
    assert [term.tokens for term in stage.terms] == [
        (ScopeToken.LOCALLY_ADVANCED,),
        (ScopeToken.METASTATIC,),
    ]
    assert all(term.parsed for term in stage.terms)
    assert status.terms[0].tokens == (ScopeToken.CHRONIC_PHASE,)
    assert normaliser.normalise(replace(row, stage="Stage III"))[0].terms[0].tokens == (
        ScopeToken.STAGE_III,
    )
    unmapped = replace(row, stage="New token|Metastatic")
    assert [term.parsed for term in normaliser.normalise(unmapped)[0].terms] == [
        False,
        True,
    ]
    assert normaliser.lint((unmapped,)).unmapped_stage == {"New token": 1}
    qualified = normaliser.normalise(
        replace(row, stage="Advanced (FIGO stages III B, III C and IV)")
    )[0].terms[0]
    assert qualified.tokens == (ScopeToken.ADVANCED,)
    assert qualified.qualifier == "FIGO stages III B, III C and IV"
    composite = normaliser.normalise(
        replace(row, stage=None, status=None, stage_or_status="Unresectable advanced")
    )[0].terms[0]
    assert composite.tokens == (ScopeToken.UNRESECTABLE, ScopeToken.ADVANCED)
    assert composite.parsed
    assert (
        normaliser.normalise(
            replace(row, stage="not applicable", status=None, stage_or_status=None)
        )
        == ()
    )


def test_age_grammar_is_lossless_and_reports_unparsed_values():
    normaliser = AgeNormaliser()
    for raw, expected in (
        ("1 to NUBp", ("pediatric", 1, None, True)),
        ("18+", (None, 18, None, True)),
        ("18-", (None, None, 18, True)),
        ("adult", ("adult", None, None, True)),
    ):
        item = normaliser.normalise(replace(source(), age=raw))[0]
        assert isinstance(item, AgeCriterion)
        assert (item.group, item.min_age, item.max_age, item.parsed) == expected
        assert item.raw == raw
    bad = replace(source(), age="about 18")
    assert normaliser.normalise(bad)[0].parsed is False
    assert normaliser.lint((bad,)) == {"about 18": 1}
    month = normaliser.normalise(replace(source(), age="1+", age_unit="month"))[0]
    assert month.min_age == 1 and month.unit == "month"


def test_prior_therapy_is_minimal_and_passthrough_stays_raw():
    normaliser = PriorTherapyNormaliser()
    for raw, expected in (
        ("", PriorTherapy.NONE_REQUIRED),
        ("Not applicable", PriorTherapy.NONE_REQUIRED),
        ("0", PriorTherapy.UNTREATED),
        ("platinum-based regimen|radiation", PriorTherapy.REQUIRES_PRIOR),
    ):
        item = normaliser.normalise(replace(source(), prior_therapy=raw))[0]
        assert isinstance(item, PriorTherapyCriterion)
        assert item.requirement is expected and item.raw == raw
    row = replace(
        source(), raw={"ineligibility": "renal impairment", "with_field": None}
    )
    criteria = PassthroughNormaliser().normalise(row)
    assert next(item for item in criteria if item.dimension == "ineligibility").raw == (
        "renal impairment"
    )
    assert normaliser.normalise(source()) == ()


def test_name_vocabulary_is_case_insensitive_and_uses_her2_canonical_name():
    normaliser = BiomarkerNormaliser()
    assert normaliser.canonical_name("erbb2") == "HER2"
    assert normaliser.canonical_name("hEr2") == "hEr2"
    assert normaliser.canonical_name("unknown marker") == "unknown marker"
    assert normaliser.canonical_name("c-Met") == "c-Met"
    assert normaliser.canonical_name("Folate receptor alpha") == "FOLR1"
    report = normaliser.lint(
        (
            source(BiomarkerSource(1, ("Bcr-Abl",), ())),
            source(BiomarkerSource(1, ("BCR-ABL",), ()), indication_id=2),
        )
    )
    assert report.case_variants == {"bcr-abl": ("BCR-ABL", "Bcr-Abl")}


def test_context_and_sex_normalisers_keep_raw_alternatives():
    row = replace(source(), context=("1L", "Adjuvant", "not applicable"), sex="female")
    (context,) = ContextNormaliser().normalise(row)
    (sex,) = SexNormaliser().normalise(row)
    assert isinstance(context, ContextCriterion)
    assert [term.setting for term in context.terms] == [
        Setting.FIRST_LINE,
        Setting.ADJUVANT,
    ]
    assert context.raw == "1L|Adjuvant|not applicable"
    assert isinstance(sex, SexCriterion) and sex.sex.value == "female"
    assert (
        ContextNormaliser().normalise(replace(row, context=("not applicable",))) == ()
    )
    assert isinstance(
        SexNormaliser().normalise(replace(row, sex="unexpected"))[0], RawCriterion
    )


def test_indication_lint_reports_unparsed_values_without_invariant_failures():
    row = replace(
        source(BiomarkerSource(1, ("BCR-ABL",), ("ITD",))),
        stage="unmapped stage",
        context=("unmapped setting",),
    )
    report = lint_indications((row,))
    diagnostics = dict(report.diagnostics)
    assert diagnostics["Unparsed findings"] == {"ITD": 1}
    assert diagnostics["Unparsed stage values"] == {"unmapped stage": 1}
    assert report.has_unparsed and report.invariant_failures == ()


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
        indications_ContextMap.__table__,
        indications_DemographicsMap.__table__,
        indications_Prior_therapy_negationMap.__table__,
        indications_Prior_therapy_settingMap.__table__,
        indications_Response_contingencyMap.__table__,
        indications_Risk_stratificationMap.__table__,
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
        connection.execute(
            indications_ContextMap.__table__.insert().values(parent_id=1, context="1L")
        )
        connection.execute(
            indications_DemographicsMap.__table__.insert().values(
                parent_id=1, demographics="adults"
            )
        )
        for table, column, value in (
            (indications_Prior_therapy_settingMap, "prior_therapy_setting", "adjuvant"),
            (indications_Prior_therapy_negationMap, "prior_therapy_negation", "FALSE"),
            (
                indications_Response_contingencyMap,
                "response_contingency",
                "progression",
            ),
            (indications_Risk_stratificationMap, "risk_stratification", "high risk"),
        ):
            connection.execute(
                table.__table__.insert().values(parent_id=1, **{column: value})
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

    assert len(calls) == 14
    assert indication.regimen_cuis == (77,)
    assert indication.withdrawn and indication.raw["withdrawn"] == "2025-01-01"
    biomarkers = [
        item for item in indication.criteria if isinstance(item, BiomarkerCriterion)
    ]
    assert [(item.slot, item.biomarker) for item in biomarkers] == [
        (1, "ER"),
        (2, "pr"),
        (3, "HER2"),
        (4, "ros1"),
    ]
    (context,) = [
        item for item in indication.criteria if isinstance(item, ContextCriterion)
    ]
    assert context.terms[0].setting is Setting.FIRST_LINE
    raw_criteria = {
        criterion.dimension: criterion.raw
        for criterion in indication.criteria
        if isinstance(criterion, RawCriterion)
    }
    assert raw_criteria == {
        "demographics": "adults",
        "prior_therapy_setting": "adjuvant",
        "response_contingency": "progression",
        "risk_stratification": "high risk",
    }


def test_wheel_contains_indication_package_files_when_uv_is_available(tmp_path):
    uv = shutil.which("uv")
    if uv is None:
        import pytest

        pytest.skip("uv is unavailable; wheel packaging check requires uv build")
    repository = Path(__file__).resolve().parents[1]
    subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(tmp_path)],
        check=True,
        cwd=repository,
        capture_output=True,
        text=True,
    )
    wheel = next(tmp_path.glob("*.whl"))
    package = importlib.resources.files("hemonc_alchemy.toolkit.core.indications")
    files = [entry.name for entry in package.iterdir() if entry.is_file()]
    with zipfile.ZipFile(wheel) as archive:
        members = set(archive.namelist())
    assert all(
        f"hemonc_alchemy/toolkit/core/indications/{name}" in members for name in files
    )
    assert all(
        f"hemonc_alchemy/toolkit/core/indications/normalisers/{name}" in members
        for name in ("age.py", "biomarker.py", "context.py", "scope.py", "sex.py")
    )
    vocabulary = importlib.resources.files(
        "hemonc_alchemy.toolkit.core.indication_vocabulary"
    )
    tables = [entry.name for entry in vocabulary.joinpath("data").iterdir()]
    modules = [entry.name for entry in vocabulary.iterdir() if entry.is_file()]
    assert tables and modules
    assert all(
        f"hemonc_alchemy/toolkit/core/indication_vocabulary/data/{name}" in members
        for name in tables
    )
    assert all(
        f"hemonc_alchemy/toolkit/core/indication_vocabulary/{name}" in members
        for name in modules
    )
