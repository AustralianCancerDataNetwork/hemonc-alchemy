"""Generate the local indication vocabulary tables from the live indications and the verified evidence.

    HEMONC_INDICATIONS_DATABASE_URL=postgresql+psycopg://hemonc:hemonc@localhost:5432/hemonc_alchemy?options=-csearch_path%3Dpublic,omop \
        uv run python scripts/indication_vocabulary/build.py

Reads evidence/*.tsv (existing-concept lookups, each id re-checked through groundworkers) and writes
hemonc_alchemy/toolkit/core/indication_vocabulary/data/*.tsv.
"""

from __future__ import annotations

import csv
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, text

from hemonc_alchemy.model import enums as model_enums
from hemonc_alchemy.toolkit.core.indication_vocabulary.loader import (
    normalise_source_value,
)

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence"
OUT = (
    HERE.parents[1]
    / "hemonc_alchemy"
    / "toolkit"
    / "core"
    / "indication_vocabulary"
    / "data"
)
VOCAB = "HemOnc Local"
LOCAL_BASE = 2_000_000_000
VERIFIED_ON = "2026-10-13"

BLOCKS = {
    "Indication": 0,
    "Biomarker State": 20_000_000,
    "Disease Extent": 30_000_000,
    "Disease Status": 32_000_000,
    "Response Contingency": 34_000_000,
    "Prior Therapy Requirement": 36_000_000,
    "Co-therapy Requirement": 37_000_000,
    "Population Qualifier": 40_000_000,
    "Treatment Context": 42_000_000,
    "Regulator": 50_000_000,
    "Approval Path": 51_000_000,
}
CLASS_CODE = {
    "Indication": "IND",
    "Biomarker State": "BST",
    "Disease Extent": "EXT",
    "Disease Status": "STA",
    "Response Contingency": "RSP",
    "Prior Therapy Requirement": "PTR",
    "Co-therapy Requirement": "COT",
    "Population Qualifier": "POP",
    "Treatment Context": "CTX",
    "Regulator": "REG",
    "Approval Path": "APP",
}
CLASS_NAME = {
    "Indication": "Regulatory indication (one source row)",
    "Biomarker State": "Pre-coordinated biomarker analyte with result, variant or threshold",
    "Disease Extent": "Stage or extent of disease",
    "Disease Status": "Disease status, course or phase",
    "Response Contingency": "Event required before the indication applies",
    "Prior Therapy Requirement": "Prior treatment requirement or count band",
    "Co-therapy Requirement": "Required co-administered therapy not resolved to a HemOnc concept",
    "Population Qualifier": "Population restriction (menopausal status, risk, performance, ineligibility)",
    "Treatment Context": "Treatment setting not present in HemOnc Context",
    "Regulator": "Regulatory body issuing the approval",
    "Approval Path": "Regulatory approval pathway",
}
DOMAIN_OF = {
    c: "Indication"
    for c in (
        "Indication",
        "Regulator",
        "Approval Path",
    )
}
DOMAIN_OF.update({c: "Observation" for c in CLASS_CODE if c not in DOMAIN_OF})

ALLOWED_RESULTS = {
    "er": {"positive", "negative", "unknown"},
    "pr": {"positive", "negative", "unknown"},
    "her2": {"positive", "negative", "unknown", "low"},
    "mmr": {"deficient", "proficient"},
    "msi": {"high", "stable", "not high"},
}
COMPOSITES = {
    (frozenset({"mmr", "msi"}), frozenset({"proficient", "not high"})): (
        ("MMR", "proficient"),
        ("MSI", "not high"),
    ),
}
PLACEHOLDER_NAMES = {"0", "none", "not applicable", "true", "false"}


@dataclass(frozen=True)
class Term:
    """One ANDed element of a criterion alternative: a concept, a scalar, or both."""

    concept_id: int | None = None
    qualifier: str = ""
    cl: str = ""
    vl: str = ""
    ch: str = ""
    vh: str = ""
    unit: str = ""
    text: str = ""

    @property
    def has_scalar(self) -> bool:
        return bool(self.vl or self.vh)


CLASS_OWNER = {
    "Indication": "HemOnc",
    "Biomarker State": "OMOP Genomic",
    "Disease Extent": "OMOP Cancer Modifier",
    "Disease Status": "OMOP Cancer Modifier",
    "Response Contingency": "HemOnc",
    "Prior Therapy Requirement": "HemOnc",
    "Co-therapy Requirement": "HemOnc",
    "Population Qualifier": "OMOP vocabulary (SNOMED, CDISC)",
    "Treatment Context": "HemOnc",
    "Regulator": "HemOnc",
    "Approval Path": "HemOnc",
}
RELATIONSHIPS = [
    # id, name, reverse id, reverse name, hierarchical, defines_ancestry
    (
        "Ind has component",
        "Indication has component",
        "Component of ind",
        "Component of indication",
        0,
        0,
    ),
    (
        "Ind has condition",
        "Indication has condition",
        "Condition of ind",
        "Condition of indication",
        0,
        0,
    ),
    (
        "Ind has regimen",
        "Indication has regimen",
        "Regimen of ind",
        "Regimen of indication",
        0,
        0,
    ),
    (
        "Ind has regulator",
        "Indication has regulator",
        "Regulator of ind",
        "Regulator of indication",
        0,
        0,
    ),
    (
        "Ind has approval path",
        "Indication has approval path",
        "Approval path of ind",
        "Approval path of indication",
        0,
        0,
    ),
    (
        "Ind has context",
        "Indication has context",
        "Context of ind",
        "Context of indication",
        0,
        0,
    ),
    (
        "State has analyte",
        "Biomarker state has analyte",
        "Analyte of state",
        "Analyte of biomarker state",
        0,
        0,
    ),
    (
        "State has result",
        "Biomarker state has result",
        "Result of state",
        "Result of biomarker state",
        0,
        0,
    ),
    (
        "State has variant",
        "Biomarker state has variant",
        "Variant of state",
        "Variant of biomarker state",
        0,
        0,
    ),
    (
        "Clinically implies",
        "Clinically implies",
        "Clinically implied by",
        "Clinically implied by",
        0,
        0,
    ),
    (
        "Equiv in indic",
        "Equivalent in indication context",
        "Equiv in indic",
        "Equivalent in indication context",
        0,
        0,
    ),
    ("Opposite of", "Opposite polarity", "Opposite of", "Opposite polarity", 0, 0),
    ("Is a", "Is a", "Subsumes", "Subsumes", 0, 0),
    ("Subsumes", "Subsumes", "Is a", "Is a", 1, 1),
]
REVERSE = {r[0]: r[2] for r in RELATIONSHIPS}
REL_CONCEPT_BASE = 2_090_000_000
REVIEWED_RELATIONSHIPS = {"Is a", "Clinically implies", "Equiv in indic", "Opposite of"}
EXISTING_REL_CONCEPT_ID = {"Is a": 44818821, "Subsumes": 44818723}

RESULTS = {  # normalised finding -> (result concept id, label)
    "positive": (9191, "positive"),
    "negative": (9189, "negative"),
    "wild-type": (45880310, "wild type"),
    "present": (4181412, "present"),
    "high": (4328749, "high"),
    "low": (4267416, "low"),
    "deficient": (4126680, "deficient"),
}
DETECTED = 4126681
MSI_ANALYTE = 700490
GENDER = {"FEMALE": 8532, "MALE": 8507}
BIOMARKER_ALIASES = {
    "pd-l1": "PD-L1",
    "clnd18_2": "CLDN18.2",
    "cldn18 2": "CLDN18.2",
    "mage-a4 antigen": "MAGE-A4 antigen",
}
VARIANT_CLASSES = {
    "Gene Protein Variant",
    "Gene DNA Variant",
    "Structural Variant",
    "Gene RNA Variant",
    "Transcript Variant",
}
MUTATED_TOKENS = {
    "mutated",
    "mutation",
    "germline mutation",
    "somatic mutation",
    "activating mutation",
    "sensitizing mutation",
    "non-resistant mutation",
    "susceptible mutation",
    "tkd activating mutation",
    "itd",
    "deletion",
    "exon 19 deletion",
    "exon 20 insertion",
    "exon 14 skipping alteration",
    "exon 18 mutation",
}
FUSION_TOKENS = {
    "fusion",
    "rearrangement",
    "translocation",
    "fusion without known acquired resistance mutation",
    "rearrangement without a known acquired resistance mutation",
}
THRESHOLD = re.compile(
    r"^(?:(?P<assay>tps|cps|til)\s+)?(?P<cmp>at least|greater than|>=|>)\s*(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>%|ng/ml|mutations/mb)?(?P<tail>.*)$"
)


norm = normalise_source_value


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow(["" if cell is None else cell for cell in row])


RANK = {"exact": 0, "narrower": 1, "broader": 2, "none": 3}


class Existing:
    """Verified existing concepts (groundworkers snapshot) and the evidence rows that cite them."""

    def __init__(self) -> None:
        self.verified: dict[int, dict[str, str]] = {}
        for name in ("verified_ids.tsv", "verified_anchors.tsv"):
            path = EVIDENCE / name
            if path.exists():
                for row in read_tsv(path):
                    if (
                        row.get("found", "yes") == "yes"
                        and row["concept_id"].strip().isdigit()
                    ):
                        self.verified[int(row["concept_id"])] = row
        self.evidence: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for lane in ("A", "B", "C", "D", "E"):
            for row in read_tsv(EVIDENCE / f"lane{lane}.tsv"):
                self.evidence[row["column"]][norm(row["raw_value"])].append(row)
        for name, columns in (("population.tsv", None), ("descriptors.tsv", None)):
            path = EVIDENCE / name
            if not path.exists():
                continue
            replaced: set[tuple[str, str]] = set()
            for row in read_tsv(path):
                key = (row["column"], norm(row["raw_value"]))
                if key not in replaced:
                    self.evidence[row["column"]][key[1]] = []
                    replaced.add(key)
                if row.get("concept_id", "").strip().isdigit():
                    cid = row["concept_id"].strip()
                    row = {
                        **row,
                        "concept_id": cid,
                        "fit": row.get("fit", "none") or "none",
                    }
                    self.evidence[row["column"]][key[1]].append(row)

    def usable(self, concept_id: int) -> bool:
        info = self.verified.get(concept_id)
        if info is None:
            return False
        return (
            not info.get("invalid_reason", "").strip()
            and info.get("valid_end_date", "2099-12-31") >= "2099-12-31"
        )

    def acceptable_target(self, concept_id: int) -> bool:
        info = self.verified.get(concept_id)
        if info is None or not self.usable(concept_id):
            return False
        return info["vocabulary_id"] == "HemOnc" or info.get(
            "standard_concept", ""
        ) in {"S", "C"}

    def rows(self, column: str, raw: str) -> list[dict[str, str]]:
        found = self.evidence.get(column, {}).get(norm(raw), [])
        out = [r for r in found if r["concept_id"].strip().isdigit()]
        out.sort(
            key=lambda r: (
                RANK.get(r["fit"], 3),
                0 if r.get("standard_concept") in {"S", "C"} else 1,
            )
        )
        return out

    def nonstandard(self, column: str, raw: str) -> tuple[int, str] | None:
        """Verified, valid but non-standard match that cannot serve as a target."""
        for row in self.rows(column, raw):
            cid = int(row["concept_id"])
            if self.usable(cid) and not self.acceptable_target(cid):
                return cid, row["fit"]
        return None

    def best(
        self, column: str, raw: str, *, classes: set[str] | None = None
    ) -> tuple[int, str] | None:
        """Best verified existing concept for a source value as (id, fit)."""
        for row in self.rows(column, raw):
            cid = int(row["concept_id"])
            if classes is not None and row["concept_class_id"] not in classes:
                continue
            if self.acceptable_target(cid):
                return cid, row["fit"]
        return None


