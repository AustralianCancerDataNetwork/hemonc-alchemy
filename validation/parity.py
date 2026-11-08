"""Compare stored semantics without depending on generated surrogate IDs."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

import sqlalchemy as sa


def canonical(value: Any) -> Any:
    """Keep type distinctions and portable representations of database values."""
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value.normalize())
    if isinstance(value, float):
        return {"float": value.hex() if math.isfinite(value) else str(value)}
    if is_dataclass(value) and not isinstance(value, type):
        return canonical(asdict(value))
    if isinstance(value, dict):
        return {str(key): canonical(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((canonical(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    return value


def digest(value: Any) -> bytes:
    encoded = json.dumps(canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).digest()


def source_manifest(data_dir: Path, models: list[Any], *, full_extract: bool) -> dict:
    from hemonc_alchemy.naming import resolve_source_csv

    files = {}
    for model in models:
        path, _ = resolve_source_csv(data_dir, model.__tablename__)
        with path.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        files[model.__tablename__] = {
            "filename": path.name, "bytes": path.stat().st_size,
            "sha256": checksum,
        }
    selected = {item["filename"] for item in files.values()}
    return {
        "id": digest(files).hex(), "full_extract": full_extract, "files": files,
        "unmodeled_files": sorted(path.name for path in data_dir.glob("*.csv") if path.name not in selected),
    }


def semantic_row(row: dict, table: sa.Table, parent_ids: dict) -> tuple[dict, bool]:
    values = dict(row)
    orphan = False
    if "id" in table.c and list(table.primary_key.columns.keys()) == ["id"]:
        values.pop("id")
    for column in table.c:
        for foreign_key in column.foreign_keys:
            reference = foreign_key.column
            if reference.name != "id" or values.get(column.name) is None:
                continue
            parent = parent_ids[reference.table.name].get(values[column.name])
            orphan |= parent is None
            values[column.name] = {"parent_semantics": parent}
    return values, orphan


def table_snapshot(connection: sa.Connection, table: sa.Table, parent_ids: dict) -> dict:
    hashes = []
    nulls: Counter = Counter({column.name: 0 for column in table.c})
    orphans = 0
    own_ids = {}
    for row in connection.execute(sa.select(table)).mappings().yield_per(10_000):
        nulls.update(key for key, value in row.items() if value is None)
        values, orphan = semantic_row(dict(row), table, parent_ids)
        hashed = digest(values)
        hashes.append(hashed)
        orphans += orphan
        if "id" in row and list(table.primary_key.columns.keys()) == ["id"]:
            own_ids[row["id"]] = hashed.hex()
    if "id" in table.c and list(table.primary_key.columns.keys()) == ["id"]:
        parent_ids[table.name] = own_ids
    return {
        "rows": len(hashes), "sha256": hashlib.sha256(b"".join(sorted(hashes))).hexdigest(),
        "nulls": dict(nulls), "orphan_rows": orphans,
    }


def differences(left: dict, right: dict) -> list[str]:
    """Return failed gates, excluding timings, database locations and versions."""
    failed = []
    for section in ["source", "loads", "tables", "queries", "vocabulary"]:
        a, b = left.get(section), right.get(section)
        if a == b:
            continue
        if isinstance(a, dict) and isinstance(b, dict):
            failed.extend(f"{section}.{key}" for key in sorted(a.keys() | b.keys()) if a.get(key) != b.get(key))
        else:
            failed.append(section)
    for name, report in [("left", left), ("right", right)]:
        if report.get("errors") or report.get("status") != "complete":
            failed.append(f"{name}.incomplete")
        if any(table["orphan_rows"] for table in report.get("tables", {}).values()):
            failed.append(f"{name}.orphan_rows")
    return failed
