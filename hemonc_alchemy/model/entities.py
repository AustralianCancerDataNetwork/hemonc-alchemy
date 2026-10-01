from __future__ import annotations

from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, foreign, mapped_column
from sqlalchemy.orm import relationship as sa_relationship

from .base import Base, EntityBase


from .enums import (
    Authors_RoleEnum,
    Canonicaltriples_Class_1Enum,
    Conditions_Age_focusEnum,
    Conditions_Condition_typeEnum,
    Conditions_Map_type_icd10cmEnum,
    Conditions_Map_type_icd9cmEnum,
    Conditions_Map_type_icdo3Enum,
    Conditions_Map_type_icdo3_morphEnum,
    Conditions_Map_type_ncitEnum,
    Conditions_Map_type_oncotreeEnum,
    Conditions_Map_type_seerEnum,
    Conditions_Map_type_snomedEnum,
    Conditions_SectionEnum,
    Contexts_IntentEnum,
    Contexts_Risk_stratificationEnum,
    Drugs_Class_typeEnum,
    Exclusions_Rev1Enum,
    Exclusions_Rev2Enum,
    HemoncClasses_Class_typeEnum,
    HemoncClasses_DomainEnum,
    HemoncClasses_Omopdomain_idEnum,
    HemoncClasses_Omopstandard_conceptEnum,
    HemoncRels_In_ohdsiEnum,
    Inclusions_ReasonEnum,
    Indications_Age_unitEnum,
    Indications_Biomarker2Enum,
    Indications_Biomarker2_findingEnum,
    Indications_Biomarker2_typeEnum,
    Indications_Biomarker3_findingEnum,
    Indications_Biomarker3_typeEnum,
    Indications_Biomarker4Enum,
    Indications_Biomarker4_findingEnum,
    Indications_Biomarker4_typeEnum,
    Indications_Biomarker_findingEnum,
    Indications_Biomarker_typeEnum,
    Indications_Exposure_phenotypeEnum,
    Indications_NoteEnum,
    Indications_RegulatorEnum,
    Indications_SexEnum,
    Persons_GenderEnum,
    Persons_Hyphen_typeEnum,
    Persons_Vital_statusEnum,
    Refs_Ref_typeEnum,
    Regimens_All_sact_fdaEnum,
    Regimens_Highest_evidenceEnum,
    Regimens_Regimen_typeEnum,
    Sigs_Class_fieldEnum,
    Sigs_Component_roleEnum,
    Sigs_Cycle_length_unitEnum,
    Sigs_DosecapunitEnum,
    Sigs_DurationunitEnum,
    Sigs_FrequencyEnum,
    Sigs_PhaseEnum,
    Sigs_RouteEnum,
    Sigs_SequenceEnum,
    Sigs_Step_numberEnum,
    Sigs_SubcomponentEnum,
    Sigs_TargetleveltypeEnum,
    Sigs_TargetlevelunitEnum,
    Studies_IntentEnum,
    Studies_PhaseEnum,
    Studies_RegistryEnum,
    Studies_Sponsor_typeEnum,
    Studies_Study_designEnum,
    StudyResults_Arm_typeEnum,
    StudyResults_Comparator_codeEnum,
    StudyResults_Endpoint_classEnum,
    StudyResults_Endpoint_typeEnum,
    StudyResults_IntentEnum,
    StudyResults_Landmark_unitEnum,
    StudyResults_Metric_unitEnum,
    StudyResults_P_valueEnum,
    StudyResults_StatisticEnum,
    VariantEligibility_SubtypeEnum,
    VariantEligibility_UnitEnum,
    Variantblob_BlockEnum,
    Variantblob_Chunk_typeEnum,
)

class Authors(EntityBase, Base):
    __tablename__ = 'authors'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    filename = 'authors.csv'
    natural_key_columns = ['pmid', 'sequence', 'aff_no']
    source_defined_keys: list[str] = []
    identity_keys: list[str] = []
    denormalised_columns: list[str] = []
    derived_columns: list[str] = []

    enum_lookup: dict[str, type] = {
        'role': Authors_RoleEnum,
    }

    __table_args__ = (
        sa.UniqueConstraint('pmid', 'sequence', 'aff_no', name='uq_authors_natural_key'),
    )

    aff_no: Mapped[int] = mapped_column(BigInteger, nullable=False)
    city: Mapped[str] = mapped_column(String(255), nullable=False)
    city_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    country: Mapped[str] = mapped_column(String(255), nullable=False)
    country_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    date_added: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    department: Mapped[str] = mapped_column(String(255), nullable=False)
    flag: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fore_name_europmc: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    fore_name_hemonc: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name_europmc: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name_hemonc: Mapped[str] = mapped_column(String(255), nullable=False)
    imputed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    initials: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name_europmc: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name_hemonc: Mapped[str] = mapped_column(String(255), nullable=False)
    orcid: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    person_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    pmid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    region: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Optional[Authors_RoleEnum]] = mapped_column(Enum(Authors_RoleEnum), nullable=True)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    site: Mapped[str] = mapped_column(String(255), nullable=False)
    site_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    suffix: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    temp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    normalisation_groups: list[list[str]] = [
    ]
    pmid_exclusions_obj: Mapped[Optional['Exclusions']] = sa_relationship(
        'Exclusions',
        primaryjoin="Authors.pmid == foreign(Exclusions.pmid)",
        lazy='selectin',
        viewonly=True,
    )

    pmid_inclusions_obj: Mapped[Optional['Inclusions']] = sa_relationship(
        'Inclusions',
        primaryjoin="Authors.pmid == foreign(Inclusions.pmid)",
        lazy='selectin',
        viewonly=True,
    )


class Conditions(EntityBase, Base):
    __tablename__ = 'conditions'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    filename = 'conditions.csv'
    natural_key_columns = ['condition_cui']
    source_defined_keys: list[str] = ['condition', 'condition_cui']
    identity_keys: list[str] = ['condition_cui']
    denormalised_columns: list[str] = ['map_icd10cm', 'map_icd9cm', 'map_icdo3', 'map_icdo3_morph', 'map_oncotree', 'map_seer', 'map_type_icdo3_morph']
    derived_columns: list[str] = []

    enum_lookup: dict[str, type] = {
        'condition_type': Conditions_Condition_typeEnum,
        'section': Conditions_SectionEnum,
        'age_focus': Conditions_Age_focusEnum,
        'map_type_ncit': Conditions_Map_type_ncitEnum,
        'map_type_snomed': Conditions_Map_type_snomedEnum,
        'map_type_oncotree': Conditions_Map_type_oncotreeEnum,
        'map_type_icd9cm': Conditions_Map_type_icd9cmEnum,
        'map_type_icd10cm': Conditions_Map_type_icd10cmEnum,
        'map_type_icdo3': Conditions_Map_type_icdo3Enum,
        'map_type_icdo3_morph': Conditions_Map_type_icdo3_morphEnum,
        'map_type_seer': Conditions_Map_type_seerEnum,
    }

    __table_args__ = (
        sa.UniqueConstraint('condition_cui', name='uq_conditions_natural_key'),
    )

    age_focus: Mapped[Conditions_Age_focusEnum] = mapped_column(Enum(Conditions_Age_focusEnum), nullable=False)
    condition: Mapped[str] = mapped_column(String(255), nullable=False)
    condition_cui: Mapped[int] = mapped_column(BigInteger, nullable=False)
    condition_type: Mapped[Conditions_Condition_typeEnum] = mapped_column(Enum(Conditions_Condition_typeEnum), nullable=False)
    date_added: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    map_ncit: Mapped[str] = mapped_column(String(255), nullable=False)
    map_snomed: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    map_type_icd10cm: Mapped[Optional[Conditions_Map_type_icd10cmEnum]] = mapped_column(Enum(Conditions_Map_type_icd10cmEnum), nullable=True)
    map_type_icd9cm: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    map_type_icdo3: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    map_type_ncit: Mapped[Conditions_Map_type_ncitEnum] = mapped_column(Enum(Conditions_Map_type_ncitEnum), nullable=False)
    map_type_oncotree: Mapped[Optional[Conditions_Map_type_oncotreeEnum]] = mapped_column(Enum(Conditions_Map_type_oncotreeEnum), nullable=True)
    map_type_seer: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    map_type_snomed: Mapped[Optional[Conditions_Map_type_snomedEnum]] = mapped_column(Enum(Conditions_Map_type_snomedEnum), nullable=True)
    regimens_count: Mapped[str] = mapped_column(String(255), nullable=False)
    regimenscount: Mapped[str] = mapped_column(String(255), nullable=False)
    regimenscountdate: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    section: Mapped[str] = mapped_column(String(255), nullable=False)
    variants_count: Mapped[str] = mapped_column(String(255), nullable=False)
    variantscount: Mapped[str] = mapped_column(String(255), nullable=False)
    variantscountdate: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    normalisation_groups: list[list[str]] = [
    ]
    map_icd10cm_items: Mapped[list['conditions_Map_icd10cmMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    map_icd9cm_items: Mapped[list['conditions_Map_icd9cmMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    map_icdo3_items: Mapped[list['conditions_Map_icdo3Map']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    map_icdo3_morph_items: Mapped[list['conditions_Map_icdo3_morphMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    map_oncotree_items: Mapped[list['conditions_Map_oncotreeMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    map_seer_items: Mapped[list['conditions_Map_seerMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    map_type_icdo3_morph_items: Mapped[list['conditions_Map_type_icdo3_morphMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')

class conditions_Map_icd10cmMap(EntityBase, Base):
    __tablename__ = 'conditions_map_icd10cm'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('conditions.id'), primary_key=True)
    map_icd10cm: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Conditions'] = sa_relationship(back_populates='map_icd10cm_items')

class conditions_Map_icd9cmMap(EntityBase, Base):
    __tablename__ = 'conditions_map_icd9cm'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('conditions.id'), primary_key=True)
    map_icd9cm: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Conditions'] = sa_relationship(back_populates='map_icd9cm_items')

class conditions_Map_icdo3Map(EntityBase, Base):
    __tablename__ = 'conditions_map_icdo3'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('conditions.id'), primary_key=True)
    map_icdo3: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Conditions'] = sa_relationship(back_populates='map_icdo3_items')

class conditions_Map_icdo3_morphMap(EntityBase, Base):
    __tablename__ = 'conditions_map_icdo3_morph'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('conditions.id'), primary_key=True)
    map_icdo3_morph: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Conditions'] = sa_relationship(back_populates='map_icdo3_morph_items')

class conditions_Map_oncotreeMap(EntityBase, Base):
    __tablename__ = 'conditions_map_oncotree'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('conditions.id'), primary_key=True)
    map_oncotree: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Conditions'] = sa_relationship(back_populates='map_oncotree_items')

class conditions_Map_seerMap(EntityBase, Base):
    __tablename__ = 'conditions_map_seer'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('conditions.id'), primary_key=True)
    map_seer: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Conditions'] = sa_relationship(back_populates='map_seer_items')

class conditions_Map_type_icdo3_morphMap(EntityBase, Base):
    __tablename__ = 'conditions_map_type_icdo3_morph'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('conditions.id'), primary_key=True)
    map_type_icdo3_morph: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Conditions'] = sa_relationship(back_populates='map_type_icdo3_morph_items')

