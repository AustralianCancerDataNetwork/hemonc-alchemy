"""Configured snapshot imports and explicitly scoped rebuilds."""

import os
import subprocess
import sys
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest
import sqlalchemy as sa
import yaml
from oa_configurator import Resolver, StackConfig
from oa_configurator.testing import isolated_test_schema

from hemonc_alchemy import bootstrap
from hemonc_alchemy.config import HemOncAlchemyConfig, create_hemonc_engine
from hemonc_alchemy.model.entities import (
    HemoncClasses,
    Units,
    hemonc_classes_Secondary_home_as_stringMap,
)


@pytest.fixture(params=[
    "sqlite",
    pytest.param("duckdb", marks=[pytest.mark.duckdb, pytest.mark.db_dialect]),
    pytest.param("postgresql", marks=[pytest.mark.postgres, pytest.mark.db_dialect]),
])
def target(request, tmp_path):
    if request.param == "postgresql":
        db = request.getfixturevalue("pg_db")
        with isolated_test_schema(db.committing_engine, prefix="hemonc_bootstrap") as schema:
            yield replace(db.resolved, schema_name=schema)
        return
    schema = "hemonc" if request.param == "duckdb" else None
    config = StackConfig.for_session(
        connections={"local": {"dialect": request.param, "database_name": str(tmp_path / "snapshot.db")}},
        databases={"local": {"kind": "generic", "connection": "local", "schema_name": schema}},
    )
    yield Resolver(config).resolve_database("local")


@pytest.fixture
def extract(tmp_path):
    directory = tmp_path / "extract"
    directory.mkdir()
    (directory / "units.csv").write_text(
        "unit,unit_type,concept_code,date_added,fixed,parameter-based,time-based\n"
        "mg,mass,1,2020-01-01,TRUE,FALSE,FALSE\n"
    )
    (directory / "hemonc_classes.csv").write_text(
        "description,domain,class_type,primary_table,secondary_home_as_string,in_OHDSI\n"
        "Registry,clinical trial,ready for core,ready for core,studies$registry|studies$trial,FALSE\n"
    )
    return directory


def test_fresh_import_and_rebuild_preserve_unrelated_tables(target, extract):
    counts = bootstrap.bootstrap_database(target, extract)
    assert counts["units"]["units"] == 1
    assert counts["hemonc_classes"]["secondary_home_as_string"] == 2
    engine = create_hemonc_engine(target)
    metadata = sa.MetaData()
    preserved = [sa.Table(name, metadata, sa.Column("value", sa.Integer), schema="primary") for name in ["concept", "_staging_unrelated"]]
    stale = sa.Table("_staging_units", metadata, sa.Column("value", sa.Integer), schema="primary")
    try:
        metadata.create_all(engine)
        with engine.begin() as connection:
            for table in preserved:
                connection.execute(table.insert(), {"value": 42})
        with pytest.raises(ValueError, match="--rebuild"):
            bootstrap.bootstrap_database(target, extract)
        with engine.connect() as connection:
            assert connection.scalar(sa.select(sa.func.count()).select_from(Units)) == 1
        repeated = bootstrap.bootstrap_database(target, extract, rebuild=True)
        assert repeated == counts
        with engine.connect() as connection:
            assert connection.scalar(sa.select(sa.func.count()).select_from(HemoncClasses)) == 1
            assert connection.scalar(sa.select(sa.func.count()).select_from(hemonc_classes_Secondary_home_as_stringMap)) == 2
            for table in preserved:
                assert connection.scalar(sa.select(table.c.value)) == 42
            schema = engine.get_execution_options()["schema_translate_map"]["primary"]
            assert stale.name not in sa.inspect(connection).get_table_names(schema=schema)
    finally:
        engine.dispose()


