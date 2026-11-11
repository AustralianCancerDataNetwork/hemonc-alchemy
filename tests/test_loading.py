"""Loading the real HemOnc extract, filename and header quirks included.

Runs against the actual extract rather than fixtures, because the point is
that HemOnc's own irregular filenames and headers load -- a synthetic
stand-in would not exercise that. Skipped if the extract isn't present; set
HEMONC_DATA_DIR if it lives outside the repo.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest
import sqlalchemy as sa
import sqlalchemy.orm as so
from orm_loader.loaders import LoadReport

from hemonc_alchemy.config import create_default_hemonc_engine
from hemonc_alchemy.model.base import Base
from hemonc_alchemy.model.entities import (
    Canonicaltriples,
    HemoncClasses,
    Refs,
    Sigs,
    Units,
    VariantEligibility,
    Variants,
    canonicaltriples_Class_1_provenanceMap,
    hemonc_classes_Secondary_home_as_stringMap,
)
from hemonc_alchemy.model.enums import (
    HemoncClasses_Class_typeEnum,
    HemoncClasses_DomainEnum,
)
from hemonc_alchemy.toolkit.loading import (
    _header_renames,
    _identity_value,
    _resolved_csv_path,
    load_all,
    load_denormalised,
    load_entity,
)

# Resolved the same way the CLI does (`HEMONC_DATA_DIR`), falling back to the
# in-repo extract directory. The hardcoded absolute path this replaces meant
# all five real-data tests below skipped silently on any other machine --
# indistinguishable, in the summary, from an intentional skip.
_REAL_DATA_DIR = Path(os.environ.get("HEMONC_DATA_DIR", "data/Tables"))


@pytest.mark.parametrize("model,positions,expected_studies", [
    (Sigs, [1688, 1689, 8876, 8877], [
        {"GELTAMO-2006", "ORCHARRD", "SHEBA-07-4466-AN-CTIL"},
        {"ORCHARRD", "SHEBA-07-4466-AN-CTIL"},
        {"RTOG 0825", "AVAglio"}, {"RTOG 0825", "AVAglio"},
    ]),
    (VariantEligibility, [210, 211], [{"APOLLO", "KarMMa-3"}, {"EQUULEUS--pom"}]),
])
def test_real_source_study_collections_remain_attached_to_each_occurrence(tmp_path, model, positions, expected_studies):
    source = _REAL_DATA_DIR / f"{model.__tablename__}.csv"
    with source.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    with (tmp_path / source.name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(rows[0])
        writer.writerows(rows[position] for position in positions)
    engine = create_default_hemonc_engine("sqlite:///:memory:")
    tables = [model.__table__, *[rel.mapper.class_.__table__ for rel in sa.inspect(model).relationships
                               if rel.key.endswith("_items")]]
    Base.metadata.create_all(engine, tables=tables)
    try:
        with so.Session(engine) as session:
            counts = load_all(session, model, tmp_path)
            assert counts[model.__tablename__] == len(positions)
            parents = session.scalars(sa.select(model).options(
                so.raiseload("*"), so.selectinload(model.study_items).raiseload("*"),
            ).order_by(model.id)).all()
            assert [{item.study for item in parent.study_items} for parent in parents] == expected_studies
    finally:
        engine.dispose()


def test_reference_semicolon_names_are_scalar_and_keep_their_cuis(tmp_path):
    with (_REAL_DATA_DIR / "refs.csv").open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    with (tmp_path / "refs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerows([rows[0], rows[1954]])
    engine = create_default_hemonc_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Refs.__table__, Refs.title_items.property.mapper.class_.__table__])
    try:
        with so.Session(engine) as session:
            assert load_all(session, Refs, tmp_path)["refs"] == 1
            record = session.execute(sa.select(Refs.study, Refs.study_cui, Refs.reference, Refs.reference_cui)).one()
            assert tuple(record) == (
                "GEICAM/2003-11; CIBOMA/2004-01", 25246,
                "GEICAM/2003-11; CIBOMA/2004-01::00", 25252,
            )
    finally:
        engine.dispose()


def test_surrogate_identity_treats_invalid_datetime_placeholder_as_null():
    column = sa.Column("date_added", sa.DateTime)
    failures = []

    assert _identity_value(
        "Uncertain date", column, on_error=failures.append
    ) is None
    assert failures == ["Uncertain date"]

pytestmark = [
    pytest.mark.skipif(
        len(Base.metadata.tables) == 0,
        reason="model/entities.py has no generated classes yet -- run `hemonc-alchemy regen` first",
    ),
    pytest.mark.skipif(
        not _REAL_DATA_DIR.is_dir(),
        reason=f"real HemOnc data directory not found at {_REAL_DATA_DIR}",
    ),
]


@pytest.fixture
def session():
    engine = create_default_hemonc_engine("sqlite:///:memory:")
    with so.Session(engine) as s:
        yield s


class TestFilenameResolution:
    def test_loads_table_whose_real_filename_does_not_match_tablename(self, session):
        # canonicaltriples is backed by canonical_triples.csv.
        Base.metadata.create_all(session.get_bind(), tables=[Canonicaltriples.__table__])

        total = load_entity(session, Canonicaltriples, _REAL_DATA_DIR)
        assert total > 0

        count = session.execute(sa.text("SELECT COUNT(*) FROM canonicaltriples")).scalar()
        assert count == total

        sample = session.execute(
            sa.text("SELECT class_1, relationship, class_2 FROM canonicaltriples LIMIT 1")
        ).first()
        assert sample is not None
        assert all(v for v in sample)

    def test_loads_table_whose_filename_already_matches(self, session):
        Base.metadata.create_all(session.get_bind(), tables=[Units.__table__])

        total = load_entity(session, Units, _REAL_DATA_DIR)
        assert total > 0

        count = session.execute(sa.text("SELECT COUNT(*) FROM units")).scalar()
        assert count == total


class TestHeaderNormalisation:
    """Headers containing dots, hyphens or Python keywords have to be
    reconciled with the generated column names before a load, or real columns
    are reported missing. Six extracts need it, `sigs` and `indications`
    included.
    """

    def test_dots_hyphens_and_keywords_are_renamed(self, tmp_path):
        csv_path = tmp_path / "sample.csv"
        csv_path.write_text(
            "class,seq.rel.when,parameter-based,already_fine\n1,2,3,4\n"
        )
        assert _header_renames(csv_path) == {
            "class": "class_field",          # Python keyword
            "seq.rel.when": "seqrelwhen",
            "parameter-based": "parameterbased",
        }

    def test_case_only_differences_are_left_alone(self, tmp_path):
        """Case already matches, so rewriting the file would cost a full copy
        for nothing."""
        csv_path = tmp_path / "sample.csv"
        csv_path.write_text("in_OHDSI,doseMinNum\n1,2\n")
        assert _header_renames(csv_path) == {}

    def test_resolved_csv_has_model_ready_headers_and_all_rows(self, tmp_path):
        source = tmp_path / "weird.csv"
        source.write_text("class,seq.rel,ok\na,b,c\nd,e,f\n")

        with (
            _resolved_csv_path(tmp_path, "weird") as resolved,
            resolved.open(newline="") as handle,
        ):
            rows = list(csv.reader(handle))

        assert rows[0] == ["class_field", "seqrel", "ok"]
        assert rows[1:] == [["a", "b", "c"], ["d", "e", "f"]]

    def test_a_clean_csv_is_passed_through_untouched(self, tmp_path):
        source = tmp_path / "clean.csv"
        source.write_text("unit,concept_code\nmg,1\n")
        with _resolved_csv_path(tmp_path, "clean") as resolved:
            assert resolved == source          # no copy, no symlink

    def test_units_loads_with_its_hyphenated_headers(self, session):
        """The original failure, end to end on the real extract."""
        Base.metadata.create_all(session.get_bind(), tables=[Units.__table__])

        total = load_entity(session, Units, _REAL_DATA_DIR)
        session.commit()
        assert total > 0
        loaded = session.execute(sa.select(Units)).scalars().all()
        assert all(row.parameterbased is not None for row in loaded)
        assert all(row.timebased is not None for row in loaded)


class TestDenormalisedLoadingNaturalKey:
    """`Canonicaltriples` is a lookup (no surrogate id) table -- its
    denormalised map tables key directly off its own natural key, no
    parent-id lookup needed, so this works on SQLite same as Postgres.
    """

    def test_explodes_pipe_delimited_provenance_columns(self, session):
        Base.metadata.create_all(
            session.get_bind(),
            tables=[Canonicaltriples.__table__]
            + [rel.mapper.class_.__table__ for rel in sa.inspect(Canonicaltriples).relationships],
        )

        load_entity(session, Canonicaltriples, _REAL_DATA_DIR)
        session.flush()

        results = load_denormalised(session, Canonicaltriples, _REAL_DATA_DIR)

        assert set(results) == {"class_1_provenance", "class_2_provenance"}
        assert all(count > 0 for count in results.values())

        count = session.execute(sa.text("SELECT COUNT(*) FROM canonicaltriples_class_1_provenance")).scalar()
        assert count == results["class_1_provenance"]

    @pytest.mark.parametrize("include_rejected", [False, True])
    def test_casts_enum_natural_key_before_child_insert(self, tmp_path, include_rejected):
        csv_path = tmp_path / "canonicaltriples.csv"
        csv_path.write_text(
            "class_1,relationship,class_2,date_added,in_ohdsi,internal,used_in,"
            "class_1_provenance\n"
            "Regimen,is_a,Context,2020-01-01,0,0,x,HTML\n"
        )

        if include_rejected:
            with csv_path.open("a") as handle:
                handle.write("Regimen,is_a,Context,2020-01-01,invalid-boolean,0,x,rejected\n")

        engine = create_default_hemonc_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            engine,
            tables=[Canonicaltriples.__table__, canonicaltriples_Class_1_provenanceMap.__table__],
        )
        with so.Session(engine) as session:
            report = LoadReport()
            results = load_all(session, Canonicaltriples, tmp_path, report=report)
            session.commit()
            assert results["canonicaltriples"] == 1
            assert report.rows_rejected == int(include_rejected)

            assert results["class_1_provenance"] == 1
            row = session.execute(
                sa.select(canonicaltriples_Class_1_provenanceMap)
            ).scalar_one()
        assert row.class_1.value == "regimen"
        assert row.class_1_provenance == "HTML"

    def test_surrogate_parent_matching_handles_sparse_natural_key(self, tmp_path):
        csv_path = tmp_path / "hemonc_classes.csv"
        csv_path.write_text(
            "description,domain,OMOP.domain_id,OMOP.standard_concept,class_type,"
            "primary_table,primary_field,concept_class_id,secondary_home_as_string,"
            "secondary_home_as_cui,in_OHDSI,date_added,date_deprecated\n"
            "Clinical Trial Registry,clinical trial,,,ready for core,ready for core,,,"
            "studies$registry,,FALSE,D-2023-06-02,\n"
        )

        engine = create_default_hemonc_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            engine,
            tables=[
                HemoncClasses.__table__,
                hemonc_classes_Secondary_home_as_stringMap.__table__,
            ],
        )
        with so.Session(engine) as session:
            session.execute(
                sa.insert(HemoncClasses),
                {
                    "id": 1,
                    "class_type": HemoncClasses_Class_typeEnum.READY_FOR_CORE,
                    "concept_class_id": None,
                    "date_added": "D-2023-06-02",
                    "date_deprecated": None,
                    "description": "Clinical Trial Registry",
                    "domain": HemoncClasses_DomainEnum.CLINICAL_TRIAL,
                    "in_ohdsi": False,
                    "omopdomain_id": None,
                    "omopstandard_concept": None,
                    "primary_field": None,
                    "primary_table": "ready for core",
                },
            )
            results = load_denormalised(session, HemoncClasses, tmp_path)
            session.commit()

            assert results["secondary_home_as_string"] == 1
            child = session.execute(
                sa.select(hemonc_classes_Secondary_home_as_stringMap)
            ).scalar_one()
            assert child.parent_id == 1
            assert child.secondary_home_as_string == "studies$registry"


class TestLoadAll:
    """`load_all` composes `load_entity` + `load_denormalised` -- the two
    prior test classes already prove each half works on real data; this
    just proves the composition itself against a real table with both an
    irregular filename and real denormalised columns.
    """

    def test_loads_primary_and_denormalised_in_one_call(self, session):
        Base.metadata.create_all(
            session.get_bind(),
            tables=[Canonicaltriples.__table__]
            + [rel.mapper.class_.__table__ for rel in sa.inspect(Canonicaltriples).relationships],
        )

        results = load_all(session, Canonicaltriples, _REAL_DATA_DIR)

        assert results["canonicaltriples"] > 0
        assert results["class_1_provenance"] > 0
        assert results["class_2_provenance"] > 0

        count = session.execute(sa.text("SELECT COUNT(*) FROM canonicaltriples")).scalar()
        assert count == results["canonicaltriples"]


@pytest.mark.postgres
class TestSurrogatePkEndToEnd:
    """`Variants` is a surrogate-PK ("content") table with real
    denormalised columns and, deliberately, zero enum columns -- so this
    exercises the natural-key-to-id parent lookup on real data without
    also hitting the separate, tracked enum-casting gap.

    Needs real Postgres. Surrogate ids are assigned on insert and aren't in
    the source CSV, and SQLite won't fill them in on an INSERT..SELECT the way
    Postgres does.
    """

    def test_primary_and_denorm_load_with_correct_linkage(self, pg_load_engine):
        from hemonc_alchemy.model.entities import variants_StudyMap

        map_tables = [rel.mapper.class_.__table__ for rel in sa.inspect(Variants).relationships]
        Base.metadata.create_all(pg_load_engine, tables=[Variants.__table__, *map_tables])
        with so.Session(pg_load_engine) as session:
            results = load_all(session, Variants, _REAL_DATA_DIR)
            session.commit()
            assert results["variants"] > 0
            assert set(results) >= {"variants", "blob", "study", "tracer"}
            assert all(count > 0 for count in results.values())
            orphaned = session.scalar(
                sa.select(sa.func.count()).select_from(variants_StudyMap.__table__.outerjoin(
                    Variants.__table__, Variants.id == variants_StudyMap.parent_id
                )).where(Variants.id.is_(None))
            )
            assert orphaned == 0


if __name__ == "__main__":
    pytest.main([__file__])
