"""Private PostgreSQL vocabulary slice for mapping and hierarchy checks."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import sqlalchemy as sa

from hemonc_alchemy import get_hemonc_context
from hemonc_alchemy.integrations.omop import load_omop_binding, schema_aware_bind

from .parity import canonical, table_snapshot


def export_snapshot(path: Path, schema: str) -> dict:
    binding = load_omop_binding()
    if binding is None:
        raise RuntimeError("The omop extra is required for vocabulary validation")
    _, database = get_hemonc_context()
    engine = schema_aware_bind(database.create_engine(register_claims=False), {"vocab": schema})
    concept = binding.concept.__table__
    relationship = binding.concept_relationship.__table__
    hemonc_ids = sa.select(concept.c.concept_id).where(concept.c.vocabulary_id == "HemOnc")
    links = sa.select(relationship).where(
        relationship.c.concept_id_1.in_(hemonc_ids),
        relationship.c.relationship_id.in_(["Is a", "Maps to"]),
    ).subquery("validation_links")
    included = hemonc_ids.union(sa.select(links.c.concept_id_2))
    statements = {
        "concept": sa.select(concept).where(concept.c.concept_id.in_(included)).order_by(concept.c.concept_id),
        "concept_relationship": sa.select(links).order_by(links.c.concept_id_1, links.c.concept_id_2, links.c.relationship_id),
        "vocabulary": sa.select(binding.vocabulary.__table__).order_by(binding.vocabulary.vocabulary_id),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=False)
    counts = Counter()
    try:
        with (
            engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection,
            gzip.open(path, "wt", encoding="utf-8") as stream,
        ):
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            for name, statement in statements.items():
                for row in connection.execute(statement).mappings().yield_per(10_000):
                    stream.write(json.dumps({"table": name, "row": canonical(dict(row))}, sort_keys=True) + "\n")
                    counts[name] += 1
    finally:
        engine.dispose()
    if not counts["concept"] or not counts["concept_relationship"]:
        raise ValueError("The source vocabulary has no HemOnc concepts or mapping/hierarchy relationships")
    return dict(counts)


def _typed_record(row: dict, table: sa.Table) -> dict:
    result = dict(row)
    for column in table.c:
        value = result[column.name]
        if value is not None and isinstance(column.type, sa.DateTime):
            result[column.name] = datetime.fromisoformat(value)
        elif value is not None and isinstance(column.type, sa.Date):
            result[column.name] = date.fromisoformat(value)
    return result


def load_snapshot(engine: sa.Engine, path: Path) -> tuple[sa.Engine, dict]:
    binding = load_omop_binding()
    if binding is None:
        raise RuntimeError("The omop extra is required for vocabulary validation")
    # PostgreSQL's primary schema is an automatically isolated test schema;
    # use it for the vocabulary too so cleanup cannot touch an existing one.
    schema = engine.get_execution_options()["schema_translate_map"]["primary"]
    routed = schema_aware_bind(engine, {"vocab": schema})
    metadata = sa.MetaData()
    for model in [binding.concept, binding.concept_relationship, binding.vocabulary]:
        sa.Table(model.__tablename__, metadata, *[
            sa.Column(c.name, c.type.copy(), primary_key=c.primary_key, nullable=c.nullable, autoincrement=False)
            for c in model.__table__.c
        ], schema="vocab")
    metadata.create_all(routed)
    with routed.begin() as connection, gzip.open(path, "rt", encoding="utf-8") as stream:
        batches: dict[str, list] = {name: [] for name in ["concept", "concept_relationship", "vocabulary"]}
        for line in stream:
            item = json.loads(line)
            name = item["table"]
            table = metadata.tables[f"vocab.{name}"]
            batches[name].append(_typed_record(item["row"], table))
            if len(batches[name]) == 10_000:
                connection.execute(table.insert(), batches[name])
                batches[name].clear()
        for name, batch in batches.items():
            if batch:
                connection.execute(metadata.tables[f"vocab.{name}"].insert(), batch)
    with path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    with routed.connect() as connection:
        tables = {table.name: table_snapshot(connection, table, {}) for table in metadata.tables.values()}
    return routed, {"snapshot_sha256": checksum, "tables": tables, "selection": "HemOnc concepts, outgoing Is a/Maps to targets, vocabulary metadata"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--schema", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(export_snapshot(args.output, args.schema), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
