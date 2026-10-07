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
    main_class_ancestry,
    map_from_standard,
    map_to_standard,
    omop_available,
    resolve_hemonc_concepts,
    rxnorm_ingredient_to_drug,
    snomed_to_condition,
    vocabulary_versions,
)
from hemonc_alchemy.toolkit.analytics.treatment.classification import DrugAncestry


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
        ingredients = [(111, "rituximab ingredient"), (112, "hyaluronidase"), (113, "aflibercept")]
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
        # Asked alone, rituximab keeps its label: the combination still counts as multi-ingredient.
        assert canonical_drug_names(session, [111]) == {111: "Rituximab"}
        names = hemonc_drug_canonical_names(session)
        assert names["Rituximab-abbs"] == ("Rituximab",)
        assert names["Rituximab and hyaluronidase human"] == ("Hyaluronidase", "Rituximab")
        assert names["Ziv-aflibercept"] == ("Ziv-aflibercept",)
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def ancestry_vocabulary():
    if load_omop_binding() is None:
        pytest.skip("the optional omop extra is not installed")
    engine, session = _sqlite_omop_session()
    binding = load_omop_binding()
    records = [
        (10, "44970", "Component Class", "HemOnc", None),
        (11, "20221", "Component Class", "HemOnc", None),
        (12, "900", "Component Class", "HemOnc", None),
        (13, "901", "Component Class", "HemOnc", None),
        (14, "100", "Component", "HemOnc", None),
        (15, "101", "Component", "HemOnc", None),
        (16, "102", "Component", "RxNorm", None),
        (17, "902", "Component Class", "HemOnc", "D"),
        (18, "103", "Component", "HemOnc", None),
        (19, "104", "Component", "HemOnc", "D"),
    ]
    session.execute(binding.concept.__table__.insert(), [
        {"concept_id": cid, "concept_code": code, "concept_name": code,
         "concept_class_id": cls, "vocabulary_id": vocab, "domain_id": "Drug", "invalid_reason": invalid}
        for cid, code, cls, vocab, invalid in records
    ])
    session.execute(binding.concept_relationship.__table__.insert(), [
        {"concept_id_1": source, "concept_id_2": target, "relationship_id": "Is a", "invalid_reason": invalid}
        for source, target, invalid in [
            (12, 10, None), (14, 12, None), (15, 13, "D"),
            (16, 12, None), (18, 17, None), (19, 12, None), (3, 13, None),
        ]
    ])
    session.commit()
    try:
        yield engine, session
    finally:
        session.close()
        engine.dispose()


def _source_drug_session(rows):
    engine = sa.create_engine("sqlite://", poolclass=StaticPool)
    metadata = sa.MetaData()
    drugs = sa.Table("drugs", metadata, sa.Column("main_class", sa.String), sa.Column("drug_cui", sa.Integer))
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(drugs.insert(), [{"main_class": cls, "drug_cui": cui} for cls, cui in rows])
    return engine, sa.orm.Session(engine)


def test_runtime_ancestry_joins_separate_databases_and_filters_active_edges(ancestry_vocabulary):
    _, vocabulary = ancestry_vocabulary
    source_engine, source = _source_drug_session([
        ("Hormone", 100), ("Invalid edge", 101), ("Wrong vocabulary", 102),
        ("Invalid target", 103), ("Invalid source", 104), ("Other", 105),
    ])
    try:
        index = main_class_ancestry(source, omop_session=vocabulary)
        assert index.unavailable_reason is None
        assert index.resolutions["Hormone"].status is DrugAncestry.ENDOCRINE
        assert index.resolutions["Other"].status is DrugAncestry.OTHER
        for cls in ("Invalid edge", "Wrong vocabulary", "Invalid target", "Invalid source"):
            assert index.resolutions[cls].status is DrugAncestry.UNRESOLVED
    finally:
        source.close()
        source_engine.dispose()


def test_runtime_ancestry_cache_is_scoped_to_both_engines_and_can_be_cleared(ancestry_vocabulary):
    _, vocabulary = ancestry_vocabulary
    source_engine, source = _source_drug_session([("Same label", 100)])
    other_engine, other_source = _source_drug_session([("Same label", 105)])
    try:
        index = main_class_ancestry(source, omop_session=vocabulary)
        with sa.orm.Session(bind=vocabulary.connection()) as same_engine_session:
            assert main_class_ancestry(source, omop_session=same_engine_session) is index
        other = main_class_ancestry(other_source, omop_session=vocabulary)
        assert other is not index
        assert other.resolutions["Same label"].status is DrugAncestry.OTHER
        vocabulary.execute(sa.text("UPDATE concept_relationship SET concept_id_2=11 WHERE concept_id_1=12"))
        vocabulary.commit()
        assert main_class_ancestry(source, omop_session=vocabulary) is index
        main_class_ancestry.cache_clear()
        refreshed = main_class_ancestry(source, omop_session=vocabulary)
        assert refreshed.resolutions["Same label"].status is DrugAncestry.SUPPORTIVE
        assert refreshed is not index
    finally:
        source.close()
        other_source.close()
        source_engine.dispose()
        other_engine.dispose()


