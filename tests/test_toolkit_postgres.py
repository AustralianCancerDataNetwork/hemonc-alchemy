"""Executable toolkit checks against an imported PostgreSQL database."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from hemonc_alchemy.model import Conditions, Drugs, Sigs, Studies, Variants
from hemonc_alchemy.model.entities import sigs_StudyMap, variants_StudyMap
from hemonc_alchemy.toolkit.analytics.treatment.bundles import VariantBundle
from hemonc_alchemy.toolkit.analytics.treatment.filters import (
    find_standalone_radiation_sigs,
)
from hemonc_alchemy.toolkit.analytics.treatment.selection import (
    CategoryRequirement,
    TreatmentSelectionSpec,
    select_variants,
)
from hemonc_alchemy.toolkit.core.components import search_components
from hemonc_alchemy.toolkit.core.conditions import conditions_by_names
from hemonc_alchemy.toolkit.core.links import (
    sig_condition_objects,
    sig_study_objects,
    sig_study_tokens,
    study_variant_objects,
)

pytestmark = pytest.mark.postgres


def test_condition_component_and_normalized_sig_links(imported_hemonc_session):
    condition_name, condition_cui = imported_hemonc_session.execute(
        sa.select(Conditions.condition, Conditions.condition_cui)
        .order_by(Conditions.condition_cui)
        .limit(1)
    ).one()
    assert [row.condition_cui for row in conditions_by_names(imported_hemonc_session, condition_name)] == [condition_cui]

    hits = search_components(imported_hemonc_session, "cisplatin")
    assert hits
    assert any(hit.drug_inn == "cisplatin" for hit in hits)

    rt_cui = imported_hemonc_session.execute(
        sa.select(Studies.condition_cui)
        .join(sigs_StudyMap, sigs_StudyMap.study == Studies.study)
        .join(Sigs, sigs_StudyMap.parent_id == Sigs.id)
        .where(
            Studies.condition_cui.is_not(None),
            Sigs.class_field == "RAD_SIG",
            Sigs.regimen == "Radiation therapy",
            Sigs.variant_cui.is_(None),
        )
        .order_by(Studies.condition_cui)
        .limit(1)
    ).scalar_one_or_none()
    if rt_cui is None:
        pytest.skip("imported database has no standalone radiation sigs")
    sigs = find_standalone_radiation_sigs(imported_hemonc_session, [rt_cui])
    assert sigs
    assert sig_study_tokens(sigs[0])
    assert sig_study_objects(sigs[0])
    assert any(condition.condition_cui == rt_cui for condition in sig_condition_objects(sigs[0]))


def test_selection_executes_category_mapping_and_version_policies(imported_hemonc_session):
    scope = imported_hemonc_session.execute(
        sa.select(Studies.condition_cui, Drugs.main_class)
        .join(variants_StudyMap, variants_StudyMap.study == Studies.study)
        .join(Variants, variants_StudyMap.parent_id == Variants.id)
        .join(Sigs, Sigs.variant_cui == Variants.variant_cui)
        .join(Drugs, Sigs.component_cui == Drugs.drug_cui)
        .where(Studies.condition_cui.is_not(None), Drugs.main_class.is_not(None))
        .order_by(Studies.condition_cui, Variants.id, Sigs.id)
        .limit(1)
    ).one()
    condition_cui, main_class = scope
    mapping = {"main_class": {main_class: "live-test-category"}}
    spec = TreatmentSelectionSpec.for_conditions(
        [condition_cui],
        category_requirements=(CategoryRequirement("live-test-category", 1),),
    )
    latest = select_variants(imported_hemonc_session, spec, category_mapping=mapping)
    all_versions = select_variants(
        imported_hemonc_session,
        TreatmentSelectionSpec.for_conditions([condition_cui], version_policy="all"),
    )
    assert latest
    assert len({variant.variant_cui for variant in latest}) == len(latest)
    assert len(all_versions) >= len(latest)
    assert VariantBundle.from_variant(latest[0]).variant_cui == latest[0].variant_cui


def test_study_variant_links_prefer_highest_version(imported_hemonc_session):
    duplicate = imported_hemonc_session.execute(
        sa.select(Studies.study)
        .join(variants_StudyMap, variants_StudyMap.study == Studies.study)
        .join(Variants, variants_StudyMap.parent_id == Variants.id)
        .group_by(Studies.study)
        .having(sa.func.count(sa.distinct(Variants.variant_cui)) < sa.func.count(Variants.id))
        .limit(1)
    ).scalar_one_or_none()
    if duplicate is None:
        pytest.skip("imported database has no study with multiple variant versions")

    study = imported_hemonc_session.execute(
        sa.select(Studies).where(Studies.study == duplicate).limit(1)
    ).scalar_one()
    variants = study_variant_objects(study)
    assert len({variant.variant_cui for variant in variants}) == len(variants)
    assert all(
        variant.version
        == max(
            candidate.version
            for candidate in study.variants
            if candidate.variant_cui == variant.variant_cui
        )
        for variant in variants
    )
