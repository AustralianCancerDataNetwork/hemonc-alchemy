"""Total text normalisation for biomarker names and findings."""

import csv
import re
from collections import Counter
from dataclasses import dataclass, field
from importlib.resources import files

from ..loader import IndicationSource
from ..model import BiomarkerCriterion, Criterion, Finding, Kind, Origin, Presence

_STATUS = {
    "positive": Presence.PRESENT,
    "present": Presence.PRESENT,
    "detected": Presence.PRESENT,
    "negative": Presence.ABSENT,
    "wild-type": Presence.ABSENT,
    "wild type": Presence.ABSENT,
    "absent": Presence.ABSENT,
    "not detected": Presence.ABSENT,
    "unknown": Presence.UNKNOWN,
}
_PROTEIN = re.compile(r"(?i)^p\.[A-Z*][A-Z0-9*_?]*$")
_EXON = re.compile(
    r"(?i)\bexon\s+(\d+)(?:\s+(deletion|insertion|mutation|skipping))?\b"
)
_THRESHOLD = re.compile(
    r"(?i)^(?:(?P<assay>.+?)\s+)?(?P<word>at least|at most|greater than|less than|above|below|equal to|>=|<=|>|<|=)\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%|mutations?/mb|mut/mb|ng/ml)?(?P<qualifier>.*)$"
)
_LEADING_THRESHOLD = re.compile(
    r"(?i)^(?P<word>>=|<=|>|<|=)\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%|mutations?/mb|mut/mb|ng/ml)?(?P<qualifier>.*)$"
)


def _name_table() -> dict[str, str]:
    path = files("hemonc_alchemy.toolkit.core.indications").joinpath(
        "vocab/biomarker_names.csv"
    )
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {
            row["source_label"].strip().casefold(): row["canonical"].strip()
            for row in csv.DictReader(handle)
        }


def _parse_finding(raw: str) -> Finding:
    text = str(raw).strip()
    lower = text.casefold()
    presence = _STATUS.get(lower, Presence.UNKNOWN)
    if lower in _STATUS:
        return Finding(text, presence, Kind.OTHER, detail=lower)
    status_detail = re.match(
        r"(?i)^(positive|negative|present|absent|detected|not detected|wild-type|wild type|unknown)\s*\((.+)\)$",
        text,
    )
    if status_detail:
        state = _STATUS[status_detail.group(1).casefold()]
        return Finding(text, state, Kind.EXPRESSION, detail=status_detail.group(2))
    if lower in {"high", "low", "not high"}:
        return Finding(text, Presence.NOT_STATED, Kind.EXPRESSION, detail=lower)
    expression_detail = re.match(r"(?i)^(high|low|not high)\s*\((.+)\)$", text)
    if expression_detail:
        return Finding(
            text,
            Presence.NOT_STATED,
            Kind.EXPRESSION,
            detail=expression_detail.group(1).casefold(),
            qualifier=expression_detail.group(2),
        )
    if lower in {"deficient", "proficient"}:
        presence = Presence.PRESENT if lower == "deficient" else Presence.ABSENT
        return Finding(text, presence, Kind.EXPRESSION, detail=lower)
    threshold = _LEADING_THRESHOLD.match(text) or _THRESHOLD.match(text)
    if threshold:
        word = threshold.group("word").casefold()
        comparator = {
            "at least": ">=",
            "greater than": ">",
            "above": ">",
            "at most": "<=",
            "less than": "<",
            "below": "<",
            "equal to": "=",
        }.get(word, word)
        unit = threshold.group("unit")
        if unit and unit.casefold() in {"mutation/mb", "mutations/mb", "mut/mb"}:
            unit = "mut/Mb"
        elif unit and unit.casefold() == "ng/ml":
            unit = "ng/mL"
        qualifier = threshold.group("qualifier").strip() or None
        return Finding(
            text,
            Presence.NOT_STATED,
            Kind.EXPRESSION,
            detail=threshold.groupdict().get("assay"),
            comparator=comparator,
            value=float(threshold.group("value")),
            unit=unit,
            qualifier=qualifier,
        )
    protein = _PROTEIN.match(text)
    if protein:
        return Finding(text, Presence.PRESENT, Kind.VARIANT, detail=text)
    exon = _EXON.search(text)
    if exon:
        alteration = exon.group(2) or "alteration"
        return Finding(
            text,
            Presence.PRESENT,
            Kind.EXON_ALTERATION,
            detail=f"exon {exon.group(1)} {alteration}",
        )
    fusion = re.search(r"(?i)\b(fusion|rearrangement|translocation)\b", text)
    if fusion:
        qualifier = text[fusion.end() :].strip() or None
        return Finding(
            text,
            Presence.PRESENT,
            Kind.FUSION,
            detail=fusion.group(1).casefold(),
            qualifier=qualifier,
        )
    if re.search(r"(?i)\bamplification\b", text):
        return Finding(text, Presence.PRESENT, Kind.AMPLIFICATION, detail=text)
    origin = (
        Origin.GERMLINE
        if "germline" in lower
        else Origin.SOMATIC
        if "somatic" in lower
        else Origin.UNSPECIFIED
    )
    if origin is not Origin.UNSPECIFIED:
        return Finding(
            text,
            Presence.PRESENT,
            Kind.MUTATION_CLASS,
            detail="mutation" if "mutation" in lower else lower,
            origin=origin,
        )
    if lower in {
        "mutated",
        "mutation",
        "deletion",
        "activating",
        "sensitizing",
        "non-resistant",
        "susceptible",
    } or re.search(
        r"(?i)\b(activating|sensitizing|non-resistant|susceptible) mutation\b", text
    ):
        return Finding(text, Presence.PRESENT, Kind.MUTATION_CLASS, detail=lower)
    if lower.startswith("without a known acquired resistance mutation"):
        return Finding(
            text,
            Presence.ABSENT,
            Kind.MUTATION_CLASS,
            detail="resistance mutation",
            qualifier=text,
        )
    return Finding(text, Presence.UNKNOWN, Kind.OTHER, parsed=False)


