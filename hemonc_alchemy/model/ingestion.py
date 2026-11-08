"""HemOnc conversion and generated IDs at orm-loader's public file boundary."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import sqlalchemy as sa
import sqlalchemy.orm as so
from orm_loader.conversion import (
    ColumnHandler,
    ConversionPolicy,
    EnumHandler,
    ErrorPolicy,
    Interpretation,
    NullPolicy,
)
from orm_loader.loaders import FileReader

from ..naming import safe_enum_key

logger = logging.getLogger(__name__)


class HemOncEnumHandler(EnumHandler):
    """Store generated member names, accepting source values and normalized names."""

    distinct = True

    def parse(self, cleaned: pa.Array, sa_type: Any) -> Interpretation:
        enum_class = sa_type.enum_class
        if enum_class is None:
            return super().parse(cleaned, sa_type)
        labels = []
        invalid = []
        for value in cleaned.to_pylist():
            label = None
            if value is not None:
                try:
                    label = enum_class(value.strip().lower()).name
                except ValueError:
                    member = enum_class.__members__.get(safe_enum_key(value))
                    label = member.name if member else None
            labels.append(label)
            invalid.append(value is not None and label is None)
        return Interpretation(pa.array(labels, pa.string()), pa.array(invalid, pa.bool_()))


@dataclass(frozen=True)
class NullableHandler(ColumnHandler):
    """Keep legacy nullable-field behavior while using upstream type conversion."""

    handler: ColumnHandler
    table_name: str
    column_name: str

    def validate(self, sa_type: Any) -> None:
        self.handler.validate(sa_type)

    def interpret(self, arr: Any, sa_type: Any, nulls: NullPolicy) -> Interpretation:
        values, invalid = self.handler.interpret(arr, sa_type, nulls)
        count = pc.sum(invalid).as_py() or 0  # ty: ignore[unresolved-attribute]  # Arrow registers compute kernels dynamically.
        if count:
            logger.warning("CAST %s.%s: %d value(s) failed; stored as NULL", self.table_name, self.column_name, count)
        return Interpretation(pc.if_else(invalid, None, values), pa.repeat(False, len(values)))  # ty: ignore[unresolved-attribute]


def conversion_policy(table: sa.Table | None = None) -> ConversionPolicy:
    """Explicit policy shared by parent loading and exploded child conversion.

    Invalid required fields reject their rows with an upstream LoadReport.
    Invalid nullable fields are logged and stored as NULL. A caller-provided
    policy is used unchanged instead of installing these compatibility rules.
    """
    policy = ConversionPolicy(
        enum=HemOncEnumHandler(),
        errors=ErrorPolicy(on_error="reject_row"),
        nulls=NullPolicy(text_markers=frozenset({"NULL", "None", "N/A", "NaN", "nan", "null", "NA", "n/a"})),
    )
    if table is None:
        return policy
    return replace(policy, columns={
        (table.name, column.name): NullableHandler(
            policy.for_column(column.type, table.name, column.name), table.name, column.name
        )
        for column in table.c if column.nullable
    })


def interpret_values(values: Any, column: sa.Column, policy: ConversionPolicy) -> Interpretation:
    """Interpret a source/database column with the file policy, retaining failures."""
    values = [value.name if isinstance(value, Enum) else value for value in values]
    table_name = column.table.name if column.table is not None else None
    handler = policy.for_column(column.type, table_name, column.name)
    return handler.interpret(pa.array(values), column.type, policy.nulls)


def convert_value(value: Any, column: sa.Column, policy: ConversionPolicy) -> Any:
    """Convert a child/identity scalar using the same handlers as file ingestion."""
    values, invalid = interpret_values([value], column, policy)
    if invalid[0].as_py():
        raise ValueError(f"{value!r} is invalid for {column}")
    return values[0].as_py()


class GeneratedIdReader(FileReader):
    """Add database-generated IDs to an ID-less snapshot of an empty target.

    PostgreSQL/DuckDB reserve IDs from the reflected native column default,
    keeping subsequent ORM inserts in sync. SQLite uses the existing public
    allocator because its BIGINT columns have no native auto-increment.
    Loading a snapshot onto existing parents is rejected before staging.
    """

    def __init__(self, reader: FileReader, model: Any, session: so.Session) -> None:
        super().__init__(reader.path, reader.model_columns)
        self.reader = reader
        self.columns = [*reader.columns, "id"]
        self.file_columns = reader.file_columns
        self.empty = reader.empty
        self.skipped = reader.skipped
        self.session = session
        self.engine = session.get_bind(mapper=model).engine
        table = model.__table__
        if session.scalar(sa.select(sa.literal(1)).select_from(table).limit(1)) is not None:
            raise ValueError(
                f"{table.name}: ID-less snapshots require an empty target; "
                "use a fresh database or supply stable IDs explicitly"
            )
        bind = session.connection(bind_arguments={"mapper": model})
        self.default = None
        self.allocator = None
        if bind.dialect.name == "sqlite":
            self.allocator = model.allocator(session)
        else:
            mapping = bind.get_execution_options().get("schema_translate_map", {})
            schema = mapping.get(table.schema, table.schema)
            columns = sa.inspect(bind).get_columns(table.name, schema=schema)
            self.default = next(c["default"] for c in columns if c["name"] == "id")
            if not self.default:
                raise ValueError(f"{table.name}.id has no database-generated default")

    def batches(self) -> Iterator[pa.RecordBatch]:
        for batch in self.reader.batches():
            if self.allocator is not None:
                ids = [self.allocator.next() for _ in range(batch.num_rows)]
            else:
                assert self.default is not None
                rows = sa.func.generate_series(1, batch.num_rows).alias("source_rows")
                # PostgreSQL consumes later batches while COPY is active on the
                # loader connection. Reserve native sequence values elsewhere.
                statement = sa.select(sa.literal_column(self.default)).select_from(rows)
                if self.engine.dialect.name == "postgresql":
                    with self.engine.connect() as connection:
                        ids = connection.scalars(statement).all()
                else:
                    ids = self.session.scalars(statement).all()
            yield batch.append_column("id", pa.array(ids, pa.int64()))
