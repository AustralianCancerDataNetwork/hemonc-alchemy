"""`dosing_instructions`, against real in-memory rows and relationship traversal."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
import sqlalchemy.orm as so

from hemonc_alchemy.model.base import Base
from hemonc_alchemy.model.entities import (
    Sigs,
    Variants,
    sigs_Cyclesigs_noteMap,
    sigs_StudyMap,
)
from hemonc_alchemy.model.enums import (
    Sigs_Cycle_length_unitEnum,
    Sigs_DosecapunitEnum,
    Sigs_DurationunitEnum,
    Sigs_FrequencyEnum,
    Sigs_PhaseEnum,
    Sigs_RouteEnum,
    Sigs_SequenceEnum,
    Sigs_SubcomponentEnum,
    Sigs_TargetleveltypeEnum,
    Sigs_TargetlevelunitEnum,
)
from hemonc_alchemy.toolkit.analytics.treatment.dosing import (
    MEMBERSHIP_PROVENANCE,
    dosing_instructions,
)

pytestmark = pytest.mark.skipif(
    len(Base.metadata.tables) == 0,
    reason="model/entities.py has no generated classes yet -- run `hemonc-alchemy regen` first",
)

_D = datetime(2020, 1, 1, tzinfo=UTC)


@pytest.fixture
def session():
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with so.Session(engine) as s:
        yield s


def _variant(session, variant_cui: int = 1, version: int = 1) -> Variants:
    variant = Variants(
        id=variant_cui, variant_cui=variant_cui, variant="v", regimen_cui=1,
        regimen="R", version=version, cyclesigs=0, components=0, portions=0,
        routes=0, sigs=0, blob_version=0, fullyspecified=True,
        allsigshavecyclesigs=True, allsigshavedose=True, allsigshavedoseunit=True,
        allsigshaveduration=True, allsigshavedurationunit=True, allsigshavefrequency=True,
        allsigshaveroute=True, allsigshaveschedule=True, allsigshavesequence=True,
        date_added=_D,
    )
    session.add(variant)
    session.flush()
    return variant


class TestDosingInstructions:
    def test_one_row_per_sig_uncollapsed(self, session):
        variant = _variant(session, variant_cui=1)
        for sig_id in (1, 2):
            session.add(Sigs(
                id=sig_id, variant_cui=1, component_cui=10, component="cisplatin",
                component_role="primary systemic", portion="1", regimen="R",
                regimen_cui=1, step_number="1", divided=False, phase_step=1,
                variant="v", route=Sigs_RouteEnum.INTRAVENOUS, alldays="1",
                date_added=_D,
            ))
        session.flush()
        session.expire_all()

        instructions = dosing_instructions(variant)
        assert [instr.sig_id for instr in instructions] == [1, 2]

    def test_every_field_preserved_as_a_raw_source_string(self, session):
        variant = _variant(session, variant_cui=2)
        sig = Sigs(
            id=10, variant_cui=2, component_cui=100, component="cytarabine",
            subcomponent_cui=200, subcomponent=Sigs_SubcomponentEnum.DECITABINE,
            component_role="primary systemic", phase=Sigs_PhaseEnum.INDUCTION,
            phase_step=1, portion="1", regimen="R", regimen_cui=1,
            step_number="1 of 2", divided=False, route=Sigs_RouteEnum.INTRAVENOUS,
            doseminnum="100", dosemaxnum="200", doseunit="mg/m^2",
            dosecapnum=400.0, dosecapunit=Sigs_DosecapunitEnum.MG,
            targetlevel="2-4", targetleveltype=Sigs_TargetleveltypeEnum.TROUGH,
            targetlevelunit=Sigs_TargetlevelunitEnum.NG_ML,
            frequency=Sigs_FrequencyEnum.ONCE_PER_DAY,
            durationminnum="24", durationmaxnum="24", durationunit=Sigs_DurationunitEnum.HOUR,
            alldays="1,8,15", timing_sequence="1,2,3",
            cycle_length_lb="21", cycle_length_ub="21",
            cycle_length_unit=Sigs_Cycle_length_unitEnum.DAY,
            sequence=Sigs_SequenceEnum.FIRST,
            variant="v", date_added=_D,
            cyclesigs_note_items=[sigs_Cyclesigs_noteMap(cyclesigs_note="see protocol note")],
            study_items=[sigs_StudyMap(study="study-a"), sigs_StudyMap(study="study-b")],
        )
        session.add(sig)
        session.flush()
        session.expire_all()

        instruction = dosing_instructions(variant)[0]
        assert instruction.sig_id == 10
        assert instruction.variant_cui == 2
        assert instruction.component_cui == 100
        assert instruction.component == "cytarabine"
        assert instruction.subcomponent_cui == 200
        assert instruction.subcomponent == Sigs_SubcomponentEnum.DECITABINE
        assert instruction.phase == Sigs_PhaseEnum.INDUCTION
        assert instruction.phase_step == 1
        assert instruction.portion == "1"
        assert instruction.step_number == "1 of 2"
        assert instruction.dose_min == "100"
        assert instruction.dose_max == "200"
        assert instruction.dose_unit == "mg/m^2"
        assert instruction.dose_cap == 400.0
        assert instruction.dose_cap_unit == Sigs_DosecapunitEnum.MG
        assert instruction.target_level == "2-4"
        assert instruction.target_level_type == Sigs_TargetleveltypeEnum.TROUGH
        assert instruction.target_level_unit == Sigs_TargetlevelunitEnum.NG_ML
        assert instruction.route == Sigs_RouteEnum.INTRAVENOUS
        assert instruction.frequency == Sigs_FrequencyEnum.ONCE_PER_DAY
        assert instruction.duration_min == "24"
        assert instruction.duration_max == "24"
        assert instruction.duration_unit == Sigs_DurationunitEnum.HOUR
        assert instruction.raw_all_days == "1,8,15"
        assert instruction.raw_timing_sequence == "1,2,3"
        assert instruction.cycle_length_lb == "21"
        assert instruction.cycle_length_unit == Sigs_Cycle_length_unitEnum.DAY
        assert instruction.sequence == Sigs_SequenceEnum.FIRST
        assert instruction.notes == ("see protocol note",)
        assert set(instruction.evidence_references) == {"study-a", "study-b"}
        assert instruction.membership_provenance == MEMBERSHIP_PROVENANCE
        assert instruction.membership_provenance == "shared_by_variant_cui"

    def test_missing_fields_are_null_not_guessed(self, session):
        variant = _variant(session, variant_cui=3)
        sig = Sigs(
            id=20, variant_cui=3, component_cui=1, component="drug",
            component_role="primary systemic", portion="1", regimen="R",
            regimen_cui=1, step_number="1", divided=False, phase_step=1,
            variant="v", route=None, alldays=None, date_added=_D,
        )
        session.add(sig)
        session.flush()
        session.expire_all()

        instruction = dosing_instructions(variant)[0]
        assert instruction.route is None
        assert instruction.raw_all_days is None
        assert instruction.dose_min is None
        assert instruction.dose_cap is None
        assert instruction.notes == ()
        assert instruction.evidence_references == ()

    def test_uncertainty_tokens_in_dose_fields_are_preserved_verbatim(self, session):
        # P0-A20: source dose fields carry "NS", scientific notation and
        # comma-grouped numbers; none of that is this module's job to normalise.
        variant = _variant(session, variant_cui=4)
        sig = Sigs(
            id=30, variant_cui=4, component_cui=1, component="drug",
            component_role="primary systemic", portion="1", regimen="R",
            regimen_cui=1, step_number="1", divided=False, phase_step=1,
            variant="v", doseminnum="NS", dosemaxnum="1,000,000", date_added=_D,
        )
        session.add(sig)
        session.flush()
        session.expire_all()

        instruction = dosing_instructions(variant)[0]
        assert instruction.dose_min == "NS"
        assert instruction.dose_max == "1,000,000"

    def test_does_not_depend_on_the_day_parser(self, session):
        # A malformed `alldays` must not stop a lossless dosing read -- this
        # module never calls `resolve_all_days`.
        variant = _variant(session, variant_cui=5)
        sig = Sigs(
            id=40, variant_cui=5, component_cui=1, component="drug",
            component_role="primary systemic", portion="1", regimen="R",
            regimen_cui=1, step_number="1", divided=False, phase_step=1,
            variant="v", alldays="(1),(2),(3),(4),(5),(6),(7)", date_added=_D,
        )
        session.add(sig)
        session.flush()
        session.expire_all()

        instruction = dosing_instructions(variant)[0]
        assert instruction.raw_all_days == "(1),(2),(3),(4),(5),(6),(7)"
