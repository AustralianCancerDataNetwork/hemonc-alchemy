"""Study reference and context-grain regressions on tiny synthetic data."""

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from hemonc_alchemy.config import create_default_hemonc_engine
from hemonc_alchemy.model import Sigs, Studies, Variants
from hemonc_alchemy.model.relationships import study_context_predicate
from hemonc_alchemy.toolkit.analytics.treatment.filters import (
    studies_with_standalone_radiation_sigs_statement,
)
from hemonc_alchemy.toolkit.analytics.treatment.selection.components import (
    build_component_statement,
)
from hemonc_alchemy.toolkit.analytics.treatment.selection.specs import (
    TreatmentSelectionSpec,
)
from hemonc_alchemy.toolkit.core.catalogue.associations import (
    study_association_statement,
)
from hemonc_alchemy.toolkit.core.catalogue.specs import CatalogueSpec
from hemonc_alchemy.toolkit.core.catalogue.variants import variant_identity_statement
from hemonc_alchemy.toolkit.core.sigs import SigSelectionSpec, sig_search_statement


@pytest.fixture(params=[
    "sqlite",
    pytest.param("duckdb", marks=[pytest.mark.duckdb, pytest.mark.db_dialect]),
    pytest.param("postgresql", marks=[pytest.mark.postgres, pytest.mark.db_dialect]),
])
def study_session(request):
    backend = request.param
    if backend == "postgresql":
        engine = request.getfixturevalue("pg_engine")
        schema = "pg_temp"
    elif backend == "duckdb":
        pytest.importorskip("duckdb_sqlalchemy")
        engine = create_default_hemonc_engine("duckdb:///:memory:")
        schema = None
    else:
        engine = create_default_hemonc_engine("sqlite://")
        schema = "temp"
    definitions = {
        "variants": "id INTEGER, variant_cui BIGINT, version INTEGER, regimen_cui BIGINT, regimen TEXT, variant TEXT",
        "sigs": "id INTEGER, variant_cui BIGINT, component_cui BIGINT, component TEXT, class_field TEXT, regimen TEXT",
        "studies": "id INTEGER, study TEXT, substudy TEXT, study_cui BIGINT, substudy_cui BIGINT, condition_cui BIGINT, biomarker_finding TEXT",
        "variants_study": "parent_id INTEGER, study TEXT",
        "sigs_study": "parent_id INTEGER, study TEXT",
        "study_results": "study TEXT, study_cui BIGINT, substudy_cui BIGINT, condition_cui BIGINT, context TEXT, biomarker_finding TEXT",
        "drugs": "id INTEGER, drug_cui BIGINT, drug TEXT, drug_inn TEXT, main_class TEXT",
        "drugs_canmed_major_class": "parent_id INTEGER, canmed_major_class TEXT",
        "drugs_canmed_minor_class": "parent_id INTEGER, canmed_minor_class TEXT",
        "conditions": "condition_cui BIGINT",
        "regimens": "regimen_cui BIGINT",
    }
    inserts = {
        "variants": "(1,100,1,10,'Regimen','Variant'),(2,101,1,10,'Regimen','Variant X')",
        "sigs": "(1,100,7,'Drug','IV_INTERMITTENT_CANONICAL_SIG','Regimen'),(2,NULL,8,'Radiation','RAD_SIG','Radiation therapy'),(3,101,7,'Drug','IV_INTERMITTENT_CANONICAL_SIG','Regimen')",
        "studies": "(1,'Trial','A',11,111,1,NULL),(2,'Trial','A',11,111,2,NULL),(3,'Trial','B',11,112,1,NULL),(4,'Trial X',NULL,12,NULL,3,NULL)",
        "variants_study": "(1,'Trial--A'),(2,'Trial X')",
        "sigs_study": "(1,'Trial--A'),(2,'Trial--A'),(3,'Trial X')",
        "study_results": "('Trial',11,111,1,'adjuvant',NULL),('Trial',11,111,2,'palliative',NULL),('Trial',11,112,1,'neoadjuvant',NULL),('Trial X',12,NULL,3,'adjuvant',NULL)",
        "conditions": "(1),(2),(3)",
        "regimens": "(10)",
    }
    with engine.connect().execution_options(schema_translate_map={"primary": schema}) as conn:
        for table, columns in definitions.items():
            conn.exec_driver_sql(f"CREATE TEMPORARY TABLE {table} ({columns})")
        for table, values in inserts.items():
            conn.exec_driver_sql(f"INSERT INTO {table} VALUES {values}")
        with Session(bind=conn) as session:
            yield session
    if backend != "postgresql":
        engine.dispose()


def test_sig_search_matches_qualified_substudy(study_session):
    statement = sig_search_statement(SigSelectionSpec.for_conditions([1])).with_only_columns(Sigs.id)
    assert set(study_session.scalars(statement)) == {1, 2}


def test_standalone_radiation_studies_match_qualified_substudy(study_session):
    assert list(study_session.scalars(studies_with_standalone_radiation_sigs_statement([1]))) == [1]


