from enum import Enum


class Authors_RoleEnum(str, Enum):
    FIRST_AUTHOR = 'first author'
    SECOND_AUTHOR = 'second author'
    MIDDLE_AUTHOR = 'middle author'
    LAST_AUTHOR = 'last author'
    CO_TO_FIRST_AUTHOR = 'co-first author'
    CO_TO_LAST_AUTHOR = 'co-last author'

class Canonicaltriples_Class_1Enum(str, Enum):
    REGIMEN = 'regimen'
    PROCEDURE = 'procedure'
    ANY_CONCEPT = 'any concept'
    COMPONENT = 'component'
    STUDY = 'study'
    SUBSTUDY = 'substudy'
    SYNTHETIC_REGIMEN = 'synthetic regimen'
    REGIMEN_CLASS = 'regimen class'
    REFERENCE = 'reference'
    COMPONENT_CLASS = 'component class'
    CONDITION = 'condition'
    CONTEXT = 'context'
    REGIMEN_STUB = 'regimen stub'
    REGIMEN_VARIANT = 'regimen variant'

class Conditions_Age_focusEnum(str, Enum):
    UNDEFINED = 'undefined'
    PEDIATRIC = 'pediatric'

class Conditions_Condition_typeEnum(str, Enum):
    BREAST = 'breast'
    CLASSICAL_HEMATOLOGY = 'classical hematology'
    CNS = 'cns'
    DERMATOLOGIC = 'dermatologic'
    ENDOCRINE = 'endocrine'
    GASTROINTESTINAL = 'gastrointestinal'
    GENITOURINARY = 'genitourinary'
    GYNECOLOGIC = 'gynecologic'
    HEAD_NECK = 'head & neck'
    LYMPHOID = 'lymphoid'
    MYELOID = 'myeloid'
    NET = 'net'
    OTHER = 'other'
    OTHER_HEMATOLOGIC_NEOPLASM = 'other hematologic neoplasm'
    OTHER_NEOPLASM = 'other neoplasm'
    OTHER_SOLID_NEOPLASM = 'other solid neoplasm'
    PLASMA_CELL = 'plasma cell'
    SARCOMA = 'sarcoma'
    THORACIC = 'thoracic'

class Conditions_Map_type_icd10cmEnum(str, Enum):
    TBD = 'tbd'
    EXACT = 'exact'

class Conditions_Map_type_icd9cmEnum(str, Enum):
    EXACT = 'exact'
    DOWN_LESS_TO_TO_TO_MORE_GRANULAR = 'down (less-to-more granular)'
    UP_MORE_TO_TO_TO_LESS_GRANULAR = 'up (more-to-less granular)'
    SIDEWAYS_SEMANTIC_EQUIVALENCE_BUT_NOT_EXACT = 'sideways (semantic equivalence but not exact)'
    BLANK = '(blank)'

class Conditions_Map_type_icdo3Enum(str, Enum):
    EXACT = 'exact'
    DOWN_LESS_TO_TO_TO_MORE_GRANULAR = 'down (less-to-more granular)'
    UP_MORE_TO_TO_TO_LESS_GRANULAR = 'up (more-to-less granular)'
    SIDEWAYS_SEMANTIC_EQUIVALENCE_BUT_NOT_EXACT = 'sideways (semantic equivalence but not exact)'
    BLANK = '(blank)'

class Conditions_Map_type_icdo3_morphEnum(str, Enum):
    EXACT = 'exact'
    DOWN_LESS_TO_TO_TO_MORE_GRANULAR = 'down (less-to-more granular)'
    UP_MORE_TO_TO_TO_LESS_GRANULAR = 'up (more-to-less granular)'
    SIDEWAYS_SEMANTIC_EQUIVALENCE_BUT_NOT_EXACT = 'sideways (semantic equivalence but not exact)'
    BLANK = '(blank)'

class Conditions_Map_type_ncitEnum(str, Enum):
    EXACT = 'exact'
    UP = 'up'
    SIDEWAYS = 'sideways'
    DOWN = 'down'

class Conditions_Map_type_oncotreeEnum(str, Enum):
    UP = 'up'
    EXACT = 'exact'
    DOWN = 'down'

class Conditions_Map_type_seerEnum(str, Enum):
    EXACT = 'exact'
    DOWN_LESS_TO_TO_TO_MORE_GRANULAR = 'down (less-to-more granular)'
    UP_MORE_TO_TO_TO_LESS_GRANULAR = 'up (more-to-less granular)'
    SIDEWAYS_SEMANTIC_EQUIVALENCE_BUT_NOT_EXACT = 'sideways (semantic equivalence but not exact)'
    BLANK = '(blank)'

