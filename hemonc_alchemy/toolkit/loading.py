"""Loading a HemOnc CSV extract into the database.

`load_all` is usually what you want: it loads an entity's own rows and then
its child tables, in that order.

Two things about the extract need handling before the rows go in. Filenames
don't always match the table they hold (`canonical_triples.csv` for the
`canonicaltriples` table), and neither do column headers (`parameter-based`
for `parameterbased`, `class` for `class_field`). Both are reconciled here so
the source files can stay exactly as HemOnc ships them.

Columns holding several pipe-delimited values in one cell live in their own
child tables rather than as a single string, and `load_denormalised` fills
those. It has to run after the parent rows exist, because a child row is
matched back to its natural key or, for sparse-key tables, its complete
scalar source-row identity.
"""

from __future__ import annotations

import csv
import logging
import tempfile
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import date, datetime
from enum import Enum
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import pandas as pd
import sqlalchemy as sa
import sqlalchemy.orm as so

from ..model.base import register_enum_casts
from ..naming import resolve_source_csv, safe_identifier

if TYPE_CHECKING:
    from orm_loader.loaders.data_classes import TableCastingStats

logger = logging.getLogger(__name__)


def _record_cast_failure(value: Any, *, column: str, stats: TableCastingStats) -> None:
    """`on_error` callback for `perform_cast`, bound per-column via `partial`."""
    stats.record(column=column, value=value)


class _MappedEntity(Protocol):
    """Structural shape shared by every generated `EntityBase` subclass,
    including the small per-column map/child tables.
    """

    __tablename__: str
    __name__: str
    __table__: sa.Table

    @classmethod
    def load_csv(cls, session: so.Session, path: Path, **kwargs: Any) -> int: ...


class _GeneratedEntity(_MappedEntity, Protocol):
    """A top-level generated entity: `_MappedEntity` plus the compiler's
    per-table metadata attributes.
    """

    id: Any
    natural_key_columns: list[str]
    denormalised_columns: list[str]
    derived_columns: list[str]


def _header_renames(path: Path) -> dict[str, str]:
    """Source headers that don't already match their generated column name.

    Six extracts need this, `sigs` and `indications` among them: a header may
    contain dots or hyphens (`seq.rel.when`, `parameter-based`) or be a Python
    keyword (`class`, `with`), none of which survive into a column name.

    Case-only differences are excluded, since those already match.
    """
    with path.open(newline="", encoding="utf-8-sig") as handle:
        header = next(csv.reader(handle), [])

    renames: dict[str, str] = {}
    for raw in header:
        normalised = safe_identifier(raw).lower()
        if raw.strip().lower() != normalised:
            renames[raw] = normalised
    return renames


@contextmanager
def _resolved_csv_path(data_dir: Path, table_name: str) -> Generator[Path, None, None]:
    """Yield a CSV whose filename and headers both match the model.

    The real file is used untouched when it already matches. Otherwise it is
    presented through a temporary directory for the duration of the `with`
    block, as a symlink if only the name differs or a rewritten copy if the
    headers do too. The original is never modified, and rewriting streams row
    by row so extract size doesn't matter.
    """
    real_path, ambiguous = resolve_source_csv(data_dir, table_name)
    if ambiguous:
        raise ValueError(f"Ambiguous CSV matches for table '{table_name}': {', '.join(ambiguous)}")
    if real_path is None:
        raise FileNotFoundError(f"No CSV found for table '{table_name}' in {data_dir}")

    renames = _header_renames(real_path)

    if real_path.stem == table_name and not renames:
        yield real_path
        return

    with tempfile.TemporaryDirectory(prefix="hemonc_alchemy_load_") as tmp_dir:
        staged = Path(tmp_dir) / f"{table_name}.csv"

        if not renames:
            staged.symlink_to(real_path.resolve())
            yield staged
            return

        logger.debug(
            "%s: normalising %d source header(s) for load: %s",
            table_name, len(renames), ", ".join(f"{k!r}->{v!r}" for k, v in renames.items()),
        )
        with (
            real_path.open(newline="", encoding="utf-8-sig") as source,
            staged.open("w", newline="", encoding="utf-8") as target,
        ):
            reader = csv.reader(source)
            writer = csv.writer(target)
            header = next(reader, [])
            writer.writerow([renames.get(col, col.strip()) for col in header])
            writer.writerows(reader)

        yield staged


def load_entity(
    session: so.Session,
    entity_cls: type[_GeneratedEntity],
    data_dir: Path,
    **load_csv_kwargs,
) -> int:
    """Load one entity's own rows, without its child tables.

    Extra keyword arguments (`merge_strategy`, `chunksize`, `dedupe`, ...) are
    passed through to the underlying loader.
    """
    register_enum_casts()
    with _resolved_csv_path(data_dir, entity_cls.__tablename__) as path:
        return entity_cls.load_csv(session, path, **load_csv_kwargs)


