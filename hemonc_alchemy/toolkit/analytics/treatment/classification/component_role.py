"""Classifying a drug's role within one regimen as defining or merely adjunct.

Resolved per (drug, regimen) pair from HemOnc role relationships

Note: the same drug (e.g. Prednisone) anchors some regimens and has an incidental 
role in others. This module holds the pure classification rule only; 

fetching the underlying relationships needs OMOP and lives in
`integrations.omop.component_role`.
"""

from __future__ import annotations

from enum import Enum

_DEFINING_RELATIONSHIPS = frozenset({
    "Cytotoxic chemo of",
    "Targeted therapy of",
    "Immunotherapy of",
    "Local therapy of",
    "Endocrine tx of",
    "Antineoplastic of",
    "Radiotherapy of",
    "AB-drug cjgt of",
    "Radioconjugate of",
    "Pept-drug cjgt of",
})

_ADJUNCT_RELATIONSHIPS = frozenset({
    "Steroid tx of",
    "Supportive med of",
    "Immunosuppressor of",
    "Growth factor of",
    "Anticoag tx of",
})


class ComponentRole(str, Enum):
    """A drug's role within one specific regimen, not a global property of the drug."""

    DEFINING = "defining"
    ADJUNCT = "adjunct"
    UNTAGGED = "untagged"


def is_defining(role: ComponentRole) -> bool:
    """Whether `role` should count toward a regimen's identity signature.

    Untagged defaults to defining: HemOnc's role relationships don't cover
    every (drug, regimen) pair, and treating a gap as adjunct risks silently
    dropping a drug that should anchor a match.
    """
    return role is not ComponentRole.ADJUNCT


def resolve_role(relationship_ids: set[str]) -> ComponentRole:
    """One drug's role, from the set of relationship types HemOnc tagged it with in one regimen."""
    # A regimen can carry both tags for the same drug (e.g. a targeted agent
    # used anti-cancer in most regimens but immunosuppressive in one) -- defining wins.
    if relationship_ids & _DEFINING_RELATIONSHIPS:
        return ComponentRole.DEFINING
    if relationship_ids & _ADJUNCT_RELATIONSHIPS:
        return ComponentRole.ADJUNCT
    return ComponentRole.UNTAGGED