class Conditions_Map_type_snomedEnum(str, Enum):
    UP = 'up'
    EXACT = 'exact'
    DOWN = 'down'

class Conditions_SectionEnum(str, Enum):
    ACUTE_LEUKEMIA = 'acute leukemia'
    AGGRESSIVE_LYMPHOMA = 'aggressive lymphoma'
    BREAST_ONCOLOGY = 'breast oncology'
    CYTOPENIAS = 'cytopenias'
    DERMATOLOGIC_ONCOLOGY = 'dermatologic oncology'
    DISEASE_TO_AGNOSTIC = 'disease-agnostic'
    ENDOCRINE_ONCOLOGY = 'endocrine oncology'
    GENITORURINARY_ONCOLOGY = 'genitorurinary oncology'
    GI_ONCOLOGY = 'gi oncology'
    GYNECOLOGIC_ONCOLOGY = 'gynecologic oncology'
    HEAD_NECK_ONCOLOGY = 'head & neck oncology'
    HEMOLYTIC_DISORDERS_AND_HEMOGLOBINOPATHIES = 'hemolytic disorders and hemoglobinopathies'
    HEMOSTASIS_AND_THROMBOSIS = 'hemostasis and thrombosis'
    HISTIOCYTE_DISORDERS = 'histiocyte disorders'
    INDOLENT_LYMPHOMA = 'indolent lymphoma'
    INFECTIOUS_COMPLICATIONS = 'infectious complications'
    LYMPHOPROLIFERATIVE_DISORDERS = 'lymphoproliferative disorders'
    MESOTHELIOMA = 'mesothelioma'
    MYELOPROLIFERATIVE_NEOPLASMS_AND_MYELODYSPLASTIC_SYNDROMES = 'myeloproliferative neoplasms and myelodysplastic syndromes'
    NEURO_TO_ONCOLOGY = 'neuro-oncology'
    PEDIATRIC_CNS_MALIGNANCIES = 'pediatric cns malignancies'
    PEDIATRIC_HEMATOLOGIC_NEOPLASMS = 'pediatric hematologic neoplasms'
    PEDIATRIC_SOLID_TUMORS = 'pediatric solid tumors'
    PLASMA_CELL_DYSCRASIAS = 'plasma cell dyscrasias'
    SARCOMA = 'sarcoma'
    SUPPORTIVE_ONCOLOGY = 'supportive oncology'
    T_TO_CELL_AND_NK_TO_CELL_NEOPLASMS = 't-cell and nk-cell neoplasms'
    THORACIC_ONCOLOGY = 'thoracic oncology'
    TRANSPLANT_AND_IEC = 'transplant and iec'
    TREATMENT_COMPLICATIONS = 'treatment complications'
    UNDEFINED_NO_EDITORIAL_BOARD_SECTION_MAPPING = 'undefined (no editorial board section mapping)'

class Contexts_IntentEnum(str, Enum):
    NON_TO_CURATIVE_INTENT = 'non-curative intent'
    CURATIVE_INTENT = 'curative intent'
    UNSPECIFIED_INTENT = 'unspecified intent'
    NOT_APPLICABLE = 'not applicable'
    PREVENTIVE_INTENT = 'preventive intent'

class Contexts_Risk_stratificationEnum(str, Enum):
    HIGH_TO_RISK = 'high-risk'
    INTERMEDIATE_TO_RISK = 'intermediate-risk'
    LOW_TO_RISK = 'low-risk'
    LOWER_TO_RISK = 'lower-risk'
    EARLY_TO_STAGE_FAVORABLE = 'early-stage favorable'
    STANDARD_TO_RISK = 'standard-risk'
    VERY_HIGH_TO_RISK = 'very high-risk'
    UNSTRATIFIED_TO_RISK = 'unstratified-risk'

class Drugs_Class_typeEnum(str, Enum):
    MECHANISTIC = 'mechanistic'
    BIOCHEMICAL = 'biochemical'
    NONSPECIFIC = 'nonspecific'
    FUNCTIONAL = 'functional'

class Exclusions_Rev1Enum(str, Enum):
    JEREMY = 'jeremy'
    ALEENAH = 'aleenah'

class Exclusions_Rev2Enum(str, Enum):
    ALEENAH = 'aleenah'
    JEREMY = 'jeremy'

class HemoncClasses_Class_typeEnum(str, Enum):
    CORE = 'core'
    READY_FOR_CORE = 'ready for core'
    EXTENSION = 'extension'
    INTERMEDIATE = 'intermediate'
    NUMERIC = 'numeric'

