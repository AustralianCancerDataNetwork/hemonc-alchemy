from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from .compiler import audit as audit_module
from .compiler import classification_generation as classification_generation_module
from .compiler import condition_target_generation as condition_target_generation_module
from .compiler import diff as diff_module
from .compiler import generate as generate_module
from .compiler import spec_adapter
from .compiler import validate as validate_module
from .compiler.schema_model import load_registry_json
from .errors import HemOncValidationError

app = typer.Typer(
    help="hemonc-alchemy schema compiler and maintenance utilities.",
    rich_markup_mode="rich",
)

_PACKAGE_ROOT = Path(__file__).parent
_MODEL_DIR = _PACKAGE_ROOT / "model"
_SCHEMA_DIR = _PACKAGE_ROOT / "schema"
_REGISTRY_JSON = _SCHEMA_DIR / "registry.json"
_CLASSIFICATION_DATA_PATH = (
    _PACKAGE_ROOT / "toolkit" / "analytics" / "treatment" / "classification" / "generated.py"
)

DataDirOption = Annotated[
    Path,
    typer.Option(
        envvar="HEMONC_DATA_DIR",
        help="Directory containing the current HemOnc CSV extracts and data.dictionary.xlsx.",
    ),
]


@app.command()
def regen(
    data_dir: DataDirOption,
    force: Annotated[bool, typer.Option(help="Proceed even if the schema diff shows unacknowledged changes.")] = False,
    accept_source_loss: Annotated[
        bool,
        typer.Option(
            help="Proceed even if a table that previously generated an entity class no longer resolves to a source file.",
        ),
    ] = False,
) -> None:
    """
    Regenerate model/entities.py, model/enums.py, and schema/registry.json
    from the HemOnc data dictionary.

    Validates and diffs as part of the same command, so a broken model or an
    unreviewed schema change stops it rather than leaving the model
    half-updated. Review a diff with `hemonc-alchemy diff`, then pass --force
    to accept it.

    A table losing its source file is gated by --accept-source-loss instead,
    separately from --force: a content update produces a large diff that gets
    forced routinely, which is how three tables once dropped out of the model
    unnoticed.
    """
    registry = generate_module.regenerate(data_dir, _MODEL_DIR)

    previous = diff_module.load_previous_registry_from_git(_REGISTRY_JSON)

    source_losses = validate_module.validate_source_regressions(registry, previous)
    if source_losses and not accept_source_loss:
        typer.secho(
            f"{len(source_losses)} table(s) no longer resolve to a source file:",
            fg=typer.colors.RED,
            bold=True,
        )
        for loss in source_losses:
            typer.echo(f"  - {loss}")
        typer.secho(
            "Re-run with --accept-source-loss once this is intended.", fg=typer.colors.YELLOW
        )
        raise typer.Exit(code=1)

    errors = validate_module.validate_all(registry, _MODEL_DIR / "entities.py", _MODEL_DIR / "enums.py")
    if errors:
        typer.secho("Validation failed:", fg=typer.colors.RED, bold=True)
        for error in errors:
            typer.echo(f"  - {error}")
        raise typer.Exit(code=1)

    orm_check = subprocess.run(
        [sys.executable, "-m", "hemonc_alchemy.cli", "validate"],
        capture_output=True,
        text=True,
        check=False,
    )
    if orm_check.returncode != 0:
        typer.secho("Generated model failed to import/map cleanly:", fg=typer.colors.RED, bold=True)
        typer.echo(orm_check.stdout)
        typer.echo(orm_check.stderr)
        raise typer.Exit(code=1)

    try:
        changes = diff_module.diff_or_raise(_REGISTRY_JSON, registry)
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    if changes and not force:
        typer.secho(
            f"Schema changed in {len(changes)} way(s) since the last committed version. "
            "Review with `hemonc-alchemy diff`, then re-run with --force to accept.",
            fg=typer.colors.YELLOW,
        )
        for change in changes:
            typer.echo(f"  - {change}")
        raise typer.Exit(code=1)

    warnings = (
        audit_module.enum_collision_warnings(registry)
        + audit_module.enum_threshold_warnings(registry)
        + audit_module.dictionary_only_column_warnings(registry)
    )
    for warning in warnings:
        typer.secho(f"Warning: {warning}", fg=typer.colors.YELLOW)

    generated = sorted(name for name, t in registry.tables.items() if t.columns)
    sourceless = sorted(name for name, t in registry.tables.items() if not t.columns)

    typer.secho(
        f"Regenerated {len(registry.tables)} tables: "
        f"{len(generated)} produced an entity class, {len(sourceless)} had no source file.",
        fg=typer.colors.GREEN,
    )
    if sourceless:
        previously_backed = (
            {name for name, t in previous.tables.items() if t.columns} if previous else set()
        )
        newly = [name for name in sourceless if name in previously_backed]
        long_standing = [name for name in sourceless if name not in previously_backed]
        if newly:
            typer.secho(
                f"  newly without a source ({len(newly)}): {', '.join(newly)}",
                fg=typer.colors.YELLOW,
            )
        if long_standing:
            typer.echo(
                f"  no source in the previous run either ({len(long_standing)}): "
                f"{', '.join(long_standing)}"
            )