@dataclass(frozen=True)
class BiomarkerNormaliser:
    name: str = "biomarker"
    columns: tuple[str, ...] = (
        "biomarker",
        "biomarker_finding",
        "biomarker2",
        "biomarker2_finding",
        "biomarker3",
        "biomarker3_finding",
        "biomarker4",
        "biomarker4_finding",
    )
    _names: dict[str, str] = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "_names", _name_table())

    def canonical_name(self, name: str) -> str | None:
        return self._names.get(name.strip().casefold())

    def parse_finding(self, raw: str) -> Finding:
        try:
            return _parse_finding(raw)
        except (TypeError, ValueError, OverflowError):
            return Finding(str(raw), Presence.UNKNOWN, Kind.OTHER, parsed=False)

    def normalise(self, source: IndicationSource) -> tuple[Criterion, ...]:
        criteria = []
        for slot in source.biomarkers:
            names = tuple(
                dict.fromkeys(name.strip() for name in slot.biomarkers if name.strip())
            )
            if not names:
                continue
            findings = tuple(self.parse_finding(value) for value in slot.findings)
            group = f"{source.indication_id}:{slot.slot}" if len(names) > 1 else None
            raw = source.raw.get(
                f"biomarker{slot.slot}" if slot.slot > 1 else "biomarker"
            ) or "|".join(names)
            for name in names:
                criteria.append(
                    BiomarkerCriterion(
                        "biomarker",
                        f"biomarker{slot.slot}" if slot.slot > 1 else "biomarker",
                        raw,
                        slot.slot,
                        self.canonical_name(name) or name,
                        name,
                        findings,
                        group,
                    )
                )
        return tuple(criteria)

    def lint(self, sources: tuple[IndicationSource, ...]) -> "BiomarkerLint":
        names, findings = Counter(), Counter()
        for source in sources:
            for slot in source.biomarkers:
                for name in slot.biomarkers:
                    if self.canonical_name(name) is None:
                        names[name] += 1
                for raw in slot.findings:
                    if not self.parse_finding(raw).parsed:
                        findings[raw] += 1
        return BiomarkerLint(
            dict(sorted(names.items())), dict(sorted(findings.items()))
        )


@dataclass(frozen=True)
class BiomarkerLint:
    unknown_names: dict[str, int]
    unparsed_findings: dict[str, int]

    @property
    def exit_code(self) -> int:
        return int(bool(self.unknown_names))


def lint_biomarkers(session, spec=None) -> BiomarkerLint:
    from ...catalogue.specs import DEFAULT_INDICATION_SPEC
    from ..loader import load_indication_sources

    normaliser = BiomarkerNormaliser()
    sources = load_indication_sources(session, spec or DEFAULT_INDICATION_SPEC)
    return normaliser.lint(sources)


__all__ = ["BiomarkerLint", "BiomarkerNormaliser", "lint_biomarkers"]