class HemoncClasses_DomainEnum(str, Enum):
    PERSON = 'person'
    CONDITION = 'condition'
    CLINICAL_TRIAL = 'clinical trial'
    DRUG = 'drug'
    GEOGRAPHIC = 'geographic'
    CLINICAL_TRIAL_DESIGN = 'clinical trial design'
    CLINICAL_TRIAL_RESULTS = 'clinical trial results'
    REGIMEN = 'regimen'
    CONTEXT = 'context'
    MEASUREMENT = 'measurement'
    PUBLICATION = 'publication'
    LINKAGE = 'linkage'
    PROCEDURE = 'procedure'
    OBSERVATION = 'observation'
    ORGANIZATION = 'organization'
    OTHER = 'other'

class HemoncClasses_Omopdomain_idEnum(str, Enum):
    CONDITION = 'condition'
    DRUG = 'drug'
    MEASUREMENT = 'measurement'
    PROCEDURE = 'procedure'
    REGIMEN = 'regimen'
    OBSERVATION = 'observation'

class HemoncClasses_Omopstandard_conceptEnum(str, Enum):
    RXNORM = 'rxnorm'
    C = 'c'
    HEMONC = 'hemonc'
    N_A_TO_NATIVELY_ENCODED = 'n/a - natively encoded'

class HemoncRels_In_ohdsiEnum(str, Enum):
    FALSE = 'false'
    TRUE = 'true'
    RENAMED_HAS_INVESTIG_USE = 'renamed: has investig use'
    RENAMED_HAS_SYNTH_REGIMEN = 'renamed: has synth regimen'
    RENAMED_IS_CURR_IN_ADULT = 'renamed: is curr in adult'
    RENAMED_IS_CURR_IN_PED = 'renamed: is curr in ped'
    RENAMED_IS_HIST_IN_ADULT = 'renamed: is hist in adult'
    RENAMED_IS_HIST_IN_PED = 'renamed: is hist in ped'

class Inclusions_ReasonEnum(str, Enum):
    EXCEPTION = 'exception'
    PHASE_3_SACT = 'phase 3 sact'
    NON_TO_PHASE_3_REGISTRATIONAL_STUDY = 'non-phase 3 registrational study'
    PHASE_3_LRACT = 'phase 3 lract'
    PHASE_3_CLASSICAL_HEMATOLOGY = 'phase 3 classical hematology'
    CLINICAL_PRACTICE_GUIDELINE = 'clinical practice guideline'
    PHASE_3_GVHD = 'phase 3 gvhd'

class Indications_Age_unitEnum(str, Enum):
    UNSPECIFIED = 'unspecified'
    YEAR = 'year'
    MONTH = 'month'

class Indications_Biomarker2Enum(str, Enum):
    HER2 = 'her2'
    MAGE_TO_A4_ANTIGEN = 'mage-a4 antigen'
    EGFR = 'egfr'
    PR = 'pr'
    ALK = 'alk'
    CD19 = 'cd19'
    KRAS = 'kras'
    BCL2 = 'bcl2'
    PD_TO_L1 = 'pd-l1'
    CLDN18_2 = 'cldn18.2'

class Indications_Biomarker2_findingEnum(str, Enum):
    NEGATIVE = 'negative'
    POSITIVE = 'positive'
    WILD_TO_TYPE = 'wild-type'
    NEGATIVE_ICH_0_1HC1_OR_IHC2_ISH_TO = 'negative (ich 0, 1hc1+ or ihc2+/ish-)'
    CPS_AT_LEAST_5 = 'cps at least 5'
    CPS_AT_LEAST_1 = 'cps at least 1'
    LOW_IHC_1_OR_IHC_2_ISH_TO_OR_ULTRALOW_IHC_0_WITH_MEMBRANE_ST = 'low (ihc 1+ or ihc 2+/ish-) or ultralow (ihc 0 with membrane staining)'

class Indications_Biomarker2_typeEnum(str, Enum):
    PROTEIN = 'protein'
    GENE = 'gene'

class Indications_Biomarker3_findingEnum(str, Enum):
    POSITIVE = 'positive'
    NEGATIVE = 'negative'
    HGVS_NOMENCLATURE = 'hgvs nomenclature'
    MORE_TO_COME = '[more to come]'

class Indications_Biomarker3_typeEnum(str, Enum):
    GENE = 'gene'
    PROTEIN = 'protein'

class Indications_Biomarker4Enum(str, Enum):
    PD_TO_L1 = 'pd-l1'
    ROS1 = 'ros1'

