"""Contract tests for the model-facing toolkit query APIs."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from hemonc_alchemy.config import create_default_hemonc_engine
from hemonc_alchemy.toolkit.analytics.treatment.filters import (
    standalone_radiation_sig_statement,
)
from hemonc_alchemy.toolkit.analytics.treatment.selection import (
    CategoryRequirement,
    ComponentRequirement,
    TreatmentSelectionSpec,
    build_variant_statement,
)
from hemonc_alchemy.toolkit.analytics.treatment.selection.components import (
    category_expression,
)
from hemonc_alchemy.toolkit.core import SigSelectionSpec, sig_search_statement
from hemonc_alchemy.toolkit.core.components import (
    component_cui_subquery,
    component_search_statement,
)
from hemonc_alchemy.toolkit.core.conditions import condition_cui_statement
from hemonc_alchemy.toolkit.core.links import sig_study_tokens


def _sql(statement: sa.Select) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_condition_lookup_is_composable_and_exact():
    sql = _sql(condition_cui_statement("Acute myeloid leukemia"))

    assert "conditions.condition IN ('Acute myeloid leukemia')" in sql


def test_standalone_radiation_filter_uses_normalized_study_links():
    sql = _sql(standalone_radiation_sig_statement([123]))

    assert 'JOIN "primary".sigs_study ON "primary".sigs_study.parent_id = "primary".sigs.id' in sql
    assert "sigs.class_field = 'RAD_SIG'" in sql
    assert "sigs.variant_cui IS NULL" in sql


def test_sig_selection_uses_normalized_links_and_explicit_nonvariant_policy():
    spec = SigSelectionSpec.for_conditions(
        [123],
        component_terms="External beam radiotherapy",
        variant_policy="none",
        class_field="rad sig",
    )
    sql = _sql(sig_search_statement(spec))

    assert 'JOIN "primary".sigs_study ON "primary".sigs_study.parent_id = "primary".sigs.id' in sql
    assert "sigs.component ILIKE '%%External beam radiotherapy%%'" in sql
    assert "sigs.variant_cui IS NULL" in sql
    assert "sigs.class_field = 'RAD_SIG'" in sql


@pytest.mark.parametrize(
    ("component_terms", "component_columns", "joined_tables"),
    [
        ((), ("component",), ()),
        (("cisplatin",), ("component",), ()),
        (("cisplatin",), ("drug",), ("drugs",)),
        (
            ("cytotoxic",),
            ("canmed_major_class",),
            ("drugs", "drugs_canmed_major_class"),
        ),
    ],
)
def test_sig_selection_adds_only_required_component_joins(
    component_terms, component_columns, joined_tables
):
    spec = SigSelectionSpec.for_conditions(
        [123],
        component_terms=component_terms,
        component_columns=component_columns,
    )
    sql = _sql(sig_search_statement(spec))

    for table in ("drugs", "drugs_canmed_major_class", "drugs_canmed_minor_class"):
        if table in joined_tables:
            assert f'JOIN "primary".{table}' in sql
        else:
            assert f'JOIN "primary".{table}' not in sql


def test_sig_selection_rejects_unknown_search_column():
    with pytest.raises(ValueError, match="Unknown component search column"):
        SigSelectionSpec.for_conditions([123], component_columns=("not_a_column",))


def test_variant_selection_ranks_versions_and_normalizes_phase():
    spec = TreatmentSelectionSpec.for_conditions(
        [123],
        component_requirements=(ComponentRequirement.from_terms("cisplatin"),),
        category_requirements=(CategoryRequirement("cytotoxic", 1),),
        phase="Adjuvant",
    )
    sql = _sql(
        build_variant_statement(
            spec,
            category_mapping={"main_class": {"Platinum agent": "cytotoxic"}},
        )
    )

    assert 'row_number() OVER (PARTITION BY "primary".variants.variant_cui' in sql
    assert 'variants_study.parent_id = "primary".variants.id' in sql
    assert "sigs.phase = 'ADJUVANT'" in sql
    assert "count(DISTINCT categorized_components.sig_id)" in sql


def test_sig_study_tokens_reads_current_normalized_map_rows():
    class StudyLink:
        def __init__(self, study: str):
            self.study = study

    class Sig:
        def __init__(self):
            self.study_items = [
                StudyLink("NCT-1"),
                StudyLink("NCT-2"),
                StudyLink("NCT-1"),
            ]

    assert sig_study_tokens(Sig()) == ["NCT-1", "NCT-2"]


def test_unknown_phase_fails_at_statement_boundary():
    spec = TreatmentSelectionSpec.for_conditions([123], phase="not-a-phase")

    with pytest.raises(ValueError, match="Unknown sig phase: 'not-a-phase'"):
        build_variant_statement(spec)


def test_category_requirements_require_an_explicit_mapping():
    spec = TreatmentSelectionSpec.for_conditions(
        [123], category_requirements=(CategoryRequirement("cytotoxic", 0),)
    )

    with pytest.raises(ValueError, match="category_mapping is required"):
        build_variant_statement(spec)


def test_category_expression_supports_one_column_and_rejects_empty_mapping():
    metadata = sa.MetaData()
    components = sa.Table(
        "components",
        metadata,
        sa.Column("main_class", sa.String),
    )
    engine = create_default_hemonc_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(components.insert(), [{"main_class": "Platinum agent"}])
        value = connection.execute(
            sa.select(
                category_expression(
                    components,
                    {"main_class": {"Platinum agent": "cytotoxic"}},
                )
            )
        ).scalar_one()
    assert value == "cytotoxic"

    with pytest.raises(ValueError, match="must not be empty"):
        category_expression(components, {"main_class": {}})


@pytest.mark.parametrize(
    "builder", [component_search_statement, component_cui_subquery]
)
def test_component_search_rejects_empty_columns(builder):
    with pytest.raises(ValueError, match="At least one component search column"):
        builder("cisplatin", columns=())