def test_missing_sources_do_not_reset_an_existing_target(target, extract):
    bootstrap.bootstrap_database(target, extract)
    with pytest.raises(FileNotFoundError):
        bootstrap.bootstrap_database(target, extract / "absent", rebuild=True)
    with pytest.raises(ValueError, match="Unknown source tables"):
        bootstrap.bootstrap_database(target, extract, rebuild=True, table_names=["not_a_table"])
    with pytest.raises(FileNotFoundError, match="No source CSV for drugs"):
        bootstrap.bootstrap_database(target, extract, rebuild=True, table_names=["drugs"])
    (extract / "units.csv").rename(extract / "units_first.csv")
    (extract / "units_second.csv").write_text((extract / "units_first.csv").read_text())
    with pytest.raises(ValueError, match="Ambiguous source CSVs for units"):
        bootstrap.bootstrap_database(target, extract, rebuild=True, table_names=["units"])
    engine = create_hemonc_engine(target)
    try:
        with engine.connect() as connection:
            assert connection.scalar(sa.select(Units.concept_code)) == 1
    finally:
        engine.dispose()


def test_cli_resolves_active_config_and_ignores_legacy_database_url(tmp_path, extract):
    config = tmp_path / "config.toml"
    config.write_text(
        '[connections.local]\ndialect="sqlite"\ndatabase_name="' + str(tmp_path / "cli.db") + '"\n'
        '[databases.local]\nkind="generic"\nconnection="local"\n'
        '[tools.hemonc_alchemy]\nhemonc_db="local"\n'
    )
    config.chmod(0o600)
    environment = {**os.environ, "OA_CONFIG_PATH": str(config), "DATABASE_URL": "not-a-database-url"}
    result = subprocess.run(
        [sys.executable, "-m", "hemonc_alchemy.bootstrap", "--data-dir", str(extract), "--table", "units"],
        env=environment, check=True, capture_output=True, text=True,
    )
    assert "HemOnc target: local" in result.stdout


@pytest.mark.parametrize("seed", ["config.toml", "config.duckdb.toml"])
def test_devcontainer_seed_preserves_existing_configuration(tmp_path, seed):
    root = Path(__file__).parents[1]
    config = tmp_path / "active.toml"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ["uv", "bash"]:
        command = bin_dir / name
        command.write_text("#!/bin/sh\nexit 0\n")
        command.chmod(0o755)
    environment = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                   "OA_CONFIG_PATH": str(config), "OA_CONFIG_SEED": str(root / ".devcontainer" / seed)}
    command = ["/bin/bash", str(root / ".devcontainer/post-create.sh")]
    subprocess.run(command, env=environment, cwd=root, check=True, capture_output=True)
    assert config.read_bytes() == (root / ".devcontainer" / seed).read_bytes()
    assert config.stat().st_mode & 0o777 == 0o600
    config.write_text("personal configuration")
    subprocess.run(command, env=environment, cwd=root, check=True, capture_output=True)
    assert config.read_text() == "personal configuration"


def test_duckdb_compose_and_seed_are_independent_of_postgres():
    root = Path(__file__).parents[1] / ".devcontainer"
    services = yaml.safe_load((root / "compose.duckdb.yaml").read_text())["services"]
    assert set(services) == {"python-hemonc-alchemy-duckdb"}
    assert "depends_on" not in services["python-hemonc-alchemy-duckdb"]
    for seed in ["config.toml", "config.duckdb.toml"]:
        seed_config = tomllib.loads((root / seed).read_text())
        config = StackConfig.model_validate(seed_config)
        resolver = Resolver(config)
        package = resolver.resolve_package_config(HemOncAlchemyConfig)
        assert package.omop_db == "cdm_db"
        if seed == "config.duckdb.toml":
            target = resolver.resolve_database(package.hemonc_db)
            file_name = seed_config["connections"]["devcontainer_duckdb"]["database_name"]
            assert Path(file_name).stem != target.schema_name
        assert resolver.resolve_database(package.hemonc_db).connection.addresses_same_database_as(
            resolver.resolve_database(package.omop_db).connection
        )


def test_postgres_ci_config_resolves_runtime_and_test_roles():
    path = Path(__file__).parents[1] / ".github/config.postgres.toml"
    resolver = Resolver(StackConfig.model_validate(tomllib.loads(path.read_text())))
    package = resolver.resolve_package_config(HemOncAlchemyConfig)
    assert not resolver.resolve_database(package.hemonc_db).connection.test_only
    assert resolver.resolve_database(package.test_hemonc_db).connection.test_only