class Indications_Biomarker4_findingEnum(str, Enum):
    TIL_AT_LEAST_1 = 'til at least 1%'
    POSITIVE = 'positive'
    WILD_TO_TYPE = 'wild-type'
    CPS_AT_LEAST_10 = 'cps at least 10'

class Indications_Biomarker4_typeEnum(str, Enum):
    PROTEIN = 'protein'
    GENE = 'gene'

class Indications_Biomarker_findingEnum(str, Enum):
    POSITIVE = 'positive'
    NEGATIVE = 'negative'
    HGVS_NOMENCLATURE = 'hgvs nomenclature'
    MORE_TO_COME = '[more to come]'

class Indications_Biomarker_typeEnum(str, Enum):
    PROTEIN_FAMILY = 'protein family'
    GENE = 'gene'
    PROTEIN = 'protein'
    CHROMOSOME = 'chromosome'
    TRACER = 'tracer'
    VIRUS = 'virus'

class Indications_Exposure_phenotypeEnum(str, Enum):
    CASTRATE_TO_RESISTANT = 'castrate-resistant'
    CASTRATE_TO_SENSITIVE = 'castrate-sensitive'
    PLATINUM_TO_RESISTANT = 'platinum-resistant'
    PLATINUM_TO_SENSITIVE = 'platinum-sensitive'
    RECURRENT = 'recurrent'
    METASTATIC = 'metastatic'
    CHEMOTHERAPY_TO_SENSITIVE = 'chemotherapy-sensitive'

class Indications_NoteEnum(str, Enum):
    NO_LINKED_CONDITION = 'no linked condition'
    TO_BE_DISSECTED = 'to be dissected'
    NO_MONTH_YEAR_INFORMATION = 'no month/year information'

class Indications_RegulatorEnum(str, Enum):
    FDA = 'fda'
    PMDA = 'pmda'
    EMA = 'ema'
    HC = 'hc'
    MFDS = 'mfds'
    NMPA = 'nmpa'

class Indications_SexEnum(str, Enum):
    MALE = 'male'
    FEMALE = 'female'

class Persons_GenderEnum(str, Enum):
    MAN = 'man'
    NOT_YET_DETERMINED = 'not yet determined'
    WOMAN = 'woman'
    COULD_NOT_BE_DETERMINED = 'could not be determined'
    UNKNOWN = 'unknown'

class Persons_Hyphen_typeEnum(str, Enum):
    MENA = 'mena'
    WESTERN = 'western'
    EASTERN = 'eastern'

class Persons_Vital_statusEnum(str, Enum):
    I_1_ALIVE_NOT_KNOWN_TO_BE_DECEASED = '1 = alive (not known to be deceased)'
    I_0_DECEASED_IF_YEAR_UNKNOWN = '0 = deceased (if year unknown)'
    YYYY_YEAR_DECEASED = 'yyyy = year deceased'

class Refs_Ref_typeEnum(str, Enum):
    BIOMARKER_ANALYSIS = 'biomarker analysis'
    GUIDELINE = 'guideline'
    HRQOL_ANALYSIS = 'hrqol analysis'
    POOLED_HRQOL_ANALYSIS = 'pooled hrqol analysis'
    POOLED_PRO_ANALYSIS = 'pooled pro analysis'
    POOLED_SUBGROUP_ANALYSIS = 'pooled subgroup analysis'
    POOLED_UPDATE = 'pooled update'
    POST_TO_HOC_ANALYSIS = 'post-hoc analysis'
    PRIMARY = 'primary'
    PRO_ANALYSIS = 'pro analysis'
    PROPENSITY_SCORE_ANALYSIS = 'propensity score analysis'
    Q_TO_TWIST_ANALYSIS = 'q-twist analysis'
    REVIEW = 'review'
    SAFETY_ANALYSIS = 'safety analysis'
    SUBGROUP_ANALYSIS = 'subgroup analysis'
    TOXICITY_ANALYSIS = 'toxicity analysis'
    TWIST_ANALYSIS = 'twist analysis'
    UPDATE = 'update'

class Regimens_All_sact_fdaEnum(str, Enum):
    TRUE = 'true'
    CBD = 'cbd'
    FALSE = 'false'

