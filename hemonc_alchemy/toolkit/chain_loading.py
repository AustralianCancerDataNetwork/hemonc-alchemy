"""Load authored chains without relying on inferred grouping or value sorting."""

from dataclasses import dataclass, field

import sqlalchemy as sa

from ..model.base import Base
from ..model.ingestion import conversion_policy, convert_value
from ..multivalue import align_values


@dataclass
class ChainCounts:
    rows_paired: int = 0
    rows_broadcast: int = 0
    rows_opaque_member: int = 0
    rows_unaligned: int = 0
    repeats_kept: int = 0
    conversion_failures: int = 0
    unaligned_parent_ids: list[int] = field(default_factory=list)


@dataclass
class ChainLoadReport:
    """Source-row counters by table/slot; output links have separate totals."""

    chains: dict[str, ChainCounts] = field(default_factory=dict)


def _chain_record(table, chain, values, parent_position, counts):
    parent_id, position = parent_position
    record = {"parent_id": parent_id, "position": position, "aligned": position > 0}
    if chain["slot"] is not None:
        record["slot"] = chain["slot"]
    for name, value in zip(chain["fields"], values):
        if f"{name}_raw" in table.c:
            record[f"{name}_raw"] = value
            try:
                value = convert_value(value, table.c[name], conversion_policy())
            except ValueError:
                counts.conversion_failures += 1
                value = None
        record[name] = value
    return record


def _aligned_records(table, chain, raw, parent_id, counts):
    alignment = align_values(tuple(raw[column] for column in chain["columns"]))
    if alignment.status == "empty":
        return []
    setattr(counts, f"rows_{alignment.status}", getattr(counts, f"rows_{alignment.status}") + 1)
    counts.repeats_kept += alignment.repeats_kept
    if alignment.status == "unaligned":
        counts.unaligned_parent_ids.append(parent_id)
        values = (None,) * len(chain["fields"])
        return [_chain_record(table, chain, values, (parent_id, 0), counts)]
    return [_chain_record(table, chain, values, (parent_id, position), counts)
            for position, values in enumerate(alignment.rows, 1)]


def load_chains(session, entity_cls, frame, parent_lookup, report: ChainLoadReport) -> dict[str, int]:
    """Store raw chains/opaque fields, aligned links and unaligned markers.

    Chains currently belong to surrogate-key source tables. Parent IDs come
    from the same accepted-row lookup used by the compatibility map loader.
    """
    chains = getattr(entity_cls, "chains", ())
    raw_columns = sorted({column for chain in chains for column in chain["columns"]}
                         | set(getattr(entity_cls, "opaque_columns", ())))
    if not raw_columns:
        return {}
    parents = []
    records = {}
    for index, row in frame.iterrows():
        key = parent_lookup.get(index)
        if key is None:
            continue
        raw = {column: row.get(column) for column in raw_columns}
        parents.append({"_chain_parent_id": key[0], **{f"{column}_raw": value for column, value in raw.items()}})
        for chain in chains:
            name = f"{entity_cls.__tablename__}_{chain['name']}"
            label = f"{name}:{chain['slot']}" if chain["slot"] is not None else name
            counts = report.chains.setdefault(label, ChainCounts())
            table = Base.metadata.tables[f"primary.{name}"]
            records.setdefault(name, []).extend(_aligned_records(table, chain, raw, key[0], counts))
    _store_raw_parents(session, entity_cls, raw_columns, parents)
    for name, values in records.items():
        if values:
            session.execute(sa.insert(Base.metadata.tables[f"primary.{name}"]), values)
    return {name: len(values) for name, values in records.items()}


def _store_raw_parents(session, entity_cls, raw_columns, parents):
    if not parents:
        return
    parent = entity_cls.__table__
    statement = sa.update(parent).where(parent.c.id == sa.bindparam("_chain_parent_id"))
    statement = statement.values({f"{column}_raw": sa.bindparam(f"{column}_raw") for column in raw_columns})
    session.connection().execute(statement, parents)
    for instance in session.identity_map.values():
        if isinstance(instance, entity_cls):
            session.expire(instance, [f"{column}_raw" for column in raw_columns])
