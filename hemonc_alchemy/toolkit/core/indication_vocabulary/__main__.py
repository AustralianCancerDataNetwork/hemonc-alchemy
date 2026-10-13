"""Run the vocabulary lint: python -m hemonc_alchemy.toolkit.core.indication_vocabulary [--strict]."""

import argparse
import os
import sys

from sqlalchemy import create_engine, text

from .lint import lint_vocabulary
from .loader import load_vocabulary

_SIMPLE = (
    ("stage", "stage"),
    ("status", "status"),
    ("stage_or_status", "stage_or_status"),
    ("prior_therapy", "prior_therapy"),
    ("with_field", "with_field"),
    ("ineligibility", "ineligibility"),
    ("time_contingency", "time_contingency"),
)
_CHILD = (
    ("context", "context"),
    ("demographics", "demographics"),
    ("prior_therapy_setting", "prior_therapy_setting"),
    ("response_contingency", "response_contingency"),
    ("risk_stratification", "risk_stratification"),
)


def _database_values(url: str) -> list[tuple[str, str, str]]:
    values: list[tuple[str, str, str]] = []
    with create_engine(url).connect() as conn:
        for column, field in _SIMPLE:
            for (raw,) in conn.execute(
                text(
                    f"select distinct v from indications, unnest(string_to_array({field}, '|')) v where {field} is not null"
                )
            ):
                values.append((column, raw.strip(), ""))
        for column, table in _CHILD:
            for (raw,) in conn.execute(
                text(
                    f"select distinct v from indications_{table}, unnest(string_to_array({column}::text, '|')) v"
                )
            ):
                parts = raw.split("&") if column == "context" else [raw]
                values.extend((column, part.strip(), "") for part in parts)
        for (raw,) in conn.execute(
            text(
                "select distinct v from indications, unnest(string_to_array(biomarker, '|')) v where biomarker is not null"
            )
        ):
            values.append(("biomarker", raw.strip(), ""))
    return [v for v in values if v[1] and normalise(v[1]) != "not applicable"]


def normalise(value: str) -> str:
    return value.strip().casefold()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="indication_vocabulary")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail when values have no concept or any warning is raised",
    )
    parser.add_argument(
        "--database-url", default=os.environ.get("HEMONC_INDICATIONS_DATABASE_URL")
    )
    args = parser.parse_args(argv)
    values = _database_values(args.database_url) if args.database_url else []
    report = lint_vocabulary(load_vocabulary(), values)
    for title, items in (
        ("Failures", report.failures),
        ("Warnings", report.warnings),
        ("Source values with no concept", report.unmapped_values),
        ("Needs review", report.needs_review),
    ):
        print(f"{title}: {len(items)}")
        for item in items:
            print(f"  {item}")
    if report.failures or (args.strict and (report.unmapped_values or report.warnings)):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
