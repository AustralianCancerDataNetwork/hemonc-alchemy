"""Loader 3 contract: ID-less snapshots, shared conversions, and failure behavior."""

from dataclasses import replace
from enum import Enum

import pytest
import sqlalchemy as sa
from oa_configurator import Resolver, StackConfig
from orm_loader.conversion import ErrorPolicy, NullPolicy
from orm_loader.helpers import ConversionError
from orm_loader.loaders.readers import FileReader
from sqlalchemy.orm import Session

from hemonc_alchemy.config import create_default_hemonc_engine
from hemonc_alchemy.model.base import Base, register_enum_casts
from hemonc_alchemy.model.entities import (
    HemoncClasses,
    Units,
    hemonc_classes_Secondary_home_as_stringMap,
)
from hemonc_alchemy.model.ingestion import conversion_policy, convert_value
from hemonc_alchemy.toolkit.loading import load_all, load_entity


@pytest.fixture(params=[
    "sqlite",
    pytest.param("duckdb", marks=[pytest.mark.duckdb, pytest.mark.db_dialect]),
    pytest.param("duckdb_memory", marks=[pytest.mark.duckdb, pytest.mark.db_dialect]),
    pytest.param("postgresql", marks=[pytest.mark.postgres, pytest.mark.db_dialect]),
])
def database(request, tmp_path):
    if request.param == "postgresql":
        db = request.getfixturevalue("pg_db")
        yield request.getfixturevalue("pg_load_engine"), db.resolved
        return
    path = ":memory:" if request.param == "duckdb_memory" else str(tmp_path / f"ingestion.{request.param}")
    dialect = request.param.split("_")[0]
    stack = StackConfig.for_session(
        connections={"local": {"dialect": dialect, "database_name": path}},
        databases={"local": {"kind": "generic", "connection": "local"}},
    )
    resolved = Resolver(stack).resolve_database("local")
    engine = resolved.create_engine(register_claims=False)
    try:
        yield engine, resolved
    finally:
        engine.dispose()


def snapshot(tmp_path):
    path = tmp_path / "hemonc_classes.csv"
    path.write_text(
        "description,domain,OMOP.domain_id,OMOP.standard_concept,class_type,"
        "primary_table,primary_field,concept_class_id,secondary_home_as_string,"
        "secondary_home_as_cui,in_OHDSI,date_added,date_deprecated\n"
        "Clinical Trial Registry,clinical trial,,,ready for core,ready for core,,,"
        "studies$registry|studies$trial,,FALSE,D-2023-06-02,\n"
        "Another Registry,clinical trial,,,ready for core,ready for core,,,"
        "studies$other,,FALSE,D-2023-06-02,\n"
    )
    return path


class SmallBatches(FileReader):
    """Force the ID adapter through several batches using the public reader contract."""

    def __init__(self, reader):
        self.__dict__.update(reader.__dict__)
        self.reader = reader

    def batches(self):
        for batch in self.reader.batches():
            for index in range(batch.num_rows):
                yield batch.slice(index, 1)


def test_idless_snapshot_attaches_sparse_parents_and_refuses_reload(database, tmp_path):
    engine, resolved = database
    tables = [HemoncClasses.__table__, hemonc_classes_Secondary_home_as_stringMap.__table__]
    Base.metadata.create_all(engine, tables=tables)
    snapshot(tmp_path)
    with Session(engine) as session:
        counts = load_all(session, HemoncClasses, tmp_path, resolved=resolved)
        session.commit()
        assert counts["hemonc_classes"] == 2
        assert counts["secondary_home_as_string"] == 3
        children = session.execute(sa.select(
            HemoncClasses.description,
            hemonc_classes_Secondary_home_as_stringMap.secondary_home_as_string,
        ).join(hemonc_classes_Secondary_home_as_stringMap,
               HemoncClasses.id == hemonc_classes_Secondary_home_as_stringMap.parent_id)).all()
        assert set(children) == {
            ("Clinical Trial Registry", "studies$registry"),
            ("Clinical Trial Registry", "studies$trial"),
            ("Another Registry", "studies$other"),
        }
        with pytest.raises(ValueError, match="require an empty target"):
            load_entity(session, HemoncClasses, tmp_path, resolved=resolved)
        assert session.scalar(sa.select(sa.func.count()).select_from(HemoncClasses)) == 2


