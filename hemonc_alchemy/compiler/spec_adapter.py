"""
Builds the "spec" orm_loader's validators check the generated model
against.

orm_loader already checks whether a mapped SQLAlchemy model
matches its own declared shape (`ModelRegistry`, plus validators for
column presence, nullability, primary keys, and foreign keys)

This module translates that Registry into the `TableSpec`/`FieldSpec`
objects orm_loader's validators can use, so the same validation
logic can run without reimplementation.

Notes:
- a surrogate-key table's real primary key is the generated `id` column, not
  the natural key in `pk_columns` (which is only a UniqueConstraint when it
  is complete and unique)
- HemOnc's cross-table relationships are all viewonly and never declared
  as a real SQLAlchemy ForeignKey (see model/relationships.py), so
  `is_foreign_key` is always False here.
"""

from __future__ import annotations

from orm_loader.registry import (
    FieldSpec,
    ModelRegistry,
    TableSpec,
    ValidationRunner,
    always_on_validators,
)
from orm_loader.registry.validation_report import ValidationReport

from .schema_model import Registry as SchemaRegistry


def hemonc_table_specs(registry: SchemaRegistry) -> dict[str, TableSpec]:
    """
    Build one TableSpec per table that produced an entity class
    """
    return {
        name: TableSpec(
            table_name=name,
            schema="primary",
            is_required=meta.maturity == "prod",
            description=meta.description,
        )
        for name, meta in registry.tables.items()
        if meta.columns
    }


def hemonc_field_specs(registry: SchemaRegistry) -> dict[str, dict[str, FieldSpec]]:
    """
    Build one FieldSpec per column that gets rendered onto the generated class
     
    Denormalised/derived columns are skipped since they don't become scalar 
    columns at all, and a surrogate-PK table's real primary key is the 
    generated `id` column rather than its natural key.
    """
    out: dict[str, dict[str, FieldSpec]] = {}

    for table_name, meta in registry.tables.items():
        if not meta.columns:
            continue

        uses_surrogate = meta.uses_surrogate_pk
        effective_pk = {"id"} if uses_surrogate else set(meta.pk_columns)

        fields: dict[str, FieldSpec] = {}
        for col_name, col in meta.columns.items():
            if col_name in meta.denormalised_columns or col_name in meta.derived_columns:
                continue
            fields[col_name] = FieldSpec(
                table_name=table_name,
                field_name=col_name,
                data_type=col.type,
                is_required=not col.nullable,
                is_primary_key=col_name in effective_pk,
                is_foreign_key=False,
                fk_table=None,
                fk_field=None,
            )

        if uses_surrogate:
            fields["id"] = FieldSpec(
                table_name=table_name,
                field_name="id",
                data_type="BigInteger",
                is_required=True,
                is_primary_key=True,
                is_foreign_key=False,
                fk_table=None,
                fk_field=None,
            )

        out[table_name] = fields

    return out


def build_model_registry(
    schema_registry: SchemaRegistry,
    models: list[type],
    *,
    model_version: str,
) -> ModelRegistry:
    """
    Build an orm_loader ModelRegistry from a schema Registry and a list
    of already-mapped ORM classes.
    """
    registry = ModelRegistry(model_version=model_version, model_name="HemOnc")

    # orm_loader's public API only reads specs from CSV files. Setting
    # these directly fills a gap orm_loader's own docstring already flags
    # as unsupported ("TODO: support generalised specification formats via
    # LinkML or similar").
    registry._table_specs = hemonc_table_specs(schema_registry)
    registry._field_specs = hemonc_field_specs(schema_registry)

    registry.register_models(models)
    return registry


def validate_with_orm_loader(
    schema_registry: SchemaRegistry,
    models: list[type],
    *,
    model_version: str = "unversioned",
) -> ValidationReport:
    """
    Run orm_loader's validators against the generated model.
    """
    registry = build_model_registry(schema_registry, models, model_version=model_version)
    runner = ValidationRunner(validators=always_on_validators())
    return runner.run(registry)
