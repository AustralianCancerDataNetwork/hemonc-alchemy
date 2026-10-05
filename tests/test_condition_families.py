"""Condition families against a hand-built hierarchy, plus coverage on SQLite and the variant index on Postgres."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from hemonc_alchemy.model import Conditions
from hemonc_alchemy.toolkit.core import condition_families as families_module
from hemonc_alchemy.toolkit.core import condition_targets as targets_module
from hemonc_alchemy.toolkit.core.condition_families import (
    compute_condition_families,
    compute_family_members,
    variant_families,
)
from hemonc_alchemy.toolkit.core.condition_targets import ConditionMapping

ROOT, MALIGNANT, SOLID, HEME, PEDIATRIC, CROSS, CLASSICAL = 30789, 124482, 44382, 46212, 46085, 46218, 46208
GI, COLON, MSI_COLON, LYMPHOMA, PEDS_HEME, PEDS_HODGKIN, AF, AF_CHILD, CARCINOID = 1, 2, 3, 4, 5, 6, 9, 10, 11

HIERARCHY = (
    (ROOT, "Condition", ()),
    (MALIGNANT, "Malignant neoplasm", (ROOT,)),
    (SOLID, "Malignant solid neoplasm", (MALIGNANT,)),
    (HEME, "Malignant hematologic neoplasm", (MALIGNANT,)),
    (PEDIATRIC, "Pediatric cancer", (MALIGNANT,)),
    (CROSS, "Cross-disciplinary condition", (ROOT,)),
    (CLASSICAL, "Classical hematologic condition", (ROOT,)),
    (GI, "Gastrointestinal cancer", (SOLID,)),
    (COLON, "Colon cancer", (GI,)),
    (MSI_COLON, "MSI-H Colon cancer", (COLON,)),
    (LYMPHOMA, "Lymphoma", (HEME,)),
    (PEDS_HEME, "Pediatric hematologic neoplasm", (PEDIATRIC,)),
    (PEDS_HODGKIN, "Classical Hodgkin lymphoma pediatric", (LYMPHOMA, PEDS_HEME)),
    (AF, "Atrial fibrillation", ()),
    (AF_CHILD, "Atrial fibrillation, valvular", (AF,)),
    (CARCINOID, "Carcinoid syndrome", (MALIGNANT,)),
)


PARENTS = {cui: found for cui, _name, found in HIERARCHY if found}
CUIS = [cui for cui, _name, _found in HIERARCHY]


def _families():
    return compute_condition_families(CUIS, PARENTS)


def test_condition_belongs_to_category_children_among_its_ancestors():
    found = _families()
    assert found[MSI_COLON] == {GI}
    assert found[PEDS_HODGKIN] == {LYMPHOMA, PEDS_HEME}


def test_category_and_nodes_above_it_stand_for_every_family_beneath():
    found = _families()
    assert found[SOLID] == {GI}
    assert found[MALIGNANT] == {GI, LYMPHOMA, PEDS_HEME}


def test_condition_outside_every_category_is_its_own_family_with_its_descendants():
    found = _families()
    assert found[AF] == {AF}
    assert found[AF_CHILD] == {AF}
    assert found[CARCINOID] == {CARCINOID}
    assert found[CROSS] == frozenset()
    assert {family for families in found.values() for family in families} == {GI, LYMPHOMA, PEDS_HEME, AF, CARCINOID}
    assert compute_family_members(found, PARENTS)[GI] == {GI, COLON, MSI_COLON}


@pytest.fixture
def imported_session(pg_session):
    try:
        count = pg_session.execute(sa.select(sa.func.count()).select_from(Conditions)).scalar_one()
    except sa.exc.DBAPIError as exc:
        pytest.skip(f"PostgreSQL test database has no imported HemOnc schema: {exc}")
    if count == 0:
        pytest.skip("PostgreSQL test database has no imported HemOnc rows")
    return pg_session


@pytest.mark.postgres
def test_variant_index_places_chop_in_lymphoma(imported_session):
    lymphoma = next(cui for cui, name in targets_module.condition_names(imported_session).items() if name == "Lymphoma")
    chop = 130614
    assert lymphoma in variant_families(imported_session)[chop]


def _sqlite_vocabulary_with_ancestry():
    from sqlalchemy.pool import StaticPool

    engine = sa.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    metadata = sa.MetaData()
    concept = sa.Table(
        "concept", metadata,
        sa.Column("concept_id", sa.Integer, primary_key=True),
        sa.Column("concept_name", sa.String), sa.Column("domain_id", sa.String),
        sa.Column("vocabulary_id", sa.String), sa.Column("concept_class_id", sa.String),
        sa.Column("standard_concept", sa.String), sa.Column("concept_code", sa.String),
        sa.Column("valid_start_date", sa.Date), sa.Column("valid_end_date", sa.Date),
        sa.Column("invalid_reason", sa.String),
    )
    relationship = sa.Table(
        "concept_relationship", metadata,
        sa.Column("concept_id_1", sa.Integer), sa.Column("concept_id_2", sa.Integer),
        sa.Column("relationship_id", sa.String), sa.Column("valid_start_date", sa.Date),
        sa.Column("valid_end_date", sa.Date), sa.Column("invalid_reason", sa.String),
    )
    ancestor = sa.Table(
        "concept_ancestor", metadata,
        sa.Column("ancestor_concept_id", sa.Integer, primary_key=True),
        sa.Column("descendant_concept_id", sa.Integer, primary_key=True),
        sa.Column("min_levels_of_separation", sa.Integer), sa.Column("max_levels_of_separation", sa.Integer),
    )
    # 100 malignant neoplastic disease > {110 colon carcinoma > 111 sigmoid adenocarcinoma, 120 lymphoma > 121 DLBCL}; 130 AF.
    concepts = {100: "MND", 110: "COLON_CA", 111: "SIGMOID_ADENO", 120: "LYMPHOMA", 121: "DLBCL", 130: "AF"}
    edges = [(100, 110, 1), (100, 111, 2), (110, 111, 1), (100, 120, 1), (100, 121, 2), (120, 121, 1)]
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(concept.insert(), [
            {"concept_id": cid, "concept_name": code, "domain_id": "Condition", "vocabulary_id": "SNOMED",
             "standard_concept": "S", "concept_code": code} for cid, code in concepts.items()
        ])
        connection.execute(relationship.insert(), [
            {"concept_id_1": cid, "concept_id_2": cid, "relationship_id": "Maps to"} for cid in concepts
        ])
        # MSI-H colon carcinoma: non-standard, standardised to colon carcinoma plus a value (a conjunction).
        connection.execute(concept.insert(), [
            {"concept_id": 140, "concept_name": "MSI_COLON_CA", "domain_id": "Condition", "vocabulary_id": "SNOMED",
             "standard_concept": None, "concept_code": "MSI_COLON_CA"},
            {"concept_id": 150, "concept_name": "High", "domain_id": "Meas Value", "vocabulary_id": "SNOMED",
             "standard_concept": "S", "concept_code": "HIGH"},
        ])
        connection.execute(relationship.insert(), [
            {"concept_id_1": 140, "concept_id_2": 110, "relationship_id": "Maps to"},
            {"concept_id_1": 140, "concept_id_2": 150, "relationship_id": "Maps to value"},
        ])
        connection.execute(ancestor.insert(), [
            {"ancestor_concept_id": a, "descendant_concept_id": d, "min_levels_of_separation": lv, "max_levels_of_separation": lv}
            for a, d, lv in edges + [(cid, cid, 0) for cid in concepts]
        ])
    return engine, sa.orm.Session(engine)


AGNOSTIC = 99
MAPPINGS = {
    **{cui: ConditionMapping(cui, name, (), None, None, None) for cui, name, _found in HIERARCHY},
    COLON: ConditionMapping(COLON, "Colon cancer", ("COLON_CA",), "exact", None, None),
    LYMPHOMA: ConditionMapping(LYMPHOMA, "Lymphoma", ("LYMPHOMA",), "exact", None, None),
    AF: ConditionMapping(AF, "Atrial fibrillation", ("AF",), "exact", None, None),
    MSI_COLON: ConditionMapping(MSI_COLON, "MSI-H Colon cancer", ("MSI_COLON_CA",), "exact", None, None),
    AGNOSTIC: ConditionMapping(AGNOSTIC, "NTRK-mutated Malignant solid neoplasm", ("MND",), "up", None, None),
}


@pytest.fixture
def covered_hierarchy(monkeypatch):
    parents = {**PARENTS, AGNOSTIC: (SOLID,)}
    monkeypatch.setattr(targets_module, "raw_condition_mappings", lambda session: MAPPINGS)
    monkeypatch.setattr(targets_module, "load_patches", dict)
    monkeypatch.setattr(targets_module, "load_overrides", list)
    monkeypatch.setattr(targets_module, "condition_parents", lambda session: parents)
    monkeypatch.setattr(families_module, "condition_parents", lambda session: parents)


@pytest.mark.usefixtures("covered_hierarchy")
def test_family_coverage_from_member_targets_with_disjoint_fallback():
    from hemonc_alchemy.integrations.omop import load_omop_binding
    from hemonc_alchemy.toolkit.core.condition_families import (
        families_for_concepts,
        family_anchors,
    )

    if load_omop_binding() is None:
        pytest.skip("the optional omop extra is not installed")
    engine, session = _sqlite_vocabulary_with_ancestry()
    try:
        anchors = family_anchors(session)
        assert anchors[GI].parent_ids == {110}  # colon cancer's target; the MSI-H conjunction adds nothing
        assert anchors[99].parent_ids == {100} and anchors[99].excluded_parent_ids == {120}
        assert PEDS_HEME not in anchors and CARCINOID not in anchors  # nothing usable: fail closed

        assert families_for_concepts(session, [111]) == {GI, 99}  # sigmoid adenocarcinoma
        assert families_for_concepts(session, [121]) == {LYMPHOMA}  # DLBCL: excluded from the solid fallback
        assert families_for_concepts(session, [130, None]) == {AF}
        assert families_for_concepts(session, [999]) == frozenset()
    finally:
        session.close()
        engine.dispose()
