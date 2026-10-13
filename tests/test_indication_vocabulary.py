"""Packaged indication vocabulary: read API, golden closures and lint failures."""

import csv
import shutil
from pathlib import Path

import pytest

from hemonc_alchemy.toolkit.core.indication_vocabulary import (
    LocalTsvVocabulary,
    lint_vocabulary,
    load_vocabulary,
)
from hemonc_alchemy.toolkit.core.indication_vocabulary.loader import (
    LOCAL_CONCEPT_BASE,
    data_directory,
    normalise_source_value,
)


@pytest.fixture(scope="module")
def vocab():
    return load_vocabulary()


def names(vocab, ids):
    return {vocab.concept(i).concept_name for i in ids}


def finding_state(vocab, gene, finding):
    concept_id = vocab.concept_for("biomarker_finding", finding, gene)
    assert concept_id is not None, f"{gene}: {finding}"
    return concept_id


def test_packaged_lint_passes_with_only_recorded_gaps(vocab):
    report = lint_vocabulary(vocab)
    assert report.failures == ()
    assert any("17p" in value for value in report.unmapped_values)
    assert any(
        "Is a edges proposed, priority lung-first" in line
        for line in report.needs_review
    )


def test_every_local_concept_is_in_the_local_range_and_has_status(vocab):
    concepts = vocab.concepts()
    assert concepts and all(c.concept_id >= LOCAL_CONCEPT_BASE for c in concepts)
    statuses = {int(r["concept_id"]) for r in vocab.table("concept_status")}
    assert {c.concept_id for c in concepts} == statuses


def test_closure_reproduces_earlier_goldens(vocab):
    l858r = finding_state(vocab, "EGFR", "p.L858R")
    implied = names(vocab, vocab.implied(l858r))
    assert {
        "EGFR: sensitizing mutation",
        "EGFR: activating mutation",
        "EGFR: mutated",
    } <= implied

    v600e = finding_state(vocab, "BRAF", "p.V600E")
    assert "BRAF: p.V600" in names(vocab, vocab.implied(v600e))


def terms_of(vocab, state_id):
    return [
        term
        for i in vocab.indication_ids()
        for criterion in vocab.criteria(i)
        for alternative in criterion.alternatives
        for term in alternative
        if term.concept_id == state_id
    ]


def test_cutoffs_are_attributes_of_a_score_state_not_concepts(vocab):
    assert vocab.concepts("Biomarker Threshold") == ()
    score = finding_state(vocab, "PD-L1", "TPS at least 50%")
    assert finding_state(vocab, "PD-L1", "TPS at least 1%") == score
    cutoffs = {t.bounds.value_low for t in terms_of(vocab, score) if t.bounds}
    assert {1.0, 5.0, 50.0} <= cutoffs
    met = {value for value in cutoffs if value <= 60}
    assert {1.0, 50.0} <= met
    assert not {value for value in cutoffs if value <= 0.5}
    assert all(
        t.bounds.comparator_low == ">="
        and t.bounds.unit == "%"
        and t.bounds.qualifier == "TPS"
        for t in terms_of(vocab, score)
        if t.bounds
    )


def test_age_prior_lines_and_time_windows_are_scalar_terms_without_concepts(vocab):
    for cls in ("Age Band", "Time Window", "Biomarker Threshold", "Criterion Set"):
        assert vocab.concepts(cls) == ()
    ages = [
        term
        for i in vocab.indication_ids()
        for criterion in vocab.criteria(i)
        if criterion.dimension == "age"
        for alternative in criterion.alternatives
        for term in alternative
        if term.bounds
    ]
    assert any(
        t.concept_id is None
        and t.bounds.comparator_low == ">="
        and t.bounds.value_low == 12
        and t.bounds.unit == "year"
        for t in ages
    )
    lines = vocab.terms_for_source("prior_therapy", "2+ SACT")
    assert any(
        t.bounds and t.bounds.unit == "lines" and t.bounds.value_low == 2
        for t in lines[0]
    )
    assert vocab.terms_for_source("age", "adult", "year") is None
    window = vocab.terms_for_source("time_contingency", "within 6 months")[0][0]
    assert (
        window.bounds.comparator_high,
        window.bounds.value_high,
        window.bounds.unit,
    ) == ("<=", 6, "month")


def test_clinical_implication_is_not_taxonomy(vocab):
    l858r = finding_state(vocab, "EGFR", "p.L858R")
    activating = finding_state(vocab, "EGFR", "activating mutation")
    assert activating in vocab.related(l858r, "Clinically implies")
    assert activating not in vocab.ancestors(l858r)
    assert vocab.relationship_types["Clinically implies"].is_hierarchical is False
    assert vocab.relationship_types["Subsumes"].is_hierarchical is True


def test_lookup_folds_case_enum_underscores_and_context(vocab):
    assert normalise_source_value(" WILD_TO_TYPE ") == "wild-type"
    assert vocab.concept_for(
        "biomarker_finding", "WILD_TO_TYPE", "EGFR"
    ) == finding_state(vocab, "EGFR", "wild-type")
    assert vocab.concept_for(
        "biomarker_finding", "CPS_AT_LEAST_1", "PD_TO_L1"
    ) == finding_state(vocab, "PD-L1", "CPS at least 1%")
    assert vocab.lookup("biomarker_finding", "no such finding", "EGFR") is None