def load_all(
    session: so.Session,
    entity_cls: type[_GeneratedEntity],
    data_dir: Path,
    **load_csv_kwargs,
) -> dict[str, int]:
    """Load one entity completely: its own rows, then its child tables.

    Returns a count per table loaded. Use `load_entity` and
    `load_denormalised` separately if you need every entity's own rows in
    place before any child tables are filled.
    """
    primary_total = load_entity(session, entity_cls, data_dir, **load_csv_kwargs)
    session.flush()
    denorm_totals = load_denormalised(session, entity_cls, data_dir)
    return {entity_cls.__tablename__: primary_total, **denorm_totals}


def _natural_key_columns(entity_cls: type[_GeneratedEntity]) -> list[str]:
    """The real declared business/natural key for an entity.

    Not the same thing as `entity_cls.natural_key_columns` for a
    surrogate-PK table -- there, a generated `UniqueConstraint` may carry
    the natural key, while `natural_key_columns` remains the source-facing
    key. This applies to both content and lookup tables, including
    sparse-key tables whose natural key cannot be constrained as a database
    key.
    """
    table = entity_cls.__table__
    preferred_name = f"uq_{table.name}_natural_key"
    uniques = [c for c in table.constraints if isinstance(c, sa.UniqueConstraint)]
    preferred = next((u for u in uniques if u.name == preferred_name), None)
    if preferred is not None:
        return [col.name for col in preferred.columns]
    return list(entity_cls.natural_key_columns)


def _map_class_for_column(entity_cls: type[_GeneratedEntity], column: str) -> type[_MappedEntity]:
    """Find the generated map (child) table class for one denormalised
    column via the entity's own declared `{column}_items` relationship,
    rather than re-deriving the compiler's `{Parent}_{Column}Map` naming
    convention independently -- one source of truth for the mapping.
    """
    rel_name = f"{column}_items"
    # Explicit raiseerr=True picks sqlalchemy's non-Optional inspect() overload.
    relationship_prop = sa.inspect(entity_cls, raiseerr=True).relationships.get(rel_name)
    if relationship_prop is None:
        raise LookupError(
            f"{entity_cls.__name__} has no relationship '{rel_name}' for denormalised column '{column}'"
        )
    return relationship_prop.mapper.class_


def _read_source_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    return df.rename(columns=lambda c: safe_identifier(c).lower())