class Drugs(EntityBase, Base):
    __tablename__ = 'drugs'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    filename = 'drugs.csv'
    natural_key_columns = ['drug_cui']
    source_defined_keys: list[str] = ['drug', 'drug_cui']
    identity_keys: list[str] = ['drug_cui']
    denormalised_columns: list[str] = ['atc', 'canmed_major_class', 'canmed_major_class_cui', 'canmed_minor_class', 'canmed_minor_class_cui']
    derived_columns: list[str] = []

    enum_lookup: dict[str, type] = {
        'class_type': Drugs_Class_typeEnum,
    }

    __table_args__ = (
        sa.UniqueConstraint('drug_cui', name='uq_drugs_natural_key'),
    )

    class_type: Mapped[Optional[Drugs_Class_typeEnum]] = mapped_column(Enum(Drugs_Class_typeEnum), nullable=True)
    date_added: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    drug: Mapped[str] = mapped_column(String(255), nullable=False)
    drug_cui: Mapped[int] = mapped_column(BigInteger, nullable=False)
    drug_inn: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    investigational: Mapped[bool] = mapped_column(Boolean, nullable=False)
    main_class: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    multiagent: Mapped[bool] = mapped_column(Boolean, nullable=False)

    normalisation_groups: list[list[str]] = [
        ['canmed_major_class', 'canmed_major_class_cui'],
    ]
    atc_items: Mapped[list['drugs_AtcMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    canmed_major_class_items: Mapped[list['drugs_Canmed_major_classMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    canmed_major_class_cui_items: Mapped[list['drugs_Canmed_major_class_cuiMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    canmed_minor_class_items: Mapped[list['drugs_Canmed_minor_classMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    canmed_minor_class_cui_items: Mapped[list['drugs_Canmed_minor_class_cuiMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')

class drugs_AtcMap(EntityBase, Base):
    __tablename__ = 'drugs_atc'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('drugs.id'), primary_key=True)
    atc: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Drugs'] = sa_relationship(back_populates='atc_items')

class drugs_Canmed_major_classMap(EntityBase, Base):
    __tablename__ = 'drugs_canmed_major_class'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('drugs.id'), primary_key=True)
    canmed_major_class: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Drugs'] = sa_relationship(back_populates='canmed_major_class_items')

class drugs_Canmed_major_class_cuiMap(EntityBase, Base):
    __tablename__ = 'drugs_canmed_major_class_cui'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('drugs.id'), primary_key=True)
    canmed_major_class_cui: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False)

    parent: Mapped['Drugs'] = sa_relationship(back_populates='canmed_major_class_cui_items')

class drugs_Canmed_minor_classMap(EntityBase, Base):
    __tablename__ = 'drugs_canmed_minor_class'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('drugs.id'), primary_key=True)
    canmed_minor_class: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Drugs'] = sa_relationship(back_populates='canmed_minor_class_items')

class drugs_Canmed_minor_class_cuiMap(EntityBase, Base):
    __tablename__ = 'drugs_canmed_minor_class_cui'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('drugs.id'), primary_key=True)
    canmed_minor_class_cui: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False)

    parent: Mapped['Drugs'] = sa_relationship(back_populates='canmed_minor_class_cui_items')

