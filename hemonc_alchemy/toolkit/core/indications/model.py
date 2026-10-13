"""Lossless, typed views of indication criteria."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum


class Presence(Enum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"
    NOT_STATED = "not_stated"


class Kind(Enum):
    VARIANT = "variant"
    EXON_ALTERATION = "exon_alteration"
    FUSION = "fusion"
    AMPLIFICATION = "amplification"
    EXPRESSION = "expression"
    MUTATION_CLASS = "mutation_class"
    OTHER = "other"


class Origin(Enum):
    GERMLINE = "germline"
    SOMATIC = "somatic"
    UNSPECIFIED = "unspecified"


@dataclass(frozen=True)
class Finding:
    raw: str
    presence: Presence
    kind: Kind
    detail: str | None = None
    origin: Origin = Origin.UNSPECIFIED
    comparator: str | None = None
    value: float | None = None
    unit: str | None = None
    qualifier: str | None = None
    parsed: bool = True


@dataclass(frozen=True)
class Criterion:
    dimension: str
    source: str
    raw: str


@dataclass(frozen=True)
class BiomarkerCriterion(Criterion):
    slot: int
    biomarker: str
    source_label: str
    findings: tuple[Finding, ...]
    group: str | None = None


@dataclass(frozen=True)
class ResolvedIndication:
    indication_id: int
    condition_cui: int | None
    condition: str
    component_cui: int | None
    component: str
    regimen_cuis: tuple[int, ...]
    regulator: str
    withdrawn: bool
    criteria: tuple[Criterion, ...]
    raw: Mapping[str, str | None]
