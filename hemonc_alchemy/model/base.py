"""
Base class for all hemonc-alchemy entity tables.

Mirrors ``omop_alchemy.cdm.base.CDMTableBase``

This class does NOT provide pipe-delimited denormalisation / explode handling 
(a HemOnc sig/regimen row can expand into N child rows), and natural-key-based 
FK resolution at load time for surrogate-PK tables 

This is handled in `toolkit/loading.py` (`load_denormalised`).
"""

from __future__ import annotations

import warnings
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import sqlalchemy as sa
import sqlalchemy.orm as so
from orm_loader.loaders import open_reader
from orm_loader.tables import FileLoadableTableInterface, SerialisableTableInterface

from .ingestion import GeneratedIdReader, conversion_policy


class Base(so.DeclarativeBase):
    pass


def hemonc_enum(enum_class: type[Enum]) -> sa.Enum:
    """Keep native PostgreSQL enums and enforce labels portably on DuckDB.

    The DuckDB dialect does not translate schema tags in named enum column
    references. Its VARCHAR variant retains database label checks without
    placing types in the wrong physical schema.
    """
    # Staging tables may reuse the type object, so attaching one must not
    # change the schema of the original table's native enum.
    return sa.Enum(enum_class, schema="primary").with_variant(
        sa.Enum(enum_class, native_enum=False, create_constraint=True), "duckdb"
    )


class EntityBase(Base, FileLoadableTableInterface, SerialisableTableInterface):
    """Generated HemOnc entity with explicit conversion and snapshot ID support."""

    __abstract__ = True

    @classmethod
    def load_file(cls, session: so.Session, path: Path, **kwargs: Any) -> int:
        policy = kwargs.get("policy") or conversion_policy(cast(sa.Table, cls.__table__))
        kwargs["policy"] = policy
        reader = kwargs.get("reader")
        if reader is None:
            reader = open_reader(
                path, cls.model_columns(),
                chunksize=kwargs.pop("chunksize", None),
                quote_mode=kwargs.pop("quote_mode", None),
                skip_malformed=policy.errors.on_error == "reject_row",
            )
        column = cls.__table__.c.get("id")
        if column is not None and column.primary_key and column.autoincrement is True and "id" not in reader.columns:
            reader = GeneratedIdReader(reader, cls, session)
        kwargs["reader"] = reader
        # SQLAlchemy's generated class descriptors are broader than upstream's protocol.
        return super().load_file(session, path, **kwargs)  # ty: ignore[invalid-argument-type]

    @classmethod
    def load_csv(cls, session: so.Session, path: Path, **kwargs: Any) -> int:
        """Compatibility alias; use load_file for new code."""
        warnings.warn("load_csv() is deprecated; use load_file()", DeprecationWarning, stacklevel=2)
        return cls.load_file(session, path, **kwargs)


def register_enum_casts() -> None:
    """Compatibility hook: HemOnc file loads now install a local conversion policy."""
    warnings.warn(
        "register_enum_casts() is unnecessary; file loads use an explicit HemOnc policy",
        DeprecationWarning, stacklevel=2,
    )


def is_concrete_entity(obj: object) -> bool:
    """
    True for a real, mapped entity class (not `Base` itself, and not an
    abstract class like `EntityBase`)
    
    This is required because SQLAlchemy only ever checks a class's 
    own `__dict__` when deciding whether to map it
    """
    return (
        isinstance(obj, type)
        and issubclass(obj, Base)
        and obj is not Base
        and not obj.__dict__.get("__abstract__", False)
    )


def concrete_entities(module: ModuleType) -> list[type]:
    """All concrete, mapped entity classes defined in a generated model module."""
    return [obj for obj in vars(module).values() if is_concrete_entity(obj)]