class Indications(EntityBase, Base):
    __tablename__ = 'indications'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    filename = 'indications.csv'
    natural_key_columns = ['component_cui', 'condition_cui', 'regulator', 'withdrawn', 'stage', 'status', 'stage_or_status', 'age', 'ineligibility', 'prior_therapy', 'with_field', 'biomarker', 'biomarker_finding', 'study', 'substudy']
    source_defined_keys: list[str] = []
    identity_keys: list[str] = ['component_cui']
    denormalised_columns: list[str] = ['biomarker2', 'biomarker2_finding', 'biomarker2_type', 'biomarker3', 'biomarker3_finding', 'biomarker3_type', 'biomarker4', 'biomarker4_finding', 'biomarker4_type', 'biomarker_type', 'context', 'demographics', 'prior_therapy_negation', 'prior_therapy_setting', 'regimen', 'regimen_cui', 'response_contingency', 'risk_stratification']
    derived_columns: list[str] = []

    enum_lookup: dict[str, type] = {
        'regulator': Indications_RegulatorEnum,
        'note': Indications_NoteEnum,
        'sex': Indications_SexEnum,
        'age_unit': Indications_Age_unitEnum,
        'biomarker_finding': Indications_Biomarker_findingEnum,
        'biomarker_type': Indications_Biomarker_typeEnum,
        'biomarker2_finding': Indications_Biomarker2_findingEnum,
        'biomarker2_type': Indications_Biomarker2_typeEnum,
        'biomarker3_finding': Indications_Biomarker3_findingEnum,
        'biomarker3_type': Indications_Biomarker3_typeEnum,
        'biomarker4_finding': Indications_Biomarker4_findingEnum,
        'biomarker4_type': Indications_Biomarker4_typeEnum,
        'exposure_phenotype': Indications_Exposure_phenotypeEnum,
        'biomarker2': Indications_Biomarker2Enum,
        'biomarker4': Indications_Biomarker4Enum,
    }

    accelerated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    age: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    age_unit: Mapped[Optional[Indications_Age_unitEnum]] = mapped_column(Enum(Indications_Age_unitEnum), nullable=True)
    biomarker: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    biomarker_finding: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    component: Mapped[str] = mapped_column(String(255), nullable=False)
    component_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    condition: Mapped[str] = mapped_column(String(255), nullable=False)
    condition_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    date_added: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    exposure_phenotype: Mapped[Optional[Indications_Exposure_phenotypeEnum]] = mapped_column(Enum(Indications_Exposure_phenotypeEnum), nullable=True)
    first_in_class: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ineligibility: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    note: Mapped[Optional[Indications_NoteEnum]] = mapped_column(Enum(Indications_NoteEnum), nullable=True)
    prior_biomarker: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    prior_therapy: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    regulator: Mapped[Indications_RegulatorEnum] = mapped_column(Enum(Indications_RegulatorEnum), nullable=False)
    sex: Mapped[Optional[Indications_SexEnum]] = mapped_column(Enum(Indications_SexEnum), nullable=True)
    stage: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    stage_or_status: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    string: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    study: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    study_cui: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    study_yn: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    substudy: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    substudy_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    temp: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    time_contingency: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    with_field: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    withdrawn: Mapped[str] = mapped_column(String(255), nullable=False)

    normalisation_groups: list[list[str]] = [
        ['biomarker2', 'biomarker2_finding'],
        ['biomarker3', 'biomarker3_finding'],
        ['biomarker4', 'biomarker4_finding'],
    ]
    biomarker2_items: Mapped[list['indications_Biomarker2Map']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    biomarker2_finding_items: Mapped[list['indications_Biomarker2_findingMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    biomarker2_type_items: Mapped[list['indications_Biomarker2_typeMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    biomarker3_items: Mapped[list['indications_Biomarker3Map']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    biomarker3_finding_items: Mapped[list['indications_Biomarker3_findingMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    biomarker3_type_items: Mapped[list['indications_Biomarker3_typeMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    biomarker4_items: Mapped[list['indications_Biomarker4Map']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    biomarker4_finding_items: Mapped[list['indications_Biomarker4_findingMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    biomarker4_type_items: Mapped[list['indications_Biomarker4_typeMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    biomarker_type_items: Mapped[list['indications_Biomarker_typeMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    context_items: Mapped[list['indications_ContextMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    demographics_items: Mapped[list['indications_DemographicsMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    prior_therapy_negation_items: Mapped[list['indications_Prior_therapy_negationMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    prior_therapy_setting_items: Mapped[list['indications_Prior_therapy_settingMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    regimen_items: Mapped[list['indications_RegimenMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    regimen_cui_items: Mapped[list['indications_Regimen_cuiMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    response_contingency_items: Mapped[list['indications_Response_contingencyMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    risk_stratification_items: Mapped[list['indications_Risk_stratificationMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    condition_obj: Mapped[Optional['Conditions']] = sa_relationship(
        'Conditions',
        primaryjoin="Indications.condition == foreign(Conditions.condition)",
        lazy='selectin',
        viewonly=True,
    )

    condition_cui_obj: Mapped[Optional['Conditions']] = sa_relationship(
        'Conditions',
        primaryjoin="Indications.condition_cui == foreign(Conditions.condition_cui)",
        lazy='selectin',
        viewonly=True,
    )

    regimen_cui_objects: Mapped[list['Regimens']] = sa_relationship(
        'Regimens',
        secondary='indications_regimen_cui',
        primaryjoin="Indications.id == indications_regimen_cui.c.parent_id",
        secondaryjoin="Regimens.regimen_cui == indications_regimen_cui.c.regimen_cui",
        lazy='selectin',
        viewonly=True,
    )


class indications_Biomarker2Map(EntityBase, Base):
    __tablename__ = 'indications_biomarker2'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('indications.id'), primary_key=True)
    biomarker2: Mapped[Indications_Biomarker2Enum] = mapped_column(Enum(Indications_Biomarker2Enum), primary_key=True, nullable=False)

    parent: Mapped['Indications'] = sa_relationship(back_populates='biomarker2_items')

class indications_Biomarker2_findingMap(EntityBase, Base):
    __tablename__ = 'indications_biomarker2_finding'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('indications.id'), primary_key=True)
    biomarker2_finding: Mapped[Indications_Biomarker2_findingEnum] = mapped_column(Enum(Indications_Biomarker2_findingEnum), primary_key=True, nullable=False)

    parent: Mapped['Indications'] = sa_relationship(back_populates='biomarker2_finding_items')

class indications_Biomarker2_typeMap(EntityBase, Base):
    __tablename__ = 'indications_biomarker2_type'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('indications.id'), primary_key=True)
    biomarker2_type: Mapped[Indications_Biomarker2_typeEnum] = mapped_column(Enum(Indications_Biomarker2_typeEnum), primary_key=True, nullable=False)

    parent: Mapped['Indications'] = sa_relationship(back_populates='biomarker2_type_items')

class indications_Biomarker3Map(EntityBase, Base):
    __tablename__ = 'indications_biomarker3'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('indications.id'), primary_key=True)
    biomarker3: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Indications'] = sa_relationship(back_populates='biomarker3_items')

class indications_Biomarker3_findingMap(EntityBase, Base):
    __tablename__ = 'indications_biomarker3_finding'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('indications.id'), primary_key=True)
    biomarker3_finding: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Indications'] = sa_relationship(back_populates='biomarker3_finding_items')

class indications_Biomarker3_typeMap(EntityBase, Base):
    __tablename__ = 'indications_biomarker3_type'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('indications.id'), primary_key=True)
    biomarker3_type: Mapped[Indications_Biomarker3_typeEnum] = mapped_column(Enum(Indications_Biomarker3_typeEnum), primary_key=True, nullable=False)

    parent: Mapped['Indications'] = sa_relationship(back_populates='biomarker3_type_items')

class indications_Biomarker4Map(EntityBase, Base):
    __tablename__ = 'indications_biomarker4'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('indications.id'), primary_key=True)
    biomarker4: Mapped[Indications_Biomarker4Enum] = mapped_column(Enum(Indications_Biomarker4Enum), primary_key=True, nullable=False)

    parent: Mapped['Indications'] = sa_relationship(back_populates='biomarker4_items')

class indications_Biomarker4_findingMap(EntityBase, Base):
    __tablename__ = 'indications_biomarker4_finding'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('indications.id'), primary_key=True)
    biomarker4_finding: Mapped[Indications_Biomarker4_findingEnum] = mapped_column(Enum(Indications_Biomarker4_findingEnum), primary_key=True, nullable=False)

    parent: Mapped['Indications'] = sa_relationship(back_populates='biomarker4_finding_items')

class indications_Biomarker4_typeMap(EntityBase, Base):
    __tablename__ = 'indications_biomarker4_type'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('indications.id'), primary_key=True)
    biomarker4_type: Mapped[Indications_Biomarker4_typeEnum] = mapped_column(Enum(Indications_Biomarker4_typeEnum), primary_key=True, nullable=False)

    parent: Mapped['Indications'] = sa_relationship(back_populates='biomarker4_type_items')

class indications_Biomarker_typeMap(EntityBase, Base):
    __tablename__ = 'indications_biomarker_type'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('indications.id'), primary_key=True)
    biomarker_type: Mapped[Indications_Biomarker_typeEnum] = mapped_column(Enum(Indications_Biomarker_typeEnum), primary_key=True, nullable=False)

    parent: Mapped['Indications'] = sa_relationship(back_populates='biomarker_type_items')

class indications_ContextMap(EntityBase, Base):
    __tablename__ = 'indications_context'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('indications.id'), primary_key=True)
    context: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Indications'] = sa_relationship(back_populates='context_items')

class indications_DemographicsMap(EntityBase, Base):
    __tablename__ = 'indications_demographics'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('indications.id'), primary_key=True)
    demographics: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Indications'] = sa_relationship(back_populates='demographics_items')

class indications_Prior_therapy_negationMap(EntityBase, Base):
    __tablename__ = 'indications_prior_therapy_negation'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('indications.id'), primary_key=True)
    prior_therapy_negation: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Indications'] = sa_relationship(back_populates='prior_therapy_negation_items')

class indications_Prior_therapy_settingMap(EntityBase, Base):
    __tablename__ = 'indications_prior_therapy_setting'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('indications.id'), primary_key=True)
    prior_therapy_setting: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Indications'] = sa_relationship(back_populates='prior_therapy_setting_items')

class indications_RegimenMap(EntityBase, Base):
    __tablename__ = 'indications_regimen'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('indications.id'), primary_key=True)
    regimen: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Indications'] = sa_relationship(back_populates='regimen_items')

class indications_Regimen_cuiMap(EntityBase, Base):
    __tablename__ = 'indications_regimen_cui'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('indications.id'), primary_key=True)
    regimen_cui: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False)

    parent: Mapped['Indications'] = sa_relationship(back_populates='regimen_cui_items')

class indications_Response_contingencyMap(EntityBase, Base):
    __tablename__ = 'indications_response_contingency'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('indications.id'), primary_key=True)
    response_contingency: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Indications'] = sa_relationship(back_populates='response_contingency_items')

class indications_Risk_stratificationMap(EntityBase, Base):
    __tablename__ = 'indications_risk_stratification'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('indications.id'), primary_key=True)
    risk_stratification: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Indications'] = sa_relationship(back_populates='risk_stratification_items')

class Persons(EntityBase, Base):
    __tablename__ = 'persons'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    filename = 'persons.csv'
    natural_key_columns = ['name', 'person_cui']
    source_defined_keys: list[str] = []
    identity_keys: list[str] = ['person_cui']
    denormalised_columns: list[str] = ['condition_types', 'conditions', 'country', 'location', 'orcid', 'site', 'study_groups', 'study_sponsors']
    derived_columns: list[str] = ['total_pubs']

    enum_lookup: dict[str, type] = {
        'hyphen_type': Persons_Hyphen_typeEnum,
        'gender': Persons_GenderEnum,
        'vital_status': Persons_Vital_statusEnum,
    }

    co_authors: Mapped[int] = mapped_column(BigInteger, nullable=False)
    co_authorships: Mapped[int] = mapped_column(BigInteger, nullable=False)
    date_added: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    first_active_year: Mapped[str] = mapped_column(String(255), nullable=False)
    gender: Mapped[Persons_GenderEnum] = mapped_column(Enum(Persons_GenderEnum), nullable=False)
    guideline_pubs: Mapped[str] = mapped_column(String(255), nullable=False)
    hyphen_type: Mapped[Optional[Persons_Hyphen_typeEnum]] = mapped_column(Enum(Persons_Hyphen_typeEnum), nullable=True)
    last_active_year: Mapped[str] = mapped_column(String(255), nullable=False)
    multi_site: Mapped[bool] = mapped_column(Boolean, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    person_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    ph3_studies: Mapped[str] = mapped_column(String(255), nullable=False)
    pivotal_studies: Mapped[str] = mapped_column(String(255), nullable=False)
    senior_pubs: Mapped[int] = mapped_column(BigInteger, nullable=False)
    temp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vital_status: Mapped[int] = mapped_column(BigInteger, nullable=False)

    normalisation_groups: list[list[str]] = [
    ]
    condition_types_items: Mapped[list['persons_Condition_typesMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    conditions_items: Mapped[list['persons_ConditionsMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    country_items: Mapped[list['persons_CountryMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    location_items: Mapped[list['persons_LocationMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    orcid_items: Mapped[list['persons_OrcidMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    site_items: Mapped[list['persons_SiteMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    study_groups_items: Mapped[list['persons_Study_groupsMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    study_sponsors_items: Mapped[list['persons_Study_sponsorsMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')

class persons_Condition_typesMap(EntityBase, Base):
    __tablename__ = 'persons_condition_types'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('persons.id'), primary_key=True)
    condition_types: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Persons'] = sa_relationship(back_populates='condition_types_items')

class persons_ConditionsMap(EntityBase, Base):
    __tablename__ = 'persons_conditions'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('persons.id'), primary_key=True)
    conditions: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Persons'] = sa_relationship(back_populates='conditions_items')

class persons_CountryMap(EntityBase, Base):
    __tablename__ = 'persons_country'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('persons.id'), primary_key=True)
    country: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Persons'] = sa_relationship(back_populates='country_items')

class persons_LocationMap(EntityBase, Base):
    __tablename__ = 'persons_location'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('persons.id'), primary_key=True)
    location: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Persons'] = sa_relationship(back_populates='location_items')

class persons_OrcidMap(EntityBase, Base):
    __tablename__ = 'persons_orcid'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('persons.id'), primary_key=True)
    orcid: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Persons'] = sa_relationship(back_populates='orcid_items')

class persons_SiteMap(EntityBase, Base):
    __tablename__ = 'persons_site'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('persons.id'), primary_key=True)
    site: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Persons'] = sa_relationship(back_populates='site_items')

class persons_Study_groupsMap(EntityBase, Base):
    __tablename__ = 'persons_study_groups'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('persons.id'), primary_key=True)
    study_groups: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)

    parent: Mapped['Persons'] = sa_relationship(back_populates='study_groups_items')

class persons_Study_sponsorsMap(EntityBase, Base):
    __tablename__ = 'persons_study_sponsors'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('persons.id'), primary_key=True)
    study_sponsors: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)

    parent: Mapped['Persons'] = sa_relationship(back_populates='study_sponsors_items')

