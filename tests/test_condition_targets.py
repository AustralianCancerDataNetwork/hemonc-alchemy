"""Source mappings and official OMOP code standardisation."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from hemonc_alchemy.config import create_default_hemonc_engine
from hemonc_alchemy.integrations.omop import load_omop_binding
from hemonc_alchemy.integrations.omop.schema import schema_aware_bind
from hemonc_alchemy.integrations.omop.standardise import (
    StandardisedCode,
    standardise_codes,
)
from hemonc_alchemy.toolkit.core.condition_targets import (
    ConditionMapping,
    accepted_codes,
    broader_codes,
    is_conjunction,
)


def test_condition_targets_use_only_exact_source_mappings():
    mappings = {
        1: ConditionMapping(1, "Breast cancer", ("254838004",), "exact", None, None),
        2: ConditionMapping(2, "Lymphoma", ("118956008",), "up", None, None),
        3: ConditionMapping(3, "Unmapped", (), None, None, None),
    }

    assert accepted_codes(mappings) == {1: ("254838004",)}
    assert broader_codes(mappings) == {2: ("118956008",)}


def _sqlite_vocabulary():
    engine = create_default_hemonc_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
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
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(concept.insert(), [
            {"concept_id": 1, "concept_name": "Carcinoma of breast", "domain_id": "Condition", "vocabulary_id": "SNOMED", "standard_concept": "S", "concept_code": "254838004"},
            {"concept_id": 2, "concept_name": "HER2-positive carcinoma of breast", "domain_id": "Condition", "vocabulary_id": "SNOMED", "standard_concept": None, "concept_code": "427685000"},
            {"concept_id": 3, "concept_name": "Positive", "domain_id": "Meas Value", "vocabulary_id": "SNOMED", "standard_concept": "S", "concept_code": "10828004"},
            {"concept_id": 4, "concept_name": "Glioblastoma", "domain_id": "Observation", "vocabulary_id": "SNOMED", "standard_concept": "S", "concept_code": "63634009"},
        ])
        connection.execute(relationship.insert(), [
            {"concept_id_1": 1, "concept_id_2": 1, "relationship_id": "Maps to"},
            {"concept_id_1": 4, "concept_id_2": 4, "relationship_id": "Maps to"},
            {"concept_id_1": 2, "concept_id_2": 1, "relationship_id": "Maps to"},
            {"concept_id_1": 2, "concept_id_2": 3, "relationship_id": "Maps to value"},
        ])
    return engine, sa.orm.Session(schema_aware_bind(engine, {"vocab": None}))


def test_standardise_codes_uses_official_omop_vocabulary():
    if load_omop_binding() is None:
        pytest.skip("the optional omop extra is not installed")
    engine, session = _sqlite_vocabulary()
    try:
        result = standardise_codes(session, ["254838004", "427685000", "63634009", "999"])
        assert result["254838004"] == StandardisedCode(1, True, frozenset({1}), False)
        assert result["427685000"] == StandardisedCode(2, False, frozenset({1}), True)
        assert result["63634009"].condition_leg == frozenset()
        assert "999" not in result
        assert is_conjunction(result["427685000"])
    finally:
        session.close()
        engine.dispose()
