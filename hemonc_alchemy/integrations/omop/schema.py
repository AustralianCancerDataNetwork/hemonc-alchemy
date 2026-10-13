"""Schema routing for logical tags on OMOP Alchemy models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy import event

_SCHEMA_TRANSLATE_MAP = "schema_translate_map"
_DATABASE_CONFIG_NAME = "oa_configurator_database_config_name"


@dataclass(frozen=True)
class OmopAvailability:
    available: bool
    reason: str | None = None


class OmopSchemaConfigurationError(RuntimeError):
    """An oa-configurator database mapping could not be resolved."""


class OmopUnavailableError(RuntimeError):
    """An OMOP query was requested but its vocabulary could not be reached."""


def _configured_map(bind: Any) -> dict[str, str | None] | None:
    options = bind.get_execution_options()
    database_name = options.get(_DATABASE_CONFIG_NAME)
    try:
        from oa_configurator import Resolver
        from oa_configurator.domains.resources.sql import connection_key

        resolver = Resolver.from_active_config()
    except ImportError:
        return None
    except Exception as exc:
        if database_name is not None:
            raise OmopSchemaConfigurationError(
                f"Could not load oa-configurator database {database_name!r}: {exc}"
            ) from exc
        return None

    if database_name is not None:
        try:
            resolved = resolver.resolve_database(database_name)
        except Exception as exc:
            raise OmopSchemaConfigurationError(
                f"Could not resolve oa-configurator database {database_name!r}: {exc}"
            ) from exc
        return resolved.configured_internal_schema_translate_map()

    engine = getattr(bind, "engine", bind)
    try:
        physical_key = connection_key(engine.url)
    except (AttributeError, TypeError, ValueError):
        return None
    for name in resolver.config.databases:
        try:
            resolved = resolver.resolve_database(name)
            mapping = resolved.configured_internal_schema_translate_map()
        except Exception as exc:
            raise OmopSchemaConfigurationError(
                f"Could not resolve oa-configurator database {name!r}: {exc}"
            ) from exc
        if "vocab" in mapping and resolved.connection.physical_key() == physical_key:
            return mapping
    return None


def _translate_map(bind: Any, explicit: dict[str, str | None] | None) -> dict[str, str | None] | None:
    if explicit is not None:
        return dict(explicit)
    existing = bind.get_execution_options().get(_SCHEMA_TRANSLATE_MAP)
    if existing is not None:
        return dict(existing)
    return _configured_map(bind)


def schema_aware_bind(
    bind: Any,
    schema_translate_map: dict[str, str | None] | None = None,
) -> Any:
    """Return a bind, or session, that translates OMOP schema tags."""
    is_session = callable(getattr(bind, "get_bind", None)) and callable(
        getattr(bind, "connection", None)
    )
    source = bind.get_bind() if is_session else bind
    if is_session and schema_translate_map is None:
        schema_translate_map = bind.info.get("schema_translate_map")
    mapping = _translate_map(source, schema_translate_map)
    if mapping is None:
        return bind
    if is_session:
        bind.info["schema_translate_map"] = mapping
        previous = bind.info.get("_omop_schema_route_listener")
        if previous is not None:
            event.remove(bind, "after_begin", previous)

        def route_transaction(
            session: Any, transaction: Any, connection: sa.Connection
        ) -> None:
            connection.execution_options(schema_translate_map=mapping)

        event.listen(bind, "after_begin", route_transaction)
        bind.info["_omop_schema_route_listener"] = route_transaction
        if bind.in_transaction():
            bind.connection().execution_options(schema_translate_map=mapping)
        return bind
    return source.execution_options(schema_translate_map=mapping)


def require_omop_available(
    session: Any, *, require_relationships: bool = False
) -> bool:
    """Route a Session and raise when installed OMOP tables are unreachable."""
    availability = omop_availability(session, require_relationships=require_relationships)
    if availability.available:
        return True
    from .binding import load_omop_binding

    if load_omop_binding() is None:
        return False
    raise OmopUnavailableError(availability.reason or "OMOP vocabulary is unavailable")


def _failure_reason(error: sa.exc.SQLAlchemyError, table: Any, mapping: Any) -> str:
    tag = table.schema or "vocab"
    if mapping is None or tag not in mapping:
        route = f"schema tag {tag!r} is unmapped"
    elif mapping[tag] is None:
        route = f"schema tag {tag!r} maps to the default schema"
    else:
        route = f"schema tag {tag!r} maps to physical schema {mapping[tag]!r}"
    original = getattr(error, "orig", None)
    sql_error = type(original).__name__ if original is not None else type(error).__name__
    message = str(original or error).splitlines()[0]
    return (
        f"OMOP query for {table.fullname} failed: {route}; "
        f"{type(error).__name__} ({sql_error}): {message}"
    )


def omop_availability(
    session: Any,
    *,
    require_relationships: bool = False,
    schema_translate_map: dict[str, str | None] | None = None,
) -> OmopAvailability:
    """Check the optional OMOP models and return a diagnostic on failure."""
    from .binding import load_omop_binding

    binding = load_omop_binding()
    if binding is None:
        return OmopAvailability(False, "omop-alchemy is not installed; install the 'omop' extra")

    try:
        schema_aware_bind(session, schema_translate_map)
        source = session.get_bind()
        mapping = session.info.get("schema_translate_map")
        if mapping is None:
            mapping = source.get_execution_options().get(_SCHEMA_TRANSLATE_MAP)
        routed = schema_aware_bind(source, mapping)
        options = routed.get_execution_options()
        if mapping is None:
            mapping = options.get(_SCHEMA_TRANSLATE_MAP)
        engine = getattr(routed, "engine", routed)
        probes = [(binding.concept, binding.concept.concept_id)]
        if require_relationships:
            probes.append(
                (binding.concept_relationship, binding.concept_relationship.concept_id_1)
            )
        with engine.connect() as connection:
            if mapping is not None:
                connection.execution_options(schema_translate_map=mapping)
            for model, column in probes:
                try:
                    connection.execute(sa.select(column).limit(1)).first()
                except sa.exc.SQLAlchemyError as exc:
                    return OmopAvailability(
                        False, _failure_reason(exc, model.__table__, mapping)
                    )
        return OmopAvailability(True)
    except OmopSchemaConfigurationError as exc:
        return OmopAvailability(False, f"OMOP schema configuration failed: {exc}")
    except sa.exc.SQLAlchemyError as exc:
        table = binding.concept.__table__
        return OmopAvailability(False, _failure_reason(exc, table, None))


__all__ = [
    "OmopAvailability",
    "OmopSchemaConfigurationError",
    "OmopUnavailableError",
    "omop_availability",
    "require_omop_available",
    "schema_aware_bind",
]
