"""Catalogue contracts on isolated tables; repeat with HEMONC_CATALOGUE_POSTGRES=1."""

import os

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from hemonc_alchemy.toolkit.core.catalogue import (
    CatalogueSpec,
    IndicationSpec,
    Pagination,
    condition_regimen_association_statement,
    get_variant,
    list_indications,
    list_regimens,
    list_variants,
    search_conditions,
)

TABLES = {
    "conditions": "id INTEGER, condition_cui BIGINT, condition TEXT, section TEXT",
    "regimens": "id INTEGER, regimen_cui BIGINT, regimen_name TEXT, regimen_type TEXT",
    "variants": "id INTEGER, variant_cui BIGINT, version INTEGER, regimen_cui BIGINT, regimen TEXT, variant TEXT, fullyspecified BOOLEAN",
    "sigs": "id INTEGER, variant_cui BIGINT, component TEXT",
    "studies": "id INTEGER, study TEXT, condition_cui BIGINT, substudy TEXT",
    "variants_study": "parent_id INTEGER, study TEXT",
    "study_results": "study TEXT, context TEXT",
    "indications": "id INTEGER, condition_cui BIGINT, condition TEXT, component_cui BIGINT, component TEXT, regulator TEXT, withdrawn TEXT, status TEXT, stage TEXT, biomarker TEXT, prior_therapy TEXT",
    "indications_regimen_cui": "parent_id INTEGER, regimen_cui BIGINT",
}
DATA = {
    "conditions": "(1,1,'Condition A','Area A'),(2,2,'Condition B','Area B'),(3,3,'100% literal','Undefined')",
    "regimens": "(1,10,'Regimen A','COMPONENT_TO_BASED_REGIMEN'),(2,20,'Regulatory only','COMPONENT_TO_BASED_REGIMEN'),(3,30,'No studies','COMPONENT_TO_BASED_REGIMEN'),(4,40,'Same name','COMPONENT_TO_BASED_REGIMEN'),(5,50,'Same name','COMPONENT_TO_BASED_REGIMEN')",
    "variants": "(1,100,-1,10,'Regimen A','Historical',false),(2,100,0,10,'Regimen A','Latest',false),(3,101,1,10,'Regimen A','No sigs',false),(4,102,1,10,'Regimen A','Other condition',false),(5,300,1,30,'No studies','Unlinked',false),(6,400,1,999,'Broken parent','Orphan',false)",
    "sigs": "(1,100,'Drug A'),(2,100,'Drug B'),(3,102,'Drug B'),(4,300,'Drug A')",
    "studies": "(1,'study-a',1,NULL),(2,'study-a',2,NULL),(3,'study-b',2,NULL),(4,'history-only',3,NULL)",
    "variants_study": "(1,'history-only'),(2,'study-a'),(3,'study-a'),(4,'study-b'),(6,'missing-study')",
    "study_results": "('study-a','adjuvant'),('study-b','palliative')",
    "indications": "(1,1,'Condition A',7,'Drug A','FDA','FALSE','Metastatic',NULL,NULL,NULL),(2,1,'Condition A',8,'Drug B','EMA','2020-01-01',NULL,NULL,NULL,NULL),(3,NULL,'Unmapped',9,'Drug C','FDA','TRUE',NULL,NULL,NULL,NULL),(4,99,'Missing condition',9,'Drug C','FDA','FALSE',NULL,NULL,NULL,NULL)",
    "indications_regimen_cui": "(1,10),(2,20),(4,999)",
}


@pytest.fixture
def catalogue_session(request):
    postgres = os.getenv("HEMONC_CATALOGUE_POSTGRES") == "1"
    engine = (
        request.getfixturevalue("pg_engine")
        if postgres
        else sa.create_engine("sqlite://")
    )
    with engine.connect() as conn:
        transaction = conn.begin()
        for name, columns in TABLES.items():
            conn.exec_driver_sql(f"CREATE TEMPORARY TABLE {name} ({columns})")
            conn.execute(sa.text(f"INSERT INTO {name} VALUES {DATA[name]}"))
        with Session(bind=conn) as session:
            yield session
        transaction.rollback()
    if not postgres:
        engine.dispose()


def test_condition_scope_retains_regulatory_only_and_no_sig_variants(catalogue_session):
    page = list_regimens(catalogue_session, CatalogueSpec(condition_cuis=(1,)))
    assert page.total == 2
    rows = {row.regimen_cui: row for row in page.items}
    assert rows[10].matching_variant_count == 2
    assert rows[10].study_count == 1
    assert rows[10].study_linked and rows[10].regulatory_linked
    assert rows[20].matching_variant_count == 0
    assert not rows[20].study_linked and rows[20].regulatory_linked
    variants = list_variants(catalogue_session, CatalogueSpec(condition_cuis=(1,)))
    assert {(v.variant_cui, v.version, v.sig_count) for v in variants.items} == {
        (100, 0, 2),
        (101, 1, 0),
    }