def test_component_selection_matches_qualified_substudy(study_session):
    statement = build_component_statement(
        TreatmentSelectionSpec.for_conditions([1])
    ).with_only_columns(Variants.variant_cui)
    assert list(study_session.scalars(statement)) == [100]


@pytest.mark.parametrize("path", ["variants", "associations", "sigs", "components"])
@pytest.mark.parametrize("condition,context,expected", [
    (1, "palliative", []),  # Same study/substudy, different condition.
    (2, "adjuvant", []),
    (1, "neoadjuvant", []),  # Same study/condition, different substudy.
    (1, "adjuvant", [100]),
    (3, "adjuvant", [101]),  # NULL substudy codes must match each other.
])
def test_context_belongs_to_the_matched_study_row(study_session, path, condition, context, expected):
    assert list(study_session.scalars(_context_statement(path, condition, context))) == expected


def _context_statement(path, condition, context):
    if path == "variants":
        statement = variant_identity_statement(CatalogueSpec(
            condition_cuis=(condition,), study_context=context,
        )).with_only_columns(Variants.variant_cui)
    elif path == "associations":
        statement = study_association_statement(CatalogueSpec(
            condition_cuis=(condition,), study_context=context,
        )).with_only_columns(Variants.variant_cui)
    elif path == "sigs":
        statement = sig_search_statement(SigSelectionSpec.for_conditions(
            [condition], study_context=context,
        )).with_only_columns(Sigs.variant_cui).where(Sigs.variant_cui.is_not(None))
    else:
        statement = build_component_statement(TreatmentSelectionSpec.for_conditions(
            [condition], study_context=context,
        )).with_only_columns(Variants.variant_cui)
    return statement


@pytest.mark.parametrize("path", ["variants", "associations", "sigs", "components"])
@pytest.mark.parametrize("result_cui,study_cui,result_name,result_condition,expected", [
    (None, 12, "Trial X", 3, [101]),
    (None, None, "Trial X", 3, [101]),
    (None, None, "Unrelated trial", 3, []),
    (99, 12, "Trial X", 3, []),
    (None, 12, "Trial X", 1, []),
])
def test_context_name_fallback_requires_missing_result_cui_and_matching_grain(
    study_session, path, result_cui, study_cui, result_name, result_condition, expected,
):
    study_session.execute(sa.text("UPDATE studies SET study_cui=:cui WHERE id=4"), {"cui": study_cui})
    study_session.execute(sa.text(
        "UPDATE study_results SET study_cui=:cui,study=:name,condition_cui=:condition "
        "WHERE study='Trial X'"
    ), {"cui": result_cui, "name": result_name, "condition": result_condition})
    assert list(study_session.scalars(_context_statement(path, 3, "adjuvant"))) == expected


@pytest.mark.parametrize("study_biomarker,result_biomarker,expected", [
    (None, None, [1]),
    ("HER2-mutated", "HER2-mutated", [1]),
    ("HER2-mutated", "ERBB3-mutated", []),
    (None, "HER2-mutated", []),
    ("HER2-mutated", None, []),
])
def test_context_stays_with_its_biomarker_cohort(
    study_session, study_biomarker, result_biomarker, expected,
):
    study_session.execute(sa.text(
        "UPDATE studies SET biomarker_finding=:finding WHERE id=1"
    ), {"finding": study_biomarker})
    study_session.execute(sa.text(
        "UPDATE study_results SET biomarker_finding=:finding "
        "WHERE study_cui=11 AND substudy_cui=111 AND condition_cui=1"
    ), {"finding": result_biomarker})
    statement = sa.select(Studies.id).where(
        Studies.id == 1, study_context_predicate("adjuvant"),
    )
    assert list(study_session.scalars(statement)) == expected


@pytest.mark.parametrize("path", ["variants", "associations", "sigs", "components"])
@pytest.mark.parametrize("stored,selected,expected", [
    ("consolidation|maintenance", "consolidation", [100]),
    ("consolidation|maintenance", "maintenance", [100]),
    ("consolidation|maintenance|salvage", "maintenance", [100]),
    ("consolidation|maintenance", "maint", []),
    ("maintenance extended|consolidation", "maintenance", []),
    ("consolidation|maintenance", "maintenance extended", []),
    ("dose 10%|dose_20|path/a", "dose 10%", [100]),
    ("dose 100|doseX20|pathXa", "dose 10%", []),
    ("dose 100|doseX20|pathXa", "dose_20", []),
    ("dose 10%|dose_20|path/a", "dose_20", [100]),
    ("dose 10%|dose_20|path/a", "path/a", [100]),
    ("consolidation|maintenance", "consolidation|maintenance", [100]),
    ("induction|consolidation|maintenance", "consolidation|maintenance", []),
])
def test_study_context_matches_whole_pipe_tokens(study_session, path, stored, selected, expected):
    study_session.execute(sa.text(
        "UPDATE study_results SET context=:context "
        "WHERE study_cui=11 AND substudy_cui=111 AND condition_cui=1"
    ), {"context": stored})
    assert list(study_session.scalars(_context_statement(path, 1, selected))) == expected
