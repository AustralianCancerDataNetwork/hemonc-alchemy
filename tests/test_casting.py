"""Malformed nullable values become NULL; malformed required values reject rows."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
import sqlalchemy.orm as so
from orm_loader.loaders import LoadReport

from hemonc_alchemy.config import create_default_hemonc_engine
from hemonc_alchemy.model.base import Base
from hemonc_alchemy.model.entities import Regimens, Units
from hemonc_alchemy.model.ingestion import conversion_policy, convert_value

pytestmark = pytest.mark.skipif(
    len(Base.metadata.tables) == 0,
    reason="model/entities.py has no generated classes yet -- run `hemonc-alchemy regen` first",
)


class TestConversionPolicy:
    def test_bad_value_is_rejected_not_defaulted(self):
        with pytest.raises(ValueError):
            convert_value("not-a-number", Units.__table__.c.concept_code, conversion_policy())

    def test_good_value_casts_cleanly(self):
        assert convert_value("134444", Units.__table__.c.concept_code, conversion_policy()) == 134444


@pytest.fixture
def session():
    engine = create_default_hemonc_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Units.__table__, Regimens.__table__])
    with so.Session(engine) as s:
        yield s


class TestLoadCsvEndToEnd:
    """`Regimens.first_studied` (nullable Integer) is the end-to-end target.

    This used `Units.concept_code` until the 2026-08 drop made every Units
    column non-nullable -- a bad value there is now a rejected row rather
    than a NULL, which tests a different property. Both are checked below.
    """

    # `id` is the generated surrogate PK for a content table; BigInteger
    # doesn't autoincrement on SQLite, so the CSV supplies it.
    _REQUIRED = (
        "id,regimen_cui,regimen_name,regimen_type,highest_evidence,sact,contains_rt,"
        "studies,variantcount,variantcountdate,date_added"
    )
    # sa.Enum columns store the member *name*; this suite deliberately does
    # not register_enum_casts() -- value-to-member casting is , in
    # test_enum_casting.py. The target column here is a plain Integer.
    _FIXED = "NULL_REGIMEN,PHASE_3_RCT,FALSE,FALSE,0,0,2020-01-01,2020-01-01"

    def test_bad_nullable_number_becomes_null_not_sentinel(self, session, tmp_path):
        csv_path = tmp_path / "regimens.csv"
        csv_path.write_text(
            f"{self._REQUIRED},first_studied\n"
            f"1,1,good,{self._FIXED},1998\n"
            f"2,2,bad,{self._FIXED},not-a-number\n"
        )

        total = Regimens.load_file(session, csv_path)
        assert total == 2

        rows = {
            row.regimen_name: row.first_studied
            for row in session.execute(sa.select(Regimens)).scalars()
        }
        assert rows["good"] == 1998
        assert rows["bad"] is None
        assert -1 not in rows.values()
        assert -1.0 not in rows.values()

    def test_bad_value_in_a_non_nullable_column_drops_the_row(self, session, tmp_path):
        """The complementary guarantee: where NULL isn't allowed, the loader
        refuses the row rather than inventing a sentinel to satisfy it.
        """
        csv_path = tmp_path / "units.csv"
        csv_path.write_text(
            "unit,unit_type,concept_code,date_added,fixed,parameterbased,timebased\n"
            "mg,UNITS_PER_VOLUME,134444,2020-01-01,TRUE,FALSE,FALSE\n"
            "bad_unit,UNITS_PER_VOLUME,not-a-number,2020-01-01,TRUE,FALSE,FALSE\n"
        )

        report = LoadReport()
        total = Units.load_file(session, csv_path, report=report)
        assert report.rows_rejected == 1
        assert report.accounted
        assert report.rejects_path.is_file()
        assert total == 1

        rows = {row.unit: row.concept_code for row in session.execute(sa.select(Units)).scalars()}
        assert rows == {"mg": 134444}
        assert "bad_unit" not in rows


if __name__ == "__main__":
    pytest.main([__file__])