class Refs(EntityBase, Base):
    __tablename__ = 'refs'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    filename = 'refs.csv'
    natural_key_columns = ['study_cui', 'substudy_cui', 'condition_cui', 'biomarker_finding', 'pmid']
    source_defined_keys: list[str] = []
    identity_keys: list[str] = []
    denormalised_columns: list[str] = ['biblio', 'doi', 'reference', 'study', 'title']
    derived_columns: list[str] = ['prop_valid_aff_city', 'prop_valid_aff_country', 'prop_valid_aff_region', 'prop_valid_aff_site']

    enum_lookup: dict[str, type] = {
        'ref_type': Refs_Ref_typeEnum,
    }

    biomarker_finding: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    citations: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    citations_as_of: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    condition: Mapped[str] = mapped_column(String(255), nullable=False)
    condition_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    date_added: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    errata: Mapped[bool] = mapped_column(Boolean, nullable=False)
    journal: Mapped[str] = mapped_column(String(255), nullable=False)
    journal_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    pmcid: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pmid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pub_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ref_type: Mapped[str] = mapped_column(String(255), nullable=False)
    reference_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    study_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    substudy: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    substudy_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    temp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    normalisation_groups: list[list[str]] = [
    ]
    biblio_items: Mapped[list['refs_BiblioMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    doi_items: Mapped[list['refs_DoiMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    reference_items: Mapped[list['refs_ReferenceMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    study_items: Mapped[list['refs_StudyMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    title_items: Mapped[list['refs_TitleMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    pmid_exclusions_obj: Mapped[Optional['Exclusions']] = sa_relationship(
        'Exclusions',
        primaryjoin="Refs.pmid == foreign(Exclusions.pmid)",
        lazy='selectin',
        viewonly=True,
    )

    pmid_inclusions_obj: Mapped[Optional['Inclusions']] = sa_relationship(
        'Inclusions',
        primaryjoin="Refs.pmid == foreign(Inclusions.pmid)",
        lazy='selectin',
        viewonly=True,
    )

    condition_obj: Mapped[Optional['Conditions']] = sa_relationship(
        'Conditions',
        primaryjoin="Refs.condition == foreign(Conditions.condition)",
        lazy='selectin',
        viewonly=True,
    )

    condition_cui_obj: Mapped[Optional['Conditions']] = sa_relationship(
        'Conditions',
        primaryjoin="Refs.condition_cui == foreign(Conditions.condition_cui)",
        lazy='selectin',
        viewonly=True,
    )

    study_objects: Mapped[list['Studies']] = sa_relationship(
        'Studies',
        secondary='refs_study',
        primaryjoin="Refs.id == refs_study.c.parent_id",
        secondaryjoin="Studies.study == refs_study.c.study",
        lazy='selectin',
        viewonly=True,
    )


class refs_BiblioMap(EntityBase, Base):
    __tablename__ = 'refs_biblio'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('refs.id'), primary_key=True)
    biblio: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Refs'] = sa_relationship(back_populates='biblio_items')

class refs_DoiMap(EntityBase, Base):
    __tablename__ = 'refs_doi'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('refs.id'), primary_key=True)
    doi: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Refs'] = sa_relationship(back_populates='doi_items')

class refs_ReferenceMap(EntityBase, Base):
    __tablename__ = 'refs_reference'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('refs.id'), primary_key=True)
    reference: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Refs'] = sa_relationship(back_populates='reference_items')

class refs_StudyMap(EntityBase, Base):
    __tablename__ = 'refs_study'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('refs.id'), primary_key=True)
    study: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Refs'] = sa_relationship(back_populates='study_items')

class refs_TitleMap(EntityBase, Base):
    __tablename__ = 'refs_title'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('refs.id'), primary_key=True)
    title: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)

    parent: Mapped['Refs'] = sa_relationship(back_populates='title_items')

class Regimens(EntityBase, Base):
    __tablename__ = 'regimens'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    filename = 'regimens.csv'
    natural_key_columns = ['regimen_cui']
    source_defined_keys: list[str] = ['regimen_name', 'regimen_cui']
    identity_keys: list[str] = []
    denormalised_columns: list[str] = []
    derived_columns: list[str] = []

    enum_lookup: dict[str, type] = {
        'regimen_type': Regimens_Regimen_typeEnum,
        'highest_evidence': Regimens_Highest_evidenceEnum,
        'all_sact_fda': Regimens_All_sact_fdaEnum,
    }

    __table_args__ = (
        sa.UniqueConstraint('regimen_cui', name='uq_regimens_natural_key'),
    )

    all_sact_fda: Mapped[Optional[Regimens_All_sact_fdaEnum]] = mapped_column(Enum(Regimens_All_sact_fdaEnum), nullable=True)
    all_sact_fda_as_of: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    components: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    contains_rt: Mapped[bool] = mapped_column(Boolean, nullable=False)
    date_added: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    first_studied: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    highest_evidence: Mapped[Regimens_Highest_evidenceEnum] = mapped_column(Enum(Regimens_Highest_evidenceEnum), nullable=False)
    last_published: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    map_ncit: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    regimen_cui: Mapped[int] = mapped_column(BigInteger, nullable=False)
    regimen_name: Mapped[str] = mapped_column(String(255), nullable=False)
    regimen_type: Mapped[Regimens_Regimen_typeEnum] = mapped_column(Enum(Regimens_Regimen_typeEnum), nullable=False)
    sact: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sact_modalities: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    studies: Mapped[int] = mapped_column(BigInteger, nullable=False)
    temp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    variantcount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    variantcountdate: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    normalisation_groups: list[list[str]] = [
    ]

