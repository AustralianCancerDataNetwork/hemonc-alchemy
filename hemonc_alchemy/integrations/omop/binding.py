"""Lazy access to ``omop-alchemy``'s public CDM models.

The optional dependency is imported only when a caller enters this bridge.
Normal HemOnc imports therefore remain valid without the ``omop`` extra. OMOP
models use logical schema tags; ``schema.py`` resolves them through explicit
maps or oa-configurator and reports unavailable tables with the SQL error.

The package's own queries are limited to HemOnc-specific joins that
``omop-alchemy`` cannot know about. OMOP model classes and their public
validity/standardness expressions remain the source of truth for OMOP-side
semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schema import OmopAvailability, omop_availability


@dataclass(frozen=True)
class OmopBinding:
    """Public OMOP Alchemy models for a configured session."""

    concept: Any
    concept_relationship: Any
    vocabulary: Any
    concept_ancestor: Any
    relationship: Any


def load_omop_binding() -> OmopBinding | None:
    """Load public OMOP models lazily, returning ``None`` if extra is absent."""

    try:
        from omop_alchemy.cdm.model import (  # type: ignore[import-not-found]  # optional extra, not always installed
            Concept,
            Concept_Ancestor,
            Concept_Relationship,
            Relationship,
            Vocabulary,
        )
    except ImportError:
        return None
    return OmopBinding(
        concept=Concept,
        concept_relationship=Concept_Relationship,
        vocabulary=Vocabulary,
        concept_ancestor=Concept_Ancestor,
        relationship=Relationship,
    )


def omop_available(
    session: Any,
    *,
    require_relationships: bool = False,
) -> bool:
    """Return whether the optional extra and configured concept table work.

    This preserves the boolean API while the detailed availability helper
    carries a failure reason. An ancestry resolver can also require relations.
    """

    return omop_availability(
        session, require_relationships=require_relationships
    ).available


__all__ = ["OmopAvailability", "OmopBinding", "load_omop_binding", "omop_available"]
