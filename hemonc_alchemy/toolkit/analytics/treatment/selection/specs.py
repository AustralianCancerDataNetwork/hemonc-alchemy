"""Consumer-independent contracts for treatment selection."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from .....toolkit.core.components import COMPONENT_SEARCH_COLUMNS

VersionPolicy = Literal["all", "latest"]
CategoryMatch = Literal["exact", "min"]

DEFAULT_COMPONENT_COLUMNS = COMPONENT_SEARCH_COLUMNS


def _required_strings(values: Iterable[str]) -> tuple[str, ...]:
    result = tuple(
        dict.fromkeys(value.strip() for value in values if value and value.strip())
    )
    if not result:
        raise ValueError("At least one non-empty string is required.")
    return result


@dataclass(frozen=True)
class ComponentRequirement:
    """Require at least one sig matching any of the supplied search terms."""

    terms: tuple[str, ...]
    columns: tuple[str, ...] = DEFAULT_COMPONENT_COLUMNS

    def __post_init__(self) -> None:
        object.__setattr__(self, "terms", _required_strings(self.terms))
        object.__setattr__(self, "columns", _required_strings(self.columns))

    @classmethod
    def from_terms(
        cls,
        terms: str | Iterable[str],
        *,
        columns: Sequence[str] | None = None,
    ) -> ComponentRequirement:
        if isinstance(terms, str):
            terms = (terms,)
        return cls(
            tuple(terms),
            tuple(columns) if columns is not None else DEFAULT_COMPONENT_COLUMNS,
        )


@dataclass(frozen=True)
class CategoryRequirement:
    """Require an exact or minimum number of sigs in a broad category."""

    category: str
    amount: int
    match: CategoryMatch = "min"

    def __post_init__(self) -> None:
        if not self.category.strip():
            raise ValueError("Category must not be empty.")
        if self.amount < 0:
            raise ValueError("Category amount must not be negative.")
        if self.match not in {"exact", "min"}:
            raise ValueError("Category match must be 'exact' or 'min'.")


@dataclass(frozen=True)
class TreatmentSelectionSpec:
    """A standalone description of a model-level variant selection query."""

    condition_cuis: tuple[int, ...]
    component_requirements: tuple[ComponentRequirement, ...] = field(
        default_factory=tuple
    )
    category_requirements: tuple[CategoryRequirement, ...] = field(
        default_factory=tuple
    )
    regimens: tuple[str, ...] = field(default_factory=tuple)
    phase: str | None = None
    study_context: str | None = None
    version_policy: VersionPolicy = "latest"

    def __post_init__(self) -> None:
        cuis = tuple(dict.fromkeys(int(cui) for cui in self.condition_cuis))
        if not cuis:
            raise ValueError("At least one condition CUI is required.")
        object.__setattr__(self, "condition_cuis", cuis)
        object.__setattr__(
            self, "regimens", _required_strings(self.regimens) if self.regimens else ()
        )
        if self.version_policy not in {"all", "latest"}:
            raise ValueError("Version policy must be 'all' or 'latest'.")

    @classmethod
    def for_conditions(
        cls,
        condition_cuis: Iterable[int],
        *,
        component_requirements: Sequence[ComponentRequirement] = (),
        category_requirements: Sequence[CategoryRequirement] = (),
        regimens: Sequence[str] = (),
        phase: str | None = None,
        study_context: str | None = None,
        version_policy: VersionPolicy = "latest",
    ) -> TreatmentSelectionSpec:
        return cls(
            condition_cuis=tuple(condition_cuis),
            component_requirements=tuple(component_requirements),
            category_requirements=tuple(category_requirements),
            regimens=tuple(regimens),
            phase=phase,
            study_context=study_context,
            version_policy=version_policy,
        )


CategoryMapping = Mapping[str, Mapping[str, str]]
