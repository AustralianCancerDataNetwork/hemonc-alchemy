"""Fetch the NCIt -> SNOMEDCT_US crosswalk for every HemOnc condition via the groundworkers UMLS plugin.

Run from an environment with `ohdsi_umls_bridge` and a configured UMLS API key, e.g.
`agent-stack/.venv/bin/python scripts/fetch_ncit_snomed_crosswalk.py data/Tables`.
Writes `ncit_snomed_crosswalk.json` (active SNOMED codes only) next to the conditions extract.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from oa_configurator import Resolver, load_stack_config
from ohdsi_umls_bridge.adapters import AsyncUMLSAdapter
from ohdsi_umls_bridge.config import UMLSConfig
from ohdsi_umls_bridge.service import UMLSService


async def fetch(ncit_codes: list[str]) -> tuple[dict[str, list[dict[str, str]]], str | None]:
    config = Resolver(load_stack_config()).resolve_package_config(UMLSConfig)
    adapter = AsyncUMLSAdapter(api_key=config.api_key or "", release=config.release, timeout=config.timeout, retries=config.retries)
    service = UMLSService(config, adapter)
    crosswalk: dict[str, list[dict[str, str]]] = {}
    release = None
    items = [{"item_id": code, "kind": "ncit_code", "value": code} for code in ncit_codes]
    for start in range(0, len(items), config.batch_limit):
        response = await service.resolve_batch(items[start:start + config.batch_limit], target_sources=["SNOMEDCT_US"])
        for result in response["results"]:
            crosswalk[result["item_id"]] = [
                {"code": entry["ui"], "name": entry["name"]}
                for entry in result.get("crosswalks", []) if not entry.get("obsolete")
            ]
            for hit in result.get("search_results", []):
                found = re.search(r"/content/([^/]+)/", hit.get("uri", ""))
                release = release or (found.group(1) if found else None)
    return crosswalk, release


def main(data_dir: Path) -> None:
    conditions = pd.read_csv(data_dir / "conditions.csv", dtype=str)
    codes = sorted(set(conditions["map_NCIT"].dropna()))
    crosswalk, release = asyncio.run(fetch(codes))
    payload = {"umls_release": release, "fetched": datetime.now(UTC).date().isoformat(), "crosswalk": crosswalk}
    out = data_dir / "ncit_snomed_crosswalk.json"
    out.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    hits = sum(1 for entries in crosswalk.values() if entries)
    print(f"Wrote {out}: {len(crosswalk)} NCIt codes, {hits} with an active SNOMED crosswalk (UMLS {release}).")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "data/Tables"))
