"""`resolve_role`/`is_defining` as pure logic, and `attach_component_roles` against OMOP."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest
import sqlalchemy as sa
import sqlalchemy.orm as so

from hemonc_alchemy.integrations.omop import attach_component_roles, load_omop_binding
from hemonc_alchemy.model.base import Base
from hemonc_alchemy.model.entities import Drugs
from hemonc_alchemy.toolkit.analytics.treatment.classification.component_role import (
    ComponentRole,
    is_defining,
    resolve_role,
)
from hemonc_alchemy.toolkit.analytics.treatment.scheduling.templates import (
    CycleTemplate,
)

pytestmark = pytest.mark.skipif(
    len(Base.metadata.tables) == 0,
    reason="model/entities.py has no generated classes yet -- run `hemonc-alchemy regen` first",
)

_D = datetime(2020, 1, 1, tzinfo=UTC)


class TestResolveRole:
    def test_defining_relationship_wins_alone(self):
        assert resolve_role({"Cytotoxic chemo of"}) is ComponentRole.DEFINING

    def test_adjunct_relationship_alone(self):
        assert resolve_role({"Steroid tx of"}) is ComponentRole.ADJUNCT

    def test_no_relationship_is_untagged(self):
        assert resolve_role(set()) is ComponentRole.UNTAGGED

    def test_defining_wins_when_both_present(self):
        assert resolve_role({"Targeted therapy of", "Immunosuppressor of"}) is ComponentRole.DEFINING


class TestIsDefining:
    @pytest.mark.parametrize(
        "role,expected",
        [
            (ComponentRole.DEFINING, True),
            (ComponentRole.UNTAGGED, True),
            (ComponentRole.ADJUNCT, False),
        ],
    )
    def test_only_adjunct_is_not_defining(self, role, expected):
        assert is_defining(role) is expected


def _empty_template(iv_drug: list[str], po_drug: list[str]) -> CycleTemplate:
    return CycleTemplate(
        id="t", common_name="t", cycle_len=1, diseases=set(),
        iv_drug=iv_drug, po_drug=po_drug,
        binary_iv=pd.DataFrame(), binary_po=pd.DataFrame(), binary_fuzzy=pd.DataFrame(),
        dose_iv=pd.DataFrame(), dose_po=pd.DataFrame(),
        endocrine_regimen=False, supportive_regimen=False, drug_role={},
    )


@pytest.fixture
def session():
    if load_omop_binding() is None:
        pytest.skip("the optional omop extra is not installed")
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    Base.metadata.create_all(engine)

    omop_metadata = sa.MetaData()
    concept = sa.Table(
        "concept", omop_metadata,
        sa.Column("concept_id", sa.Integer, primary_key=True),
        sa.Column("concept_name", sa.String), sa.Column("domain_id", sa.String),
        sa.Column("vocabulary_id", sa.String), sa.Column("concept_class_id", sa.String),
        sa.Column("standard_concept", sa.String), sa.Column("concept_code", sa.String),
        sa.Column("valid_start_date", sa.Date), sa.Column("valid_end_date", sa.Date),
        sa.Column("invalid_reason", sa.String),
    )
    relationship = sa.Table(
        "concept_relationship", omop_metadata,
        sa.Column("concept_id_1", sa.Integer), sa.Column("concept_id_2", sa.Integer),
        sa.Column("relationship_id", sa.String), sa.Column("valid_start_date", sa.Date),
        sa.Column("valid_end_date", sa.Date), sa.Column("invalid_reason", sa.String),
    )
    with engine.connect() as connection:
        omop_metadata.create_all(connection)
        connection.execute(concept.insert(), [
            {"concept_id": 1, "concept_name": "Cyclophosphamide and Prednisone", "domain_id": "Regimen", "vocabulary_id": "HemOnc", "concept_class_id": "Regimen", "concept_code": "1001", "invalid_reason": None},
            {"concept_id": 2, "concept_name": "Unrelated regimen", "domain_id": "Regimen", "vocabulary_id": "HemOnc", "concept_class_id": "Regimen", "concept_code": "9999", "invalid_reason": None},
            {"concept_id": 10, "concept_name": "Cyclophosphamide", "domain_id": "Drug", "vocabulary_id": "HemOnc", "concept_class_id": "Component", "concept_code": "2001", "invalid_reason": None},
            {"concept_id": 11, "concept_name": "Prednisone", "domain_id": "Drug", "vocabulary_id": "HemOnc", "concept_class_id": "Component", "concept_code": "2002", "invalid_reason": None},
            {"concept_id": 12, "concept_name": "Vincristine", "domain_id": "Drug", "vocabulary_id": "HemOnc", "concept_class_id": "Component", "concept_code": "2003", "invalid_reason": None},
        ])
        connection.execute(relationship.insert(), [
            {"concept_id_1": 10, "concept_id_2": 1, "relationship_id": "Cytotoxic chemo of"},
            {"concept_id_1": 11, "concept_id_2": 1, "relationship_id": "Steroid tx of"},
            # Same drug, tagged for a different regimen -- must not leak into regimen 1001's resolution.
            {"concept_id_1": 10, "concept_id_2": 2, "relationship_id": "Immunosuppressor of"},
        ])
        connection.commit()

    with so.Session(engine) as s:
        s.add_all([
            Drugs(id=1, date_added=_D, drug="Cyclophosphamide", drug_cui=2001, investigational=False, multiagent=False),
            Drugs(id=2, date_added=_D, drug="Prednisone", drug_cui=2002, investigational=False, multiagent=False),
            Drugs(id=3, date_added=_D, drug="Vincristine", drug_cui=2003, investigational=False, multiagent=False),
        ])
        s.commit()
        yield s


class TestAttachComponentRoles:
    def test_classifies_each_drug_for_its_own_regimen(self, session):
        template = _empty_template(iv_drug=["Cyclophosphamide"], po_drug=["Prednisone", "Vincristine"])
        enriched = attach_component_roles(session, 1001, template)
        assert enriched.drug_role == {
            "Cyclophosphamide": ComponentRole.DEFINING,
            "Prednisone": ComponentRole.ADJUNCT,
            "Vincristine": ComponentRole.UNTAGGED,
        }

    def test_other_regimens_tags_do_not_leak_in(self, session):
        template = _empty_template(iv_drug=["Cyclophosphamide"], po_drug=[])
        enriched = attach_component_roles(session, 1001, template)
        assert enriched.drug_role["Cyclophosphamide"] is ComponentRole.DEFINING

    def test_no_drugs_is_a_noop(self, session):
        template = _empty_template(iv_drug=[], po_drug=[])
        assert attach_component_roles(session, 1001, template).drug_role == {}
