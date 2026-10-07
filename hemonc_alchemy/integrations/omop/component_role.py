"""Enriching a `CycleTemplate` with HemOnc's per-(drug, regimen) role relationships."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Any

import sqlalchemy as sa

from ...caching import cached_per_engine
from ...model import Drugs
from ...toolkit.analytics.treatment.classification.component_role import (
    ComponentRole,
    resolve_role,
)
from ...toolkit.analytics.treatment.scheduling.templates import CycleTemplate
from .queries import component_roles


@cached_per_engine
def regimen_component_roles(session: Any) -> dict[int, dict[str, ComponentRole]]:
    """regimen_cui -> drug name -> role, for every drug HemOnc tags with a role in that regimen."""
    name_by_cui = {str(cui): name for name, cui in session.execute(sa.select(Drugs.drug, Drugs.drug_cui)).all()}
    tags: dict[int, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for relationship in component_roles(session):
        name = name_by_cui.get(relationship.source.concept_code)
        if name is not None and relationship.target.concept_code.isdigit():
            tags[int(relationship.target.concept_code)][name].add(relationship.relationship_id)
    return {regimen: {name: resolve_role(found) for name, found in drugs.items()} for regimen, drugs in tags.items()}


def attach_component_roles(
    session: Any, regimen_cui: int, template: CycleTemplate
) -> CycleTemplate:
    """`template` with `drug_role` filled in for `regimen_cui`."""
    roles = regimen_component_roles(session).get(int(regimen_cui), {})
    names = template.iv_drug + template.po_drug
    return replace(template, drug_role={name: roles.get(name, ComponentRole.UNTAGGED) for name in names})


__all__ = ["ComponentRole", "attach_component_roles", "regimen_component_roles"]