class Sigs(EntityBase, Base):
    __tablename__ = 'sigs'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    filename = 'sigs.csv'
    natural_key_columns = ['variant_cui', 'portion', 'component_cui', 'subcomponent_cui', 'frequency_cui', 'timing_sequence', 'step_number']
    source_defined_keys: list[str] = []
    identity_keys: list[str] = []
    denormalised_columns: list[str] = ['cyclesigs_note', 'inparens', 'seqrel', 'seqrelwhat', 'seqrelwhen', 'seqrelwhenunit', 'study', 'timing']
    derived_columns: list[str] = []

    enum_lookup: dict[str, type] = {
        'phase': Sigs_PhaseEnum,
        'component_role': Sigs_Component_roleEnum,
        'cycle_length_unit': Sigs_Cycle_length_unitEnum,
        'step_number': Sigs_Step_numberEnum,
        'class_field': Sigs_Class_fieldEnum,
        'targetleveltype': Sigs_TargetleveltypeEnum,
        'subcomponent': Sigs_SubcomponentEnum,
        'dosecapunit': Sigs_DosecapunitEnum,
        'targetlevelunit': Sigs_TargetlevelunitEnum,
        'route': Sigs_RouteEnum,
        'durationunit': Sigs_DurationunitEnum,
        'frequency': Sigs_FrequencyEnum,
        'sequence': Sigs_SequenceEnum,
    }

    alldays: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    class_field: Mapped[Optional[Sigs_Class_fieldEnum]] = mapped_column(Enum(Sigs_Class_fieldEnum), nullable=True)
    component: Mapped[str] = mapped_column(String(255), nullable=False)
    component_cui: Mapped[int] = mapped_column(BigInteger, nullable=False)
    component_role: Mapped[Sigs_Component_roleEnum] = mapped_column(Enum(Sigs_Component_roleEnum), nullable=False)
    cycle_length_lb: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    cycle_length_ub: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    cycle_length_unit: Mapped[Optional[Sigs_Cycle_length_unitEnum]] = mapped_column(Enum(Sigs_Cycle_length_unitEnum), nullable=True)
    cyclesigs: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    date_added: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    divided: Mapped[bool] = mapped_column(Boolean, nullable=False)
    dosecapnum: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dosecapunit: Mapped[Optional[Sigs_DosecapunitEnum]] = mapped_column(Enum(Sigs_DosecapunitEnum), nullable=True)
    dosecapunit_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    dosemaxnum: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    doseminnum: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    doseunit: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    doseunit_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    durationmaxnum: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    durationminnum: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    durationunit: Mapped[Optional[Sigs_DurationunitEnum]] = mapped_column(Enum(Sigs_DurationunitEnum), nullable=True)
    durationunit_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    frequency: Mapped[Optional[Sigs_FrequencyEnum]] = mapped_column(Enum(Sigs_FrequencyEnum), nullable=True)
    frequency_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    phase: Mapped[Optional[Sigs_PhaseEnum]] = mapped_column(Enum(Sigs_PhaseEnum), nullable=True)
    phase_step: Mapped[int] = mapped_column(BigInteger, nullable=False)
    portion: Mapped[str] = mapped_column(String(255), nullable=False)
    regimen: Mapped[str] = mapped_column(String(255), nullable=False)
    regimen_cui: Mapped[int] = mapped_column(BigInteger, nullable=False)
    route: Mapped[Optional[Sigs_RouteEnum]] = mapped_column(Enum(Sigs_RouteEnum), nullable=True)
    route_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    sequence: Mapped[Optional[Sigs_SequenceEnum]] = mapped_column(Enum(Sigs_SequenceEnum), nullable=True)
    step_number: Mapped[str] = mapped_column(String(255), nullable=False)
    subcomponent: Mapped[Optional[Sigs_SubcomponentEnum]] = mapped_column(Enum(Sigs_SubcomponentEnum), nullable=True)
    subcomponent_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    tail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    targetlevel: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    targetleveltype: Mapped[Optional[Sigs_TargetleveltypeEnum]] = mapped_column(Enum(Sigs_TargetleveltypeEnum), nullable=True)
    targetlevelunit: Mapped[Optional[Sigs_TargetlevelunitEnum]] = mapped_column(Enum(Sigs_TargetlevelunitEnum), nullable=True)
    targetlevelunit_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    temp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    timing_sequence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    variant: Mapped[str] = mapped_column(String(255), nullable=False)
    variant_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    normalisation_groups: list[list[str]] = [
    ]
    cyclesigs_note_items: Mapped[list['sigs_Cyclesigs_noteMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    inparens_items: Mapped[list['sigs_InparensMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    seqrel_items: Mapped[list['sigs_SeqrelMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    seqrelwhat_items: Mapped[list['sigs_SeqrelwhatMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    seqrelwhen_items: Mapped[list['sigs_SeqrelwhenMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    seqrelwhenunit_items: Mapped[list['sigs_SeqrelwhenunitMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    study_items: Mapped[list['sigs_StudyMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    timing_items: Mapped[list['sigs_TimingMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    regimen_cui_obj: Mapped[Optional['Regimens']] = sa_relationship(
        'Regimens',
        primaryjoin="Sigs.regimen_cui == foreign(Regimens.regimen_cui)",
        lazy='selectin',
        viewonly=True,
    )

    study_objects: Mapped[list['Studies']] = sa_relationship(
        'Studies',
        secondary='sigs_study',
        primaryjoin="Sigs.id == sigs_study.c.parent_id",
        secondaryjoin="Studies.study == sigs_study.c.study",
        lazy='selectin',
        viewonly=True,
    )


class sigs_Cyclesigs_noteMap(EntityBase, Base):
    __tablename__ = 'sigs_cyclesigs_note'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('sigs.id'), primary_key=True)
    cyclesigs_note: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)

    parent: Mapped['Sigs'] = sa_relationship(back_populates='cyclesigs_note_items')

class sigs_InparensMap(EntityBase, Base):
    __tablename__ = 'sigs_inparens'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('sigs.id'), primary_key=True)
    inparens: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Sigs'] = sa_relationship(back_populates='inparens_items')

class sigs_SeqrelMap(EntityBase, Base):
    __tablename__ = 'sigs_seqrel'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('sigs.id'), primary_key=True)
    seqrel: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Sigs'] = sa_relationship(back_populates='seqrel_items')

class sigs_SeqrelwhatMap(EntityBase, Base):
    __tablename__ = 'sigs_seqrelwhat'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('sigs.id'), primary_key=True)
    seqrelwhat: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Sigs'] = sa_relationship(back_populates='seqrelwhat_items')

class sigs_SeqrelwhenMap(EntityBase, Base):
    __tablename__ = 'sigs_seqrelwhen'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('sigs.id'), primary_key=True)
    seqrelwhen: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Sigs'] = sa_relationship(back_populates='seqrelwhen_items')

class sigs_SeqrelwhenunitMap(EntityBase, Base):
    __tablename__ = 'sigs_seqrelwhenunit'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('sigs.id'), primary_key=True)
    seqrelwhenunit: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Sigs'] = sa_relationship(back_populates='seqrelwhenunit_items')

class sigs_StudyMap(EntityBase, Base):
    __tablename__ = 'sigs_study'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('sigs.id'), primary_key=True)
    study: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Sigs'] = sa_relationship(back_populates='study_items')

class sigs_TimingMap(EntityBase, Base):
    __tablename__ = 'sigs_timing'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('sigs.id'), primary_key=True)
    timing: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Sigs'] = sa_relationship(back_populates='timing_items')

class Studies(EntityBase, Base):
    __tablename__ = 'studies'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    filename = 'studies.csv'
    natural_key_columns = ['study_cui', 'substudy_cui', 'condition_cui', 'biomarker_finding']
    source_defined_keys: list[str] = []
    identity_keys: list[str] = ['study']
    denormalised_columns: list[str] = ['intent', 'sponsor', 'study_group']
    derived_columns: list[str] = []

    enum_lookup: dict[str, type] = {
        'registry': Studies_RegistryEnum,
        'intent': Studies_IntentEnum,
        'phase': Studies_PhaseEnum,
        'study_design': Studies_Study_designEnum,
        'sponsor_type': Studies_Sponsor_typeEnum,
    }

    biomarker_finding: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    condition: Mapped[str] = mapped_column(String(255), nullable=False)
    condition_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    date_added: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    enrollment: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phase: Mapped[str] = mapped_column(String(255), nullable=False)
    pubs_in_hemonc: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    reg_study: Mapped[bool] = mapped_column(Boolean, nullable=False)
    registry: Mapped[Optional[Studies_RegistryEnum]] = mapped_column(Enum(Studies_RegistryEnum), nullable=True)  # type: ignore[misc,assignment]  # collides with DeclarativeBase ClassVar
    sact: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sponsor_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    sponsor_type: Mapped[Optional[Studies_Sponsor_typeEnum]] = mapped_column(Enum(Studies_Sponsor_typeEnum), nullable=True)
    start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    study: Mapped[str] = mapped_column(String(255), nullable=False)
    study_arms: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    study_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    study_design: Mapped[Optional[Studies_Study_designEnum]] = mapped_column(Enum(Studies_Study_designEnum), nullable=True)
    study_design_imputed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    substudy: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    substudy_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    temp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trial_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    unreg_study: Mapped[bool] = mapped_column(Boolean, nullable=False)

    normalisation_groups: list[list[str]] = [
    ]
    intent_items: Mapped[list['studies_IntentMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    sponsor_items: Mapped[list['studies_SponsorMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    study_group_items: Mapped[list['studies_Study_groupMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    condition_obj: Mapped[Optional['Conditions']] = sa_relationship(
        'Conditions',
        primaryjoin="Studies.condition == foreign(Conditions.condition)",
        lazy='selectin',
        viewonly=True,
    )

    condition_cui_obj: Mapped[Optional['Conditions']] = sa_relationship(
        'Conditions',
        primaryjoin="Studies.condition_cui == foreign(Conditions.condition_cui)",
        lazy='selectin',
        viewonly=True,
    )


class studies_IntentMap(EntityBase, Base):
    __tablename__ = 'studies_intent'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('studies.id'), primary_key=True)
    intent: Mapped[Studies_IntentEnum] = mapped_column(Enum(Studies_IntentEnum), primary_key=True, nullable=False)

    parent: Mapped['Studies'] = sa_relationship(back_populates='intent_items')

class studies_SponsorMap(EntityBase, Base):
    __tablename__ = 'studies_sponsor'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('studies.id'), primary_key=True)
    sponsor: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)

    parent: Mapped['Studies'] = sa_relationship(back_populates='sponsor_items')

class studies_Study_groupMap(EntityBase, Base):
    __tablename__ = 'studies_study_group'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('studies.id'), primary_key=True)
    study_group: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Studies'] = sa_relationship(back_populates='study_group_items')