class Builder:
    def __init__(self, existing: Existing) -> None:
        self.ex = existing
        self.concepts: dict[str, dict[str, object]] = {}
        self.ids: dict[str, int] = {}
        self.next_in_class: Counter[str] = Counter()
        self.relationships: set[tuple[int, int, str]] = set()
        self.review: dict[tuple[int, int, str], dict[str, str]] = {}
        self.status: dict[str, dict[str, str]] = {}
        self.source_map: dict[tuple[str, str, str], dict[str, object]] = {}
        self.value_terms: dict[tuple[str, str, str], tuple[str, str, list]] = {}
        self.criteria_rows: list[list[object]] = []
        self.term_rows: list[list[object]] = []
        self.cited_existing: dict[int, set[str]] = defaultdict(set)
        self.previous = self._previous_ids()
        self.state_columns: dict[tuple[str, str], int] = {}
        self.unresolved: list[list[object]] = []

    @staticmethod
    def _previous_ids() -> dict[str, int]:
        path = OUT / "concept.tsv"
        if not path.exists():
            return {}
        return {row["concept_code"]: int(row["concept_id"]) for row in read_tsv(path)}

    def concept(
        self,
        cls: str,
        key: str,
        name: str,
        *,
        owner: str | None = None,
        provenance: str = "proposed, needs clinical review",
        status: str = "proposed-new",
        start: str = "1970-01-01",
        end: str = "2099-12-31",
        invalid: str = "",
    ) -> int:
        code = f"HOL-{CLASS_CODE[cls]}-{key}"
        if code in self.ids:
            return self.ids[code]
        if code in self.previous:
            cid = self.previous[code]
        else:
            used = {v for v in self.ids.values()} | set(self.previous.values())
            cid = LOCAL_BASE + BLOCKS[cls] + 1 + self.next_in_class[cls]
            while cid in used:
                cid += 1
        self.next_in_class[cls] = max(
            self.next_in_class[cls], cid - LOCAL_BASE - BLOCKS[cls]
        )
        self.ids[code] = cid
        self.concepts[code] = {
            "concept_id": cid,
            "concept_name": name[:255],
            "domain_id": DOMAIN_OF[cls],
            "vocabulary_id": VOCAB,
            "concept_class_id": cls,
            "standard_concept": "",
            "concept_code": code,
            "valid_start_date": start,
            "valid_end_date": end,
            "invalid_reason": invalid,
        }
        self.status[code] = {
            "concept_id": str(cid),
            "status": status,
            "provenance": provenance,
            "proposed_owner": owner or CLASS_OWNER[cls],
            "review_status": "proposed",
        }
        return cid

    def relate(
        self,
        a: int,
        b: int,
        rel: str,
        *,
        review: dict[str, str] | None = None,
        cite: str = "",
    ) -> None:
        self.relationships.add((a, b, rel))
        self.relationships.add((b, a, REVERSE[rel]))
        for cid in (a, b):
            if cid < LOCAL_BASE:
                self.cited_existing[cid].add(cite or rel)
        if review is not None:
            self.review[(a, b, rel)] = review

    def cid(self, cls: str, key: str) -> int | None:
        return self.ids.get(f"HOL-{CLASS_CODE[cls]}-{key}")

    def map_source(
        self,
        column: str,
        raw: str,
        context: str,
        target: int,
        fit: str,
        status: str,
        provenance: str,
    ) -> None:
        self.source_map[(column, norm(raw), norm(context))] = {
            "source_column": column,
            "raw_value": raw,
            "context": context,
            "target_concept_id": target,
            "target_kind": "existing" if target < LOCAL_BASE else "local",
            "fit": fit,
            "status": status,
            "provenance": provenance,
        }


def slug(text_value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._+-]+", "-", text_value.strip()).strip("-")[:90]


# ---------------------------------------------------------------- database


def fetch(
    engine,
) -> tuple[
    list[dict[str, object]],
    dict[str, dict[int, list[str]]],
    dict[str, dict[str, tuple[int, str, str]]],
]:
    with engine.connect() as conn:
        rows = [
            dict(r._mapping)
            for r in conn.execute(text("select * from indications order by id"))
        ]
        children: dict[str, dict[int, list[str]]] = {}
        for table, column in (
            ("biomarker2", "biomarker2"),
            ("biomarker3", "biomarker3"),
            ("biomarker4", "biomarker4"),
            ("biomarker2_finding", "biomarker2_finding"),
            ("biomarker3_finding", "biomarker3_finding"),
            ("biomarker4_finding", "biomarker4_finding"),
            ("context", "context"),
            ("demographics", "demographics"),
            ("prior_therapy_setting", "prior_therapy_setting"),
            ("prior_therapy_negation", "prior_therapy_negation"),
            ("response_contingency", "response_contingency"),
            ("risk_stratification", "risk_stratification"),
            ("regimen_cui", "regimen_cui"),
        ):
            data: dict[int, list[str]] = defaultdict(list)
            enum = getattr(model_enums, f"Indications_{column.capitalize()}Enum", None)
            for parent, value in conn.execute(
                text(
                    f"select parent_id, {column}::text from indications_{table} order by parent_id, ctid"
                )
            ):
                data[parent].append(
                    enum[value].value
                    if enum is not None and value in enum.__members__
                    else value
                )
            children[column] = data
        codes: dict[str, dict[str, tuple[int, str, str]]] = defaultdict(dict)
        for cid, code, cls, name in conn.execute(
            text(
                "select concept_id, concept_code, concept_class_id, concept_name from concept where vocabulary_id='HemOnc'"
            )
        ):
            codes[cls][code] = (cid, name, cls)
    return rows, children, codes


