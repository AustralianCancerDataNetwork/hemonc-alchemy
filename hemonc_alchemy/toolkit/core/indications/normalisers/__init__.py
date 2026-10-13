"""Normaliser contracts and the default step-one registry."""

from typing import Protocol

from ..loader import IndicationSource
from ..model import Criterion


class Normaliser(Protocol):
    name: str
    columns: tuple[str, ...]

    def normalise(self, source: IndicationSource) -> tuple[Criterion, ...]: ...


def default_normalisers() -> tuple[Normaliser, ...]:
    from .biomarker import BiomarkerNormaliser

    return (BiomarkerNormaliser(),)


__all__ = ["Normaliser", "default_normalisers"]
