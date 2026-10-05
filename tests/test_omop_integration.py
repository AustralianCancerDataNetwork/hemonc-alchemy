"""Unit checks for the optional OMOP integration boundary."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from hemonc_alchemy.integrations.omop import (
    condition_to_snomed,
    coverage_report,
    drug_to_rxnorm_ingredient,
    load_omop_binding,
    map_from_standard,
    map_to_standard,
    omop_available,
    resolve_hemonc_concepts,
    rxnorm_ingredient_to_drug,
    snomed_to_condition,
    vocabulary_versions,
)


def _sqlite_omop_session():
    engine = sa.create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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
    vocabulary = sa.Table(
        "vocabulary", metadata,
        sa.Column("vocabulary_id", sa.String, primary_key=True),
        sa.Column("vocabulary_name", sa.String), sa.Column("vocabulary_reference", sa.String),
        sa.Column("vocabulary_version", sa.String), sa.Column("vocabulary_concept_id", sa.Integer),
    )
    with engine.connect() as connection:
        metadata.create_all(connection)
        connection.execute(concept.insert(), [
            {"concept_id": 1, "concept_name": "Classical Hodgkin lymphoma", "domain_id": "Condition", "vocabulary_id": "HemOnc", "concept_class_id": "Condition", "concept_code": "614", "invalid_reason": None},
            {"concept_id": 2, "concept_name": "Hodgkin disease", "domain_id": "Condition", "vocabulary_id": "SNOMED", "concept_class_id": "Disorder", "standard_concept": "S", "concept_code": "118599009", "invalid_reason": None},
            {"concept_id": 3, "concept_name": "Cisplatin", "domain_id": "Drug", "vocabulary_id": "HemOnc", "concept_class_id": "Component", "concept_code": "105", "invalid_reason": None},
            {"concept_id": 4, "concept_name": "cisplatin", "domain_id": "Drug", "vocabulary_id": "RxNorm", "concept_class_id": "Ingredient", "standard_concept": "S", "concept_code": "2555", "invalid_reason": None},
            {"concept_id": 5, "concept_name": "Retired source", "domain_id": "Condition", "vocabulary_id": "HemOnc", "concept_class_id": "Condition", "concept_code": "999", "invalid_reason": "D"},
        ])
        connection.execute(relationship.insert(), [
            {"concept_id_1": 1, "concept_id_2": 2, "relationship_id": "Maps to"},
            {"concept_id_1": 3, "concept_id_2": 4, "relationship_id": "Maps to"},
            {"concept_id_1": 5, "concept_id_2": 2, "relationship_id": "Maps to"},
        ])
        connection.execute(vocabulary.insert(), [
            {"vocabulary_id": "HemOnc", "vocabulary_version": "test-hemonc"},
            {"vocabulary_id": "SNOMED", "vocabulary_version": "test-snomed"},
            {"vocabulary_id": "RxNorm", "vocabulary_version": "test-rxnorm"},
        ])
        connection.commit()
    return engine, sa.orm.Session(engine)


def test_absent_omop_is_a_noop():
    engine = sa.create_engine("sqlite://")
    session = sa.orm.Session(engine)
    assert not omop_available(session)
    assert resolve_hemonc_concepts(session, [614]) == []
    assert map_to_standard(session, [614]) == []
    assert map_from_standard(session, [2]) == []
    session.close()
    engine.dispose()


def test_present_omop_preserves_identifiers_and_mapping_rows():
    if load_omop_binding() is None:
        pytest.skip("the optional omop extra is not installed")
    engine, session = _sqlite_omop_session()
    try:
        resolved = resolve_hemonc_concepts(session, [614])
        assert resolved[0].hemonc_cui == "614"
        assert resolved[0].concept.concept_id == 1
        condition = condition_to_snomed(session, [614])
        assert condition[0].target is not None
        assert condition[0].target.concept_id == 2
        drug = drug_to_rxnorm_ingredient(session, [105])
        assert drug[0].target is not None
        assert drug[0].target.concept_code == "2555"
        assert resolve_hemonc_concepts(session, [999]) == []
        report = coverage_report(session, [614, 999], target_vocabulary="SNOMED")
        assert report.requested_cuis == 2
        assert report.resolved_cuis == 1
        assert report.mapped_cuis == 1
        assert report.unmatched_cuis == ("999",)
        assert {v.vocabulary_id for v in vocabulary_versions(session)} == {"HemOnc", "SNOMED", "RxNorm"}
    finally:
        session.close()
        engine.dispose()


def test_snomed_to_condition_is_the_reverse_of_condition_to_snomed():
    if load_omop_binding() is None:
        pytest.skip("the optional omop extra is not installed")
    engine, session = _sqlite_omop_session()
    try:
        # A non-Condition HemOnc source mapped onto the same SNOMED concept must not leak through.
        session.execute(sa.text(
            "INSERT INTO concept (concept_id, concept_name, domain_id, vocabulary_id, concept_class_id, concept_code)"
            " VALUES (6, 'Stray drug', 'Drug', 'HemOnc', 'Component', '777')"
        ))
        session.execute(sa.text(
            "INSERT INTO concept_relationship (concept_id_1, concept_id_2, relationship_id) VALUES (6, 2, 'Maps to')"
        ))
        session.commit()
        snomed_concept_id = condition_to_snomed(session, [614])[0].target.concept_id
        back = snomed_to_condition(session, [snomed_concept_id])
        assert [m.hemonc_cui for m in back] == ["614"]
        assert {m.hemonc_cui for m in map_from_standard(session, [snomed_concept_id])} == {"614", "777"}
        assert snomed_to_condition(session, [999999]) == []
    finally:
        session.close()
        engine.dispose()


def test_rxnorm_ingredient_to_drug_is_the_reverse_of_drug_to_rxnorm_ingredient():
    if load_omop_binding() is None:
        pytest.skip("the optional omop extra is not installed")
    engine, session = _sqlite_omop_session()
    try:
        forward = drug_to_rxnorm_ingredient(session, [105])
        rxnorm_concept_id = forward[0].target.concept_id
        back = rxnorm_ingredient_to_drug(session, [rxnorm_concept_id])
        assert len(back) == 1
        assert back[0].hemonc_cui == "105"
        assert back[0].hemonc_concept.concept_name == "Cisplatin"
        # Unknown/unmapped standard concept ids resolve to no rows.
        assert rxnorm_ingredient_to_drug(session, [999999]) == []
    finally:
        session.close()
        engine.dispose()


def test_biosimilars_and_combinations_share_one_canonical_drug_identity():
    from hemonc_alchemy.integrations.omop import (
        canonical_drug_names,
        hemonc_drug_canonical_names,
    )

    if load_omop_binding() is None:
        pytest.skip("the optional omop extra is not installed")
    engine, session = _sqlite_omop_session()
    try:
        # HemOnc: Rituximab (1), Rituximab-abbs (2), Rituximab and hyaluronidase human (3), Ziv-aflibercept (4);
        # RxNorm ingredients: rituximab (11), hyaluronidase (12), aflibercept (13).
        drugs = [(101, "Rituximab", "446"), (102, "Rituximab-abbs", "445"), (103, "Rituximab and hyaluronidase human", "447"),
                 (104, "Ziv-aflibercept", "500")]
        ingredients = [(111, "rituximab"), (112, "hyaluronidase"), (113, "aflibercept")]
        for cid, name, code in drugs:
            session.execute(sa.text(
                "INSERT INTO concept (concept_id, concept_name, domain_id, vocabulary_id, concept_class_id, concept_code)"
                " VALUES (:i, :n, 'Drug', 'HemOnc', 'Component', :c)"), {"i": cid, "n": name, "c": code})
        for cid, name in ingredients:
            session.execute(sa.text(
                "INSERT INTO concept (concept_id, concept_name, domain_id, vocabulary_id, concept_class_id, standard_concept, concept_code)"
                " VALUES (:i, :n, 'Drug', 'RxNorm', 'Ingredient', 'S', :c)"), {"i": cid, "n": name, "c": str(cid)})
        for source, target in [(101, 111), (102, 111), (103, 111), (103, 112), (104, 113)]:
            session.execute(sa.text(
                "INSERT INTO concept_relationship (concept_id_1, concept_id_2, relationship_id) VALUES (:a, :b, 'Maps to')"),
                {"a": source, "b": target})
        session.execute(sa.text(
            "INSERT INTO concept_relationship (concept_id_1, concept_id_2, relationship_id) VALUES (102, 101, 'Biosimilar of')"))
        session.commit()

        assert canonical_drug_names(session, [111, 112, 113, 999]) == {
            111: "Rituximab", 112: "Hyaluronidase", 113: "Ziv-aflibercept",
        }
        names = hemonc_drug_canonical_names(session)
        assert names["Rituximab-abbs"] == ("Rituximab",)
        assert names["Rituximab and hyaluronidase human"] == ("Hyaluronidase", "Rituximab")
        assert names["Ziv-aflibercept"] == ("Ziv-aflibercept",)
    finally:
        session.close()
        engine.dispose()
