"""Coverage, ambiguity, vocabulary-version, and information-loss diagnostics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa

from .binding import load_omop_binding
from .mapping import StandardConceptMapping, map_to_standard, resolve_hemonc_concepts
from .schema import require_omop_available


@dataclass(frozen=True)
class VocabularyVersion:
    """The version advertised by one OMOP vocabulary release."""

    vocabulary_id: str
    vocabulary_version: str | None


@dataclass(frozen=True)
class MappingCoverage:
    """Coverage counts calculated from the current database, never constants."""

    target_vocabulary: str | None
    requested_cuis: int
    resolved_cuis: int
    mapped_cuis: int
    mapping_rows: int
    unmatched_cuis: tuple[str, ...]
    ambiguous_cuis: tuple[str, ...]
    vocabulary_versions: tuple[VocabularyVersion, ...]


def vocabulary_versions(
    session: Any,
    vocabulary_ids: Iterable[str] | None = None,
) -> list[VocabularyVersion]:
    """Return the database-declared versions for the requested vocabularies."""

    if not require_omop_available(session):
        return []
    binding = load_omop_binding()
    if binding is None:
        return []
    vocabulary = binding.vocabulary
    statement = sa.select(vocabulary)
    if vocabulary_ids is not None:
        values = tuple(dict.fromkeys(str(value) for value in vocabulary_ids))
        if not values:
            return []
        statement = statement.where(vocabulary.vocabulary_id.in_(values))
    statement = statement.with_only_columns(
        vocabulary.vocabulary_id,
        vocabulary.vocabulary_version,
    ).order_by(vocabulary.vocabulary_id)
    return [
        VocabularyVersion(str(row.vocabulary_id), row.vocabulary_version)
        for row in session.execute(statement)
    ]


def coverage_report(
    session: Any,
    cuis: Iterable[str | int],
    *,
    target_vocabulary: str | Sequence[str] | None = None,
    source_domain: str | None = None,
    target_domain: str | None = None,
    target_concept_class: str | None = None,
    include_invalid: bool = False,
) -> MappingCoverage:
    """Report source resolution, mapping coverage, and ambiguity.

    ``mapped_cuis`` means a source CUI with at least one resolved target
    concept.  An edge with a missing target is retained in the underlying
    mapping query but does not count as mapped.
    """

    requested = tuple(dict.fromkeys(str(value) for value in cuis))
    resolved = resolve_hemonc_concepts(
        session,
        requested,
        domain=source_domain,
        include_invalid=include_invalid,
    )
    mappings = map_to_standard(
        session,
        requested,
        target_vocabulary=target_vocabulary,
        source_domain=source_domain,
        target_domain=target_domain,
        target_concept_class=target_concept_class,
        include_invalid=include_invalid,
    )
    counts = Counter(mapping.hemonc_cui for mapping in mappings if mapping.target is not None)
    mapped = set(counts)
    requested_set = set(requested)
    resolved_set = {concept.hemonc_cui for concept in resolved}
    vocabulary_ids = ["HemOnc"]
    if isinstance(target_vocabulary, str):
        vocabulary_ids.append(target_vocabulary)
    elif target_vocabulary is not None:
        vocabulary_ids.extend(target_vocabulary)
    return MappingCoverage(
        target_vocabulary=target_vocabulary if isinstance(target_vocabulary, str) else None,
        requested_cuis=len(requested_set),
        resolved_cuis=len(resolved_set & requested_set),
        mapped_cuis=len(mapped & requested_set),
        mapping_rows=len(mappings),
        unmatched_cuis=tuple(sorted(requested_set - mapped)),
        ambiguous_cuis=tuple(sorted(cui for cui, count in counts.items() if count > 1)),
        vocabulary_versions=tuple(vocabulary_versions(session, vocabulary_ids)),
    )


@dataclass(frozen=True)
class BiomarkerMappingDiagnostic:
    """A source condition whose qualifier is not retained by the target."""

    hemonc_cui: str
    hemonc_name: str
    target_names: tuple[str, ...]
    target_concept_ids: tuple[int, ...]
    warning: str


@dataclass(frozen=True)
class SuspiciousMappingDiagnostic:
    """A mapping whose target vocabulary/domain is unexpected for a condition."""

    hemonc_cui: str
    hemonc_name: str
    target: str
    warning: str


def biomarker_qualifier_diagnostics(
    session: Any,
    condition_cuis: Iterable[str | int],
) -> list[BiomarkerMappingDiagnostic]:
    """Flag condition mappings that lose a source biomarker qualifier.

    The caller supplies the qualified condition set because “biomarker” is a
    HemOnc data/content policy, not an OMOP property.  The diagnostic compares
    source names with target names and is intentionally advisory.
    """

    from hemonc_alchemy.model import Conditions

    values = tuple(dict.fromkeys(int(value) for value in condition_cuis))
    if not values or not require_omop_available(session, require_relationships=True):
        return []
    names = dict(
        session.execute(
            Conditions.__table__.select()
            .with_only_columns(Conditions.condition_cui, Conditions.condition)
            .where(Conditions.condition_cui.in_(values))
        ).all()
    )
    mappings = map_to_standard(
        session,
        values,
        target_vocabulary="SNOMED",
        source_domain="Condition",
        target_domain="Condition",
    )
    by_cui: dict[str, list[StandardConceptMapping]] = {}
    for mapping in mappings:
        if mapping.target is not None:
            by_cui.setdefault(mapping.hemonc_cui, []).append(mapping)
    result = []
    for cui, name in names.items():
        rows = by_cui.get(str(cui), [])
        target_names = tuple(sorted({row.target.concept_name for row in rows if row.target}))
        target_ids = tuple(sorted({row.target.concept_id for row in rows if row.target}))
        if not target_names or all(str(name).lower() not in target.lower() for target in target_names):
            result.append(
                BiomarkerMappingDiagnostic(
                    hemonc_cui=str(cui),
                    hemonc_name=str(name),
                    target_names=target_names,
                    target_concept_ids=target_ids,
                    warning="HemOnc qualifier may be lost or unresolved in SNOMED; retain the HemOnc CUI and qualifier fields.",
                )
            )
    return result


def suspicious_condition_mappings(
    session: Any,
    condition_cuis: Iterable[str | int],
) -> list[SuspiciousMappingDiagnostic]:
    """Flag condition mappings to modifier vocabularies or measurement classes.

    This is a conservative quality-control heuristic, not a remapping rule.
    In the current release it surfaces the ``MET Non-small cell lung cancer``
    edge to the ``Cancer Modifier`` vocabulary and its ``Metastasis`` concept.
    Consumers should review these rows with the vocabulary publisher before
    excluding them.
    """

    from hemonc_alchemy.model import Conditions

    values = tuple(dict.fromkeys(int(value) for value in condition_cuis))
    if not values or not require_omop_available(session, require_relationships=True):
        return []
    names = dict(
        session.execute(
            Conditions.__table__.select()
            .with_only_columns(Conditions.condition_cui, Conditions.condition)
            .where(Conditions.condition_cui.in_(values))
        ).all()
    )
    mappings = map_to_standard(
        session,
        values,
        source_domain="Condition",
    )
    result = []
    for mapping in mappings:
        target = mapping.target
        if target is None or not (
            target.vocabulary_id == "Cancer Modifier"
            or target.concept_class_id == "Metastasis"
        ):
            continue
        result.append(
            SuspiciousMappingDiagnostic(
                hemonc_cui=mapping.hemonc_cui,
                hemonc_name=str(names.get(int(mapping.hemonc_cui), "")),
                target=f"{target.vocabulary_id}:{target.concept_code} {target.concept_name}",
                warning="Condition maps to a modifier/measurement concept; treat this as a probable vocabulary QC issue and preserve the HemOnc source condition.",
            )
        )
    return result


__all__ = [
    "BiomarkerMappingDiagnostic",
    "MappingCoverage",
    "SuspiciousMappingDiagnostic",
    "VocabularyVersion",
    "biomarker_qualifier_diagnostics",
    "coverage_report",
    "suspicious_condition_mappings",
    "vocabulary_versions",
]
