"""Authored chains, independent of dictionary sheets and statistical inference.

The HemOnc author's note establishes that variables are "chained" and that
splitting columns independently creates too many rows, specifically
with/regimen/regimen_cui and biomarker/biomarker_finding.
Inference is diagnostic only; it never adds a chain to this declaration.
"""

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .schema_model import TableMeta


@dataclass(frozen=True)
class ChainSpec:
    name: str
    columns: tuple[str, ...]
    fields: tuple[str, ...]
    slot: int | None = None

    @classmethod
    def from_dict(cls, raw: dict) -> "ChainSpec":
        return cls(
            raw["name"], tuple(raw["columns"]), tuple(raw["fields"]), raw.get("slot")
        )


CHAIN_DECLARATIONS = {
    "indications": tuple(
        ChainSpec(
            "biomarker_slots",
            (
                f"biomarker{suffix}",
                f"biomarker{suffix}_finding",
                f"biomarker{suffix}_type",
            ),
            ("biomarker", "biomarker_finding", "biomarker_type"),
            slot,
        )
        for slot, suffix in ((1, ""), (2, "2"), (3, "3"), (4, "4"))
    )
    + (
        ChainSpec(
            "regimen_links",
            ("with_field", "regimen", "regimen_cui"),
            ("with_field", "regimen", "regimen_cui"),
        ),
    ),
    "drugs": (
        ChainSpec(
            "canmed_pairs",
            ("canmed_major_class", "canmed_major_class_cui"),
            ("canmed_major_class", "canmed_major_class_cui"),
        ),
    ),
}


def chain_classname(parent: str, name: str) -> str:
    return f"{parent}_{''.join(part.capitalize() for part in name.split('_'))}"


def render_source_metadata(table: "TableMeta") -> list[str]:
    """Emit raw source fields and the metadata needed to populate them."""
    lines = []
    if table.chains:
        lines.append(f"    chains = {[asdict(chain) for chain in table.chains]!r}")
    if table.opaque_columns:
        lines.append(f"    opaque_columns = {table.opaque_columns!r}")
    columns = {column for chain in table.chains for column in chain.columns} | set(
        table.opaque_columns
    )
    lines.extend(
        f"    {column}_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)"
        for column in sorted(columns)
    )
    return lines


def render_chain_tables(table: "TableMeta") -> list[tuple[str, str]]:
    """Render one additive table for each named chain (slots share one table)."""
    result = []
    for name, chain in sorted({chain.name: chain for chain in table.chains}.items()):
        classname = chain_classname(table.name, name)
        lines = [
            f"class {classname}(EntityBase, Base):",
            f"    __tablename__ = '{table.name}_{name}'",
            "    __table_args__ = {'schema': 'primary'}",
            f"    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('primary.{table.name}.id'), primary_key=True)",
        ]
        if chain.slot is not None:
            lines.append(
                "    slot: Mapped[int] = mapped_column(BigInteger, primary_key=True)"
            )
        lines += [
            "    position: Mapped[int] = mapped_column(BigInteger, primary_key=True)",
            "    aligned: Mapped[bool] = mapped_column(Boolean, nullable=False)",
        ]
        for column in chain.fields:
            numeric = column.endswith("_cui")
            py_type, sa_type = ("int", "BigInteger") if numeric else ("str", "Text")
            lines.append(
                f"    {column}: Mapped[Optional[{py_type}]] = mapped_column({sa_type}, nullable=True)"
            )
            if numeric:
                lines.append(
                    f"    {column}_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)"
                )
        result.append((classname, "\n".join(lines)))
    return result