def split_pipe(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").split("|") if p.strip()]


def is_placeholder(value: str) -> bool:
    return norm(value) in {"", "not applicable"}


# ---------------------------------------------------------------- bounds


def parse_age(raw: str, unit: str | None) -> dict[str, object] | None:
    low = raw.strip()
    if m := re.fullmatch(r"(\d+)\+", low):
        return {"cl": ">=", "vl": int(m[1]), "ch": "", "vh": "", "unit": unit}
    if m := re.fullmatch(r"(\d+)-", low):
        return {"cl": "", "vl": "", "ch": "<=", "vh": int(m[1]), "unit": unit}
    if m := re.fullmatch(r"(\d+)\s+to\s+(\d+)", low, re.IGNORECASE):
        return {"cl": ">=", "vl": int(m[1]), "ch": "<=", "vh": int(m[2]), "unit": unit}
    if m := re.fullmatch(r"(\d+)\s+to\s+(nubp|nubya)", low, re.IGNORECASE):
        return {"cl": ">=", "vl": int(m[1]), "ch": "", "vh": "", "unit": unit}
    if m := re.fullmatch(r"\d+", low):
        return {"cl": "=", "vl": int(low), "ch": "", "vh": "", "unit": unit}
    return None


def parse_count(raw: str) -> tuple[dict[str, object], str] | None:
    """Leading number-of-prior-lines expression: (bounds, remainder)."""
    m = re.match(
        r"^(\d+)(?:\s*(\+)|\s+to\s+(\d+)|\s+or\s+(\d+)|-(\d+))?\s*,?\s*(.*)$",
        raw.strip(),
        re.IGNORECASE,
    )
    if not m:
        return None
    low, plus, to, orr, dash, rest = m.groups()
    if plus:
        bounds = {"cl": ">=", "vl": int(low), "ch": "", "vh": ""}
    elif to or orr or dash:
        bounds = {"cl": ">=", "vl": int(low), "ch": "<=", "vh": int(to or orr or dash)}
    else:
        bounds = {"cl": "=", "vl": int(low), "ch": "", "vh": ""}
    bounds["unit"] = "lines"
    return bounds, rest


def parse_window(raw: str) -> dict[str, object] | None:
    low = norm(raw)
    m = re.search(
        r"(within|up to|at least|less than|on or within)?\s*(\d+|one)\s*(day|week|month|year)s?",
        low,
    )
    if not m:
        return None
    qualifier, number, unit = m.groups()
    value = 1 if number == "one" else int(number)
    if qualifier in {"within", "up to", "on or within"}:
        return {"cl": "", "vl": "", "ch": "<=", "vh": value, "unit": unit}
    if qualifier == "at least":
        return {"cl": ">=", "vl": value, "ch": "", "vh": "", "unit": unit}
    if qualifier == "less than":
        return {"cl": "", "vl": "", "ch": "<", "vh": value, "unit": unit}
    return {"cl": "=", "vl": value, "ch": "", "vh": "", "unit": unit}


def parse_threshold(finding: str) -> dict[str, object] | None:
    low = norm(finding)
    if m := re.match(r"^>=\s*(\d+(?:\.\d+)?)\s*mutations/mb$", low):
        return {
            "qualifier": "",
            "cl": ">=",
            "vl": float(m[1]),
            "ch": "",
            "vh": "",
            "unit": "mut/Mb",
        }
    if m := re.match(r"^>(\d+)% of tumor cells with strong \(3\+ ihc\) staining$", low):
        return {
            "qualifier": "IHC 3+",
            "cl": ">",
            "vl": float(m[1]),
            "ch": "",
            "vh": "",
            "unit": "%",
        }
    m = THRESHOLD.match(low)
    if not m or m["tail"].strip():
        return None
    unit = m["unit"] or ""
    assay = (m["assay"] or "").upper()
    if assay == "CPS":
        unit = "score"
    unit = (
        "mut/Mb" if unit == "mutations/mb" else ("ng/mL" if unit == "ng/ml" else unit)
    )
    cmp = ">" if m["cmp"] in {"greater than", ">"} else ">="
    return {
        "qualifier": assay,
        "cl": cmp,
        "vl": float(m["val"]),
        "ch": "",
        "vh": "",
        "unit": unit,
    }


# ---------------------------------------------------------------- resolution

DISEASE_COLUMNS = ("status", "stage", "stage_or_status")
EXTENT_WORDS = {
    "locally advanced",
    "advanced",
    "metastatic",
    "early",
    "localized",
    "regionally advanced",
    "limited stage",
    "extensive stage",
    "node positive",
    "inflammatory",
    "non metastatic",
    "muscle invasive",
    "non muscle invasive",
}
LEXICON = sorted(
    {
        "unresectable",
        "resectable",
        "locally advanced",
        "advanced",
        "metastatic",
        "recurrent",
        "relapsed",
        "refractory",
        "locally recurrent",
        "primary",
        "inoperable",
        "early",
        "localized",
        "regionally advanced",
        "persistent",
        "progressive",
        "newly diagnosed",
        "untreated",
        "active",
        "symptomatic",
        "chronic phase",
        "accelerated phase",
        "blast crisis",
    },
    key=len,
    reverse=True,
)
DISEASE_EDGES = (
    ("locally advanced", "advanced"),
    ("metastatic", "advanced"),
    ("regionally advanced", "advanced"),
    ("locally recurrent", "recurrent"),
    ("first recurrence", "recurrent"),
    ("first relapse", "relapsed"),
)
DISEASE_ALIASES = {
    "localled advanced": "locally advanced",
    "early stage": "early",
    "extensive-stage": "extensive stage",
    "node-positive": "node positive",
    "non-metastatic": "non metastatic",
}


class Vocabulary(Builder):
    def __init__(
        self, existing: Existing, anchors: dict[str, dict[str, tuple[int, str, str]]]
    ) -> None:
        super().__init__(existing)
        self.anchors = anchors
        self.cache: dict[tuple[str, str], tuple[int, str, str]] = {}
        self.used_states: dict[int, set[int]] = defaultdict(set)
        self.notes: list[list[object]] = []
        self.gene_states: dict[str, dict[str, int]] = defaultdict(dict)
        self.state_meta: dict[int, dict[str, object]] = {}
        self.mapping_rows: dict[tuple[str, str, str], dict[str, object]] = {}
        self.gene_case: dict[str, str] = {}
        self.static()

    # ---- static concepts
    def static(self) -> None:
        self.regulators = {
            name: self.concept(
                "Regulator",
                name,
                name,
                owner="HemOnc",
                provenance="regulator values of the indications table",
            )
            for name in ("FDA", "EMA", "PMDA", "HC", "MFDS", "NMPA")
        }
        self.accelerated = self.concept(
            "Approval Path",
            "ACCELERATED",
            "Accelerated approval",
            owner="HemOnc",
            provenance="accelerated flag of the indications table",
        )

    # ---- existing concept helpers
    def name_of(self, cid: int) -> str:
        for info in self.concepts.values():
            if info["concept_id"] == cid:
                return str(info["concept_name"])
        v = self.ex.verified.get(cid)
        return v["concept_name"] if v else str(cid)

    def _name_index(self) -> dict[int, str]:
        if getattr(self, "_names_n", -1) != len(self.concepts):
            self._names = {
                int(i["concept_id"]): str(i["concept_name"])
                for i in self.concepts.values()
            }
            self._names_n = len(self.concepts)
        return self._names

    def label(self, cid: int) -> str:
        names = self._name_index()
        if cid in names:
            return names[cid]
        v = self.ex.verified.get(cid)
        return v["concept_name"] if v else str(cid)

    def cite(self, column: str, raw: str, cid: int, fit: str, role: str) -> None:
        v = self.ex.verified[cid]
        self.mapping_rows[(column, norm(raw), str(cid))] = {
            "source_column": column,
            "raw_value": raw,
            "context": "",
            "concept_id": cid,
            "concept_name": v["concept_name"],
            "vocabulary_id": v["vocabulary_id"],
            "concept_class_id": v["concept_class_id"],
            "standard_concept": v.get("standard_concept", ""),
            "fit": fit,
            "used_as": role,
            "status": "mapped-to-existing",
            "verified_on": VERIFIED_ON,
        }

    def local_value(
        self,
        column: str,
        raw: str,
        cls: str,
        *,
        shared_key: str | None = None,
        name: str | None = None,
        owner: str | None = None,
        ex_rows: bool = True,
    ) -> tuple[int, str, str]:
        """Concept for one source value: verified existing exact match, else a local concept."""
        key = (cls, shared_key or norm(raw))
        if key in self.cache:
            cid, fit, status = self.cache[key]
            self.map_source(column, raw, "", cid, fit, status, "see concept_status")
            return cid, fit, status
        best = self.ex.best(column, raw) if ex_rows else None
        if best and best[1] == "exact":
            cid, fit, status = best[0], "exact", "mapped-to-existing"
            self.cite(column, raw, cid, fit, "target")
        else:
            label = name or raw.strip()
            cid = self.concept(
                cls,
                slug(shared_key or norm(raw)),
                label,
                owner=owner,
                provenance="proposed, needs clinical review: no adequate existing concept",
            )
            fit, status = "none", "proposed-new"
            if not best and (alt := self.ex.nonstandard(column, raw)):
                self.cite(column, raw, alt[0], alt[1], "candidate, non-standard")
            if best:
                fit = best[1]
                self.cite(column, raw, best[0], fit, "candidate")
                if best[1] == "broader":
                    self.relate(
                        cid,
                        best[0],
                        "Is a",
                        review={
                            "status": "proposed",
                            "provenance": f"existing concept is broader than '{raw}' (evidence lane)",
                            "reviewer": "",
                            "reviewed_on": "",
                            "priority": "later",
                            "note": "",
                        },
                    )
        self.cache[key] = (cid, fit, status)
        self.map_source(column, raw, "", cid, fit, status, "see concept_status")
        return cid, fit, status

    # ---- disease words (stage, status, stage_or_status)
    def disease_token(self, token: str, column: str) -> int:
        key = norm(DISEASE_ALIASES.get(norm(token), token))
        if ("disease", key) in self.cache:
            return self.cache[("disease", key)][0]
        cls = (
            "Disease Extent"
            if key in EXTENT_WORDS or re.match(r"^(stage|figo|dukes|d2)", key)
            else "Disease Status"
        )
        for col in (column, *DISEASE_COLUMNS):
            best = self.ex.best(col, token) or self.ex.best(col, key)
            if best and best[1] == "exact":
                self.cache[("disease", key)] = (best[0], "exact", "mapped-to-existing")
                self.cite(col, token, best[0], "exact", "target")
                return best[0]
        cid = self.concept(
            cls,
            slug(key),
            key.capitalize(),
            provenance="proposed, needs clinical review: no adequate standard existing concept",
        )
        best = next(
            (
                b
                for col in (column, *DISEASE_COLUMNS)
                if (b := self.ex.best(col, token) or self.ex.best(col, key))
            ),
            None,
        )
        if not best:
            for col in (column, *DISEASE_COLUMNS):
                if alt := self.ex.nonstandard(col, token) or self.ex.nonstandard(
                    col, key
                ):
                    self.cite(col, token, alt[0], alt[1], "candidate, non-standard")
                    break
        fit = "none"
        if best:
            fit = best[1]
            self.cite(column, token, best[0], fit, "candidate")
            if fit == "broader":
                self.relate(
                    cid,
                    best[0],
                    "Is a",
                    review={
                        "status": "proposed",
                        "provenance": "existing concept is broader (evidence lane)",
                        "reviewer": "",
                        "reviewed_on": "",
                        "priority": "later",
                        "note": "",
                    },
                )
        self.cache[("disease", key)] = (cid, fit, "proposed-new")
        return cid

    def disease_alternatives(self, column: str, raw: str) -> list[list[int]]:
        norm_raw = norm(re.sub(r"\([^()]*\)", " ", raw))
        norm_raw = DISEASE_ALIASES.get(norm_raw, norm_raw)
        whole = self.ex.best(column, raw)
        if whole and whole[1] == "exact":
            cid, _, _ = self.local_value(column, raw, "Disease Status")
            return [[cid]]
        parts = re.split(r"\s+or\s+", norm_raw)
        if len(parts) > 1 and all(self.lexicon_ok(p) for p in parts):
            return [self.lexicon_and(p, column) for p in parts]
        if self.lexicon_ok(norm_raw):
            return [self.lexicon_and(norm_raw, column)]
        cls = "Disease Extent" if column == "stage" else "Disease Status"
        cid, _, _ = self.local_value(
            column, raw, cls, shared_key=norm_raw, name=re.sub(r"\s+", " ", raw.strip())
        )
        return [[cid]]

    @staticmethod
    def lexicon_split(text_value: str) -> list[str] | None:
        rest = re.sub(r"[,/-]", " ", text_value)
        found = []
        for phrase in LEXICON:
            pattern = rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])"
            if re.search(pattern, rest):
                found.append(phrase)
                rest = re.sub(pattern, " ", rest)
        residue = " ".join(w for w in rest.split() if w not in {"and", "to", "of"})
        return found if found and not residue else None

    def lexicon_ok(self, text_value: str) -> bool:
        return self.lexicon_split(text_value) is not None

    def lexicon_and(self, text_value: str, column: str) -> list[int]:
        return [
            self.disease_token(t, column) for t in self.lexicon_split(text_value) or []
        ]

    def link_disease_values(self) -> None:
        for child, parent in DISEASE_EDGES:
            child_key, parent_key = norm(child), norm(parent)
            if ("disease", child_key) not in self.cache and not any(
                k[1] == child_key for k in self.cache if k[0] != "disease"
            ):
                continue
            cid = self.cache.get(("disease", child_key), (None,))[0]
            if cid is None:
                continue
            pid = self.disease_token(parent_key, "status")
            if cid != pid:
                self.relate(
                    cid,
                    pid,
                    "Is a",
                    review={
                        "status": "proposed",
                        "provenance": f"clinical judgement: '{child}' is a kind of '{parent}'; no such link in SNOMED or Cancer Modifier",
                        "reviewer": "",
                        "reviewed_on": "",
                        "priority": "later",
                        "note": "",
                    },
                )

    # ---- sets
    # ---- biomarkers
    def gene_name(self, raw: str) -> str:
        key = norm(raw)
        return BIOMARKER_ALIASES.get(key) or self.gene_case.get(key, raw.strip())

    def analyte(self, gene: str, protein_first: bool) -> tuple[int | None, str]:
        if norm(gene) == "msi":
            return MSI_ANALYTE, "exact"
        candidates = []
        for row in self.ex.rows("biomarker", gene):
            cid = int(row["concept_id"])
            if not self.ex.acceptable_target(cid):
                continue
            is_gene = row["concept_class_id"] == "Genetic Variation"
            is_test = row["concept_class_id"] in {
                "Lab Test",
                "Observable Entity",
                "Clinical Observation",
                "Measurement",
            }
            fit_rank = RANK.get(row["fit"], 3)
            if is_gene or is_test:
                candidates.append(
                    (0 if (is_test == protein_first) else 1, fit_rank, cid, row["fit"])
                )
        if not candidates:
            return None, "none"
        candidates.sort()
        _, _, cid, fit = candidates[0]
        return cid, fit

    def variant_for(self, gene: str, finding: str) -> int | None:
        for row in self.ex.rows("biomarker_finding", finding):
            ctx = row.get("gene_context", "")
            if row["fit"] != "exact" or row["concept_class_id"] not in VARIANT_CLASSES:
                continue
            cid = int(row["concept_id"])
            gene_ok = norm(gene) in norm(ctx).replace("/", " ").split() or norm(
                gene
            ) in {norm(g) for g in ctx.split("/")}
            if gene_ok and self.ex.acceptable_target(cid):
                return cid
        return None

    def finding_kind(self, f: str) -> str:
        if parse_threshold(f):
            return "threshold"
        if f in MUTATED_TOKENS or f.startswith(("p.", "exon ")):
            return "variant"
        if f in FUSION_TOKENS:
            return "fusion"
        return "result"

    def state_key(self, gene_raw: str, finding_raw: str) -> tuple[str, str]:
        gene = self.gene_name(gene_raw)
        f = {"mutation": "mutated"}.get(norm(finding_raw), norm(finding_raw))
        bounds = parse_threshold(f)
        if bounds:
            f = f"score {bounds['qualifier'].lower()}".strip()
        return gene, f

    @staticmethod
    def finding_label(finding_raw: str) -> str:
        label = finding_raw.strip()
        if "_" in label or label.isupper():
            label = norm(label)
            label = re.sub(r"\b(cps|tps|til|ihc|ish)\b", lambda m: m[1].upper(), label)
        return label

    @staticmethod
    def finding_scalar(finding_raw: str) -> dict[str, object] | None:
        """Numeric cut-off of a finding, held as an attribute and not as a concept."""
        return parse_threshold(norm(finding_raw))

    def state(
        self, gene_raw: str, finding_raw: str, indication: int | None = None
    ) -> int:
        gene, f_key = self.state_key(gene_raw, finding_raw)
        f = norm(finding_raw)
        f = {"mutation": "mutated"}.get(f, f)
        cache_key = (gene, f_key)
        if cache_key in self.state_columns:
            sid = self.state_columns[cache_key]
        else:
            kind = self.finding_kind(f)
            bounds = parse_threshold(f) if kind == "threshold" else None
            label = self.finding_label(finding_raw)
            if bounds:
                label = bounds["qualifier"] or "measured value"
            sid = self.concept(
                "Biomarker State",
                slug(f"{gene}-{f_key}"),
                f"{gene}: {label}",
                provenance="proposed, needs clinical review: pre-coordinated from the indications table",
                owner="OMOP Genomic"
                if kind in {"variant", "fusion"}
                else "HemOnc / OMOP vocabulary",
            )
            self.state_columns[cache_key] = sid
            self.gene_states[gene][f_key] = sid
            self.state_meta[sid] = {"gene": gene, "finding": f_key, "kind": kind}
            protein_first = kind in {"result", "threshold"} and f != "wild-type"
            analyte, _ = self.analyte(gene, protein_first)
            if analyte:
                self.relate(sid, analyte, "State has analyte", cite="analyte")
            if kind in {"variant", "fusion"}:
                self.relate(sid, DETECTED, "State has result", cite="result")
                variant = self.variant_for(
                    gene, finding_raw.strip()
                ) or self.variant_for(gene, f)
                if variant:
                    self.relate(sid, variant, "State has variant", cite="variant")
            elif kind != "threshold":
                base = re.sub(r"\s*\(.*\)$", "", f)
                if base in RESULTS:
                    self.relate(
                        sid, RESULTS[base][0], "State has result", cite="result"
                    )
        if indication is not None:
            self.used_states[indication].add(sid)
        return sid

    def state_term(
        self, gene_raw: str, finding_raw: str, indication: int | None = None
    ) -> Term:
        sid = self.state(gene_raw, finding_raw, indication)
        bounds = self.finding_scalar(finding_raw)
        if bounds is None:
            return Term(sid)
        return Term(
            sid,
            qualifier=str(bounds["qualifier"]),
            cl=str(bounds["cl"]),
            vl=f"{bounds['vl']:g}",
            unit=str(bounds["unit"]),
        )

    @staticmethod
    def result_base(finding: str) -> str:
        return re.sub(r"\s*\(.*\)( or .*)?$", "", norm(finding))

    def allowed(self, gene: str, finding: str) -> bool:
        results = ALLOWED_RESULTS.get(norm(gene))
        if results is None or self.finding_kind(norm(finding)) != "result":
            return True
        return self.result_base(finding) in results

    def pairs(
        self, genes: list[str], findings: list[str]
    ) -> tuple[str, list[tuple[str, str]]]:
        """Reading of a slot: ('any' | 'all', pairs) from an independent OR cross product."""
        gene_keys = frozenset(norm(g) for g in genes)
        finding_keys = frozenset(norm(f) for f in findings)
        composite = COMPOSITES.get((gene_keys, finding_keys))
        if composite:
            return "all", list(composite)
        product = list(
            dict.fromkeys(
                (g, f) for g in dict.fromkeys(genes) for f in dict.fromkeys(findings)
            )
        )
        kept = [(g, f) for g, f in product if self.allowed(g, f)]
        return "any", kept or product

    @staticmethod
    def positional_pairs(
        genes: list[str], findings: list[str]
    ) -> list[tuple[str, str]]:
        if len(genes) == len(findings):
            return list(zip(genes, findings, strict=True))
        if len(genes) == 1:
            return [(genes[0], f) for f in findings]
        if len(findings) == 1:
            return [(g, findings[0]) for g in genes]
        return [(g, f) for g in genes for f in findings]

    def slot_note(
        self,
        rid: int,
        column: str,
        genes_raw: object,
        findings_raw: object,
        genes: list[str],
        findings: list[str],
        mode: str,
        pairs: list[tuple[str, str]],
    ) -> None:
        old = {
            (self.gene_name(g), self.state_key(g, f)[1])
            for g, f in self.positional_pairs(genes, findings)
        }
        new = {(self.gene_name(g), self.state_key(g, f)[1]) for g, f in pairs}
        if mode == "any" and old == new:
            return
        join = " AND " if mode == "all" else " OR "
        self.notes.append(
            [
                rid,
                column,
                f"{genes_raw} / {findings_raw}",
                "reading changed; old: "
                + " OR ".join(f"{g}: {f}" for g, f in sorted(old))
                + "; new: "
                + join.join(f"{g}: {f}" for g, f in sorted(new)),
            ]
        )

    def link_biomarker_values(self) -> None:
        """Hierarchy and polarity edges between the states created from the data."""
        import yaml

        path = EVIDENCE / "curated_implications.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for entry in data["implications"]:
            for token in (entry["finding"], *entry["satisfies"]):
                self.state(entry["biomarker"], token)
        for gene, states in list(self.gene_states.items()):
            mutated_children = [
                s
                for f, s in states.items()
                if self.state_meta[s]["kind"] == "variant" and f != "mutated"
            ]
            if mutated_children and "mutated" not in states:
                self.state(gene, "mutated")
            mutated = states.get("mutated")
            for f, sid in list(states.items()):
                meta = self.state_meta[sid]
                if meta["kind"] == "variant" and mutated and sid != mutated:
                    self.relate(
                        sid,
                        mutated,
                        "Is a",
                        review={
                            "status": "proposed",
                            "provenance": "structural rule: a specific variant or mutation class is a kind of mutation of the gene",
                            "reviewer": "",
                            "reviewed_on": "",
                            "priority": "later",
                            "note": "",
                        },
                    )
                if m := re.match(r"^(p\.[a-z]\d+)[a-z*=]$", f):
                    parent = states.get(m[1])
                    if parent:
                        self.relate(
                            sid,
                            parent,
                            "Is a",
                            review={
                                "status": "proposed",
                                "provenance": "structural rule: protein substitution at a codon is a kind of change at that codon",
                                "reviewer": "",
                                "reviewed_on": "",
                                "priority": "later",
                                "note": "",
                            },
                        )
                if m := re.match(r"^(positive|negative|low) \(.*\)( or .*)?$", f):
                    parent = states.get(m[1])
                    if parent:
                        self.relate(
                            sid,
                            parent,
                            "Is a",
                            review={
                                "status": "proposed",
                                "provenance": "structural rule: a qualified result is a kind of the plain result",
                                "reviewer": "",
                                "reviewed_on": "",
                                "priority": "later",
                                "note": "",
                            },
                        )
            for a, b in (
                ("positive", "negative"),
                ("mutated", "wild-type"),
                ("deficient", "proficient"),
                ("high", "not high"),
            ):
                if a in states and b in states:
                    self.relate(
                        states[a],
                        states[b],
                        "Opposite of",
                        review={
                            "status": "proposed",
                            "provenance": "polarity pair of results for the same analyte",
                            "reviewer": "",
                            "reviewed_on": "",
                            "priority": "later",
                            "note": "",
                        },
                    )
        # reviewed-in-code implications carried over as proposed, with their original source text
        entries = {
            (e["biomarker"].casefold(), norm(e["finding"])): e
            for e in data["implications"]
        }
        for (gene_key, finding), entry in entries.items():
            gene = self.gene_name(entry["biomarker"])
            for target in entry["satisfies"]:
                reverse = entries.get((gene_key, norm(target)))
                src = self.state(gene, entry["finding"])
                dst = self.state(gene, target)
                review = {
                    "status": "proposed",
                    "provenance": "carried over from the earlier finding implication data; no external citation supplied",
                    "reviewer": "",
                    "reviewed_on": "",
                    "priority": "later",
                    "note": "confirm the target classes and identify a clinical source",
                }
                if reverse and norm(entry["finding"]) in [
                    norm(t) for t in reverse["satisfies"]
                ]:
                    if src < dst:
                        self.relate(src, dst, "Equiv in indic", review=review)
                else:
                    self.relate(src, dst, "Clinically implies", review=review)

    # ---- other criteria
    def or_alternatives(
        self, column: str, raw: str, cls: str, *, split: bool
    ) -> list[list[int]]:
        whole = self.ex.best(column, raw)
        if not (whole and whole[1] == "exact") and split:
            parts = [
                p.strip()
                for p in re.split(r",\s*or\s+|\s+or\s+|,\s+", raw)
                if p.strip()
            ]
            if len(parts) > 1 and all(len(p.split()) <= 4 for p in parts):
                out = []
                for part in parts:
                    cid, _, _ = self.local_value(column, part, cls, ex_rows=True)
                    out.append([cid])
                return out
        cid, _, _ = self.local_value(column, raw, cls)
        return [[cid]]

    def therapy_leaf(self, column: str, token: str, cls: str) -> int:
        key = (cls, norm(token))
        if key in self.cache:
            return self.cache[key][0]
        best = self.ex.best(column, token) or self.ex.best(
            "prior_therapy" if column == "with_field" else "with_field", token
        )
        if best and best[1] == "exact":
            cid = best[0]
            self.cite(column, token, cid, "exact", "target")
            self.cache[key] = (cid, "exact", "mapped-to-existing")
            return cid
        cid = self.concept(
            cls,
            slug(norm(token)),
            token.strip(),
            provenance="proposed, needs clinical review: no adequate existing concept",
        )
        fit = "none"
        if not best and (alt := self.ex.nonstandard(column, token)):
            self.cite(column, token, alt[0], alt[1], "candidate, non-standard")
        if best:
            fit = best[1]
            self.cite(column, token, best[0], fit, "candidate")
            if fit == "broader":
                self.relate(
                    cid,
                    best[0],
                    "Is a",
                    review={
                        "status": "proposed",
                        "provenance": f"existing concept is broader than '{token}'",
                        "reviewer": "",
                        "reviewed_on": "",
                        "priority": "later",
                        "note": "",
                    },
                )
        self.cache[key] = (cid, fit, "proposed-new")
        return cid

    @staticmethod
    def scalar_term(
        bounds: dict[str, object], unit: str, *, qualifier: str = "", text: str = ""
    ) -> Term:
        def fmt(value: object) -> str:
            return "" if value in ("", None) else f"{float(value):g}"  # type: ignore[arg-type]

        return Term(
            None,
            qualifier,
            str(bounds.get("cl", "")),
            fmt(bounds.get("vl", "")),
            str(bounds.get("ch", "")),
            fmt(bounds.get("vh", "")),
            unit,
            text,
        )

    def count_term(self, raw: str) -> Term:
        parsed = parse_count(raw)
        assert parsed is not None
        return self.scalar_term(parsed[0], "lines")

    @staticmethod
    def concept_terms(alternatives: list[list[int]]) -> list[list[Term]]:
        return [[Term(c) for c in alt] for alt in alternatives]

    def record_value(
        self,
        column: str,
        raw: str,
        alternatives: list[list[Term]],
        *,
        context: str = "",
        provenance: str = "",
    ) -> None:
        """Register how one raw value reads: a single concept, or terms held in the native tables."""
        key = (column, norm(raw), norm(context))
        single = len(alternatives) == 1 and len(alternatives[0]) == 1
        term = alternatives[0][0] if single else None
        if term is not None and term.concept_id is not None:
            if key not in self.source_map:
                target = term.concept_id
                self.map_source(
                    column,
                    raw,
                    context,
                    target,
                    "none",
                    "proposed-new" if target >= LOCAL_BASE else "mapped-to-existing",
                    provenance,
                )
            if term.has_scalar:
                self.value_terms[key] = (raw, context, alternatives)
            return
        self.map_source(column, raw, context, 0, "none", "decomposed", provenance)
        self.value_terms[key] = (raw, context, alternatives)

    def therapy_alternatives(
        self, column: str, raw: str, cls: str, indication: int
    ) -> list[list[Term]]:
        alternatives = []
        for part in split_pipe(raw):
            if is_placeholder(part):
                continue
            members: list[Term] = []
            rest = part
            if column == "with_field" and norm(part) == "0":
                members.append(Term(self.monotherapy()))
                rest = ""
            if column == "prior_therapy":
                parsed = parse_count(part)
                if parsed:
                    prefix = re.match(
                        r"^(\d+(?:\s*\+|\s+to\s+\d+|\s+or\s+\d+|-\d+)?)", part
                    )
                    assert prefix is not None
                    members.append(self.count_term(prefix.group(1)))
                    rest = parsed[1]
            for token in re.split(r"\s+AND\s+|,\s+(?:and\s+)?|\s+and\s+", rest):
                token = re.sub(
                    r"^(including|and|an|a)\s+",
                    "",
                    token.strip().strip("()").strip(),
                    flags=re.IGNORECASE,
                ).strip()
                if token:
                    members.append(Term(self.therapy_leaf(column, token, cls)))
            if members:
                members = list(dict.fromkeys(members))
                alternatives.append(members)
                self.record_value(
                    column, part, [members], provenance="decomposed therapy descriptors"
                )
        return alternatives

    def monotherapy(self) -> int:
        return self.concept(
            "Co-therapy Requirement",
            "MONOTHERAPY",
            "Monotherapy (no co-therapy)",
            provenance="with_field value 0 of the indications table: no co-therapy required",
        )

    def population_leaf(self, column: str, value: str, cls: str) -> int:
        if column == "ineligibility" and norm(value) == "none":
            return self.local_value(
                column,
                value,
                cls,
                shared_key="no-ineligibility-restriction",
                name="No ineligibility restriction",
            )[0]
        return self.local_value(column, value, cls)[0]

    def build_criteria(
        self, r: dict[str, object], ch: dict[str, dict[int, list[str]]], indication: int
    ) -> list[tuple[str, str, list[list[Term]]]]:
        out: list[tuple[str, str, list[list[Term]]]] = []
        rid = int(r["id"])
        slots = [(r["biomarker"], r["biomarker_finding"])]
        for n in (2, 3, 4):
            slots.append(
                (
                    "|".join(ch[f"biomarker{n}"].get(rid, [])),
                    "|".join(ch[f"biomarker{n}_finding"].get(rid, [])),
                )
            )
        for index, (genes_raw, findings_raw) in enumerate(slots, start=1):
            genes, findings = (
                split_pipe(str(genes_raw or "")),
                split_pipe(str(findings_raw or "")),
            )
            if not genes or not findings:
                continue
            mode, pairs = self.pairs(genes, findings)
            self.slot_note(
                rid,
                f"biomarker{index}" if index > 1 else "biomarker",
                genes_raw,
                findings_raw,
                genes,
                findings,
                mode,
                pairs,
            )
            terms = []
            for gene, finding in pairs:
                terms.append(self.state_term(gene, finding, rid))
                self.map_state_source(gene, finding)
            terms = list(dict.fromkeys(terms))
            alts = [terms] if mode == "all" else [[term] for term in terms]
            out.append(("biomarker", "requires", alts))
        for column in ("stage", "status", "stage_or_status"):
            values = [
                v for v in split_pipe(str(r[column] or "")) if not is_placeholder(v)
            ]
            alts = []
            for v in values:
                per_value = self.concept_terms(self.disease_alternatives(column, v))
                self.record_value(
                    column, v, per_value, provenance="decomposed disease phrase"
                )
                alts.extend(per_value)
            if alts:
                out.append((column, "requires", alts))
        age = str(r["age"] or "").strip()
        if age and norm(age) not in {"any", "not applicable"}:
            unit = str(r["age_unit"] or "UNSPECIFIED").lower()
            out.append(("age", "requires", [[self.age_term(age, unit)]]))
        if r["sex"]:
            cid = GENDER[str(r["sex"])]
            self.cite("sex", str(r["sex"]), cid, "exact", "target")
            self.map_source(
                "sex",
                str(r["sex"]),
                "",
                cid,
                "exact",
                "mapped-to-existing",
                "OMOP Gender",
            )
            out.append(("sex", "requires", [[Term(cid)]]))
        negation = ch["prior_therapy_negation"].get(rid, [])
        polarity = (
            "excludes"
            if negation and all(norm(v) == "true" for v in negation)
            else "requires"
        )
        if (
            negation
            and any(norm(v) not in {"true", "false"} for v in negation)
            or (negation and {norm(v) for v in negation} == {"true", "false"})
        ):
            self.notes.append(
                [
                    rid,
                    "prior_therapy_negation",
                    "|".join(negation),
                    "mixed negation values; criterion kept as required",
                ]
            )
        alts = self.therapy_alternatives(
            "prior_therapy",
            str(r["prior_therapy"] or ""),
            "Prior Therapy Requirement",
            rid,
        )
        if alts:
            out.append(("prior_therapy", polarity, alts))
        settings = [
            v
            for raw in ch["prior_therapy_setting"].get(rid, [])
            for v in split_pipe(raw)
            if not is_placeholder(v)
        ]
        if settings:
            leaves = []
            for v in settings:
                term = self.setting_term(v)
                self.record_value(
                    "prior_therapy_setting",
                    v,
                    [[term]],
                    provenance="prior therapy setting",
                )
                leaves.append([term])
            out.append(("prior_therapy_setting", "requires", leaves))
        pbm = str(r["prior_biomarker"] or "").strip()
        if pbm and norm(pbm) not in {"not applicable", "0"}:
            self.notes.append(
                [
                    rid,
                    "prior_biomarker",
                    pbm,
                    "free text kept as a note; no closed vocabulary",
                ]
            )
        alts = self.therapy_alternatives(
            "with_field", str(r["with_field"] or ""), "Co-therapy Requirement", rid
        )
        if alts:
            out.append(("with_field", "requires", alts))
        for column, cls, values in (
            (
                "ineligibility",
                "Population Qualifier",
                split_pipe(str(r["ineligibility"] or "")),
            ),
            (
                "demographics",
                "Population Qualifier",
                [v for raw in ch["demographics"].get(rid, []) for v in split_pipe(raw)],
            ),
            (
                "risk_stratification",
                "Population Qualifier",
                [
                    v
                    for raw in ch["risk_stratification"].get(rid, [])
                    for v in split_pipe(raw)
                ],
            ),
        ):
            alts = [
                [Term(self.population_leaf(column, v, cls))]
                for v in values
                if not is_placeholder(v)
            ]
            if alts:
                out.append((column, "requires", alts))
        rc = [
            v
            for raw in ch["response_contingency"].get(rid, [])
            for v in split_pipe(raw)
            if not is_placeholder(v)
        ]
        alts = []
        for v in rc:
            per_value = self.concept_terms(
                self.or_alternatives(
                    "response_contingency", v, "Response Contingency", split=True
                )
            )
            self.record_value(
                "response_contingency",
                v,
                per_value,
                provenance="decomposed alternatives",
            )
            alts.extend(per_value)
        if alts:
            out.append(("response_contingency", "requires", alts))
        if r["exposure_phenotype"]:
            cid, _, _ = self.local_value(
                "exposure_phenotype",
                str(r["exposure_phenotype"]),
                "Prior Therapy Requirement",
                name=norm(str(r["exposure_phenotype"])).capitalize(),
            )
            out.append(("exposure_phenotype", "requires", [[Term(cid)]]))
        windows = []
        for window in split_pipe(str(r["time_contingency"] or "")):
            if is_placeholder(window):
                continue
            parsed = parse_window(window)
            term = (
                self.scalar_term(parsed, str(parsed["unit"]), text=window)
                if parsed
                else Term(text=window)
            )
            self.record_value(
                "time_contingency", window, [[term]], provenance="time contingency"
            )
            windows.append([term])
        if windows:
            out.append(("time_contingency", "requires", windows))
        return out

    def age_term(self, raw: str, unit: str) -> Term:
        if norm(raw) in {"adult", "pediatric"}:
            cid = self.concept(
                "Population Qualifier",
                f"AGE-{slug(norm(raw))}",
                raw.strip().capitalize(),
                provenance="age group word of the indications table",
            )
            term = Term(cid)
            self.record_value(
                "age", raw, [[term]], context=unit, provenance="age group"
            )
            return term
        parsed = parse_age(raw, unit)
        marker = re.search(r"nub(p|ya)", raw, re.IGNORECASE)
        term = (
            self.scalar_term(
                parsed, unit, qualifier=marker.group(0).upper() if marker else ""
            )
            if parsed
            else Term(text=raw)
        )
        self.record_value("age", raw, [[term]], context=unit, provenance="age grammar")
        return term

    def setting_term(self, raw: str) -> Term:
        if parse_count(raw) and re.fullmatch(
            r"\d+(\s*\+|\s+to\s+\d+|\s+or\s+\d+)?", raw.strip()
        ):
            return self.count_term(raw)
        if self.lexicon_ok(norm(raw)):
            alts = self.disease_alternatives("prior_therapy_setting", raw)
            if len(alts) == 1 and len(alts[0]) == 1:
                return Term(alts[0][0])
        return Term(
            self.local_value("prior_therapy_setting", raw, "Prior Therapy Requirement")[
                0
            ]
        )

    def map_state_source(self, gene: str, finding: str) -> None:
        sid = self.state_columns[self.state_key(gene, finding)]
        self.map_source(
            "biomarker_finding",
            finding,
            self.gene_name(gene),
            sid,
            "none",
            "proposed-new",
            "pre-coordinated biomarker state",
        )
        term = self.state_term(gene, finding)
        if term.has_scalar:
            self.record_value(
                "biomarker_finding",
                finding,
                [[term]],
                context=self.gene_name(gene),
                provenance="cut-off held as an attribute",
            )
        analyte, fit = self.analyte(self.gene_name(gene), False)
        if analyte:
            self.cite("biomarker", gene, analyte, fit, "target")
            self.map_source(
                "biomarker",
                gene,
                "",
                analyte,
                fit,
                "mapped-to-existing",
                "gene or protein analyte",
            )
        else:
            self.map_source(
                "biomarker", gene, "", 0, "none", "gap", "no analyte concept found"
            )

    def context_links(self, raw_values: list[str]) -> list[int]:
        links = []
        for raw in raw_values:
            for part in re.split(r"\||&", raw):
                part = part.strip()
                if is_placeholder(part):
                    continue
                target = None
                for row in self.ex.rows("context", part):
                    cid = int(row["concept_id"])
                    if row[
                        "concept_class_id"
                    ] == "Context" and self.ex.acceptable_target(cid):
                        target = (cid, row["fit"])
                        break
                if target:
                    self.cite("context", part, target[0], target[1], "target")
                    self.map_source(
                        "context",
                        part,
                        "",
                        target[0],
                        target[1],
                        "mapped-to-existing",
                        "HemOnc Context",
                    )
                    links.append(target[0])
                else:
                    cid, _, _ = self.local_value(
                        "context", part, "Treatment Context", ex_rows=False
                    )
                    links.append(cid)
        return list(dict.fromkeys(links))

    # ---- indications
    def build_indication(
        self,
        r: dict[str, object],
        ch: dict[str, dict[int, list[str]]],
        criteria: list,
        comp: int,
        cond: int,
    ) -> int:
        rid = int(r["id"])
        regulator = str(r["regulator"])
        withdrawn = str(r["withdrawn"] or "FALSE")
        start = r["date"].strftime("%Y-%m-%d") if r["date"] else "1970-01-01"
        end, invalid, provenance = (
            "2099-12-31",
            "",
            "regulatory row of the indications table",
        )
        if withdrawn.upper() != "FALSE":
            invalid = "D"
            if re.match(r"^\d{4}-\d{2}-\d{2}$", withdrawn):
                end = withdrawn
            else:
                end = VERIFIED_ON
                provenance += (
                    "; withdrawn without a date, end date set to the load date"
                )
        name = f"{regulator} indication {rid}: {r['component']} for {r['condition']}"
        iid = self.concept(
            "Indication",
            str(rid),
            name,
            owner="HemOnc",
            provenance=provenance,
            start=start,
            end=end,
            invalid=invalid,
        )
        self.relate(iid, comp, "Ind has component", cite="component")
        self.relate(iid, cond, "Ind has condition", cite="condition")
        self.relate(iid, self.regulators[regulator], "Ind has regulator")
        if r["accelerated"]:
            self.relate(iid, self.accelerated, "Ind has approval path")
        for code in ch["regimen_cui"].get(rid, []):
            for part in split_pipe(code):
                hit = self.anchors["Regimen"].get(part)
                if hit and hit[0] in self.ex.verified:
                    self.relate(iid, hit[0], "Ind has regimen", cite="regimen")
        for cid in self.context_links(ch["context"].get(rid, [])):
            self.relate(iid, cid, "Ind has context", cite="context")
        for dimension, polarity, alts in criteria:
            criterion_id = len(self.criteria_rows) + 1
            self.criteria_rows.append([criterion_id, iid, dimension, polarity])
            unique = list(dict.fromkeys(tuple(dict.fromkeys(alt)) for alt in alts))
            for alt_no, alt in enumerate(unique, start=1):
                for term_no, term in enumerate(alt, start=1):
                    self.term_rows.append(
                        [criterion_id, alt_no, term_no, *term_columns(term)]
                    )
        return iid


