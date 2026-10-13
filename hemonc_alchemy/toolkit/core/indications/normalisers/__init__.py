"""Normaliser contracts and the default step-one registry."""

from typing import Protocol

from ..loader import IndicationSource
from ..model import Criterion


class Normaliser(Protocol):
    name: str
    columns: tuple[str, ...]

    def normalise(self, source: IndicationSource) -> tuple[Criterion, ...]: ...


def default_normalisers() -> tuple[Normaliser, ...]:
    from .age import AgeNormaliser
    from .biomarker import BiomarkerNormaliser
    from .context import ContextNormaliser
    from .passthrough import PassthroughNormaliser
    from .prior_therapy import PriorTherapyNormaliser
    from .scope import ScopeNormaliser
    from .sex import SexNormaliser

    return (
        BiomarkerNormaliser(),
        ScopeNormaliser(),
        AgeNormaliser(),
        PriorTherapyNormaliser(),
        ContextNormaliser(),
        SexNormaliser(),
        PassthroughNormaliser(),
    )


__all__ = ["Normaliser", "default_normalisers"]