def test_generated_ids_across_batches_leave_native_sequence_ready(database, tmp_path):
    from orm_loader.loaders import open_reader

    engine, resolved = database
    HemoncClasses.__table__.create(engine)
    path = snapshot(tmp_path)
    reader = SmallBatches(open_reader(path, HemoncClasses.model_columns()))
    with Session(engine) as session:
        assert HemoncClasses.load_file(session, path, reader=reader, resolved=resolved) == 2
        rows = session.execute(sa.select(HemoncClasses.__table__).order_by(HemoncClasses.id)).mappings().all()
        assert [r["id"] for r in rows] == [1, 2]
        if engine.dialect.name != "sqlite":
            record = dict(rows[0])
            del record["id"]
            record["description"] = "Subsequent ORM insert"
            assert session.scalar(sa.insert(HemoncClasses.__table__).returning(HemoncClasses.id), record) == 3


def test_nullable_conversion_keeps_children_attached(database, tmp_path):
    engine, resolved = database
    Base.metadata.create_all(engine, tables=[
        HemoncClasses.__table__, hemonc_classes_Secondary_home_as_stringMap.__table__,
    ])
    path = snapshot(tmp_path)
    path.write_text(path.read_text().replace("clinical trial,,,ready", "clinical trial,NOT_A_DOMAIN,,ready"))
    with Session(engine) as session:
        counts = load_all(session, HemoncClasses, tmp_path, resolved=resolved)
        assert counts["hemonc_classes"] == 2
        assert session.scalars(sa.select(HemoncClasses.omopdomain_id)).all() == [None, None]
        assert counts["secondary_home_as_string"] == 3


def test_policy_preserves_compiler_enum_collision_equivalence():
    class Labels(Enum):
        CPS_AT_LEAST_10 = "cps at least 10"

    column = sa.Column("label", sa.Enum(Labels))
    assert convert_value("CPS at least 10%", column, conversion_policy()) == "CPS_AT_LEAST_10"


def test_explicit_policy_can_keep_text_null_markers():
    column = sa.Column("label", sa.String)
    policy = conversion_policy()
    assert convert_value("N/A", column, policy) is None
    assert convert_value("N/A", column, replace(policy, nulls=NullPolicy())) == "N/A"


def test_strict_policy_aborts_before_merging(tmp_path):
    path = tmp_path / "units.csv"
    path.write_text(
        "unit,unit_type,concept_code,date_added,fixed,parameterbased,timebased\n"
        "bad,UNITS_PER_VOLUME,no-number,2020-01-01,TRUE,FALSE,FALSE\n"
    )
    engine = create_default_hemonc_engine("sqlite:///:memory:")
    Units.__table__.create(engine)
    with Session(engine) as session:
        with pytest.raises(ConversionError):
            Units.load_file(session, path, policy=replace(conversion_policy(), errors=ErrorPolicy()))
        assert session.scalar(sa.select(sa.func.count()).select_from(Units)) == 0
        assert not any(n.startswith("_staging_") for n in sa.inspect(engine).get_table_names())


def test_compatibility_hooks_do_not_require_legacy_upstream_modules(tmp_path):
    path = tmp_path / "units.csv"
    path.write_text("unit,unit_type,concept_code,date_added,fixed,parameterbased,timebased\nmg,u,1,2020-01-01,1,0,0\n")
    engine = create_default_hemonc_engine("sqlite:///:memory:")
    Units.__table__.create(engine)
    with pytest.warns(DeprecationWarning, match="unnecessary"):
        register_enum_casts()
    with Session(engine) as session, pytest.warns(DeprecationWarning, match="load_csv"):
        assert Units.load_csv(session, path) == 1


def test_primary_commit_survives_child_load_failure(tmp_path):
    engine = create_default_hemonc_engine("sqlite:///:memory:")
    HemoncClasses.__table__.create(engine)
    snapshot(tmp_path)
    with Session(engine) as session:
        # The child table is deliberately absent to exercise a failure after merge.
        with pytest.raises(sa.exc.OperationalError):
            load_all(session, HemoncClasses, tmp_path)
        session.rollback()
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(HemoncClasses)) == 2
