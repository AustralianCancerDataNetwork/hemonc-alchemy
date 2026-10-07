"""Condition target generation and runtime helpers against hand-built mappings and a fake vocabulary, plus SQLite."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from hemonc_alchemy.compiler.condition_target_generation import Candidate, generate
from hemonc_alchemy.integrations.omop import load_omop_binding
from hemonc_alchemy.integrations.omop.standardise import (
    StandardisedCode,
    standardise_codes,
)
from hemonc_alchemy.toolkit.core.condition_targets import (
    ConditionMapping,
    accepted_codes,
    apply_patches,
    broader_codes,
    is_conjunction,
)

# Concept ids: 1 malignant neoplasm of breast > 2 carcinoma of breast; 10 lymphoma > 11 B-cell lymphoma.
STANDARD = {
    "MN_BREAST": StandardisedCode(1, True, frozenset({1}), False),
    "CA_BREAST": StandardisedCode(2, True, frozenset({2}), False),
    "HER2_CA_BREAST": StandardisedCode(3, False, frozenset({2}), True),
    "LYMPHOMA": StandardisedCode(10, True, frozenset({10}), False),
    "B_LYMPHOMA": StandardisedCode(11, True, frozenset({11}), False),
    "FATIGUE": StandardisedCode(20, True, frozenset({20}), False),
    "MORPHOLOGY": StandardisedCode(30, True, frozenset(), False),
    "DISEASE": StandardisedCode(40, True, frozenset({40}), False),
    "CANCER_FATIGUE": StandardisedCode(50, False, frozenset({1, 20}), False),
}
PAIRS = {(1, 2), (10, 11)}


class FakeVocabulary:
    def standardise(self, codes: Iterable[str]) -> Mapping[str, StandardisedCode]:
        return {code: STANDARD[code] for code in codes if code in STANDARD}

    def subsumes(self, concept_ids: Iterable[int]) -> set[tuple[int, int]]:
        ids = set(concept_ids)
        return {(a, b) for a, b in PAIRS if a in ids and b in ids}

    def labels(self, concept_ids: Iterable[int]) -> Mapping[int, tuple[str, str]]:
        return {cid: (str(cid), f"concept {cid}") for cid in concept_ids}

    def hemonc_concept_ids(self, condition_cuis: Iterable[int]) -> Mapping[int, int]:
        return {cui: 1000 + cui for cui in condition_cuis}


def _conditions(*rows: tuple) -> dict[int, ConditionMapping]:
    """Rows of (condition, cui, map_SNOMED, map_type_SNOMED, map_NCIT, map_type_NCIT)."""
    return {
        int(cui): ConditionMapping(int(cui), name, (snomed,) if snomed else (), snomed_type, ncit, ncit_type)
        for name, cui, snomed, snomed_type, ncit, ncit_type in rows
    }


def _by(result, cui: int) -> dict[str, Candidate]:
    return {c.snomed_code: c for c in result.targets if c.condition_cui == cui}


def _run(conditions, parents=None, crosswalk=None, overrides=(), proposals=()):
    return generate(conditions, parents or {}, crosswalk or {}, FakeVocabulary(), overrides, proposals)


def test_hemonc_exact_target_is_accepted_and_up_is_not():
    result = _run(_conditions(
        ("Condition", "1", "DISEASE", "exact", "N1", "exact"),
        ("Malignant breast neoplasm", "2", "MN_BREAST", "exact", "N2", "exact"),
        ("Lymphoma", "3", "LYMPHOMA", "up", "N3", "exact"),
    ), parents={2: (1,), 3: (1,)})

    assert _by(result, 1)["DISEASE"].status == "grouping"
    assert _by(result, 2)["MN_BREAST"].status == "exact"
    assert _by(result, 3)["LYMPHOMA"].status == "up"


def test_crosswalk_fills_a_gap_but_only_supports_an_accepted_hemonc_target():
    result = _run(
        _conditions(
            ("Condition", "1", "DISEASE", "exact", "N1", "exact"),
            ("Lymphoma", "2", "LYMPHOMA", "exact", "N2", "exact"),
            ("B-cell lymphoma", "3", None, None, "N3", "exact"),
        ),
        parents={2: (1,), 3: (2,)},
        crosswalk={"N2": ("B_LYMPHOMA",), "N3": ("B_LYMPHOMA",)},
    )

    assert _by(result, 2)["B_LYMPHOMA"].status == "supporting"
    assert _by(result, 3)["B_LYMPHOMA"].status == "exact"


def test_child_target_no_narrower_than_parent_is_demoted_and_crosswalk_fills_it():
    result = _run(
        _conditions(
            ("Condition", "1", "DISEASE", "exact", "N1", "exact"),
            ("Malignant breast neoplasm", "2", "MN_BREAST", "exact", "N2", "exact"),
            ("Breast cancer", "3", "MN_BREAST", "exact", "N3", "exact"),
        ),
        parents={2: (1,), 3: (2,)},
        crosswalk={"N3": ("CA_BREAST",)},
    )

    breast = _by(result, 3)
    assert breast["MN_BREAST"].status == "demoted"
    assert breast["MN_BREAST"].note == "not_narrower_than:Malignant breast neoplasm"
    assert breast["CA_BREAST"].status == "exact"


def test_post_coordinated_biomarker_code_is_exempt_from_the_narrower_check():
    result = _run(_conditions(
        ("Condition", "1", "DISEASE", "exact", "N1", "exact"),
        ("Breast cancer", "2", "CA_BREAST", "exact", "N2", "exact"),
        ("HER2-positive Breast cancer", "3", "HER2_CA_BREAST", "exact", "N3", "exact"),
    ), parents={2: (1,), 3: (2,)})

    her2 = _by(result, 3)["HER2_CA_BREAST"]
    assert (her2.status, her2.note) == ("exact", "conjunction")


def test_code_with_several_condition_parts_is_a_conjunction_and_never_flagged_or_constraining():
    result = _run(
        _conditions(
            ("Condition", "1", "DISEASE", "exact", "N1", "exact"),
            ("Cancer-related fatigue", "2", None, None, "N2", "exact"),
            ("Breast cancer", "3", "CA_BREAST", "exact", "N3", "exact"),
            ("HER2-positive Breast cancer", "4", "HER2_CA_BREAST", "exact", "N4", "exact"),
            ("HER2-positive Breast cancer, metastatic", "5", "CA_BREAST", "exact", "N5", "exact"),
        ),
        parents={2: (1,), 3: (1,), 4: (1,), 5: (4,)},
        crosswalk={"N2": ("CANCER_FATIGUE",)},
    )

    fatigue = _by(result, 2)["CANCER_FATIGUE"]
    assert (fatigue.status, fatigue.note) == ("exact", "conjunction")
    assert not any(flag["condition_cui"] in (2, 4) for flag in result.coverage_flags)
    assert _by(result, 5)["CA_BREAST"].status == "exact"


def test_runtime_reads_patched_exact_maps_adjusted_by_overrides():
    mappings = _conditions(
        ("Breast cancer", "1", "MN_BREAST", "exact", "N1", "exact"),
        ("Lymphoma", "2", "LYMPHOMA", "up", "N2", "exact"),
        ("CUP", "3", "DISEASE", "up", "N3", "exact"),
    )
    patched = apply_patches(mappings.values(), {
        1: {"map_SNOMED": "CA_BREAST|HER2_CA_BREAST", "map_type_SNOMED": "exact"},
        2: {"map_SNOMED": "LYMPHOMA", "map_type_SNOMED": "exact"},
    })
    overrides = [{"condition_cui": "1", "snomed_code": "HER2_CA_BREAST", "action": "remove"},
                 {"condition_cui": "3", "snomed_code": "FATIGUE", "action": "add"}]

    assert accepted_codes(patched, overrides) == {1: ("CA_BREAST",), 2: ("LYMPHOMA",), 3: ("FATIGUE",)}
    assert broader_codes(patched) == {3: ("DISEASE",)}
    assert is_conjunction(STANDARD["HER2_CA_BREAST"]) and is_conjunction(STANDARD["CANCER_FATIGUE"])
    assert not is_conjunction(STANDARD["CA_BREAST"])


def test_conflicting_or_composite_crosswalk_goes_to_review():
    result = _run(
        _conditions(
            ("Condition", "1", "DISEASE", "exact", "N1", "exact"),
            ("Lymphoma", "2", "LYMPHOMA", "exact", "N2", "exact"),
            ("Cancer-related fatigue", "3", None, None, "N3", "exact"),
        ),
        parents={2: (1,), 3: (1,)},
        crosswalk={"N2": ("FATIGUE",), "N3": ("MN_BREAST", "FATIGUE")},
    )

    assert _by(result, 2)["FATIGUE"].note == "conflicts_with_hemonc_snomed"
    assert {c.note for c in _by(result, 3).values()} == {"composite_crosswalk"}
    assert {(r["condition_cui"], r["target_snomed_code"], r["action"]) for r in result.suggestions} == {
        (2, "FATIGUE", "add"), (3, "MN_BREAST", "add"), (3, "FATIGUE", "add"),
    }


def test_unknown_codes_and_non_condition_concepts_are_not_accepted():
    result = _run(_conditions(
        ("Condition", "1", "DISEASE", "exact", "N1", "exact"),
        ("Sarcoma", "2", "MORPHOLOGY", "exact", "N2", "exact"),
        ("Lymphoma", "3", "NOT_IN_VOCAB", "exact", "N3", "exact"),
    ), parents={2: (1,), 3: (1,)})

    assert _by(result, 2)["MORPHOLOGY"].status == "not_condition"
    assert _by(result, 3)["NOT_IN_VOCAB"].status == "unresolved"


def test_overrides_add_and_remove():
    result = _run(
        _conditions(
            ("Condition", "1", "DISEASE", "exact", "N1", "exact"),
            ("Lymphoma", "2", "LYMPHOMA", "exact", "N2", "exact"),
        ),
        parents={2: (1,)},
        overrides=[
            {"condition_cui": "2", "snomed_code": "LYMPHOMA", "action": "remove", "note": "too broad"},
            {"condition_cui": "2", "snomed_code": "B_LYMPHOMA", "action": "add", "note": "reviewed"},
        ],
    )

    lymphoma = _by(result, 2)
    assert lymphoma["LYMPHOMA"].status == "removed"
    assert lymphoma["B_LYMPHOMA"].status == "override"


def test_patches_hold_gap_fills_and_demotions_in_table_shape():
    result = _run(
        _conditions(
            ("Condition", "1", "DISEASE", "exact", "N1", "exact"),
            ("Malignant breast neoplasm", "2", "MN_BREAST", "exact", "N2", "exact"),
            ("Breast cancer", "3", "MN_BREAST", "exact", "N3", "exact"),
            ("Breast cancer NOS", "4", "MN_BREAST", "exact", "N4", "exact"),
        ),
        parents={2: (1,), 3: (2,), 4: (2,)},
        crosswalk={"N3": ("CA_BREAST",)},
    )

    patches = {row["condition_cui"]: row for row in result.patches}
    assert set(patches) == {3, 4}
    assert (patches[3]["map_SNOMED"], patches[3]["map_type_SNOMED"], patches[3]["original_map_SNOMED"]) == ("CA_BREAST", "exact", "MN_BREAST")
    assert "crosswalk gap-fill" in patches[3]["reason"] and "demoted" in patches[3]["reason"]
    assert (patches[4]["map_SNOMED"], patches[4]["map_type_SNOMED"]) == ("MN_BREAST", "up")


def _sqlite_vocabulary():
    engine = sa.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    metadata = sa.MetaData()
    concept = sa.Table(
        "concept", metadata,
        sa.Column("concept_id", sa.Integer, primary_key=True),
        sa.Column("concept_name", sa.String), sa.Column("domain_id", sa.String),
        sa.Column("vocabulary_id", sa.String), sa.Column("concept_class_id", sa.String),
        sa.Column("standard_concept", sa.String), sa.Column("concept_code", sa.String),
        sa.Column("valid_start_date", sa.Date), sa.Column("valid_end_date", sa.Date),
        sa.Column("invalid_reason", sa.String),
    )
    relationship = sa.Table(
        "concept_relationship", metadata,
        sa.Column("concept_id_1", sa.Integer), sa.Column("concept_id_2", sa.Integer),
        sa.Column("relationship_id", sa.String), sa.Column("valid_start_date", sa.Date),
        sa.Column("valid_end_date", sa.Date), sa.Column("invalid_reason", sa.String),
    )
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(concept.insert(), [
            {"concept_id": 1, "concept_name": "Carcinoma of breast", "domain_id": "Condition", "vocabulary_id": "SNOMED", "standard_concept": "S", "concept_code": "254838004"},
            {"concept_id": 2, "concept_name": "HER2-positive carcinoma of breast", "domain_id": "Condition", "vocabulary_id": "SNOMED", "standard_concept": None, "concept_code": "427685000"},
            {"concept_id": 3, "concept_name": "Positive", "domain_id": "Meas Value", "vocabulary_id": "SNOMED", "standard_concept": "S", "concept_code": "10828004"},
            {"concept_id": 4, "concept_name": "Glioblastoma", "domain_id": "Observation", "vocabulary_id": "SNOMED", "standard_concept": "S", "concept_code": "63634009"},
        ])
        connection.execute(relationship.insert(), [
            {"concept_id_1": 1, "concept_id_2": 1, "relationship_id": "Maps to"},
            {"concept_id_1": 4, "concept_id_2": 4, "relationship_id": "Maps to"},
            {"concept_id_1": 2, "concept_id_2": 1, "relationship_id": "Maps to"},
            {"concept_id_1": 2, "concept_id_2": 3, "relationship_id": "Maps to value"},
        ])
    return engine, sa.orm.Session(engine)


def test_standardise_codes_keeps_condition_legs_only():
    if load_omop_binding() is None:
        pytest.skip("the optional omop extra is not installed")
    engine, session = _sqlite_vocabulary()
    try:
        result = standardise_codes(session, ["254838004", "427685000", "63634009", "999"])
        assert result["254838004"] == StandardisedCode(1, True, frozenset({1}), False)
        assert result["427685000"] == StandardisedCode(2, False, frozenset({1}), True)
        assert result["63634009"].condition_leg == frozenset()
        assert "999" not in result
    finally:
        session.close()
        engine.dispose()


def test_suggestions_hold_only_human_decisions_with_identifiers():
    result = _run(
        _conditions(
            ("Condition", "1", "DISEASE", "exact", "N1", "exact"),
            ("Malignant breast neoplasm", "2", "MN_BREAST", "exact", "N2", "exact"),
            ("Breast cancer", "3", "MN_BREAST", "exact", "C4872", "exact"),
            ("Lymphoma", "4", None, None, "N4", "exact"),
            ("B-cell lymphoma", "5", "B_LYMPHOMA", "exact", "N5", "exact"),
        ),
        parents={2: (1,), 3: (2,), 4: (1,), 5: (4,)},
        crosswalk={"N2": ("FATIGUE",)},
        proposals=[
            {"condition_cui": "4", "snomed_code": "LYMPHOMA", "match_tier": "EXACT", "judgement": "good"},
            {"condition_cui": "4", "snomed_code": "FATIGUE", "match_tier": "EMBEDDING", "judgement": "reject: wrong"},
            {"condition_cui": "5", "snomed_code": "B_LYMPHOMA", "match_tier": "EXACT", "judgement": "good"},
        ],
    )

    rows = {(r["condition_cui"], r["target_snomed_code"]): r for r in result.suggestions}
    assert set(rows) == {(2, "FATIGUE"), (4, "LYMPHOMA")}  # the demotion of 3 is a patch, not a suggestion
    conflict = rows[(2, "FATIGUE")]
    assert conflict["override_line"] == "2,FATIGUE,add,crosswalk target reviewed"
    assert (conflict["hemonc_concept_id"], conflict["map_SNOMED"], conflict["hemonc_snomed_concept_id"]) == (1002, "MN_BREAST", 1)
    assert conflict["hemonc_snomed_standard"] == "1 concept 1"
    proposal = rows[(4, "LYMPHOMA")]
    assert proposal["override_line"] == "4,LYMPHOMA,add,search proposal reviewed"
    assert proposal["hemonc_snomed_standard"] == ""