class Regimens_Highest_evidenceEnum(str, Enum):
    NON_TO_RANDOMIZED_TRIAL = 'non-randomized trial'
    PHASE_3_RCT = 'phase 3 rct'
    NON_TO_RANDOMIZED_PORTION_OF_RCT_REGISTRATIONAL = 'non-randomized portion of rct (registrational)'
    NON_TO_RANDOMIZED_PORTION_OF_RCT = 'non-randomized portion of rct'
    PHASE_3_RCT_REGISTRATIONAL = 'phase 3 rct (registrational)'
    NON_TO_PHASE_3_RCT = 'non-phase 3 rct'
    NON_TO_RANDOMIZED_TRIAL_REGISTRATIONAL = 'non-randomized trial (registrational)'
    OBSERVATIONAL = 'observational'
    EARLY_TO_STAGE_NON_TO_RANDOMIZED_TRIAL = 'early-stage non-randomized trial'
    NON_TO_PHASE_3_RCT_REGISTRATIONAL = 'non-phase 3 rct (registrational)'
    EARLY_TO_STAGE_NON_TO_RANDOMIZED_TRIAL_REGISTRATIONAL = 'early-stage non-randomized trial (registrational)'
    NO_SUPPORTING_EVIDENCE = 'no supporting evidence'
    EXPERT_OPINION = 'expert opinion'
    LATE_TO_STAGE_NON_TO_RANDOMIZED_TRIAL = 'late-stage non-randomized trial'
    LATE_TO_STAGE_NON_TO_RANDOMIZED_TRIAL_REGISTRATIONAL = 'late-stage non-randomized trial (registrational)'

class Regimens_Regimen_typeEnum(str, Enum):
    COMPONENT_TO_BASED_REGIMEN = 'component-based regimen'
    HYBRID_REGIMEN = 'hybrid regimen'
    NULL_REGIMEN = 'null regimen'
    CLASS_TO_BASED_REGIMEN = 'class-based regimen'

class Sigs_Class_fieldEnum(str, Enum):
    NON_TO_CANONICAL_SIG = 'non-canonical sig'
    IV_INTERMITTENT_CANONICAL_SIG = 'iv intermittent canonical sig'
    RAD_SIG = 'rad sig'
    IV_CONTINUOUS_CANONICAL_SIG = 'iv continuous canonical sig'
    NON_TO_IV_CANONICAL_SIG = 'non-iv canonical sig'

class Sigs_Component_roleEnum(str, Enum):
    PRIMARY_SYSTEMIC = 'primary systemic'
    SECONDARY_SYSTEMIC = 'secondary systemic'
    LOCOREGIONAL = 'locoregional'

class Sigs_Cycle_length_unitEnum(str, Enum):
    INDETERMINATE = 'indeterminate'
    DAY = 'day'
    WEEK = 'week'
    MONTH = 'month'
    YEAR = 'year'
    NS = 'ns'

class Sigs_DosecapunitEnum(str, Enum):
    MBQ = 'mbq'
    MG = 'mg'
    MG_M_2 = 'mg/m^2'
    MG_DAY = 'mg/day'
    UNITS = 'units'
    IU = 'iu'

class Sigs_DurationunitEnum(str, Enum):
    MINUTE = 'minute'
    DAY = 'day'
    HOUR = 'hour'
    NS = 'ns'
    SECOND = 'second'

class Sigs_FrequencyEnum(str, Enum):
    ONCE = 'once'
    ONCE_PER_DAY = 'once per day'
    CONTINUOUS = 'continuous'
    EVERY_12_HOURS = 'every 12 hours'
    TWICE_PER_DAY = 'twice per day'
    THREE_TIMES_PER_DAY = 'three times per day'
    DAILY_NOS = 'daily nos'
    NS = 'ns'
    FOUR_TIMES_PER_DAY = 'four times per day'
    EVERY_6_HOURS = 'every 6 hours'
    EVERY_4_HOURS = 'every 4 hours'
    TWICE = 'twice'
    ONCE_EVERY_MORNING = 'once every morning'
    ONCE_EVERY_EVENING = 'once every evening'
    EVERY_8_HOURS = 'every 8 hours'
    FIVE_TIMES_PER_DAY = 'five times per day'

class Sigs_PhaseEnum(str, Enum):
    INDUCTION = 'induction'
    CONSOLIDATION = 'consolidation'
    PERIOPERATIVE = 'perioperative'
    NEOADJUVANT = 'neoadjuvant'
    ADJUVANT = 'adjuvant'
    MAINTENANCE = 'maintenance'
    DEFINITIVE = 'definitive'
    PRE_TO_DEFINITIVE = 'pre-definitive'
    POST_TO_DEFINITIVE = 'post-definitive'
    CONCURRENT = 'concurrent'
    LATE_INTENSIFICATION = 'late intensification'
    PRE_TO_PHASE = 'pre-phase'
    CONTINUATION = 'continuation'
    INTERIM_MAINTENANCE = 'interim maintenance'

