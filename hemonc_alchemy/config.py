"""
oa-configurator integration for hemonc-alchemy.
"""

from __future__ import annotations

from typing import Annotated, Any, ClassVar

import sqlalchemy as sa
from oa_configurator import (  # type: ignore[import-untyped]  # no py.typed marker upstream
    CDMDatabaseConfig,
    GenericDatabaseConfig,
    PackageConfigBase,
    RefTo,
    ResolvedDatabase,
    Resolver,
    load_stack_config,
)


class HemOncAlchemyConfig(PackageConfigBase):
    """oa-configurator config class for hemonc-alchemy, the HemOnc database owner.

    Attributes
    ----------
    hemonc_db : str
        Name of the ``[databases.*]`` entry holding the HemOnc database.
    omop_db : str, optional
        CDM target supplying the vocabulary role for same-database joins.
    test_hemonc_db : str, optional
        Name of the ``[databases.*]`` entry holding the test HemOnc database,
        marked ``RefTo(GenericDatabaseConfig, is_test=True)``.
    test_hemonc_db_duckdb : str, optional
        DuckDB test target; leave unset for disposable-file provisioning.
    """

    tool_name: ClassVar[str] = "hemonc_alchemy"
    extra_logging_namespaces: ClassVar[tuple[str, ...]] = ("orm_loader",)

    hemonc_db: Annotated[str, RefTo(GenericDatabaseConfig)] = "hemonc_db"
    omop_db: Annotated[str | None, RefTo(CDMDatabaseConfig)] = None
    test_hemonc_db: Annotated[
        str | None, RefTo(GenericDatabaseConfig, is_test=True)
    ] = None
    test_hemonc_db_duckdb: Annotated[
        str | None, RefTo(GenericDatabaseConfig, is_test=True)
    ] = None


def get_hemonc_context() -> tuple[HemOncAlchemyConfig, ResolvedDatabase]:
    """Return (pkg_config, resolved_hemonc_database), loading config once.

    Raises
    ------
    RuntimeError
        If no oa-configurator stack config file exists yet.
    """
    try:
        stack = load_stack_config()
    except FileNotFoundError as exc:
        raise RuntimeError(
            "No hemonc-alchemy configuration found. "
            "Run `omop-config configure hemonc_alchemy` to set it up."
        ) from exc
    resolver = Resolver(stack)
    pkg_config = resolver.resolve_package_config(HemOncAlchemyConfig)
    resolved = resolver.resolve_database(pkg_config.hemonc_db)
    if not isinstance(resolved, ResolvedDatabase):
        raise TypeError(
            f"HemOncAlchemyConfig.hemonc_db must resolve to a database, got "
            f"{type(resolved).__name__}"
        )
    return pkg_config, resolved


def create_hemonc_engine(resolved: ResolvedDatabase) -> sa.Engine:
    """Create the hemonc-alchemy database engine."""
    return resolved.create_engine()


def create_default_hemonc_engine(url: str | sa.URL, **kwargs: Any) -> sa.Engine:
    """Create a URL-based engine with HemOnc in the connection's default schema.

    Explicit execution options, including schema routes, take precedence.
    Use create_hemonc_engine for an oa-configurator target instead.
    """
    options = dict(kwargs.pop("execution_options", {}))
    mapping = {"primary": None, **(options.get("schema_translate_map") or {})}
    return sa.create_engine(url, execution_options={**options, "schema_translate_map": mapping}, **kwargs)