TERM_HEADER = [
    "concept_id",
    "qualifier",
    "comparator_low",
    "value_low",
    "comparator_high",
    "value_high",
    "unit",
    "text",
]


def term_columns(term: Term) -> list[object]:
    return [
        term.concept_id or "",
        term.qualifier,
        term.cl,
        term.vl,
        term.ch,
        term.vh,
        term.unit,
        term.text,
    ]


def anchor(builder_anchors, cls: str, code: object, ex: Existing) -> int | None:
    if code is None:
        return None
    hit = builder_anchors[cls].get(str(code))
    if hit and hit[0] in ex.verified and ex.usable(hit[0]):
        return hit[0]
    return None


def main() -> None:
    url = os.environ.get("HEMONC_INDICATIONS_DATABASE_URL")
    if not url:
        sys.exit("set HEMONC_INDICATIONS_DATABASE_URL")
    engine = create_engine(url)
    rows, ch, anchors = fetch(engine)
    ex = Existing()
    vocab = Vocabulary(ex, anchors)
    for r in rows:
        for name in split_pipe(str(r["biomarker"] or "")):
            vocab.gene_case.setdefault(norm(name), name)
    anchored, unanchored = [], []
    for r in rows:
        comp = anchor(anchors, "Component", r["component_cui"], ex)
        cond = anchor(anchors, "Condition", r["condition_cui"], ex)
        (anchored if comp and cond else unanchored).append((r, comp, cond))
    indications: dict[int, int] = {}
    # every row's values resolve to concepts, anchored or not
    criteria_by_row = {
        int(r["id"]): vocab.build_criteria(r, ch, int(r["id"])) for r in rows
    }
    for r, _, _ in anchored + unanchored:
        vocab.context_links(ch["context"].get(int(r["id"]), []))
    vocab.link_biomarker_values()
    vocab.link_disease_values()
    for r, comp, cond in anchored:
        indications[int(r["id"])] = vocab.build_indication(
            r, ch, criteria_by_row[int(r["id"])], comp, cond
        )
    write_all(vocab, rows, ch, anchored, unanchored, indications, criteria_by_row)