class Sigs_RouteEnum(str, Enum):
    INTRAVENOUS = 'intravenous'
    ORAL = 'oral'
    SUBCUTANEOUS = 'subcutaneous'
    INTRAMUSCULAR = 'intramuscular'
    INTRATHECAL = 'intrathecal'
    NS = 'ns'
    TOPICAL = 'topical'
    BY_SCARIFICATION = 'by scarification'
    INTRAVESICAL = 'intravesical'
    INHALATION = 'inhalation'
    INTRACAVITARY = 'intracavitary'
    INTRA_TO_ARTERIAL = 'intra-arterial'

class Sigs_SequenceEnum(str, Enum):
    FOURTH = 'fourth'
    FIRST = 'first'
    SECOND = 'second'
    THIRD = 'third'
    LAST = 'last'
    PRIOR_TO_INFUSIONS = 'prior to infusions'

class Sigs_Step_numberEnum(str, Enum):
    I_1_OF_1_DEFAULT = '1 of 1 (default)'
    I_1_OF_2 = '1 of 2'
    I_2_OF_2 = '2 of 2'
    I_1_OF_N = '1 of n'
    I_2_OF_N = '2 of n'
    N_OF_N = '[…], n of n'

class Sigs_SubcomponentEnum(str, Enum):
    TO = '-'
    ABIRATERONE = 'abiraterone'
    NIRAPARIB = 'niraparib'
    PERTUZUMAB = 'pertuzumab'
    TRASTUZUMAB_AND_HYALURONIDASE = 'trastuzumab and hyaluronidase'
    SULFAMETHOXAZOLE = 'sulfamethoxazole'
    TRIMETHOPRIM = 'trimethoprim'
    CEDAZURIDINE = 'cedazuridine'
    DECITABINE = 'decitabine'
    NIVOLUMAB = 'nivolumab'
    RELATLIMAB = 'relatlimab'

class Sigs_TargetleveltypeEnum(str, Enum):
    STEADY_STATE = 'steady state'
    TROUGH = 'trough'
    GOAL = 'goal'

class Sigs_TargetlevelunitEnum(str, Enum):
    INR = 'inr'
    NG_ML = 'ng/ml'
    MCG_L = 'mcg/l'
    MG = 'mg'
    APTT = 'aptt'
    MG_L = 'mg/l'

class Studies_IntentEnum(str, Enum):
    NOT_APPLICABLE = 'not applicable'
    NON_TO_CURATIVE_INTENT = 'non-curative intent'
    CURATIVE_INTENT = 'curative intent'
    UNSPECIFIED_INTENT = 'unspecified intent'
    MIXED_INTENT = 'mixed intent'
    PREVENTIVE_INTENT = 'preventive intent'
    MIXED = 'mixed'

class Studies_PhaseEnum(str, Enum):
    ADAPTIVELY_RANDOMIZED_PHASE_2 = 'adaptively randomized phase 2'
    BASKET_TRIAL = 'basket trial'
    CASE_REPORT = 'case report'
    CASE_SERIES = 'case series'
    CONSENSUS_GUIDELINE = 'consensus guideline'
    DONOR_TO_BASED_RANDOMIZATION = 'donor-based randomization'
    EXPANDED_ACCESS_PROGRAM = 'expanded access program'
    EXPERT_RECOMMENDATION = 'expert recommendation'
    NAMED_PATIENT_PROGRAM = 'named patient program'
    NON_TO_RANDOMIZED = 'non-randomized'
    NON_TO_RANDOMIZED_PHASE_2_3 = 'non-randomized phase 2/3'
    NON_TO_RANDOMIZED_PHASE_3 = 'non-randomized phase 3'
    OBSERVATIONAL = 'observational'
    PHASE_1 = 'phase 1'
    PHASE_1_2 = 'phase 1/2'
    PHASE_1_2A = 'phase 1/2a'
    PHASE_1_2B = 'phase 1/2b'
    PHASE_1A_1B = 'phase 1a/1b'
    PHASE_1B = 'phase 1b'
    PHASE_1B_2 = 'phase 1b/2'
    PHASE_1B_2A = 'phase 1b/2a'
    PHASE_2 = 'phase 2'
    PHASE_2_3 = 'phase 2/3'
    PHASE_2A = 'phase 2a'
    PHASE_2B = 'phase 2b'
    PHASE_2B_3 = 'phase 2b/3'
    PHASE_3 = 'phase 3'
    PHASE_3B = 'phase 3b'
    PHASE_3B_4 = 'phase 3b/4'
    PHASE_4 = 'phase 4'
    PRAGMATIC_RANDOMIZED_TRIAL = 'pragmatic randomized trial'
    PROPENSITY_SCORE_ANALYSIS = 'propensity score analysis'
    PSEUDO_TO_MENDELIAN_RANDOMIZATION = 'pseudo-mendelian randomization'
    QUASI_TO_RANDOMIZED = 'quasi-randomized'
    RANDOMIZED = 'randomized'
    RANDOMIZED_PHASE_1 = 'randomized phase 1'
    RANDOMIZED_PHASE_1_2 = 'randomized phase 1/2'
    RANDOMIZED_PHASE_1B = 'randomized phase 1b'
    RANDOMIZED_PHASE_1B_2 = 'randomized phase 1b/2'
    RANDOMIZED_PHASE_2 = 'randomized phase 2'
    RANDOMIZED_PHASE_2B = 'randomized phase 2b'
    REGISTRY = 'registry'
    RESPONSE_TO_ADAPTED_RANDOMIZED_TRIAL = 'response-adapted randomized trial'
    RETROSPECTIVE = 'retrospective'
    REVIEW = 'review'
    RISK_TO_ADAPTED_THERAPY = 'risk-adapted therapy'
    SINGLE_TO_ARM_PHASE_3 = 'single-arm phase 3'
    NS_NOT_SPECIFIED = 'ns (not specified)'
    BLANK_TO_NOT_YET_DETERMINED = '(blank - not yet determined)'