class StudyResults(EntityBase, Base):
    __tablename__ = 'study_results'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    filename = 'study_results.csv'
    natural_key_columns = ['study_cui', 'substudy_cui', 'condition_cui', 'biomarker_finding', 'context', 'regimen', 'r_modifier', 'comparator', 'c_modifier', 'endpoint', 'metric', 'metric_version']
    source_defined_keys: list[str] = []
    identity_keys: list[str] = []
    denormalised_columns: list[str] = ['comparator_code']
    derived_columns: list[str] = ['metric_num_that_arm', 'metric_num_this_arm']

    enum_lookup: dict[str, type] = {
        'intent': StudyResults_IntentEnum,
        'comparator_code': StudyResults_Comparator_codeEnum,
        'endpoint_class': StudyResults_Endpoint_classEnum,
        'landmark_unit': StudyResults_Landmark_unitEnum,
        'endpoint_type': StudyResults_Endpoint_typeEnum,
        'arm_type': StudyResults_Arm_typeEnum,
        'metric_unit': StudyResults_Metric_unitEnum,
        'statistic': StudyResults_StatisticEnum,
        'p_value': StudyResults_P_valueEnum,
    }

    arm_type: Mapped[Optional[StudyResults_Arm_typeEnum]] = mapped_column(Enum(StudyResults_Arm_typeEnum), nullable=True)
    biomarker_finding: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    c_modifier: Mapped[str] = mapped_column(String(255), nullable=False)
    comparator: Mapped[str] = mapped_column(Text, nullable=False)
    condition: Mapped[str] = mapped_column(String(255), nullable=False)
    condition_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    context: Mapped[str] = mapped_column(String(255), nullable=False)
    date_added: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    efficacy: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    endpoint: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    endpoint_class: Mapped[Optional[StudyResults_Endpoint_classEnum]] = mapped_column(Enum(StudyResults_Endpoint_classEnum), nullable=True)
    endpoint_type: Mapped[Optional[StudyResults_Endpoint_typeEnum]] = mapped_column(Enum(StudyResults_Endpoint_typeEnum), nullable=True)
    error: Mapped[bool] = mapped_column(Boolean, nullable=False)
    est_ci: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    est_lb: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    est_ub: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    estimate: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    intent: Mapped[StudyResults_IntentEnum] = mapped_column(Enum(StudyResults_IntentEnum), nullable=False)
    landmark_num: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    landmark_unit: Mapped[Optional[StudyResults_Landmark_unitEnum]] = mapped_column(Enum(StudyResults_Landmark_unitEnum), nullable=True)
    metric: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    metric_ci: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    metric_lb: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    metric_ub: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    metric_unit: Mapped[Optional[StudyResults_Metric_unitEnum]] = mapped_column(Enum(StudyResults_Metric_unitEnum), nullable=True)
    metric_version: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    p_value: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    r_modifier: Mapped[str] = mapped_column(String(255), nullable=False)
    regimen: Mapped[str] = mapped_column(String(255), nullable=False)
    regimen_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    statistic: Mapped[Optional[StudyResults_StatisticEnum]] = mapped_column(Enum(StudyResults_StatisticEnum), nullable=True)
    study: Mapped[str] = mapped_column(String(255), nullable=False)
    study_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    substudy: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    substudy_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    temp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    toxicity: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    normalisation_groups: list[list[str]] = [
    ]
    comparator_code_items: Mapped[list['study_results_Comparator_codeMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    regimen_cui_obj: Mapped[Optional['Regimens']] = sa_relationship(
        'Regimens',
        primaryjoin="StudyResults.regimen_cui == foreign(Regimens.regimen_cui)",
        lazy='selectin',
        viewonly=True,
    )

    condition_obj: Mapped[Optional['Conditions']] = sa_relationship(
        'Conditions',
        primaryjoin="StudyResults.condition == foreign(Conditions.condition)",
        lazy='selectin',
        viewonly=True,
    )

    condition_cui_obj: Mapped[Optional['Conditions']] = sa_relationship(
        'Conditions',
        primaryjoin="StudyResults.condition_cui == foreign(Conditions.condition_cui)",
        lazy='selectin',
        viewonly=True,
    )


class study_results_Comparator_codeMap(EntityBase, Base):
    __tablename__ = 'study_results_comparator_code'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('study_results.id'), primary_key=True)
    comparator_code: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['StudyResults'] = sa_relationship(back_populates='comparator_code_items')

class VariantEligibility(EntityBase, Base):
    __tablename__ = 'variant_eligibility'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    filename = 'variant_eligibility.csv'
    natural_key_columns = ['variant_cui', 'logic_count']
    source_defined_keys: list[str] = []
    identity_keys: list[str] = []
    denormalised_columns: list[str] = ['study']
    derived_columns: list[str] = []

    enum_lookup: dict[str, type] = {
        'subtype': VariantEligibility_SubtypeEnum,
        'unit': VariantEligibility_UnitEnum,
    }

    date_added: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    logic: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    logic_count: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    regimen: Mapped[str] = mapped_column(String(255), nullable=False)
    regimen_cui: Mapped[int] = mapped_column(BigInteger, nullable=False)
    string: Mapped[str] = mapped_column(String(255), nullable=False)
    subtype: Mapped[Optional[VariantEligibility_SubtypeEnum]] = mapped_column(Enum(VariantEligibility_SubtypeEnum), nullable=True)
    temp: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    type: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[Optional[VariantEligibility_UnitEnum]] = mapped_column(Enum(VariantEligibility_UnitEnum), nullable=True)
    unit_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    variant_cui: Mapped[int] = mapped_column(BigInteger, nullable=False)

    normalisation_groups: list[list[str]] = [
    ]
    study_items: Mapped[list['variant_eligibility_StudyMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    regimen_cui_obj: Mapped[Optional['Regimens']] = sa_relationship(
        'Regimens',
        primaryjoin="VariantEligibility.regimen_cui == foreign(Regimens.regimen_cui)",
        lazy='selectin',
        viewonly=True,
    )

    unit_obj: Mapped[Optional['Units']] = sa_relationship(
        'Units',
        primaryjoin="VariantEligibility.unit == foreign(Units.unit)",
        lazy='selectin',
        viewonly=True,
    )

    study_objects: Mapped[list['Studies']] = sa_relationship(
        'Studies',
        secondary='variant_eligibility_study',
        primaryjoin="VariantEligibility.id == variant_eligibility_study.c.parent_id",
        secondaryjoin="Studies.study == variant_eligibility_study.c.study",
        lazy='selectin',
        viewonly=True,
    )


class variant_eligibility_StudyMap(EntityBase, Base):
    __tablename__ = 'variant_eligibility_study'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('variant_eligibility.id'), primary_key=True)
    study: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['VariantEligibility'] = sa_relationship(back_populates='study_items')

class Variants(EntityBase, Base):
    __tablename__ = 'variants'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    filename = 'variants.csv'
    natural_key_columns = ['variant_cui', 'version']
    source_defined_keys: list[str] = []
    identity_keys: list[str] = ['variant_cui']
    denormalised_columns: list[str] = ['blob', 'study', 'tracer']
    derived_columns: list[str] = []

    enum_lookup: dict[str, type] = {}

    __table_args__ = (
        sa.UniqueConstraint('variant_cui', 'version', name='uq_variants_natural_key'),
    )

    allsigshavecyclesigs: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allsigshavedose: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allsigshavedoseunit: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allsigshaveduration: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allsigshavedurationunit: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allsigshavefrequency: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allsigshaveroute: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allsigshaveschedule: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allsigshavesequence: Mapped[bool] = mapped_column(Boolean, nullable=False)
    blob_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    components: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cyclesigs: Mapped[int] = mapped_column(BigInteger, nullable=False)
    date_added: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    date_study_modified: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    date_tracer_modified: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    fullyspecified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    portions: Mapped[int] = mapped_column(BigInteger, nullable=False)
    regimen: Mapped[str] = mapped_column(String(255), nullable=False)
    regimen_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    routes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sigs: Mapped[int] = mapped_column(BigInteger, nullable=False)
    temp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    variant: Mapped[str] = mapped_column(String(255), nullable=False)
    variant_cui: Mapped[int] = mapped_column(BigInteger, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)

    normalisation_groups: list[list[str]] = [
    ]
    blob_items: Mapped[list['variants_BlobMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    study_items: Mapped[list['variants_StudyMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    tracer_items: Mapped[list['variants_TracerMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    regimen_cui_obj: Mapped[Optional['Regimens']] = sa_relationship(
        'Regimens',
        primaryjoin="Variants.regimen_cui == foreign(Regimens.regimen_cui)",
        lazy='selectin',
        viewonly=True,
    )

    study_objects: Mapped[list['Studies']] = sa_relationship(
        'Studies',
        secondary='variants_study',
        primaryjoin="Variants.id == variants_study.c.parent_id",
        secondaryjoin="Studies.study == variants_study.c.study",
        lazy='selectin',
        viewonly=True,
    )


class variants_BlobMap(EntityBase, Base):
    __tablename__ = 'variants_blob'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('variants.id'), primary_key=True)
    blob: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)

    parent: Mapped['Variants'] = sa_relationship(back_populates='blob_items')

class variants_StudyMap(EntityBase, Base):
    __tablename__ = 'variants_study'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('variants.id'), primary_key=True)
    study: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Variants'] = sa_relationship(back_populates='study_items')

class variants_TracerMap(EntityBase, Base):
    __tablename__ = 'variants_tracer'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('variants.id'), primary_key=True)
    tracer: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Variants'] = sa_relationship(back_populates='tracer_items')