def write_all(
    vocab: Vocabulary, rows, ch, anchored, unanchored, indications, criteria_by_row
) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cited = set(vocab.cited_existing)
    # lung-first review priority: concepts used by lung indications' criteria
    lung_concepts: set[int] = {
        term.concept_id
        for r, _, _ in anchored
        if "lung" in str(r["condition"]).casefold()
        for _, _, alts in criteria_by_row[int(r["id"])]
        for alt in alts
        for term in alt
        if term.concept_id is not None
    }
    for key, info in vocab.review.items():
        a, b, _ = key
        if a in lung_concepts or b in lung_concepts:
            info["priority"] = "lung-first"
    # concept tables
    concept_rows = sorted(vocab.concepts.values(), key=lambda c: int(c["concept_id"]))
    write_tsv(
        OUT / "concept.tsv",
        [
            "concept_id",
            "concept_name",
            "domain_id",
            "vocabulary_id",
            "concept_class_id",
            "standard_concept",
            "concept_code",
            "valid_start_date",
            "valid_end_date",
            "invalid_reason",
        ],
        [
            [
                c[k]
                for k in (
                    "concept_id",
                    "concept_name",
                    "domain_id",
                    "vocabulary_id",
                    "concept_class_id",
                    "standard_concept",
                    "concept_code",
                    "valid_start_date",
                    "valid_end_date",
                    "invalid_reason",
                )
            ]
            for c in concept_rows
        ],
    )
    rel_rows = sorted(vocab.relationships, key=lambda t: (t[2], t[0], t[1]))
    write_tsv(
        OUT / "concept_relationship.tsv",
        [
            "concept_id_1",
            "concept_id_2",
            "relationship_id",
            "valid_start_date",
            "valid_end_date",
            "invalid_reason",
        ],
        [[a, b, rel, "1970-01-01", "2099-12-31", ""] for a, b, rel in rel_rows],
    )
    relationship_rows = []
    next_id = REL_CONCEPT_BASE
    explicit = {r[0]: r for r in RELATIONSHIPS}
    emitted: set[str] = set()
    for rid, name, rev, rev_name, hier, anc in RELATIONSHIPS:
        pair = [(rid, name, rev, hier, anc)]
        if rev not in explicit:
            pair.append((rev, rev_name, rid, 0, 0))
        for rel_id, rel_name, rel_rev, h, a in pair:
            if rel_id in emitted:
                continue
            emitted.add(rel_id)
            concept_id = EXISTING_REL_CONCEPT_ID.get(rel_id)
            if concept_id is None:
                next_id += 1
                concept_id = next_id
            relationship_rows.append([rel_id, rel_name, h, a, rel_rev, concept_id])
    write_tsv(
        OUT / "relationship.tsv",
        [
            "relationship_id",
            "relationship_name",
            "is_hierarchical",
            "defines_ancestry",
            "reverse_relationship_id",
            "relationship_concept_id",
        ],
        relationship_rows,
    )
    write_tsv(
        OUT / "concept_class.tsv",
        ["concept_class_id", "concept_class_name", "concept_class_concept_id"],
        [
            [c, CLASS_NAME[c], LOCAL_BASE + 80_000_000 + i]
            for i, c in enumerate(CLASS_CODE, start=1)
        ],
    )
    write_tsv(
        OUT / "domain.tsv",
        ["domain_id", "domain_name", "domain_concept_id", "fallback_domain_id"],
        [
            [
                "Indication",
                "Indication (local proposal)",
                LOCAL_BASE + 90_000_000,
                "Procedure",
            ]
        ],
    )
    write_tsv(
        OUT / "vocabulary.tsv",
        [
            "vocabulary_id",
            "vocabulary_name",
            "vocabulary_reference",
            "vocabulary_version",
            "vocabulary_concept_id",
        ],
        [
            [
                VOCAB,
                "HemOnc indication vocabulary (local proposal)",
                "hemonc-alchemy",
                VERIFIED_ON,
                LOCAL_BASE + 90_000_001,
            ]
        ],
    )
    write_tsv(
        OUT / "indication_criterion.tsv",
        ["criterion_id", "indication_id", "dimension", "polarity"],
        vocab.criteria_rows,
    )
    write_tsv(
        OUT / "criterion_term.tsv",
        ["criterion_id", "alternative_no", "term_no", *TERM_HEADER],
        vocab.term_rows,
    )
    write_tsv(
        OUT / "source_value_terms.tsv",
        [
            "source_column",
            "raw_value",
            "context",
            "alternative_no",
            "term_no",
            *TERM_HEADER,
        ],
        [
            [column, raw, context, alt_no, term_no, *term_columns(term)]
            for (column, _, _), (raw, context, alts) in sorted(
                vocab.value_terms.items()
            )
            for alt_no, alt in enumerate(alts, start=1)
            for term_no, term in enumerate(alt, start=1)
        ],
    )
    write_tsv(
        OUT / "concept_status.tsv",
        [
            "concept_id",
            "concept_code",
            "status",
            "provenance",
            "proposed_owner",
            "review_status",
        ],
        [
            [
                vocab.status[c["concept_code"]]["concept_id"],
                c["concept_code"],
                vocab.status[c["concept_code"]]["status"],
                vocab.status[c["concept_code"]]["provenance"],
                vocab.status[c["concept_code"]]["proposed_owner"],
                vocab.status[c["concept_code"]]["review_status"],
            ]
            for c in concept_rows
        ],
    )
    write_tsv(
        OUT / "relationship_review.tsv",
        [
            "concept_id_1",
            "concept_id_2",
            "relationship_id",
            "status",
            "provenance",
            "reviewer",
            "reviewed_on",
            "priority",
            "note",
        ],
        [
            [
                a,
                b,
                rel,
                i["status"],
                i["provenance"],
                i["reviewer"],
                i["reviewed_on"],
                i["priority"],
                i["note"],
            ]
            for (a, b, rel), i in sorted(
                vocab.review.items(),
                key=lambda t: (
                    t[1]["priority"] != "lung-first",
                    t[0][2],
                    t[0][0],
                    t[0][1],
                ),
            )
        ],
    )
    # source map: only rows with a defined target unless it is a recorded gap
    src_rows = sorted(
        vocab.source_map.values(),
        key=lambda s: (
            s["source_column"],
            norm(str(s["raw_value"])),
            norm(str(s["context"])),
        ),
    )
    write_tsv(
        OUT / "source_concept_map.tsv",
        [
            "source_column",
            "raw_value",
            "context",
            "target_concept_id",
            "target_kind",
            "fit",
            "status",
            "provenance",
        ],
        [
            [
                s["source_column"],
                s["raw_value"],
                s["context"],
                s["target_concept_id"] or "",
                s["target_kind"] if s["target_concept_id"] else "none",
                s["fit"],
                s["status"],
                s["provenance"],
            ]
            for s in src_rows
        ],
    )
    mapped = sorted(
        vocab.mapping_rows.values(),
        key=lambda m: (
            m["source_column"],
            norm(str(m["raw_value"])),
            int(m["concept_id"]),
        ),
    )
    write_tsv(
        OUT / "mapping_to_existing.tsv",
        [
            "source_column",
            "raw_value",
            "context",
            "concept_id",
            "concept_name",
            "vocabulary_id",
            "concept_class_id",
            "standard_concept",
            "fit",
            "used_as",
            "status",
            "verified_on",
        ],
        [
            [
                m[k]
                for k in (
                    "source_column",
                    "raw_value",
                    "context",
                    "concept_id",
                    "concept_name",
                    "vocabulary_id",
                    "concept_class_id",
                    "standard_concept",
                    "fit",
                    "used_as",
                    "status",
                    "verified_on",
                )
            ]
            for m in mapped
        ],
    )
    term_ids = {
        term.concept_id
        for rows_ in criteria_by_row.values()
        for _, _, alts in rows_
        for alt in alts
        for term in alt
        if term.concept_id is not None and term.concept_id < LOCAL_BASE
    }
    cited_all = cited | term_ids | {int(m["concept_id"]) for m in mapped}
    write_tsv(
        OUT / "existing_concepts.tsv",
        [
            "concept_id",
            "concept_name",
            "vocabulary_id",
            "domain_id",
            "concept_class_id",
            "concept_code",
            "standard_concept",
            "valid_start_date",
            "valid_end_date",
            "invalid_reason",
            "verified_via",
            "verified_on",
        ],
        [
            [
                cid,
                v["concept_name"],
                v["vocabulary_id"],
                v["domain_id"],
                v["concept_class_id"],
                v["concept_code"],
                v.get("standard_concept", ""),
                v.get("valid_start_date", ""),
                v.get("valid_end_date", ""),
                v.get("invalid_reason", ""),
                v.get("verified_via", ""),
                VERIFIED_ON,
            ]
            for cid in sorted(cited_all)
            if (v := ex_verified(vocab, cid))
        ],
    )
    write_tsv(
        OUT / "indication_notes.tsv",
        ["indication_id", "source_column", "raw_value", "issue"],
        sorted(vocab.notes, key=lambda n: (n[0], str(n[1]))),
    )
    write_tsv(
        OUT / "unanchored_indications.tsv",
        [
            "indication_id",
            "regulator",
            "component_cui",
            "component",
            "condition_cui",
            "condition",
            "reason",
        ],
        [
            [
                r["id"],
                r["regulator"],
                r["component_cui"] or "",
                r["component"],
                r["condition_cui"] or "",
                r["condition"],
                unanchored_reason(
                    r, comp, cond, ex_obj=vocab.ex, anchors=vocab.anchors
                ),
            ]
            for r, comp, cond in unanchored
        ],
    )
    write_tsv(
        OUT / "gap_register.tsv",
        GAP_HEADER,
        gap_rows(rows, ch, vocab, anchored, unanchored),
    )
    print(
        {
            "concepts": len(concept_rows),
            "relationships": len(rel_rows),
            "anchored": len(anchored),
            "unanchored": len(unanchored),
        }
    )