class Studies_RegistryEnum(str, Enum):
    CLINICALTRIALS_GOV = 'clinicaltrials.gov'
    EUDRACT = 'eudract'
    DRKS = 'drks'
    ISRCTN = 'isrctn'
    NETHERLANDS_TRIAL_REGISTRY = 'netherlands trial registry'
    CHICTR = 'chictr'
    ACTRN = 'actrn'
    UMIN = 'umin'
    KCT = 'kct'
    CLINICAL_TRIALS_REGISTRY_OF_INDIA = 'clinical trials registry of india'
    JRCTS = 'jrcts'
    ANZCTR = 'anzctr'
    JAPANESE_CLINICAL_TRIALS_REGISTRY = 'japanese clinical trials registry'
    RPCEC = 'rpcec'
    NATIONAL_MEDICAL_RESEARCH_REGISTER_OF_MALAYSIA = 'national medical research register of malaysia'

class Studies_Sponsor_typeEnum(str, Enum):
    PHARMACEUTICAL_INDUSTRY = 'pharmaceutical industry'
    GOVERNMENT = 'government'
    COOPERATIVE_GROUP = 'cooperative group'
    ACADEMIC_MEDICAL_CENTER = 'academic medical center'
    OTHER = 'other'
    COMMUNITY_PRACTICE = 'community practice'
    SPONSOR_TO_INVESTIGATOR = 'sponsor-investigator'
    ACADEMIC_CONSORTIUM = 'academic consortium'

class Studies_Study_designEnum(str, Enum):
    NON_TO_RANDOMIZED = 'non-randomized'
    ESCALATION = 'escalation'
    OUT_TO_OF_TO_CLASS_SWITCH = 'out-of-class switch'
    MIXED = 'mixed'
    IN_TO_CLASS_SWITCH = 'in-class switch'
    CBD = 'cbd'
    DE_TO_ESCALATION = 'de-escalation'
    OTHER = 'other'

class StudyResults_Arm_typeEnum(str, Enum):
    CONTROL = 'control'
    ESCALATION = 'escalation'
    NOT_APPLICABLE = 'not applicable'
    IN_TO_CLASS_SWITCH = 'in-class switch'
    OUT_TO_OF_TO_CLASS_SWITCH = 'out-of-class switch'
    DE_TO_ESCALATION = 'de-escalation'

