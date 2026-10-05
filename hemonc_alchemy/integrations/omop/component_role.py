"""Enriching a `CycleTemplate` with HemOnc's per-(drug, regimen) role relationships."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Any

import sqlalchemy as sa

from ...model import Drugs
from ...toolkit.analytics.treatment.classification.component_role import ComponentRole, resolve_role
from ...toolkit.analytics.treatment.scheduling.templates import CycleTemplate
from .queries import component_roles


def attach_component_roles(
    session: Any, regimen_cui: int, template: CycleTemplate
) -> CycleTemplate:
    """`template` with `drug_role` filled in for `regimen_cui`."""
    names = template.iv_drug + template.po_drug
    if not names:
        return replace(template, drug_role={})

    cui_by_name = dict(
        session.execute(sa.select(Drugs.drug, Drugs.drug_cui).where(Drugs.drug.in_(names))).all()
    )
    name_by_cui = {cui: name for name, cui in cui_by_name.items()}

    regimen_code = str(regimen_cui)
    tags: dict[str, set[str]] = defaultdict(set)
    for relationship in component_roles(session, cui_by_name.values()):
        if relationship.target.concept_code != regimen_code:
            continue
        name = name_by_cui.get(int(relationship.source.concept_code))
        if name is not None:
            tags[name].add(relationship.relationship_id)

    return replace(template, drug_role={name: resolve_role(tags[name]) for name in names})


__all__ = ["ComponentRole", "attach_component_roles"]
