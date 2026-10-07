"""Lazy concept-group operations for source-defined anchors."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import sqlalchemy as sa


def resolve_concept_groups(
    session: Any, anchors: Mapping[int, Any], *, name_prefix: str,
) -> dict[int, Any]:
    """Resolve named source groups using OMOP Alchemy's vocabulary cache."""
    from omop_alchemy.toolkit.core.concepts import (  # type: ignore[import-not-found,import-untyped]
        ConceptGroupSpec,
        resolve_concept_group,
    )

    return {
        cui: resolve_concept_group(session, ConceptGroupSpec(name=f"{name_prefix}:{cui}", unit=found))
        for cui, found in anchors.items()
    }


def concept_group_cache_scope(session: Any) -> str | sa.Engine:
    """Vocabulary identity, or the engine when no identity is registered."""
    from omop_alchemy.toolkit.core.concepts.identity import (  # type: ignore[import-not-found,import-untyped]
        cache_scope,
    )

    return cache_scope(session)


__all__ = ["concept_group_cache_scope", "resolve_concept_groups"]