class StudyResults_Comparator_codeEnum(str, Enum):
    NONE_TO_DEFAULT = 'none - default'
    NOT_APPLICABLE_FOR_NON_TO_RANDOMIZED_STUDIES_333_A_REGIMEN_C = 'not applicable (for non-randomized studies)\n333: a regimen comprised entirely of approved drugs that might be "wanted" for adding to the wiki - usually an experimental arm that might have superior efficacy (e.g., hr crosses 1 but ub is <=1.05)\n555: a regimen that is present on the stub page, regardless of whether it contains approved and/or investigational drugs\n666: a regimen comprised entirely of approved drugs being tested as an experimental arm, with results still pending\n777: a regimen with at least one component that is investigational in all regulatory domains that is wanted if and when the investigational component is approved\n888: a regimen comprised entirely of approved drugs that is definitely "wanted" for adding to the wiki\n995: a regimen comprised of approved and/or investigational drugs that is "unwanted" for adding to the wiki - negative experimental arms, etc. the comparative design of the unwanted regimen is in-class-switch\n996: a regimen comprised of approved and/or investigational drugs that is "unwanted" for adding to the wiki - negative experimental arms, etc. the comparative design of the unwanted regimen is out-of-class-switch\n997: a regimen comprised of approved and/or investigational drugs that is "unwanted" for adding to the wiki - negative experimental arms, etc. the comparative design of the unwanted regimen is de-escalation \n998: a regimen comprised of approved and/or investigational drugs that is "unwanted" for adding to the wiki - negative experimental arms, etc. the comparative design of the unwanted regimen is escalation\n999: a regimen comprised of approved and/or investigational drugs that is "unwanted" for adding to the wiki - negative experimental arms, etc. the comparative design of the unwanted regimen is unspecified.'

class StudyResults_Endpoint_classEnum(str, Enum):
    TIME_TO_TO_TO_EVENT = 'time-to-event'
    RATE = 'rate'
    LANDMARK = 'landmark'
    OTHER = 'other'
    COULD_NOT_BE_DETERMINED = 'could not be determined'
    PHARMACOLOGY = 'pharmacology'
    TIME_TO_TO_TO_MEDIAN_EVENT = 'time-to-median event'

class StudyResults_Endpoint_typeEnum(str, Enum):
    UNDESIGNATED = 'undesignated'
    SECONDARY = 'secondary'
    PRIMARY = 'primary'
    CO_TO_PRIMARY = 'co-primary'

class StudyResults_IntentEnum(str, Enum):
    NON_TO_CURATIVE_INTENT = 'non-curative intent'
    CURATIVE_INTENT = 'curative intent'
    UNSPECIFIED_INTENT = 'unspecified intent'
    NOT_APPLICABLE = 'not applicable'
    PREVENTIVE_INTENT = 'preventive intent'

class StudyResults_Landmark_unitEnum(str, Enum):
    YEARS = 'years'
    WEEKS = 'weeks'
    MONTHS = 'months'
    DAYS = 'days'
    CYCLES = 'cycles'

class StudyResults_Metric_unitEnum(str, Enum):
    MONTHS = 'months'
    RATE = 'rate'
    WEEKS = 'weeks'
    DAYS = 'days'
    YEARS = 'years'
    NYR = 'nyr'

class StudyResults_P_valueEnum(str, Enum):
    I_0_01_TO_1_00_IN_0_01_INCREMENTS = '0.01 to 1.00 in 0.01 increments'
    LT_0_01 = '<0.01'
    GT_0_20 = '>0.20'
    NS_NOT_SIGNIFICANT = 'ns (not significant)'

class StudyResults_StatisticEnum(str, Enum):
    HR = 'hr'
    NOT_APPLICABLE = 'not applicable'
    SHR = 'shr'
    AHR = 'ahr'
    RR = 'rr'
    RMST = 'rmst:'
    OR = 'or'
    AOR = 'aor'
    RMST24 = 'rmst24:'

class VariantEligibility_SubtypeEnum(str, Enum):
    PLATELETS = 'platelets'
    WBC_COUNT = 'wbc count'
    EGFR = 'egfr'
    CREATININE = 'creatinine'
    CREATININE_CLEARANCE = 'creatinine clearance'
    ECOG_PS = 'ecog ps'
    CD4_COUNT = 'cd4+ count'
    CD34_CELLS = 'cd34+ cells'
    ANC = 'anc'

class VariantEligibility_UnitEnum(str, Enum):
    L = '/l'
    YEAR = 'year'
    KG = 'kg'
    ML_MIN_1_73M_2 = 'ml/min/1.73m^2'
    MG_DL = 'mg/dl'
    M_2 = 'm^2'
    KG_M_2 = 'kg/m^2'
    MONTH = 'month'
    UL = '/ul'
    PERCENT = 'percent'
    CELLS_KG = 'cells/kg'

class Variantblob_BlockEnum(str, Enum):
    HEADER = 'header'
    BODY_TOP = 'body.top'
    BODY = 'body'
    BODY_BOTTOM = 'body.bottom'

class Variantblob_Chunk_typeEnum(str, Enum):
    STRING = 'string'
    NUMERIC = 'numeric'
    CUI = 'cui'

