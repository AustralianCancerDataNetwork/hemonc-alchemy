"""Query the HemOnc.org oncology terminology as Python objects.

Every entity class is importable straight from this package, alongside the
connection helpers and `resolve_all_days`. See the README for what the
entities are, how they relate, and how to configure a connection.
"""

from importlib import import_module
from typing import TYPE_CHECKING

from .config import HemOncAlchemyConfig as HemOncAlchemyConfig
from .config import create_default_hemonc_engine as create_default_hemonc_engine
from .config import create_hemonc_engine as create_hemonc_engine
from .config import get_hemonc_context as get_hemonc_context

if TYPE_CHECKING:
    from .model import *
    from .toolkit.analytics.treatment.scheduling import (
        resolve_all_days as resolve_all_days,
    )

_EAGER = ["HemOncAlchemyConfig", "create_default_hemonc_engine", "create_hemonc_engine", "get_hemonc_context"]


def _model():
    # importlib rather than `from . import model`, which would re-enter this
    # __getattr__ through the import system and recurse.
    return import_module(".model", __name__)


def _public_names() -> list[str]:
    return [*_EAGER, "resolve_all_days", *_model().__all__]


def __getattr__(name: str):
    """Resolve entity classes on first use.

    Kept lazy so `hemonc-alchemy regen` can rebuild a broken model rather
    than failing while importing it.
    """
    if name == "resolve_all_days":
        value = import_module(
            ".toolkit.analytics.treatment.scheduling", __name__
        ).resolve_all_days
    elif name == "__all__":
        value = _public_names()
    else:
        try:
            value = import_module(f".{name}", __name__)
        except ModuleNotFoundError:
            try:
                value = getattr(_model(), name)
            except AttributeError:
                raise AttributeError(
                    f"module {__name__!r} has no attribute {name!r}"
                ) from None

    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(_public_names())