def test_runtime_ancestry_missing_roots_is_not_a_negative_classification(ancestry_vocabulary):
    _, vocabulary = ancestry_vocabulary
    source_engine, source = _source_drug_session([("Hormone", 100)])
    try:
        vocabulary.execute(sa.text("UPDATE concept SET invalid_reason='D' WHERE concept_code='44970'"))
        vocabulary.commit()
        index = main_class_ancestry(source, omop_session=vocabulary)
        assert "44970" in index.unavailable_reason
        assert index.purity({"Hormone"}, DrugAncestry.ENDOCRINE) is None
    finally:
        source.close()
        source_engine.dispose()


def test_runtime_ancestry_absent_omop_preserves_source_transaction():
    engine, session = _source_drug_session([("Hormone", 100)])
    try:
        index = main_class_ancestry(session)
        assert index.unavailable_reason == "OMOP vocabulary is unavailable"
        assert index.purity({"Hormone"}, DrugAncestry.ENDOCRINE) is None
        assert session.scalar(sa.text("SELECT count(*) FROM drugs")) == 1
    finally:
        session.close()
        engine.dispose()


def test_runtime_ancestry_distinguishes_vocabulary_engines(ancestry_vocabulary):
    _, vocabulary = ancestry_vocabulary
    source_engine, source = _source_drug_session([("Hormone", 100)])
    other_engine, other_vocabulary = _sqlite_omop_session()
    binding = load_omop_binding()
    try:
        other_vocabulary.execute(binding.concept.__table__.insert(), [
            dict(row) for row in vocabulary.execute(sa.text("SELECT * FROM concept WHERE concept_id >= 10")).mappings()
        ])
        other_vocabulary.execute(binding.concept_relationship.__table__.insert(), [
            dict(row) for row in vocabulary.execute(sa.text("SELECT * FROM concept_relationship WHERE relationship_id='Is a'")).mappings()
        ])
        other_vocabulary.execute(sa.text("UPDATE concept_relationship SET concept_id_2=11 WHERE concept_id_1=12"))
        other_vocabulary.commit()
        endocrine = main_class_ancestry(source, omop_session=vocabulary)
        supportive = main_class_ancestry(source, omop_session=other_vocabulary)
        assert endocrine.resolutions["Hormone"].status is DrugAncestry.ENDOCRINE
        assert supportive.resolutions["Hormone"].status is DrugAncestry.SUPPORTIVE
        assert main_class_ancestry(source, omop_session=vocabulary) is endocrine
    finally:
        source.close()
        other_vocabulary.close()
        source_engine.dispose()
        other_engine.dispose()


def test_runtime_ancestry_retries_after_missing_relationships(ancestry_vocabulary):
    _, vocabulary = ancestry_vocabulary
    source_engine, source = _source_drug_session([("Hormone", 100)])
    try:
        vocabulary.execute(sa.text("DROP TABLE concept_relationship"))
        vocabulary.commit()
        missing = main_class_ancestry(source, omop_session=vocabulary)
        assert missing.unavailable_reason == "OMOP vocabulary is unavailable"
        assert vocabulary.scalar(sa.text("SELECT count(*) FROM concept")) > 0
        vocabulary.execute(sa.text("CREATE TABLE concept_relationship (concept_id_1 INTEGER, concept_id_2 INTEGER, relationship_id TEXT, invalid_reason TEXT, valid_start_date DATE, valid_end_date DATE)"))
        vocabulary.execute(sa.text("INSERT INTO concept_relationship (concept_id_1,concept_id_2,relationship_id) VALUES (12,10,'Is a'),(14,12,'Is a')"))
        vocabulary.commit()
        restored = main_class_ancestry(source, omop_session=vocabulary)
        assert restored.unavailable_reason is None
        assert restored.resolutions["Hormone"].status is DrugAncestry.ENDOCRINE
    finally:
        source.close()
        source_engine.dispose()
