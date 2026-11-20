"""Print chain alignment counts and source issues; never modify extracts.

Run with the installed development environment:
    python scripts/audit_chains.py data/Tables
Output is Markdown, including every unaligned/suspicious source row.
"""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from hemonc_alchemy.compiler.chains import CHAIN_DECLARATIONS
from hemonc_alchemy.multivalue import align_values, split_positions
from hemonc_alchemy.naming import safe_identifier


def _suspicious(chain, raw):
    if chain.name != "regimen_links":
        return False
    partner, names, _ = map(split_positions, raw)
    return (
        len(partner) == 1
        and partner[0] is not None
        and len(names) > 1
        and any(partner[0].casefold() not in (name or "").casefold() for name in names)
    )


def audit(data_dir: Path) -> str:
    lines = [
        "# Chain source audit",
        "",
        (
            "Computed from source CSV records (header is row 1). `paired` includes blank sides; "
            "`broadcast` means at least one nonblank singleton was expanded across a longer member, including type. "
            "`opaque_member` means a nested-pipe expression was excluded from alignment. "
            "Counters are mutually exclusive. Link counts exclude position-zero unaligned markers."
        ),
        "",
        "| Chain | Source multi rows | Paired | Broadcast | Opaque member | Unaligned | Aligned links | Repeats kept |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    issues = []
    placeholder_rows = Counter()
    for parent, chains in CHAIN_DECLARATIONS.items():
        with (data_dir / f"{parent}.csv").open(
            newline="", encoding="utf-8-sig"
        ) as handle:
            rows = [
                {safe_identifier(key).lower(): value for key, value in row.items()}
                for row in csv.DictReader(handle)
            ]
        for chain in chains:
            counts = Counter()
            for line, row in enumerate(rows, 2):
                raw = tuple(row.get(column) for column in chain.columns)
                alignment = align_values(raw)
                counts[alignment.status] += 1
                counts["links"] += len(alignment.rows)
                counts["multi"] += any("|" in (value or "") for value in raw)
                counts["repeats"] += alignment.repeats_kept
                if chain.name == "regimen_links":
                    has_placeholder = any(
                        value in {"TBA", "CBD"} for value in split_positions(raw[2])
                    )
                    placeholder_rows["all"] += has_placeholder
                    placeholder_rows["multi"] += has_placeholder and "|" in (
                        raw[1] or ""
                    )
                    placeholder_rows["aligned_multi"] += (
                        has_placeholder
                        and "|" in (raw[1] or "")
                        and alignment.status != "unaligned"
                    )
                if alignment.status in {"unaligned", "opaque_member"} or _suspicious(
                    chain, raw
                ):
                    issues.append((parent, chain, line, row, alignment.status))
            label = f"{parent}.{chain.name}" + (
                f" slot {chain.slot}" if chain.slot is not None else ""
            )
            lines.append(
                f"| {label} | {counts['multi']} | {counts['paired']} | {counts['broadcast']} | {counts['opaque_member']} | {counts['unaligned']} | {counts['links']} | {counts['repeats']} |"
            )
    lines += [
        "",
        (
            f"Regimen codes containing TBA/CBD: {placeholder_rows['all']} source rows, "
            f"including {placeholder_rows['multi']} with multiple regimen names. "
            f"Of those multi-regimen rows, {placeholder_rows['aligned_multi']} can be aligned; "
            "the remainder retain the full raw code on the parent and an unaligned child marker."
        ),
        "",
        "## Complete unaligned and suspicious rows",
        "",
        (
            "Suspicion is a conservative text check: a singleton partner is not present literally in every "
            "regimen name it broadcasts to. It flags review candidates and does not correct source data."
        ),
        "",
    ]
    for parent, chain, line, row, status in issues:
        label = (
            status.replace("_", " ")
            if status in {"unaligned", "opaque_member"}
            else "suspicious broadcast"
        )
        lines += [
            f"### {parent}.csv row {line}: {row.get('component', row.get('drug', ''))} ({label})",
            "",
            "```json",
            json.dumps(
                {column: row.get(column) for column in chain.columns},
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
        ]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path)
    print(audit(parser.parse_args().data_dir))