def test_ancestors_and_descendants_are_inverse_and_cycle_safe(vocab):
    p_v600 = finding_state(vocab, "BRAF", "p.V600")
    assert finding_state(vocab, "BRAF", "p.V600E") in vocab.descendants(p_v600)
    for concept in vocab.concepts("Biomarker State")[:50]:
        for ancestor in vocab.ancestors(concept.concept_id):
            assert concept.concept_id in vocab.descendants(ancestor)


def test_indication_criteria_are_ands_of_ors_with_polarity(vocab):
    triple_negative = [
        i
        for i in vocab.indication_ids()
        if {c.dimension for c in vocab.criteria(i)} >= {"biomarker"}
        and sum(c.dimension == "biomarker" for c in vocab.criteria(i)) >= 3
    ]
    assert triple_negative
    excludes = [
        c
        for i in vocab.indication_ids()
        for c in vocab.criteria(i)
        if c.polarity == "excludes"
    ]
    assert excludes and all(c.dimension == "prior_therapy" for c in excludes)
    egfr_or = [
        c
        for i in vocab.indication_ids()
        for c in vocab.criteria(i)
        if c.dimension == "biomarker"
        and len(c.alternatives) == 2
        and {vocab.concept(a[0].concept_id).concept_name for a in c.alternatives}
        == {"EGFR: exon 19 deletion", "EGFR: p.L858R"}
    ]
    assert egfr_or


def test_unanchored_indications_have_no_local_component_or_condition(vocab):
    unanchored = vocab.table("unanchored_indications")
    assert len(unanchored) + len(vocab.indication_ids()) == 3093
    assert {r["indication_id"] for r in unanchored}.isdisjoint(
        {
            vocab.concept(i).concept_code.rsplit("-", 1)[1]
            for i in vocab.indication_ids()
        }
    )
    assert all(
        not rel.concept_id_2 >= LOCAL_CONCEPT_BASE
        for i in vocab.indication_ids()
        for rel in vocab.relationships(i, "Ind has component")
        + vocab.relationships(i, "Ind has condition")
    )


def test_msi_analyte_is_the_replacement_concept(vocab):
    assert vocab.concept_for("biomarker", "MSI") == 700490
    assert vocab.concept(35977040) is None


@pytest.fixture
def copy(tmp_path):
    target = tmp_path / "data"
    shutil.copytree(data_directory(), target)
    return target


