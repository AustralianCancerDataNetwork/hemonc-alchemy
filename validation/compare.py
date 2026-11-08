"""Compare two aggregate backend receipts; exit nonzero at a failed gate."""

import argparse
import json
from pathlib import Path

from hemonc_alchemy.model import Base

from .parity import differences
from .queries import REQUIRED_QUERIES


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    left = json.loads(args.left.read_text())
    right = json.loads(args.right.read_text())
    failed = differences(left, right)
    if not left["source"]["full_extract"] or not right["source"]["full_extract"]:
        failed.append("full_extract_required")
    if not left.get("queries") or not right.get("queries"):
        failed.append("representative_queries_required")
    if left.get("vocabulary") is None or right.get("vocabulary") is None:
        failed.append("vocabulary_snapshot_required")
    for name, report in [("left", left), ("right", right)]:
        if set(report["tables"]) != {table.name for table in Base.metadata.tables.values()}:
            failed.append(f"{name}.all_tables_required")
        if set(report["loads"]) != set(report["source"]["files"]):
            failed.append(f"{name}.all_source_reports_required")
        if any(not load["accounted"] for load in report["loads"].values()):
            failed.append(f"{name}.unaccounted_source_rows")
        if not REQUIRED_QUERIES <= report["queries"].keys():
            failed.append(f"{name}.all_representative_queries_required")
    receipt = {
        "passed": not failed, "differences": failed,
        "source_id": left["source"]["id"],
        "loadable_sources": len(left["source"]["files"]),
        "tables_compared": len(left["tables"]),
        "rows": {"left": sum(t["rows"] for t in left["tables"].values()),
                 "right": sum(t["rows"] for t in right["tables"].values())},
    }
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, indent=2))
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
