"""Resolve filtered indication records through registered normalisers."""

from ..catalogue.specs import DEFAULT_INDICATION_SPEC, IndicationSpec
from .loader import load_indication_sources
from .model import ResolvedIndication
from .normalisers import Normaliser, default_normalisers


def _withdrawn(value: str) -> bool:
    return value.strip().casefold() != "false"


def resolve_indications(
    session,
    spec: IndicationSpec = DEFAULT_INDICATION_SPEC,
    normalisers: tuple[Normaliser, ...] | None = None,
) -> tuple[ResolvedIndication, ...]:
    """Return typed criteria while retaining the original indication fields."""
    if normalisers is None:
        normalisers = default_normalisers()
    result = []
    for source in load_indication_sources(session, spec):
        criteria = tuple(
            criterion
            for normaliser in normalisers
            for criterion in normaliser.normalise(source)
        )
        result.append(
            ResolvedIndication(
                source.indication_id,
                source.condition_cui,
                source.condition,
                source.component_cui,
                source.component,
                source.regimen_cuis,
                source.regulator,
                _withdrawn(source.withdrawn_raw),
                criteria,
                source.raw,
            )
        )
    return tuple(result)