def rewrite(directory: Path, table: str, change):
    path = directory / f"{table}.tsv"
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        header, rows = reader.fieldnames, list(reader)
    rows = change(rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, header, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def lint_failures(directory):
    return lint_vocabulary(LocalTsvVocabulary(directory)).failures


def test_lint_reports_a_dangling_relationship_endpoint(copy):
    rewrite(
        copy,
        "concept_relationship",
        lambda rows: (
            rows
            + [
                {
                    "concept_id_1": "2000000001",
                    "concept_id_2": "123456789",
                    "relationship_id": "Is a",
                    "valid_start_date": "",
                    "valid_end_date": "",
                    "invalid_reason": "",
                }
            ]
        ),
    )
    failures = lint_failures(copy)
    assert any("endpoint that does not exist" in f for f in failures)


def test_lint_reports_a_missing_reverse_row(copy):
    rewrite(
        copy,
        "concept_relationship",
        lambda rows: [r for r in rows if r["relationship_id"] != "Subsumes"][
            : -0 or None
        ],
    )
    assert any("no reverse row" in f for f in lint_failures(copy))


def test_lint_reports_an_undefined_relationship_id(copy):
    rewrite(
        copy,
        "relationship",
        lambda rows: [r for r in rows if r["relationship_id"] != "State has analyte"],
    )
    assert any("not defined in relationship.tsv" in f for f in lint_failures(copy))


def test_lint_reports_a_hierarchy_cycle(copy):
    vocab = LocalTsvVocabulary(copy)
    child = finding_state(vocab, "BRAF", "p.V600E")
    parent = finding_state(vocab, "BRAF", "p.V600")

    def add(rows):
        return rows + [
            {
                "concept_id_1": str(parent),
                "concept_id_2": str(child),
                "relationship_id": "Is a",
                "valid_start_date": "",
                "valid_end_date": "",
                "invalid_reason": "",
            },
            {
                "concept_id_1": str(child),
                "concept_id_2": str(parent),
                "relationship_id": "Subsumes",
                "valid_start_date": "",
                "valid_end_date": "",
                "invalid_reason": "",
            },
        ]

    rewrite(copy, "concept_relationship", add)
    assert any("hierarchy cycle" in f for f in lint_failures(copy))


def test_lint_reports_an_existing_concept_not_verified_in_groundworkers(copy):
    rewrite(
        copy,
        "existing_concepts",
        lambda rows: [r for r in rows if r["concept_id"] != "9191"],
    )
    assert any(
        "cited existing concept 9191 is missing" in f for f in lint_failures(copy)
    )


def test_lint_reports_an_invalid_existing_concept(copy):
    def invalidate(rows):
        for r in rows:
            if r["concept_id"] == "9191":
                r["invalid_reason"] = "D"
        return rows

    rewrite(copy, "existing_concepts", invalidate)
    assert any("is not valid in groundworkers" in f for f in lint_failures(copy))


def test_lint_reports_an_edge_without_review_and_a_reviewed_edge_without_reviewer(copy):
    rewrite(copy, "relationship_review", lambda rows: rows[1:])
    assert any("has no relationship_review row" in f for f in lint_failures(copy))

    def mark(rows):
        rows[0]["status"] = "reviewed"
        return rows

    shutil.rmtree(copy)
    shutil.copytree(data_directory(), copy)
    rewrite(copy, "relationship_review", mark)
    assert any("needs a reviewer and a date" in f for f in lint_failures(copy))


def test_lint_reports_unmapped_live_source_values(vocab):
    report = lint_vocabulary(vocab, [("stage", "Not a stage", "")])
    assert any("Not a stage" in value for value in report.unmapped_values)


def biomarker_criteria(vocab, raw):
    by_code = {c.concept_code: c.concept_id for c in vocab.concepts("Indication")}
    for row in vocab.table("indication_notes"):
        if row["raw_value"] == raw and f"HOL-IND-{row['indication_id']}" in by_code:
            return [
                c
                for c in vocab.criteria(by_code[f"HOL-IND-{row['indication_id']}"])
                if c.dimension == "biomarker"
            ]
    raise AssertionError(f"no anchored indication with {raw}")


def state_names(vocab, alternatives):
    return {
        frozenset(vocab.concept(t.concept_id).concept_name for t in alt)
        for alt in alternatives
    }


def test_slot_pairing_is_an_independent_or_product_filtered_by_allowed_results(vocab):
    (criterion,) = [
        c
        for c in biomarker_criteria(vocab, "ER|PR / positive|unknown")
        if {vocab.concept(a[0].concept_id).concept_name for a in c.alternatives}
        >= {"PR: unknown"}
    ]
    assert state_names(vocab, criterion.alternatives) == {
        frozenset({name})
        for name in ("ER: positive", "ER: unknown", "PR: positive", "PR: unknown")
    }


def test_mmr_msi_composites_follow_the_curated_readings(vocab):
    either = {frozenset({"MMR: deficient"}), frozenset({"MSI: high"})}
    found = [
        c
        for i in vocab.indication_ids()
        for c in vocab.criteria(i)
        if c.dimension == "biomarker" and state_names(vocab, c.alternatives) == either
    ]
    assert found
    (proficient,) = biomarker_criteria(vocab, "MMR|MSI / proficient|not high")
    assert state_names(vocab, proficient.alternatives) == {
        frozenset({"MMR: proficient", "MSI: not high"})
    }
    names = {c.concept_name for c in vocab.concepts("Biomarker State")}
    assert {
        "MMR: high",
        "MSI: deficient",
        "MSI: proficient",
        "MMR: not high",
    }.isdisjoint(names)


def test_every_changed_slot_records_the_old_and_new_reading(vocab):
    changed = [
        r
        for r in vocab.table("indication_notes")
        if r["issue"].startswith("reading changed")
    ]
    assert len(changed) == 16
    assert all("old: " in r["issue"] and "new: " in r["issue"] for r in changed)


def test_placeholder_values_become_explicit_concepts_not_bare_names(vocab):
    names = {c.concept_name.casefold() for c in vocab.concepts()}
    assert {"0", "none", "true", "false", "not applicable"}.isdisjoint(names)
    monotherapy = vocab.concept_for("with_field", "0")
    assert vocab.concept(monotherapy).concept_name == "Monotherapy (no co-therapy)"
    assert vocab.concept(monotherapy).concept_class_id == "Co-therapy Requirement"
    restriction = vocab.concept_for("ineligibility", "none")
    assert vocab.concept(restriction).concept_name == "No ineligibility restriction"


def test_lint_reports_a_bare_placeholder_concept_name(copy):
    def rename(rows):
        rows[0]["concept_name"] = "0"
        rows[1]["concept_name"] = "Co-therapy: none"
        return rows

    rewrite(copy, "concept", rename)
    failures = lint_failures(copy)
    assert sum("bare placeholder" in f for f in failures) == 2


def test_lint_reports_a_scalar_term_without_a_unit_and_a_term_with_nothing(copy):
    def blank_unit(rows):
        for row in rows:
            if row["value_low"]:
                row["unit"] = ""
                break
        return rows

    rewrite(copy, "criterion_term", blank_unit)
    assert any("number without a unit" in f for f in lint_failures(copy))

    shutil.rmtree(copy)
    shutil.copytree(data_directory(), copy)

    def empty(rows):
        rows[0].update(concept_id="", value_low="", value_high="", text="")
        return rows

    rewrite(copy, "criterion_term", empty)
    assert any("no concept, number or text" in f for f in lint_failures(copy))
