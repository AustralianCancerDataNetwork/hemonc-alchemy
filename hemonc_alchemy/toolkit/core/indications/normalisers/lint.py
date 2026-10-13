"""Aggregate indication parse diagnostics and normalizer invariants."""

from collections.abc import Mapping
from dataclasses import dataclass

from ..loader import IndicationSource
from . import default_normalisers
from .age import AgeNormaliser
from .biomarker import BiomarkerLint, lint_biomarkers
from .context import ContextNormaliser
from .scope import ScopeLint, ScopeNormaliser
from .sex import SexNormaliser


@dataclass(frozen=True)
class IndicationLintReport:
    diagnostics: tuple[tuple[str, Mapping[str, int | tuple[str, ...]]], ...]
    invariant_failures: tuple[str, ...]

    @property
    def has_unparsed(self) -> bool:
        return any(
            values
            for label, values in self.diagnostics
            if label != "Biomarker name case variants"
        )


def lint_indications(sources: tuple[IndicationSource, ...]) -> IndicationLintReport:
    biomarker: BiomarkerLint = lint_biomarkers(sources=sources)
    scope_normaliser, age_normaliser = ScopeNormaliser(), AgeNormaliser()
    context_normaliser, sex_normaliser = ContextNormaliser(), SexNormaliser()
    scope: ScopeLint = scope_normaliser.lint(sources)
    age = age_normaliser.lint(sources)
    context = context_normaliser.lint(sources)
    sex = sex_normaliser.lint(sources)
    diagnostics = (
        ("Unrecognised biomarker names", biomarker.unknown_names),
        ("Biomarker name case variants", biomarker.case_variants),
        ("Unparsed findings", biomarker.unparsed_findings),
        ("Unparsed stage values", scope.unmapped_stage),
        ("Unparsed status values", scope.unmapped_status),
        ("Unparsed stage_or_status values", scope.unmapped_stage_or_status),
        ("Unparsed age values", age),
        ("Unparsed context values", context),
        ("Unrecognised sex values", sex),
    )
    failures = []
    normalisers = default_normalisers()
    for source in sources:
        for normaliser in normalisers:
            try:
                criteria = normaliser.normalise(source)
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    f"{normaliser.name} on indication {source.indication_id}: {exc}"
                )
                continue
            if any(not isinstance(criterion.raw, str) for criterion in criteria):
                failures.append(
                    f"{normaliser.name} lost raw text on indication {source.indication_id}"
                )
    return IndicationLintReport(diagnostics, tuple(failures))
