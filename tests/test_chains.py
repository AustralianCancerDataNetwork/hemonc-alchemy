"""Positional chain semantics and identical SQLite/DuckDB/PostgreSQL output."""

import csv
from dataclasses import asdict

import pandas as pd
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from hemonc_alchemy.compiler.chains import CHAIN_DECLARATIONS
from hemonc_alchemy.compiler.schema_model import Registry, TableMeta
from hemonc_alchemy.config import create_default_hemonc_engine
from hemonc_alchemy.model import (
    Drugs,
    Indications,
    drugs_CanmedPairs,
    indications_BiomarkerSlots,
    indications_ContextMap,
    indications_RegimenLinks,
)
from hemonc_alchemy.model.base import Base
from hemonc_alchemy.multivalue import align_values
from hemonc_alchemy.toolkit.chain_loading import ChainLoadReport
from hemonc_alchemy.toolkit.core.indications import (
    load_indication_sources,
    resolve_indications,
)
from hemonc_alchemy.toolkit.core.indications.model import (
    BiomarkerCriterion,
    RawCriterion,
)
from hemonc_alchemy.toolkit.loading import load_all


@pytest.mark.parametrize("values,status,rows", [
    (("MMR|MSI", "deficient|high"), "paired", (("MMR", "deficient"), ("MSI", "high"))),
    (("FGFR3", "mutation|fusion"), "broadcast", (("FGFR3", "mutation"), ("FGFR3", "fusion"))),
    (("A|B", ""), "paired", (("A", None), ("B", None))),
    (("A||B", "x|y|z"), "paired", (("A", "x"), (None, "y"), ("B", "z"))),
    (("A|B", "x|y|z", "type"), "unaligned", ()),
    (("A AND (B|C)", "one|two"), "opaque_member", ((None, "one"), (None, "two"))),
    (("A AND (B|C)", "one|two", "1|2"), "opaque_member", ((None, "one", "1"), (None, "two", "2"))),
    (("A AND (B|C)", "", ""), "unaligned", ()),
    (("", None), "empty", ()),
])
def test_alignment(values, status, rows):
    alignment = align_values(values)
    assert alignment.status == status
    assert alignment.rows == rows


def test_declarations_are_separate_slots_and_round_trip(caplog):
    meta = TableMeta("indications", "", "content", "prod", [])
    meta.finalise_from_data(pd.DataFrame({"biomarker": ["A|B"], "biomarker_finding": ["x|y|z"]}))
    assert meta.chains == list(CHAIN_DECLARATIONS["indications"])
    assert "contradicted" in caplog.text
    assert "missing declared columns" in caplog.text
    assert Registry.from_dict(asdict(Registry({meta.name: meta}))).tables[meta.name].chains == meta.chains


@pytest.fixture(params=[
    "sqlite",
    pytest.param("duckdb", marks=[pytest.mark.duckdb, pytest.mark.db_dialect]),
    pytest.param("postgresql", marks=[pytest.mark.postgres, pytest.mark.db_dialect]),
])
def chain_engine(request):
    if request.param == "sqlite":
        engine = create_default_hemonc_engine("sqlite://")
        try:
            yield engine, None
        finally:
            engine.dispose()
    elif request.param == "duckdb":
        db = request.getfixturevalue("duckdb_db")
        yield db.committing_engine, db.resolved
    else:
        db = request.getfixturevalue("pg_db")
        yield request.getfixturevalue("pg_load_engine"), db.resolved


