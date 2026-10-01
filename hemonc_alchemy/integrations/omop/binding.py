"""Lazy access to ``omop-alchemy``'s public CDM models.

The optional dependency is imported only when a caller enters this bridge.
Normal HemOnc imports therefore remain valid in installations without the
``omop`` extra. The current development configuration loads the HemOnc and
OMOP tables into the same database schema, so the public schema-neutral OMOP
models can be used directly on the caller's session. Future schema resolution
belongs in oa-configurator rather than in this bridge.

The package's own queries are limited to HemOnc-specific joins that
``omop-alchemy`` cannot know about. OMOP model classes and their public
validity/standardness expressions remain the source of truth for OMOP-side
semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa


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
) -> bool:
    """Return whether the optional extra and configured concept table work.

    Missing extras, missing schemas, permissions, connection failures, and
    incompatible OMOP installations all return ``False``.  This deliberately
    performs a harmless model query rather than reflecting database metadata.
    """

    binding = load_omop_binding()
    if binding is None:
        return False
    try:
        # Use a separate connection so a failed probe cannot leave the
        # caller's Session transaction in an aborted state.
        with session.get_bind().connect() as connection:
            connection.execute(
                sa.select(binding.concept.concept_id).limit(1)
            ).first()
        return True
    except Exception:  # noqa: BLE001 - availability must never break callers
        return False


__all__ = ["OmopBinding", "load_omop_binding", "omop_available"]