def test_latest_is_selected_before_condition_matching(catalogue_session):
    assert (
        list_variants(catalogue_session, CatalogueSpec(condition_cuis=(3,))).total == 0
    )
    history = list_variants(
        catalogue_session, CatalogueSpec(condition_cuis=(3,), version_policy="all")
    )
    assert [(v.variant_cui, v.version) for v in history.items] == [(100, -1)]
    assert get_variant(catalogue_session, 100, -1).version == -1
    assert get_variant(catalogue_session, 100, 99) is None


def test_duplicate_study_name_preserves_both_conditions_without_fanout(
    catalogue_session,
):
    statement = condition_regimen_association_statement(
        CatalogueSpec(regimen_cuis=(10,), basis="study")
    )
    rows = catalogue_session.execute(statement).mappings().all()
    assert {(row["condition_cui"], row["evidence_id"]) for row in rows} == {
        (1, 1),
        (2, 2),
        (2, 3),
    }
    combined = list_regimens(catalogue_session, CatalogueSpec(condition_cuis=(1, 2, 1)))
    assert combined.items[0].matching_variant_count == 3
    assert combined.items[0].study_count == 3


def test_component_and_context_match_same_variant(catalogue_session):
    no_match = CatalogueSpec(
        condition_cuis=(2,), component_terms=("Drug A",), study_context="palliative"
    )
    assert list_regimens(catalogue_session, no_match).total == 0
    match = CatalogueSpec(
        condition_cuis=(2,), component_terms=("Drug B",), study_context="palliative"
    )
    assert list_regimens(catalogue_session, match).items[0].matching_variant_count == 1


def test_regulatory_orphans_and_raw_withdrawal_survive(catalogue_session):
    page = list_indications(catalogue_session)
    assert page.total == 4
    assert page.items[1].withdrawn == "2020-01-01"
    assert page.items[0].clinical_status == "Metastatic"
    assert (
        not page.items[2].condition_resolves and page.items[2].linked_regimen_count == 0
    )
    assert (
        not page.items[3].condition_resolves and page.items[3].linked_regimen_count == 0
    )
    assert (
        list_indications(catalogue_session, IndicationSpec(regulators=("fda",))).total
        == 3
    )
    assert (
        list_indications(catalogue_session, IndicationSpec(condition_cuis=())).total
        == 0
    )


def test_pagination_global_orphans_empty_scope_and_literal_search(catalogue_session):
    assert list_regimens(catalogue_session).total == 5
    unlinked = list_regimens(
        catalogue_session, CatalogueSpec(regimen_cuis=(30,))
    ).items[0]
    assert unlinked.matching_variant_count == 1 and unlinked.study_count == 0
    assert list_regimens(catalogue_session, CatalogueSpec(condition_cuis=())).total == 0
    assert get_variant(catalogue_session, 400, 1).regimen_cui == 999
    names = CatalogueSpec(q="Same name")
    first = list_regimens(catalogue_session, names, Pagination(page=1, page_size=1))
    second = list_regimens(catalogue_session, names, Pagination(page=2, page_size=1))
    assert first.total == second.total == 2
    assert [first.items[0].regimen_cui, second.items[0].regimen_cui] == [40, 50]
    assert search_conditions(catalogue_session, CatalogueSpec(q="%")).total == 1
    assert (
        search_conditions(catalogue_session, CatalogueSpec(q="2"))
        .items[0]
        .condition_cui
        == 2
    )


def test_basis_filter_and_constant_query_count(catalogue_session):
    calls = []
    engine = catalogue_session.get_bind()

    def count_calls(*args):
        calls.append(1)

    sa.event.listen(engine, "before_cursor_execute", count_calls)
    try:
        page = list_regimens(
            catalogue_session, CatalogueSpec(condition_cuis=(1,), basis="regulatory")
        )
        assert page.total == 2 and len(calls) == 2
        calls.clear()
        page = list_regimens(
            catalogue_session, CatalogueSpec(condition_cuis=(1,), basis="study")
        )
        assert page.total == 1 and len(calls) == 2
    finally:
        sa.event.remove(engine, "before_cursor_execute", count_calls)


@pytest.mark.parametrize(
    "arguments", [{"page": 0}, {"page_size": 0}, {"page_size": 101}]
)
def test_invalid_pagination(arguments):
    with pytest.raises(ValueError):
        Pagination(**arguments)


def test_invalid_query_policy():
    with pytest.raises(ValueError):
        CatalogueSpec(version_policy="oldest")
    with pytest.raises(ValueError):
        CatalogueSpec(basis="drug-inferred")