def _write_indications(path):
    examples = [
        {"biomarker": "MMR|MSI", "biomarker_finding": "deficient|high", "context": "B|A|B",
         "biomarker3": " Z | A ", "biomarker3_finding": "x|y"},
        {"biomarker": "FGFR3", "biomarker_finding": "mutation|fusion"},
        {"with": "P|Q", "regimen": "one|two", "regimen_cui": ""},
        {"with": "P|P", "regimen": "same|same", "regimen_cui": "TBA|42"},
        {"with": "P AND (Q|R)", "regimen": "one|two", "regimen_cui": "1|2"},
        {"with": "P|Q", "regimen": "one|two|three", "regimen_cui": "1"},
        {"biomarker3": "A||B", "biomarker3_finding": "x|y|z"},
        {"regulator": "invalid", "regimen": "rejected", "regimen_cui": "TBA"},
    ]
    base = {"component": "Synthetic drug", "condition": "Synthetic condition", "regulator": "FDA",
            "accelerated": "FALSE", "first_in_class": "FALSE", "withdrawn": "FALSE", "date_added": "2026-01-01"}
    columns = sorted(set(base).union(*(set(row) for row in examples)))
    with (path / "indications.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, columns)
        writer.writeheader()
        writer.writerows(base | row for row in examples)


def test_load_and_resolve_identical_chain_positions(chain_engine, tmp_path):
    engine, resolved = chain_engine
    Base.metadata.create_all(engine)
    _write_indications(tmp_path)
    report = ChainLoadReport()
    with Session(engine) as session:
        totals = load_all(session, Indications, tmp_path, resolved=resolved, chain_report=report)
        assert totals["indications"] == 7
        session.commit()
        assert session.scalars(sa.select(indications_ContextMap.context).order_by(indications_ContextMap.position)).all() == ["B", "A", "B"]
        links = session.execute(sa.select(indications_RegimenLinks.__table__).order_by(
            indications_RegimenLinks.parent_id, indications_RegimenLinks.position)).mappings().all()
        assert [(link.position, link.regimen, link.regimen_cui_raw, link.regimen_cui, link.aligned) for link in links] == [
            (1, "one", None, None, True), (2, "two", None, None, True),
            (1, "same", "TBA", None, True), (2, "same", "42", 42, True),
            (1, "one", "1", 1, True), (2, "two", "2", 2, True),
            (0, None, None, None, False),
        ]
        assert session.scalar(sa.select(Indications.with_field_raw).where(Indications.id == 5)) == "P AND (Q|R)"
        slots = session.execute(sa.select(indications_BiomarkerSlots.__table__).order_by(
            indications_BiomarkerSlots.parent_id, indications_BiomarkerSlots.slot,
            indications_BiomarkerSlots.position)).mappings().all()
        assert [(row.slot, row.position, row.biomarker, row.biomarker_finding) for row in slots] == [
            (1, 1, "MMR", "deficient"), (1, 2, "MSI", "high"),
            (3, 1, "Z", "x"), (3, 2, "A", "y"),
            (1, 1, "FGFR3", "mutation"), (1, 2, "FGFR3", "fusion"),
            (3, 1, "A", "x"), (3, 2, None, "y"), (3, 3, "B", "z"),
        ]
        sources = load_indication_sources(session)
        assert sources[0].raw["biomarker3"] == " Z | A "
        assert sources[0].biomarkers[2].pairs == (("Z", "x"), ("A", "y"))
        assert [(link.name, link.raw_code, link.code) for link in sources[3].regimen_links] == [("same", "TBA", None), ("same", "42", 42)]
        assert sources[4].raw["with_field"] == "P AND (Q|R)"
        resolved_rows = resolve_indications(session)
        criteria = resolved_rows[0].criteria
        assert [(item.biomarker, [finding.raw for finding in item.findings])
                for item in criteria if isinstance(item, BiomarkerCriterion)] == [
                    ("MMR", ["deficient"]), ("MSI", ["high"]), ("Z", ["x"]), ("A", ["y"])]
        assert [(item.biomarker, item.findings[0].raw) for item in resolved_rows[6].criteria
                if isinstance(item, BiomarkerCriterion)] == [("A", "x"), ("B", "z")]
        assert any(isinstance(item, RawCriterion) and item.raw == "y" for item in resolved_rows[6].criteria)
    counts = report.chains["indications_regimen_links"]
    assert (counts.rows_paired, counts.rows_broadcast, counts.rows_opaque_member,
            counts.rows_unaligned, counts.repeats_kept) == (2, 0, 1, 1, 2)
    assert len(counts.unaligned_parent_ids) == 1
    assert counts.conversion_failures == 1
    assert report.chains["indications_biomarker_slots:1"].rows_broadcast == 1


def test_canmed_chain_retains_order_and_numeric_raw(chain_engine, tmp_path):
    engine, resolved = chain_engine
    Base.metadata.create_all(engine)
    (tmp_path / "drugs.csv").write_text(
        "drug,drug_cui,date_added,investigational,multiagent,canmed_major_class,canmed_major_class_cui\n"
        "Synthetic,1,2026-01-01,FALSE,FALSE,B|A|B,2|TBA|2\n"
    )
    with Session(engine) as session:
        load_all(session, Drugs, tmp_path, resolved=resolved)
        rows = session.execute(sa.select(drugs_CanmedPairs.__table__).order_by(drugs_CanmedPairs.position)).mappings().all()
        assert [(row.position, row.canmed_major_class, row.canmed_major_class_cui_raw, row.canmed_major_class_cui) for row in rows] == [
            (1, "B", "2", 2), (2, "A", "TBA", None), (3, "B", "2", 2)]


def test_unaligned_biomarkers_stay_raw():
    from hemonc_alchemy.toolkit.core.indications.loader import (
        BiomarkerSource,
        IndicationSource,
    )
    from hemonc_alchemy.toolkit.core.indications.normalisers.biomarker import (
        BiomarkerNormaliser,
    )

    source = IndicationSource(1, None, "C", None, "D", "FDA", "FALSE",
                              (BiomarkerSource(1, (), (), (), False),), (),
                              {"biomarker": "A|B", "biomarker_finding": "x|y|z"})
    criteria = BiomarkerNormaliser().normalise(source)
    assert all(isinstance(item, RawCriterion) for item in criteria)
    assert [item.raw for item in criteria] == ["A|B", "x|y|z"]


def test_full_compiler_regeneration_twice_is_identical(tmp_path):
    from hemonc_alchemy.compiler.generate import regenerate

    _write_indications(tmp_path)
    with pd.ExcelWriter(tmp_path / "data.dictionary.xlsx") as writer:
        pd.DataFrame([{"Content Tables": "indications", "Description": "Synthetic",
                       "Maturity": "prod", "Unique Key": ""}]).to_excel(writer, sheet_name="Content", index=False)
        pd.DataFrame(columns=["Lookup and Metadata Tables", "Description", "Maturity", "Unique Key"]).to_excel(
            writer, sheet_name="Lookup", index=False)
    output = tmp_path / "generated" / "model"
    output.mkdir(parents=True)
    (output.parent / "schema").mkdir()
    regenerate(tmp_path, output)
    paths = [output / "entities.py", output / "enums.py", output.parent / "schema" / "registry.json"]
    first = [path.read_bytes() for path in paths]
    regenerate(tmp_path, output)
    assert [path.read_bytes() for path in paths] == first


def test_source_audit_reports_all_unaligned_and_suspicious_rows(tmp_path):
    from scripts.audit_chains import audit

    (tmp_path / "indications.csv").write_text(
        "component,with,regimen,regimen_cui\n"
        "D,P,one|two,TBA|2\n"
        "D,P AND (Q|R),one|two,1|2\n"
    )
    (tmp_path / "drugs.csv").write_text("canmed_major_class,canmed_major_class_cui\nB|A,2|1\n")
    report = audit(tmp_path)
    assert "row 2: D (suspicious broadcast)" in report
    assert "row 3: D (opaque member)" in report
    assert '"regimen_cui": "TBA|2"' in report
    assert "drugs.canmed_pairs | 1 |" in report


def test_empty_source_does_not_remove_authored_chains():
    meta = TableMeta("drugs", "", "content", "prod", [])
    meta.finalise_from_data(pd.DataFrame(columns=["canmed_major_class", "canmed_major_class_cui"]))
    assert meta.chains == list(CHAIN_DECLARATIONS["drugs"])


def test_opaque_blob_is_preserved_with_legacy_map_unchanged(chain_engine, tmp_path):
    from hemonc_alchemy.model import Variants, variants_BlobMap

    engine, resolved = chain_engine
    Base.metadata.create_all(engine)
    row = {}
    for column in Variants.__table__.c:
        if column.nullable or column.name == "id":
            continue
        if isinstance(column.type, sa.Boolean):
            row[column.name] = "FALSE"
        elif isinstance(column.type, sa.Integer):
            row[column.name] = "1"
        elif isinstance(column.type, sa.DateTime):
            row[column.name] = "2026-01-01"
        else:
            row[column.name] = "Synthetic"
    row["blob"] = " 001|TBA||002|001 "
    with (tmp_path / "variants.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, row.keys())
        writer.writeheader()
        writer.writerow(row)
    with Session(engine) as session:
        load_all(session, Variants, tmp_path, resolved=resolved)
        assert session.scalar(sa.select(Variants.blob_raw)) == row["blob"]
        assert session.scalars(sa.select(variants_BlobMap.blob).order_by(variants_BlobMap.blob)).all() == ["001", "002", "TBA"]
        assert "position" not in variants_BlobMap.__table__.c
