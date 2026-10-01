"""Source catalogue scopes, independent of treatment eligibility and HTTP."""

from dataclasses import dataclass
from typing import Literal

VersionPolicy = Literal["latest", "all"]
AssociationBasis = Literal["any", "study", "regulatory"]


@dataclass(frozen=True)
class Pagination:
    page: int = 1
    page_size: int = 25

    def __post_init__(self):
        if self.page < 1 or not 1 <= self.page_size <= 100:
            raise ValueError(
                "page must be positive and page_size must be between 1 and 100"
            )


@dataclass(frozen=True)
class CatalogueSpec:
    """None is global scope; an empty CUI tuple deliberately matches nothing.

    Component terms are ORed against source component labels. In condition
    scope, component/context criteria must hold on the same study-linked
    variant. Version selection happens before applying association filters.
    """

    condition_cuis: tuple[int, ...] | None = None
    regimen_cuis: tuple[int, ...] | None = None
    q: str = ""
    version_policy: VersionPolicy = "latest"
    basis: AssociationBasis = "any"
    component_terms: tuple[str, ...] = ()
    study_context: str | None = None
    descending: bool = False

    def __post_init__(self):
        if self.version_policy not in {"latest", "all"}:
            raise ValueError("version_policy must be latest or all")
        if self.basis not in {"any", "study", "regulatory"}:
            raise ValueError("basis must be any, study or regulatory")
        for field in ("condition_cuis", "regimen_cuis"):
            values = getattr(self, field)
            if values is not None:
                object.__setattr__(
                    self, field, tuple(dict.fromkeys(int(v) for v in values))
                )
        object.__setattr__(self, "q", self.q.strip())
        terms = tuple(
            dict.fromkeys(term.strip() for term in self.component_terms if term.strip())
        )
        object.__setattr__(self, "component_terms", terms)


@dataclass(frozen=True)
class IndicationSpec:
    condition_cuis: tuple[int, ...] | None = None
    regimen_cuis: tuple[int, ...] | None = None
    regulators: tuple[str, ...] = ()
    withdrawn_values: tuple[str, ...] = ()
    q: str = ""


# Frozen values can be shared safely across statement/execution defaults.
DEFAULT_CATALOGUE_SPEC = CatalogueSpec()
DEFAULT_INDICATION_SPEC = IndicationSpec()
DEFAULT_PAGINATION = Pagination()
