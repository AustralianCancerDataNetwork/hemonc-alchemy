"""Lossless, typed views of indication criteria."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from ....model.enums import Indications_SexEnum


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


class PriorTherapy(Enum):
    NONE_REQUIRED = "none_required"
    UNTREATED = "untreated"
    REQUIRES_PRIOR = "requires_prior"


class ScopeToken(Enum):
    EARLY = "early"
    LOCALLY_ADVANCED = "locally_advanced"
    ADVANCED = "advanced"
    METASTATIC = "metastatic"
    NODE_POSITIVE = "node_positive"
    EXTENSIVE_STAGE = "extensive_stage"
    INFLAMMATORY = "inflammatory"
    UNRESECTABLE = "unresectable"
    RESECTABLE = "resectable"
    RECURRENT = "recurrent"
    LOCALLY_RECURRENT = "locally_recurrent"
    RELAPSED = "relapsed"
    REFRACTORY = "refractory"
    RELAPSED_OR_REFRACTORY = "relapsed_or_refractory"
    CHRONIC = "chronic"
    CHRONIC_PHASE = "chronic_phase"
    ACCELERATED_PHASE = "accelerated_phase"
    BLAST_CRISIS = "blast_crisis"
    STAGE_I = "stage_i"
    STAGE_II = "stage_ii"
    STAGE_III = "stage_iii"
    STAGE_IV = "stage_iv"
    LIMITED_STAGE = "limited_stage"
    LOCALIZED = "localized"
    REGIONALLY_ADVANCED = "regionally_advanced"
    NON_MUSCLE_INVASIVE = "non_muscle_invasive"
    MUSCLE_INVASIVE = "muscle_invasive"
    CUTANEOUS = "cutaneous"
    PERSISTENT = "persistent"
    PROGRESSIVE = "progressive"
    ACUTE = "acute"
    ACTIVE = "active"
    OPERABLE = "operable"
    BULKY = "bulky"
    NON_METASTATIC = "non_metastatic"
    NEWLY_DIAGNOSED = "newly_diagnosed"
    UNTREATED = "untreated"
    SYMPTOMATIC = "symptomatic"
    SEVERE = "severe"
    MODERATE = "moderate"
    PALLIATIVE = "palliative"
    SENSITIVE = "sensitive"
    RESISTANT = "resistant"
    INDOLENT = "indolent"
    FIRST_RELAPSE = "first_relapse"
    FIRST_RECURRENCE = "first_recurrence"
    SYSTEMIC_THERAPY_REQUIRED = "systemic_therapy_required"
    TRANSFUSION_DEPENDENT = "transfusion_dependent"
    CLINICALLY_AGGRESSIVE = "clinically_aggressive"
    NMIBC = "nmibc"
    LOW_GRADE = "low_grade"
    SKIN_LESIONS = "skin_lesions"
    STAGE_B2 = "stage_b2"
    STAGE_C = "stage_c"
    D2 = "d2"
    CR1 = "cr1"
    CR2 = "cr2"


class Setting(Enum):
    FIRST_LINE = "first_line"
    SECOND_LINE = "second_line"
    LATER_LINE = "later_line"
    INDUCTION = "induction"
    CONSOLIDATION = "consolidation"
    ADJUVANT = "adjuvant"
    NEOADJUVANT = "neoadjuvant"
    MAINTENANCE = "maintenance"
    FIRST_LINE_MAINTENANCE = "first_line_maintenance"
    PERIOPERATIVE = "perioperative"
    UNPARSED = "unparsed"


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
class ScopeTerm:
    raw: str
    tokens: tuple[ScopeToken, ...]
    qualifier: str | None
    parsed: bool


@dataclass(frozen=True)
class ScopeCriterion(Criterion):
    terms: tuple[ScopeTerm, ...]


@dataclass(frozen=True)
class AgeCriterion(Criterion):
    """Age bounds stay in the source unit; no conversion is applied."""

    group: str | None
    min_age: int | None
    max_age: int | None
    unit: str | None
    parsed: bool


@dataclass(frozen=True)
class PriorTherapyCriterion(Criterion):
    """Absence of this criterion means no stated prior-therapy requirement."""

    requirement: PriorTherapy


@dataclass(frozen=True)
class ContextTerm:
    raw: str
    setting: Setting
    parsed: bool


@dataclass(frozen=True)
class ContextCriterion(Criterion):
    terms: tuple[ContextTerm, ...]


@dataclass(frozen=True)
class SexCriterion(Criterion):
    sex: Indications_SexEnum


@dataclass(frozen=True)
class RawCriterion(Criterion):
    pass


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