class Canonicaltriples(EntityBase, Base):
    __tablename__ = 'canonicaltriples'
    filename = 'canonical_triples.csv'
    natural_key_columns = ['class_1', 'relationship', 'class_2']
    source_defined_keys: list[str] = []
    identity_keys: list[str] = []
    denormalised_columns: list[str] = ['class_1_provenance', 'class_2_provenance']
    derived_columns: list[str] = []

    enum_lookup: dict[str, type] = {
        'class_1': Canonicaltriples_Class_1Enum,
    }

    class_1: Mapped[Canonicaltriples_Class_1Enum] = mapped_column(Enum(Canonicaltriples_Class_1Enum), primary_key=True, nullable=False)
    class_2: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False, default='')
    date_added: Mapped[str] = mapped_column(String(255), nullable=False)
    date_deprecated: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    in_ohdsi: Mapped[bool] = mapped_column(Boolean, nullable=False)
    internal: Mapped[bool] = mapped_column(Boolean, nullable=False)
    relationship: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False, default='')
    used_in: Mapped[str] = mapped_column(String(255), nullable=False)

    normalisation_groups: list[list[str]] = [
    ]
    class_1_provenance_items: Mapped[list['canonicaltriples_Class_1_provenanceMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    class_2_provenance_items: Mapped[list['canonicaltriples_Class_2_provenanceMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')

class canonicaltriples_Class_1_provenanceMap(EntityBase, Base):
    __tablename__ = 'canonicaltriples_class_1_provenance'

    class_1: Mapped[Canonicaltriples_Class_1Enum] = mapped_column(Enum(Canonicaltriples_Class_1Enum), primary_key=True)
    relationship: Mapped[str] = mapped_column(String(255), primary_key=True)
    class_2: Mapped[str] = mapped_column(String(255), primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(['class_1', 'relationship', 'class_2'], ['canonicaltriples.class_1', 'canonicaltriples.relationship', 'canonicaltriples.class_2']),
    )
    class_1_provenance: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Canonicaltriples'] = sa_relationship(back_populates='class_1_provenance_items')

class canonicaltriples_Class_2_provenanceMap(EntityBase, Base):
    __tablename__ = 'canonicaltriples_class_2_provenance'

    class_1: Mapped[Canonicaltriples_Class_1Enum] = mapped_column(Enum(Canonicaltriples_Class_1Enum), primary_key=True)
    relationship: Mapped[str] = mapped_column(String(255), primary_key=True)
    class_2: Mapped[str] = mapped_column(String(255), primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(['class_1', 'relationship', 'class_2'], ['canonicaltriples.class_1', 'canonicaltriples.relationship', 'canonicaltriples.class_2']),
    )
    class_2_provenance: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Canonicaltriples'] = sa_relationship(back_populates='class_2_provenance_items')

class HemoncClasses(EntityBase, Base):
    __tablename__ = 'hemonc_classes'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    filename = 'hemonc_classes.csv'
    natural_key_columns = ['concept_class_id']
    source_defined_keys: list[str] = []
    identity_keys: list[str] = []
    denormalised_columns: list[str] = ['secondary_home_as_cui', 'secondary_home_as_string']
    derived_columns: list[str] = []

    enum_lookup: dict[str, type] = {
        'domain': HemoncClasses_DomainEnum,
        'omopdomain_id': HemoncClasses_Omopdomain_idEnum,
        'omopstandard_concept': HemoncClasses_Omopstandard_conceptEnum,
        'class_type': HemoncClasses_Class_typeEnum,
    }

    class_type: Mapped[HemoncClasses_Class_typeEnum] = mapped_column(Enum(HemoncClasses_Class_typeEnum), nullable=False)
    concept_class_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    date_added: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    date_deprecated: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[Optional[HemoncClasses_DomainEnum]] = mapped_column(Enum(HemoncClasses_DomainEnum), nullable=True)
    in_ohdsi: Mapped[bool] = mapped_column(Boolean, nullable=False)
    omopdomain_id: Mapped[Optional[HemoncClasses_Omopdomain_idEnum]] = mapped_column(Enum(HemoncClasses_Omopdomain_idEnum), nullable=True)
    omopstandard_concept: Mapped[Optional[HemoncClasses_Omopstandard_conceptEnum]] = mapped_column(Enum(HemoncClasses_Omopstandard_conceptEnum), nullable=True)
    primary_field: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    primary_table: Mapped[str] = mapped_column(String(255), nullable=False)

    normalisation_groups: list[list[str]] = [
    ]
    secondary_home_as_cui_items: Mapped[list['hemonc_classes_Secondary_home_as_cuiMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    secondary_home_as_string_items: Mapped[list['hemonc_classes_Secondary_home_as_stringMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')

class hemonc_classes_Secondary_home_as_cuiMap(EntityBase, Base):
    __tablename__ = 'hemonc_classes_secondary_home_as_cui'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('hemonc_classes.id'), primary_key=True)
    secondary_home_as_cui: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['HemoncClasses'] = sa_relationship(back_populates='secondary_home_as_cui_items')

class hemonc_classes_Secondary_home_as_stringMap(EntityBase, Base):
    __tablename__ = 'hemonc_classes_secondary_home_as_string'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('hemonc_classes.id'), primary_key=True)
    secondary_home_as_string: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)

    parent: Mapped['HemoncClasses'] = sa_relationship(back_populates='secondary_home_as_string_items')

class HemoncRels(EntityBase, Base):
    __tablename__ = 'hemonc_rels'
    filename = 'hemonc_rels.csv'
    natural_key_columns = ['relationship_id']
    source_defined_keys: list[str] = ['relationship_id']
    identity_keys: list[str] = []
    denormalised_columns: list[str] = []
    derived_columns: list[str] = []

    enum_lookup: dict[str, type] = {
        'in_ohdsi': HemoncRels_In_ohdsiEnum,
    }

    date_added: Mapped[str] = mapped_column(String(255), nullable=False)
    date_deprecated: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    heritable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    in_ohdsi: Mapped[HemoncRels_In_ohdsiEnum] = mapped_column(Enum(HemoncRels_In_ohdsiEnum), nullable=False)
    relationship_id: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False, default='')

    normalisation_groups: list[list[str]] = [
    ]

class Affiliations(EntityBase, Base):
    __tablename__ = 'affiliations'
    filename = 'affiliations.csv'
    natural_key_columns = ['pmid', 'sequence', 'aff_no']
    source_defined_keys: list[str] = []
    identity_keys: list[str] = []
    denormalised_columns: list[str] = ['affiliation_europmc', 'affiliation_journal']
    derived_columns: list[str] = []

    enum_lookup: dict[str, type] = {}

    aff_no: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False, default=-1)
    affiliation_hemonc: Mapped[str] = mapped_column(Text, nullable=False)
    date_added: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    full_name_europmc: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name_hemonc: Mapped[str] = mapped_column(String(255), nullable=False)
    person_cui: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    pmid: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False, default=-1)
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False, default=-1)
    temp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    valid_city: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    valid_country: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    valid_region: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    valid_site: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    normalisation_groups: list[list[str]] = [
    ]
    affiliation_europmc_items: Mapped[list['affiliations_Affiliation_europmcMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    affiliation_journal_items: Mapped[list['affiliations_Affiliation_journalMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    pmid_exclusions_obj: Mapped[Optional['Exclusions']] = sa_relationship(
        'Exclusions',
        primaryjoin="Affiliations.pmid == foreign(Exclusions.pmid)",
        lazy='selectin',
        viewonly=True,
    )

    pmid_inclusions_obj: Mapped[Optional['Inclusions']] = sa_relationship(
        'Inclusions',
        primaryjoin="Affiliations.pmid == foreign(Inclusions.pmid)",
        lazy='selectin',
        viewonly=True,
    )


class affiliations_Affiliation_europmcMap(EntityBase, Base):
    __tablename__ = 'affiliations_affiliation_europmc'

    pmid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    aff_no: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(['pmid', 'sequence', 'aff_no'], ['affiliations.pmid', 'affiliations.sequence', 'affiliations.aff_no']),
    )
    affiliation_europmc: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)

    parent: Mapped['Affiliations'] = sa_relationship(back_populates='affiliation_europmc_items')

class affiliations_Affiliation_journalMap(EntityBase, Base):
    __tablename__ = 'affiliations_affiliation_journal'

    pmid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    aff_no: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(['pmid', 'sequence', 'aff_no'], ['affiliations.pmid', 'affiliations.sequence', 'affiliations.aff_no']),
    )
    affiliation_journal: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)

    parent: Mapped['Affiliations'] = sa_relationship(back_populates='affiliation_journal_items')