@app.command()
def validate() -> None:
    """
    Check the currently generated model for structural correctness.
    """
    if not _REGISTRY_JSON.exists():
        typer.secho(f"No registry found at {_REGISTRY_JSON} — run `regen` first.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    registry = load_registry_json(_REGISTRY_JSON)
    try:
        validate_module.validate_or_raise(registry, _MODEL_DIR / "entities.py", _MODEL_DIR / "enums.py")
    except HemOncValidationError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    from .model import entities
    from .model.base import concrete_entities

    models = concrete_entities(entities)
    report = spec_adapter.validate_with_orm_loader(registry, models)

    typer.echo(report.summary())
    if not report.is_valid():
        typer.echo(report.render_text_report())
    if report.exit_code():
        raise typer.Exit(code=1)

    typer.secho("Model is structurally valid.", fg=typer.colors.GREEN)


@app.command()
def diff(
    ref: Annotated[str, typer.Option(help="Git ref to diff against.")] = "HEAD",
) -> None:
    """Diff the currently generated schema against the last committed one."""
    if not _REGISTRY_JSON.exists():
        typer.secho(f"No registry found at {_REGISTRY_JSON} — run `regen` first.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    registry = load_registry_json(_REGISTRY_JSON)
    try:
        changes = diff_module.diff_or_raise(_REGISTRY_JSON, registry, ref=ref)
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    if not changes:
        typer.secho(f"No schema changes since {ref}.", fg=typer.colors.GREEN)
        return

    typer.secho(f"{len(changes)} change(s) since {ref}:", fg=typer.colors.YELLOW)
    for change in changes:
        typer.echo(f"  - {change}")


@app.command()
def audit(
    data_dir: DataDirOption,
    output: Annotated[Path | None, typer.Option(help="Write the report here instead of printing it.")] = None,
    report_only: Annotated[
        bool, typer.Option(help="Always exit 0, even if hard mismatches are found (for local/manual review).")
    ] = False,
) -> None:
    """
    Audit natural/business keys for duplicates and enum-threshold risk.
    """
    results = audit_module.run_audit(data_dir)
    report = audit_module.build_report(results, data_dir)

    if output is None:
        typer.echo(report)
    else:
        output.write_text(report, encoding="utf-8")
        typer.secho(f"Wrote report to {output}", fg=typer.colors.GREEN)

    if audit_module.has_hard_failures(results) and not report_only:
        raise typer.Exit(code=1)


@app.command(name="regen-classification")
def regen_classification(data_dir: DataDirOption) -> None:
    """Regenerate toolkit/analytics/treatment/classification/generated.py from `data_dir`'s `omop.RData`. Review the diff before committing."""
    result = classification_generation_module.regenerate(data_dir, _CLASSIFICATION_DATA_PATH)

    typer.secho(
        f"Regenerated {_CLASSIFICATION_DATA_PATH}: "
        f"{len(result.endocrine_main_classes)} endocrine, "
        f"{len(result.supportive_main_classes)} supportive main_class value(s).",
        fg=typer.colors.GREEN,
    )
    if result.inconsistent_main_classes:
        typer.secho(
            f"  {len(result.inconsistent_main_classes)} main_class value(s) had inconsistent "
            f"component ancestry, excluded from both sets: "
            f"{', '.join(result.inconsistent_main_classes)}",
            fg=typer.colors.YELLOW,
        )


@app.command(name="regen-condition-targets")
def regen_condition_targets(
    data_dir: DataDirOption,
    db_url: Annotated[str, typer.Option(envvar="HEMONC_VOCAB_URL", help="SQLAlchemy URL of a database holding HemOnc's tables and the OMOP vocabulary.")],
    vocab_schema: Annotated[str | None, typer.Option(help="Schema holding the OMOP vocabulary tables, if not the connection's default.")] = None,
    review_out: Annotated[Path, typer.Option(help="Where to write the suggested-changes CSV.")] = Path("condition_targets_review.csv"),
    proposals: Annotated[Path | None, typer.Option(help="Search proposals CSV; defaults to `data_dir`/condition_target_proposals.csv.")] = None,
    coverage_flags_out: Annotated[Path | None, typer.Option(help="Also write targets that cover conditions outside their HemOnc subtree.")] = None,
    crosswalk: Annotated[Path | None, typer.Option(help="NCIt -> SNOMED crosswalk JSON; defaults to `data_dir`/ncit_snomed_crosswalk.json.")] = None,
) -> None:
    """Rewrite toolkit/core/condition_patches.csv and write a suggestions sheet. Review the diff before committing."""
    import sqlalchemy as sa
    from sqlalchemy.orm import Session

    engine = sa.create_engine(db_url)
    # TODO: replace with oa-configurator's resolved vocab schema once its schema handling lands.
    if vocab_schema:
        engine = engine.execution_options(schema_translate_map={"vocab": vocab_schema})
    with Session(engine) as session:
        result = condition_target_generation_module.regenerate(
            data_dir, session, review_out,
            crosswalk_path=crosswalk, proposals_path=proposals, coverage_flags_path=coverage_flags_out,
        )
    typer.secho(
        f"Wrote {len(result.patches)} patch row(s) to {condition_target_generation_module.PATCHES_PATH} and "
        f"{len(result.suggestions)} suggested change(s) to {review_out}.",
        fg=typer.colors.GREEN,
    )

def main() -> None:
    app()


if __name__ == "__main__":
    main()
