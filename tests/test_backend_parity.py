"""Evidence must detect semantic changes even when row counts agree."""

from copy import deepcopy
from datetime import date
from enum import Enum

import sqlalchemy as sa

from hemonc_alchemy.config import create_default_hemonc_engine
from validation.parity import canonical, differences, table_snapshot


def stored_snapshot(parent_id, *, wrong_parent=False, child_count=1):
    engine = create_default_hemonc_engine("sqlite://")
    metadata = sa.MetaData(schema="primary")
    parent = sa.Table("parent", metadata, sa.Column("id", sa.Integer, primary_key=True), sa.Column("label", sa.String))
    child = sa.Table("child", metadata, sa.Column("parent_id", sa.ForeignKey(parent.c.id)), sa.Column("value", sa.String))
    metadata.create_all(engine)
    try:
        with engine.begin() as connection:
            connection.execute(parent.insert(), [{"id": parent_id, "label": "A"}, {"id": parent_id + 1, "label": "B"}])
            connection.execute(child.insert(), [{"parent_id": parent_id + int(wrong_parent), "value": "token"}] * child_count)
            ids = {}
            return {table.name: table_snapshot(connection, table, ids) for table in metadata.sorted_tables}
    finally:
        engine.dispose()


def test_generated_ids_do_not_change_semantic_snapshots():
    assert stored_snapshot(1) == stored_snapshot(879)


def test_equal_counts_with_wrong_child_attachment_are_detected():
    correct = stored_snapshot(1)
    wrong = stored_snapshot(1, wrong_parent=True)
    assert correct["child"]["rows"] == wrong["child"]["rows"]
    assert correct["child"]["sha256"] != wrong["child"]["sha256"]


def test_multiset_fingerprint_retains_duplicate_rows():
    assert stored_snapshot(1)["child"]["sha256"] != stored_snapshot(1, child_count=2)["child"]["sha256"]


def test_canonical_values_preserve_null_float_enum_and_date_meaning():
    class Labels(Enum):
        A = "source value"

    assert canonical([None, 1, True, 1.0, Labels.A, date(2026, 11, 7)]) == [
        None, 1, True, {"float": "0x1.0000000000000p+0"}, "A", "2026-11-07",
    ]


def test_comparison_ignores_timings_but_rejects_missing_work_or_orphans():
    report = {"source": "same", "loads": {}, "tables": stored_snapshot(1), "queries": {},
              "vocabulary": None, "status": "complete", "errors": [], "timings_seconds": {"total": 1}}
    other = deepcopy(report)
    other["timings_seconds"]["total"] = 99
    assert differences(report, other) == []
    other["tables"]["child"]["orphan_rows"] = 1
    assert "right.orphan_rows" in differences(report, other)
    other["status"] = "running"
    assert "right.incomplete" in differences(report, other)