class Contexts(EntityBase, Base):
    __tablename__ = 'contexts'
    filename = 'contexts.csv'
    natural_key_columns = ['context_raw']
    source_defined_keys: list[str] = ['context_raw', 'context_pretty']
    identity_keys: list[str] = []
    denormalised_columns: list[str] = ['context', 'context_pretty', 'phase', 'phenotype', 'setting', 'stage_or_status']
    derived_columns: list[str] = []

    enum_lookup: dict[str, type] = {
        'intent': Contexts_IntentEnum,
        'risk_stratification': Contexts_Risk_stratificationEnum,
    }

    context_raw: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False, default='')
    date_added: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    date_last_used: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    intent: Mapped[Contexts_IntentEnum] = mapped_column(Enum(Contexts_IntentEnum), nullable=False)
    prior_therapy: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    prior_therapy_negation: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    risk_stratification: Mapped[Optional[Contexts_Risk_stratificationEnum]] = mapped_column(Enum(Contexts_Risk_stratificationEnum), nullable=True)
    therapy_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    normalisation_groups: list[list[str]] = [
    ]
    context_items: Mapped[list['contexts_ContextMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    context_pretty_items: Mapped[list['contexts_Context_prettyMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    phase_items: Mapped[list['contexts_PhaseMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    phenotype_items: Mapped[list['contexts_PhenotypeMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    setting_items: Mapped[list['contexts_SettingMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    stage_or_status_items: Mapped[list['contexts_Stage_or_statusMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')

class contexts_ContextMap(EntityBase, Base):
    __tablename__ = 'contexts_context'

    context_raw: Mapped[str] = mapped_column(String(255), primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(['context_raw'], ['contexts.context_raw']),
    )
    context: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Contexts'] = sa_relationship(back_populates='context_items')

class contexts_Context_prettyMap(EntityBase, Base):
    __tablename__ = 'contexts_context_pretty'

    context_raw: Mapped[str] = mapped_column(String(255), primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(['context_raw'], ['contexts.context_raw']),
    )
    context_pretty: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Contexts'] = sa_relationship(back_populates='context_pretty_items')

class contexts_PhaseMap(EntityBase, Base):
    __tablename__ = 'contexts_phase'

    context_raw: Mapped[str] = mapped_column(String(255), primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(['context_raw'], ['contexts.context_raw']),
    )
    phase: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Contexts'] = sa_relationship(back_populates='phase_items')

class contexts_PhenotypeMap(EntityBase, Base):
    __tablename__ = 'contexts_phenotype'

    context_raw: Mapped[str] = mapped_column(String(255), primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(['context_raw'], ['contexts.context_raw']),
    )
    phenotype: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Contexts'] = sa_relationship(back_populates='phenotype_items')

class contexts_SettingMap(EntityBase, Base):
    __tablename__ = 'contexts_setting'

    context_raw: Mapped[str] = mapped_column(String(255), primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(['context_raw'], ['contexts.context_raw']),
    )
    setting: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Contexts'] = sa_relationship(back_populates='setting_items')

class contexts_Stage_or_statusMap(EntityBase, Base):
    __tablename__ = 'contexts_stage_or_status'

    context_raw: Mapped[str] = mapped_column(String(255), primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(['context_raw'], ['contexts.context_raw']),
    )
    stage_or_status: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Contexts'] = sa_relationship(back_populates='stage_or_status_items')

class Exclusions(EntityBase, Base):
    __tablename__ = 'exclusions'
    filename = 'exclusions.csv'
    natural_key_columns = ['pmid']
    source_defined_keys: list[str] = ['pmid']
    identity_keys: list[str] = []
    denormalised_columns: list[str] = ['title']
    derived_columns: list[str] = []

    enum_lookup: dict[str, type] = {
        'rev1': Exclusions_Rev1Enum,
        'rev2': Exclusions_Rev2Enum,
    }

    date_added: Mapped[str] = mapped_column(String(255), nullable=False)
    pmid: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False, default='')
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    rev1: Mapped[Exclusions_Rev1Enum] = mapped_column(Enum(Exclusions_Rev1Enum), nullable=False)
    rev2: Mapped[Optional[Exclusions_Rev2Enum]] = mapped_column(Enum(Exclusions_Rev2Enum), nullable=True)
    rev3: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    year: Mapped[str] = mapped_column(String(255), nullable=False)

    normalisation_groups: list[list[str]] = [
    ]
    title_items: Mapped[list['exclusions_TitleMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    pmid_obj: Mapped[Optional['Inclusions']] = sa_relationship(
        'Inclusions',
        primaryjoin="Exclusions.pmid == foreign(Inclusions.pmid)",
        lazy='selectin',
        viewonly=True,
    )


class exclusions_TitleMap(EntityBase, Base):
    __tablename__ = 'exclusions_title'

    pmid: Mapped[str] = mapped_column(String(255), primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(['pmid'], ['exclusions.pmid']),
    )
    title: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)

    parent: Mapped['Exclusions'] = sa_relationship(back_populates='title_items')

class Inclusions(EntityBase, Base):
    __tablename__ = 'inclusions'
    filename = 'inclusions.csv'
    natural_key_columns = ['pmid']
    source_defined_keys: list[str] = ['pmid']
    identity_keys: list[str] = []
    denormalised_columns: list[str] = ['reason_note', 'ref_type']
    derived_columns: list[str] = []

    enum_lookup: dict[str, type] = {
        'reason': Inclusions_ReasonEnum,
    }

    date_added: Mapped[str] = mapped_column(String(255), nullable=False)
    pmid: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False, default=-1)
    reason: Mapped[Inclusions_ReasonEnum] = mapped_column(Enum(Inclusions_ReasonEnum), nullable=False)

    normalisation_groups: list[list[str]] = [
    ]
    reason_note_items: Mapped[list['inclusions_Reason_noteMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    ref_type_items: Mapped[list['inclusions_Ref_typeMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')
    pmid_obj: Mapped[Optional['Exclusions']] = sa_relationship(
        'Exclusions',
        primaryjoin="Inclusions.pmid == foreign(Exclusions.pmid)",
        lazy='selectin',
        viewonly=True,
    )


class inclusions_Reason_noteMap(EntityBase, Base):
    __tablename__ = 'inclusions_reason_note'

    pmid: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(['pmid'], ['inclusions.pmid']),
    )
    reason_note: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)

    parent: Mapped['Inclusions'] = sa_relationship(back_populates='reason_note_items')

class inclusions_Ref_typeMap(EntityBase, Base):
    __tablename__ = 'inclusions_ref_type'

    pmid: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(['pmid'], ['inclusions.pmid']),
    )
    ref_type: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['Inclusions'] = sa_relationship(back_populates='ref_type_items')

class SigBranchTypes(EntityBase, Base):
    __tablename__ = 'sig_branch_types'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    filename = 'sig_branch_types.csv'
    natural_key_columns = ['value']
    source_defined_keys: list[str] = ['value']
    identity_keys: list[str] = []
    denormalised_columns: list[str] = ['description']
    derived_columns: list[str] = []

    enum_lookup: dict[str, type] = {}

    value: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    normalisation_groups: list[list[str]] = [
    ]
    description_items: Mapped[list['sig_branch_types_DescriptionMap']] = sa_relationship(back_populates='parent', lazy='selectin', cascade='all, delete-orphan')

class sig_branch_types_DescriptionMap(EntityBase, Base):
    __tablename__ = 'sig_branch_types_description'

    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('sig_branch_types.id'), primary_key=True)
    description: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)

    parent: Mapped['SigBranchTypes'] = sa_relationship(back_populates='description_items')

class Units(EntityBase, Base):
    __tablename__ = 'units'
    filename = 'units.csv'
    natural_key_columns = ['unit']
    source_defined_keys: list[str] = ['unit', 'concept_code']
    identity_keys: list[str] = []
    denormalised_columns: list[str] = []
    derived_columns: list[str] = []

    enum_lookup: dict[str, type] = {}

    concept_code: Mapped[int] = mapped_column(BigInteger, nullable=False)
    date_added: Mapped[str] = mapped_column(String(255), nullable=False)
    fixed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    parameterbased: Mapped[bool] = mapped_column(Boolean, nullable=False)
    timebased: Mapped[bool] = mapped_column(Boolean, nullable=False)
    unit: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False, default='')
    unit_type: Mapped[str] = mapped_column(String(255), nullable=False)

    normalisation_groups: list[list[str]] = [
    ]

class Variantblob(EntityBase, Base):
    __tablename__ = 'variantblob'
    filename = 'variant_blob.csv'
    natural_key_columns = ['version', 'chunk']
    source_defined_keys: list[str] = []
    identity_keys: list[str] = []
    denormalised_columns: list[str] = []
    derived_columns: list[str] = []

    enum_lookup: dict[str, type] = {
        'block': Variantblob_BlockEnum,
        'chunk_type': Variantblob_Chunk_typeEnum,
    }

    block: Mapped[Variantblob_BlockEnum] = mapped_column(Enum(Variantblob_BlockEnum), nullable=False)
    chunk: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False, default='')
    chunk_type: Mapped[Variantblob_Chunk_typeEnum] = mapped_column(Enum(Variantblob_Chunk_typeEnum), nullable=False)
    date_created: Mapped[str] = mapped_column(String(255), nullable=False)
    date_retired: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    order: Mapped[int] = mapped_column(BigInteger, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False, default=-1)

    normalisation_groups: list[list[str]] = [
    ]

__all__ = [
    'Affiliations',
    'Authors',
    'Canonicaltriples',
    'Conditions',
    'Contexts',
    'Drugs',
    'Exclusions',
    'HemoncClasses',
    'HemoncRels',
    'Inclusions',
    'Indications',
    'Persons',
    'Refs',
    'Regimens',
    'SigBranchTypes',
    'Sigs',
    'Studies',
    'StudyResults',
    'Units',
    'VariantEligibility',
    'Variantblob',
    'Variants',
    'affiliations_Affiliation_europmcMap',
    'affiliations_Affiliation_journalMap',
    'canonicaltriples_Class_1_provenanceMap',
    'canonicaltriples_Class_2_provenanceMap',
    'conditions_Map_icd10cmMap',
    'conditions_Map_icd9cmMap',
    'conditions_Map_icdo3Map',
    'conditions_Map_icdo3_morphMap',
    'conditions_Map_oncotreeMap',
    'conditions_Map_seerMap',
    'conditions_Map_type_icdo3_morphMap',
    'contexts_ContextMap',
    'contexts_Context_prettyMap',
    'contexts_PhaseMap',
    'contexts_PhenotypeMap',
    'contexts_SettingMap',
    'contexts_Stage_or_statusMap',
    'drugs_AtcMap',
    'drugs_Canmed_major_classMap',
    'drugs_Canmed_major_class_cuiMap',
    'drugs_Canmed_minor_classMap',
    'drugs_Canmed_minor_class_cuiMap',
    'exclusions_TitleMap',
    'hemonc_classes_Secondary_home_as_cuiMap',
    'hemonc_classes_Secondary_home_as_stringMap',
    'inclusions_Reason_noteMap',
    'inclusions_Ref_typeMap',
    'indications_Biomarker2Map',
    'indications_Biomarker2_findingMap',
    'indications_Biomarker2_typeMap',
    'indications_Biomarker3Map',
    'indications_Biomarker3_findingMap',
    'indications_Biomarker3_typeMap',
    'indications_Biomarker4Map',
    'indications_Biomarker4_findingMap',
    'indications_Biomarker4_typeMap',
    'indications_Biomarker_typeMap',
    'indications_ContextMap',
    'indications_DemographicsMap',
    'indications_Prior_therapy_negationMap',
    'indications_Prior_therapy_settingMap',
    'indications_RegimenMap',
    'indications_Regimen_cuiMap',
    'indications_Response_contingencyMap',
    'indications_Risk_stratificationMap',
    'persons_Condition_typesMap',
    'persons_ConditionsMap',
    'persons_CountryMap',
    'persons_LocationMap',
    'persons_OrcidMap',
    'persons_SiteMap',
    'persons_Study_groupsMap',
    'persons_Study_sponsorsMap',
    'refs_BiblioMap',
    'refs_DoiMap',
    'refs_ReferenceMap',
    'refs_StudyMap',
    'refs_TitleMap',
    'sig_branch_types_DescriptionMap',
    'sigs_Cyclesigs_noteMap',
    'sigs_InparensMap',
    'sigs_SeqrelMap',
    'sigs_SeqrelwhatMap',
    'sigs_SeqrelwhenMap',
    'sigs_SeqrelwhenunitMap',
    'sigs_StudyMap',
    'sigs_TimingMap',
    'studies_IntentMap',
    'studies_SponsorMap',
    'studies_Study_groupMap',
    'study_results_Comparator_codeMap',
    'variant_eligibility_StudyMap',
    'variants_BlobMap',
    'variants_StudyMap',
    'variants_TracerMap',
]
