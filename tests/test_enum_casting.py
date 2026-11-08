"""HemOnc enums use one explicit policy for file loads and child values."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest
import sqlalchemy as sa
import sqlalchemy.orm as so

from hemonc_alchemy.config import create_default_hemonc_engine
from hemonc_alchemy.model.base import Base
from hemonc_alchemy.model.entities import Canonicaltriples, Drugs
from hemonc_alchemy.model.enums import (
    Canonicaltriples_Class_1Enum,
    Drugs_Class_typeEnum,
)
from hemonc_alchemy.model.ingestion import conversion_policy, convert_value
from hemonc_alchemy.toolkit.loading import load_entity

# Resolved the same way the CLI does (`HEMONC_DATA_DIR`), falling back to the
# in-repo extract directory. This was previously hardcoded to one machine's
# absolute path, which only went unnoticed because the module failed to import
# at all while the generated model was stale.
_REAL_DATA_DIR = Path(os.environ.get("HEMONC_DATA_DIR", "data/Tables"))

pytestmark = pytest.mark.skipif(
    len(Base.metadata.tables) == 0,
    reason="model/entities.py has no generated classes yet -- run `hemonc-alchemy regen` first",
)


class TestEnumPolicy:
    def test_real_parent_and_child_columns_use_the_policy(self):
        for table, column in [("canonicaltriples", "class_1"), ("drugs", "class_type"), ("indications_biomarker2", "biomarker2")]:
            col = Base.metadata.tables[f"primary.{table}"].c[column]
            policy = conversion_policy()
            assert convert_value(col.type.enums[0], col, policy) == col.type.enums[0]

    def test_matches_case_insensitively_like_the_compiler_does(self):
        column = Canonicaltriples.__table__.c.class_1
        assert convert_value("Procedure", column, conversion_policy()) == "PROCEDURE"
        assert convert_value("  Regimen  ", column, conversion_policy()) == "REGIMEN"

    def test_unmatched_value_raises_for_the_caller_to_handle(self):
        with pytest.raises(ValueError):
            convert_value("not a real class", Canonicaltriples.__table__.c.class_1, conversion_policy())


@pytest.fixture
def sqlite_session():
    engine = create_default_hemonc_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Canonicaltriples.__table__])
    with so.Session(engine) as s:
        yield s


def _real_csv_path() -> Path:
    """The canonicaltriples extract, via the resolver the loader itself uses."""
    from hemonc_alchemy.naming import resolve_source_csv

    path, _ = resolve_source_csv(_REAL_DATA_DIR, "canonicaltriples")
    assert path is not None, f"no canonicaltriples CSV under {_REAL_DATA_DIR}"
    return path


@pytest.mark.skipif(
    not _REAL_DATA_DIR.is_dir(),
    reason=f"real HemOnc extracts not found at {_REAL_DATA_DIR} (set HEMONC_DATA_DIR)",
)
class TestLoadEntityEndToEnd:
    def test_real_lookup_table_enum_column_casts_correctly(self, sqlite_session):
        # Canonicaltriples has no surrogate id, so this runs cleanly on
        # SQLite (the surrogate-PK autoincrement limitation doesn't apply).
        # Derived from the extract rather than hardcoded: this was `199` and
        # broke on the 2026-08 drop, which brought the table to 228 rows.
        expected = len(pd.read_csv(_real_csv_path()))

        total = load_entity(sqlite_session, Canonicaltriples, _REAL_DATA_DIR)
        sqlite_session.commit()

        assert total == expected
        rows = sqlite_session.execute(sa.select(Canonicaltriples.class_1)).scalars().all()
        assert len(rows) == expected
        assert all(isinstance(v, Canonicaltriples_Class_1Enum) for v in rows)
        # Confirms real, differently-cased source values ("Procedure") did
        # resolve, not just that nothing crashed.
        assert Canonicaltriples_Class_1Enum.PROCEDURE in rows
        assert Canonicaltriples_Class_1Enum.REGIMEN in rows

    def test_unknown_value_is_dropped_not_crashed(self, sqlite_session, tmp_path):
        csv_path = tmp_path / "canonicaltriples.csv"
        csv_path.write_text(
            "class_1,relationship,class_2,date_added,in_ohdsi,internal,used_in\n"
            "Procedure,is_a,thing,2020-01-01,0,0,x\n"
            "BOGUS_CLASS,is_a,other,2020-01-01,0,0,y\n"
            "Regimen,is_a,third,2020-01-01,0,0,z\n"
        )

        total = Canonicaltriples.load_file(sqlite_session, csv_path)
        sqlite_session.commit()

        assert total == 2
        rows = sqlite_session.execute(sa.select(Canonicaltriples.class_1)).scalars().all()
        assert set(rows) == {Canonicaltriples_Class_1Enum.PROCEDURE, Canonicaltriples_Class_1Enum.REGIMEN}


@pytest.mark.skipif(
    not _REAL_DATA_DIR.is_dir(),
    reason=f"real HemOnc extracts not found at {_REAL_DATA_DIR} (set HEMONC_DATA_DIR)",
)
@pytest.mark.postgres
class TestSurrogatePkEnumColumn:
    """`Drugs` is a surrogate-PK ("content") table with a nullable sa.Enum
    column (`class_type`) -- needs real Postgres, same as the rest of the
    surrogate-PK loading story (see test_loading.py).
    """

    def test_nullable_enum_column_casts_correctly_on_real_postgres(self, pg_load_engine):
        Base.metadata.create_all(pg_load_engine, tables=[Drugs.__table__])
        with so.Session(pg_load_engine) as session:
            total = load_entity(session, Drugs, _REAL_DATA_DIR)
            assert total > 0
            rows = session.execute(sa.select(Drugs.class_type)).scalars().all()
            assert all(v is None or isinstance(v, Drugs_Class_typeEnum) for v in rows)
            assert any(v == Drugs_Class_typeEnum.MECHANISTIC for v in rows)
            assert any(v is None for v in rows)


if __name__ == "__main__":
    pytest.main([__file__])
