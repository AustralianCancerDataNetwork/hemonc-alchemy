from datetime import date, datetime

import pandas as pd
import pytest
import sqlalchemy as sa

from hemonc_alchemy.compiler.schema_model import Registry, TableMeta
from hemonc_alchemy.dates import DateParts, complete_source_date, parse_source_date
from hemonc_alchemy.model.ingestion import conversion_policy, convert_value


def test_parse_source_dates_without_filling_missing_precision():
    assert parse_source_date("2001") == DateParts(2001, None, None, "year")
    assert parse_source_date("2001-05") == DateParts(2001, 5, None, "month")
    assert parse_source_date("2001-5-2") == DateParts(2001, 5, 2, "day")
    assert parse_source_date('<time datetime="2001-05-02">May 2</time>') == DateParts(2001, 5, 2, "day")
    assert parse_source_date("Withdrawn on 2001-05-02") == DateParts(2001, 5, 2, "day")
    assert parse_source_date("Uncertain date") is None
    assert parse_source_date("not reported") is None


def test_complete_source_date_ignores_withdrawal_dates():
    assert complete_source_date("2001-5-2") == date(2001, 5, 2)
    assert complete_source_date("Withdrawn on 2001-05-02") is None
    assert complete_source_date("2001-05") is None


@pytest.mark.parametrize(("source", "expected"), [
    ("2001-5-2", datetime.fromisoformat("2001-05-02")),
    ("<time datetime=\"2001-05-02\">May 2</time>", datetime.fromisoformat("2001-05-02")),
    ("Withdrawn on 2001-05-02", None),
    ("2001", None),
    ("not reported…", None),
    ("Uncertain date", None),
    ("2001-05", None),
])
def test_loader_date_shapes(source, expected):
    column = sa.Column("date", sa.DateTime())
    if expected is None:
        with pytest.raises(ValueError):
            convert_value(source, column, conversion_policy())
    else:
        assert convert_value(source, column, conversion_policy()) == expected


def test_compiler_adds_raw_field_for_mixed_date_shapes():
    meta = TableMeta("studies", "", "content", "prod", [], columns={})
    meta.finalise_from_data(pd.DataFrame({"date": [
        "2001-05-02", "2002-05-02", "2003-05-02", "2004-05-02",
        "2005-05-02", "2006-05-02", "2007-05-02", "2008-05-02",
        "2001", "not reported",
    ]}))

    assert meta.raw_date_columns == ["date"]
    rendered = meta.table_class(Registry({"studies": meta}))
    assert "date_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)" in rendered


def test_compiler_omits_raw_field_for_complete_date_column():
    meta = TableMeta("studies", "", "content", "prod", [], columns={})
    meta.finalise_from_data(pd.DataFrame({"date": ["2001-05-02", "2002-05-02"]}))

    assert meta.raw_date_columns == []
