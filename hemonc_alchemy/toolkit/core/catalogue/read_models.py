"""Immutable, framework-free catalogue projections."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Page[T]:
    items: tuple[T, ...]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True)
class ConditionSummary:
    condition_cui: int
    condition: str
    section: str | None


@dataclass(frozen=True)
class VariantRecord:
    variant_cui: int
    version: int
    regimen_cui: int | None
    regimen: str
    variant: str
    source_fullyspecified: bool
    sig_count: int


@dataclass(frozen=True)
class RegimenSummary:
    regimen_cui: int
    regimen_name: str
    regimen_type: str
    matching_variant_count: int
    study_count: int
    study_linked: bool
    regulatory_linked: bool


@dataclass(frozen=True)
class IndicationRecord:
    record_id: int
    condition_cui: int | None
    condition: str
    component_cui: int | None
    component: str
    regulator: str
    withdrawn: str
    clinical_status: str | None
    stage: str | None
    biomarker: str | None
    prior_therapy: str | None
    condition_resolves: bool
    linked_regimen_count: int