def _identity_value(
    value: Any, column: sa.Column, *, source: bool, on_error: Callable[[Any], None]
) -> object:
    """Return a comparable representation of one parent identity value.

    Source CSV values and values read back from SQLAlchemy have different
    Python representations (for example ``"Regimen"`` versus an enum
    member, or ``"0"`` versus ``False``).  Parent matching must compare the
    values after the same casts used by the main loader.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NaT:
        return None

    column_type = column.type
    if isinstance(column_type, sa.Enum):
        if isinstance(value, Enum):
            return ("enum", value.name)
        from orm_loader.loaders.data.converters import perform_cast

        cast = perform_cast(
            value,
            column_type,
            on_error=on_error,
            table_name=column.table.name,
            column_name=column.name,
        )
        return None if cast is None else ("enum", str(cast))

    try:
        python_type = column_type.python_type
    except NotImplementedError:
        python_type = str

    if python_type is bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"true", "t", "yes", "y", "1"}
    if python_type is int:
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            on_error(value)
            return None
    if python_type is float:
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            on_error(value)
            return None
    if python_type in {date, datetime}:
        try:
            return pd.Timestamp(value).isoformat()
        except (TypeError, ValueError, OverflowError):
            # Match orm-loader's handling of placeholders such as
            # "Uncertain date": an invalid value is loaded as NULL when the
            # generated column is nullable, so it must not abort parent-row
            # matching here.
            on_error(value)
            return None
    return str(value).strip()


def _surrogate_parent_lookup(
    session: so.Session,
    entity_cls: type[_GeneratedEntity],
    df: pd.DataFrame,
    denormalised_columns: set[str],
    stats,
) -> dict[object, int | None]:
    """Map a source-row identity to its generated parent id.

    A nullable natural key cannot identify a denormalised row.  For those
    tables, use every scalar source column as the row identity. The returned
    mapping is keyed by source dataframe index. ``None`` means the identity
    was missing or ambiguous in the database and is deliberately not attached
    to an arbitrary parent.
    """
    table = entity_cls.__table__
    identity_columns = [
        column
        for column in table.columns
        if column.name != "id"
        and column.name not in denormalised_columns
        and column.name not in set(getattr(entity_cls, "derived_columns", []))
        and column.name in df.columns
    ]
    if not identity_columns:
        raise RuntimeError(
            f"{entity_cls.__name__} has a surrogate id but no scalar source columns "
            "available to match denormalised rows."
        )

    def failed(value):
        stats.record(column="<row identity>", value=value)

    parent_rows = session.execute(
        sa.select(entity_cls.id, *(getattr(entity_cls, column.name) for column in identity_columns))
    ).all()
    lookup: dict[tuple[object, ...], int | None] = {}
    for row in parent_rows:
        key = tuple(
            _identity_value(value, column, source=False, on_error=failed)
            for value, column in zip(row[1:], identity_columns)
        )
        if key in lookup:
            lookup[key] = None
        else:
            lookup[key] = row[0]

    source_lookup: dict[object, int | None] = {}
    for index, source_row in df.iterrows():
        key = tuple(
            _identity_value(source_row[column.name], column, source=True, on_error=failed)
            for column in identity_columns
        )
        source_lookup[index] = lookup.get(key)
    return source_lookup


def load_denormalised(
    session: so.Session,
    entity_cls: type[_GeneratedEntity],
    data_dir: Path,
) -> dict[str, int]:
    """Fill the child tables holding an entity's pipe-delimited columns.

    Must run after `load_entity` for the same entity. Returns a count per
    column loaded.

    Values are cast the same way `load_csv` casts them, so a bad value is
    dropped with a warning rather than replaced by a sentinel. This includes
    enum-valued natural-key columns copied into a map table: those key fields
    need the same normalisation as the denormalised value itself.
    """
    from orm_loader.loaders.data.converters import perform_cast
    from orm_loader.loaders.data_classes import TableCastingStats

    register_enum_casts()

    if not entity_cls.denormalised_columns:
        return {}

    with _resolved_csv_path(data_dir, entity_cls.__tablename__) as path:
        df = _read_source_csv(path)

    key_cols = _natural_key_columns(entity_cls)
    is_surrogate = "id" in entity_cls.__table__.c

    parent_lookup: dict[object, int | None] = {}
    if is_surrogate:
        identity_stats = TableCastingStats(table_name=entity_cls.__tablename__)
        parent_lookup = _surrogate_parent_lookup(
            session,
            entity_cls,
            df,
            set(entity_cls.denormalised_columns),
            identity_stats,
        )
        if identity_stats.has_failures():
            for col_name, col_stats in identity_stats.columns.items():
                logger.warning(
                    "CAST %s.%s: %d row(s) failed. Examples: %s",
                    entity_cls.__tablename__,
                    col_name,
                    col_stats.count,
                    col_stats.examples,
                )
    elif not key_cols or not all(column in df.columns for column in key_cols):
        raise RuntimeError(
            f"{entity_cls.__name__} has denormalised columns but no complete natural key "
            "available in its source CSV."
        )

    results: dict[str, int] = {}
    for column in entity_cls.denormalised_columns:
        if column not in df.columns:
            continue

        map_cls = _map_class_for_column(entity_cls, column)
        value_type = map_cls.__table__.c[column].type
        stats = TableCastingStats(table_name=map_cls.__tablename__)

        seen: set[tuple] = set()
        records: list[dict] = []
        for index, row in df.iterrows():
            raw = row.get(column)
            if raw is None or (isinstance(raw, float) and pd.isna(raw)):
                continue

            if is_surrogate:
                parent_id = parent_lookup.get(index)
                if parent_id is None:
                    continue
                fixed_fields = {"parent_id": parent_id}
            else:
                fixed_fields = {}
                for key_col in key_cols:
                    key_value = row[key_col]
                    key_type = map_cls.__table__.c[key_col].type
                    if isinstance(key_type, sa.Enum):
                        key_value = perform_cast(
                            key_value,
                            key_type,
                            on_error=partial(_record_cast_failure, column=key_col, stats=stats),
                            table_name=map_cls.__tablename__,
                            column_name=key_col,
                        )
                        if key_value is None:
                            break
                    fixed_fields[key_col] = key_value

                if len(fixed_fields) != len(key_cols):
                    continue

            for token in str(raw).split("|"):
                token = token.strip()
                if not token:
                    continue

                value = perform_cast(
                    token,
                    value_type,
                    on_error=partial(_record_cast_failure, column=column, stats=stats),
                    table_name=map_cls.__tablename__,
                    column_name=column,
                )
                if value is None:
                    continue

                dedupe_key = (*fixed_fields.values(), value)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)

                records.append({**fixed_fields, column: value})

        # A single bulk insert per column rather than one `session.merge()`
        # per exploded value -- `merge()` is a SELECT-then-insert/update
        # round trip *per row*, and denormalised columns routinely explode
        # into tens of thousands of values across a real HemOnc table.
        # Deduping into `records` above already makes a plain insert safe;
        # nothing here needs merge's update-if-exists behaviour.
        if records:
            session.execute(sa.insert(map_cls.__table__), records)

        if stats.has_failures():
            for col_name, col_stats in stats.columns.items():
                logger.warning(
                    "CAST %s.%s: %d row(s) failed. Examples: %s",
                    map_cls.__tablename__,
                    col_name,
                    col_stats.count,
                    col_stats.examples,
                )

        results[column] = len(records)

    session.flush()
    return results