def ex_verified(vocab: Vocabulary, cid: int):
    return vocab.ex.verified.get(cid)


def unanchored_reason(r, comp, cond, *, ex_obj: Existing, anchors) -> str:
    reasons = []
    if r["component_cui"] is None:
        reasons.append("component_cui is null")
    elif comp is None:
        reasons.append("component code not in the HemOnc load")
    if r["condition_cui"] is None:
        reasons.append("condition_cui is null")
    elif cond is None:
        hit = anchors["Regimen Class"].get(str(r["condition_cui"]))
        reasons.append(
            "condition code is a Regimen Class concept"
            if hit
            else "condition code not in the HemOnc load"
        )
    return "; ".join(reasons)


GAP_HEADER = [
    "gap_id",
    "area",
    "description",
    "home",
    "owner",
    "indications_affected",
    "completes",
    "status",
]


def gap_rows(rows, ch, vocab: Vocabulary, anchored, unanchored) -> list[list[object]]:
    def findings(r) -> str:
        rid = int(r["id"])
        parts = [str(r["biomarker_finding"] or "")] + [
            "|".join(ch[f"biomarker{n}_finding"].get(rid, [])) for n in (2, 3, 4)
        ]
        return norm("|".join(parts))

    def genes(r) -> str:
        rid = int(r["id"])
        return "|".join(
            [str(r["biomarker"] or "")]
            + ["|".join(ch[f"biomarker{n}"].get(rid, [])) for n in (2, 3, 4)]
        )

    def count(pred) -> int:
        return sum(1 for r in rows if pred(r))

    def disease(r) -> str:
        return norm(
            "|".join(str(r[c] or "") for c in ("stage", "status", "stage_or_status"))
        )

    def col(r, name) -> str:
        return "|".join(ch[name].get(int(r["id"]), []))

    G = []

    def add(gid, area, desc, home, owner, n, completes, status="open"):
        G.append([gid, area, desc, home, owner, n, completes, status])

    add(
        "G01",
        "indication model",
        "No Indication, Regulator or Approval Path concept classes, no Ind or State relationship types, and no native criterion tables for AND, OR, polarity and numeric attributes",
        "HemOnc",
        "HemOnc team",
        len(rows),
        "all indication concepts",
    )
    add(
        "G02",
        "anchors",
        "Component codes used by indications but absent from the HemOnc load, or null",
        "HemOnc",
        "HemOnc team",
        sum(1 for _, c, _ in unanchored if c is None),
        "Ind has component",
    )
    add(
        "G03",
        "anchors",
        "Condition codes used by indications but absent from the HemOnc load, null, or pointing at Regimen Class concepts",
        "HemOnc",
        "HemOnc team",
        sum(1 for _, _, c in unanchored if c is None),
        "Ind has condition",
    )
    add(
        "G04",
        "regulators",
        "No `Has MFDS indication` relationship type; NMPA, EMA, PMDA, HC and FDA pair relationships incomplete against the indications table",
        "HemOnc",
        "HemOnc team",
        count(lambda r: r["regulator"] == "MFDS" or r["regulator"] == "NMPA"),
        "derived Component to Condition pair views",
    )
    add(
        "G05",
        "stage and status",
        "No closed value sets or enums for stage, status and stage_or_status (spelling and case variants such as Localled advanced)",
        "HemOnc",
        "HemOnc team",
        count(lambda r: disease(r).strip("|")),
        "Disease Extent and Disease Status concepts",
    )
    add(
        "G06",
        "workflow values",
        "`not applicable` placeholder used as a value in several columns",
        "HemOnc",
        "HemOnc team",
        count(
            lambda r: (
                norm(col(r, "context")) == "not applicable"
                or norm(col(r, "demographics")) == "not applicable"
            )
        ),
        "clean null handling",
    )
    add(
        "G07",
        "prior therapy",
        "prior_therapy_negation carries extended logic values (`TRUE AND FALSE`, `unless unsuitable`)",
        "HemOnc",
        "HemOnc team",
        count(
            lambda r: any(
                norm(v) not in {"true", "false"}
                for v in ch["prior_therapy_negation"].get(int(r["id"]), [])
            )
        ),
        "polarity of prior-therapy criteria",
    )
    add(
        "G08",
        "prior therapy",
        "Therapy descriptors with no HemOnc concept (SACT, standard therapies, multi-modality treatment, R-CHP, TC, generic approved-drug phrases)",
        "HemOnc",
        "HemOnc team",
        count(
            lambda r: re.search(
                r"sact|standard therap|multi-modality|r-chp|satisfactory",
                norm(str(r["prior_therapy"] or "") + "|" + str(r["with_field"] or "")),
            )
        ),
        "prior therapy and co-therapy descriptors",
    )
    add(
        "G09",
        "regimen links",
        "Indications whose regimen text has no regimen_cui",
        "HemOnc",
        "HemOnc team",
        count(lambda r: ch["regimen_cui"].get(int(r["id"])) is None),
        "Ind has regimen",
    )
    add(
        "G10",
        "biomarker findings",
        "Clinical class concepts: activating, sensitizing, non-resistant, susceptible, TKD activating mutation",
        "OMOP Genomic or a clinical classification",
        "OMOP Genomic team",
        count(
            lambda r: re.search(
                r"activating|sensitizing|non-resistant|susceptible|without known acquired",
                findings(r),
            )
        ),
        "Clinically implies targets (held locally)",
    )
    add(
        "G11",
        "biomarker findings",
        "No generic fusion or rearrangement concept per gene (RET, FGFR2, NTRK, NRG1, ROS1, BRAF fusions; rearrangement without known acquired resistance)",
        "OMOP Genomic",
        "OMOP Genomic team",
        count(lambda r: re.search(r"fusion|rearrangement|translocation", findings(r))),
        "fusion biomarker states",
    )
    add(
        "G12",
        "biomarker findings",
        "No codon-level group concept (BRAF p.V600 any substitution, IDH1 p.R132)",
        "OMOP Genomic",
        "OMOP Genomic team",
        count(lambda r: re.search(r"p\.v600(\||$)|p\.r132", findings(r))),
        "codon biomarker states",
    )
    add(
        "G13",
        "biomarker findings",
        "Scoring methods are not concepts (PD-L1 CPS, TPS, TIL, IHC 3+); only assay concepts exist (OMOP Extension 718584 to 718589). The cut-offs themselves are numeric attributes held natively",
        "OMOP Genomic and LOINC",
        "OMOP Genomic team",
        count(
            lambda r: re.search(
                r"cps|tps|til |at least|>=|>50|greater than|mutations/mb", findings(r)
            )
        ),
        "score states for PD-L1 scoring methods and TMB; cut-offs stay numeric attributes",
    )
    add(
        "G14",
        "biomarker findings",
        "HER2 IHC categories (0, 1+, 2+, 3+, low, ultralow) have no result concepts; slot-2 enum labels for HER2 negative and low are truncated in the source",
        "LOINC and OMOP",
        "OMOP vocabulary team",
        count(
            lambda r: (
                "her2" in norm(genes(r)) and re.search(r"ihc|low|ich", findings(r))
            )
        ),
        "HER2 biomarker states",
    )
    add(
        "G15",
        "biomarker findings",
        "No valid standard value concepts for MSI-high, microsatellite stable or MMR proficient; MSI-H 35977040 is deprecated (replaced by 700490, an analyte, not a result)",
        "OMOP Genomic, SNOMED",
        "OMOP vocabulary team",
        count(lambda r: re.search(r"^(msi|mmr)", norm(genes(r)))),
        "MSI and MMR result values",
    )
    add(
        "G16",
        "biomarker findings",
        "Germline versus somatic origin has no result concept",
        "LOINC and OMOP",
        "OMOP vocabulary team",
        count(lambda r: re.search(r"germline|somatic", findings(r))),
        "origin biomarker states",
    )
    add(
        "G17",
        "biomarker findings",
        "Result values for unknown and not high",
        "OMOP",
        "OMOP vocabulary team",
        count(lambda r: re.search(r"unknown|not high", findings(r))),
        "unknown and negative threshold states",
    )
    add(
        "G18",
        "biomarker analytes",
        "Analytes with no standard concept: 17p and 5q deletion, KMT2A translocation, PDGFRA exon 18, FLT3 ITD (test only), H3 K27M (morphology only), HLA-A alleles, CLDN18.2 isoform, CCR4, MIBG and iobenguane scan, PSMA, MAGE-A4, somatostatin receptor",
        "OMOP Genomic and LOINC",
        "OMOP Genomic team",
        count(
            lambda r: re.search(
                r"17p|5q|kmt2a|ccr4|mibg|iobenguane|psma|mage|somatostatin|hla-a|cldn18|h3|flt3",
                norm(genes(r)),
            )
        ),
        "analyte anchors",
    )
    add(
        "G19",
        "biomarker analytes",
        "No EGFR, ALK, ROS1 or MET protein (IHC) concept",
        "LOINC",
        "LOINC team",
        count(
            lambda r: (
                re.search(
                    r"^(egfr|alk|ros1|met|c-met)$", norm(str(r["biomarker"] or ""))
                )
                and re.search(r"positive|negative", findings(r))
            )
        ),
        "protein analytes",
    )
    add(
        "G20",
        "disease extent",
        "Locally advanced exists only as a non-standard CDISC concept with no link to Advanced; node-positive, inflammatory, muscle-invasive, non-muscle-invasive, non-metastatic, persistent, newly diagnosed have no standard concept",
        "Cancer Modifier, SNOMED",
        "OMOP Cancer Modifier team",
        count(
            lambda r: re.search(
                r"node|inflammatory|invasive|non-metastatic|non metastatic|persistent|newly|untreated|locally advanced",
                disease(r),
            )
        ),
        "Disease Extent and Status concepts",
    )
    add(
        "G21",
        "exposure",
        "Platinum-sensitive and platinum-resistant exist only as generic Sensitive and Resistant",
        "SNOMED, Cancer Modifier",
        "OMOP vocabulary team",
        count(
            lambda r: re.search(
                r"platinum|chemotherapy-sensitive",
                norm(
                    str(r["exposure_phenotype"] or "")
                    + "|"
                    + col(r, "response_contingency")
                ),
            )
        ),
        "exposure concepts",
    )
    add(
        "G22",
        "time and counts",
        "Time windows and prior-line count bands have no concepts",
        "HemOnc",
        "HemOnc team",
        count(
            lambda r: (
                (
                    r["time_contingency"]
                    and not is_placeholder(str(r["time_contingency"]))
                )
                or re.match(r"^\d", str(r["prior_therapy"] or ""))
            )
        ),
        "time window and prior-line count attributes on criterion terms",
    )
    add(
        "G23",
        "population",
        "Population qualifiers: premenopausal (CDISC only), ECOG 0 to 1 values, comorbidities precluding intensive chemotherapy, good performance status, low-to-intermediate risk, factor VIII inhibitor presence",
        "SNOMED, CDISC, HemOnc",
        "OMOP vocabulary team",
        count(lambda r: col(r, "demographics") or col(r, "risk_stratification")),
        "Population Qualifier concepts",
    )
    add(
        "G24",
        "age",
        "Age bands: only generic age groups exist (Age group 44804452, Newborn 4046034, Adolescent 4305318, LOINC Pediatric 45880636); SNOMED Adult 4046779 is non-standard; no numeric bands",
        "HemOnc",
        "HemOnc team",
        count(
            lambda r: r["age"] and norm(str(r["age"])) not in {"any", "not applicable"}
        ),
        "age attributes on criterion terms; adult and pediatric as qualifiers",
    )
    add(
        "G25",
        "ineligibility",
        "No vocabulary for ineligibility; no pre-coordinated ineligible-for-X concept found",
        "HemOnc",
        "HemOnc team",
        count(lambda r: r["ineligibility"]),
        "Population Qualifier concepts",
    )
    add(
        "G26",
        "free text",
        "prior_biomarker free text kept as a note",
        "HemOnc",
        "HemOnc team",
        count(
            lambda r: (
                r["prior_biomarker"]
                and norm(str(r["prior_biomarker"])) not in {"not applicable", "0"}
            )
        ),
        "criteria not expressible",
    )
    return G


if __name__ == "__main__":
    main()
