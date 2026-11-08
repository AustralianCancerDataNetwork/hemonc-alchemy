"""Aggregate evidence for public toolkit queries on the imported extract."""

from time import perf_counter

from sqlalchemy.orm import Session

from hemonc_alchemy.integrations.omop import (
    condition_to_snomed,
    drug_to_rxnorm_ingredient,
    regimen_to_hemonc,
)
from hemonc_alchemy.toolkit.core.catalogue.indications import indication_statement
from hemonc_alchemy.toolkit.core.catalogue.regimens import regimen_catalogue_statement
from hemonc_alchemy.toolkit.core.condition_families import condition_families

from .parity import digest

REQUIRED_QUERIES = frozenset({
    "regimen_catalogue", "indication_catalogue", "condition_families",
    "condition_614_to_snomed", "drug_105_to_rxnorm", "regimen_2204_to_hemonc",
})


def toolkit_queries(engine, parent_ids, *, include_omop=True) -> tuple[dict, dict]:
    with Session(engine) as session:
        def indications():
            rows = []
            for row in session.execute(indication_statement()).mappings():
                record = dict(row)
                record["record_id"] = parent_ids["indications"][record["record_id"]]
                rows.append(record)
            return rows

        calls = {
            "regimen_catalogue": lambda: [dict(row) for row in session.execute(regimen_catalogue_statement()).mappings()],
            "indication_catalogue": indications,
        }
        if include_omop:
            calls.update({
                "condition_families": lambda: condition_families(session),
                "condition_614_to_snomed": lambda: condition_to_snomed(session, [614]),
                "drug_105_to_rxnorm": lambda: drug_to_rxnorm_ingredient(session, [105]),
                "regimen_2204_to_hemonc": lambda: regimen_to_hemonc(session, [2204]),
            })
        results, timings = {}, {}
        for name, call in calls.items():
            start = perf_counter()
            values = call()
            if not values:
                raise ValueError(f"Representative query {name} returned no rows")
            # SQL row order can differ while the returned multiset agrees.
            hashes = sorted(digest(row).hex() for row in values) if isinstance(values, list) else values
            results[name] = {"rows": len(values), "sha256": digest(hashes).hex()}
            timings[name] = round(perf_counter() - start, 4)
        return results, timings
