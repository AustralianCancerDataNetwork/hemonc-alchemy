"""Paged source catalogue queries without web or clinical eligibility policy."""

from .associations import condition_regimen_association_statement
from .conditions import condition_search_statement, search_conditions
from .indications import indication_statement, list_indications
from .read_models import (
    ConditionSummary,
    IndicationRecord,
    Page,
    RegimenSummary,
    VariantRecord,
)
from .regimens import get_regimen_detail, list_regimens, regimen_catalogue_statement
from .specs import CatalogueSpec, IndicationSpec, Pagination
from .variants import (
    get_variant,
    latest_variant_ids,
    list_variants,
    variant_catalogue_statement,
)

__all__ = [
    "CatalogueSpec",
    "ConditionSummary",
    "IndicationRecord",
    "IndicationSpec",
    "Page",
    "Pagination",
    "RegimenSummary",
    "VariantRecord",
    "condition_regimen_association_statement",
    "condition_search_statement",
    "get_regimen_detail",
    "get_variant",
    "indication_statement",
    "latest_variant_ids",
    "list_indications",
    "list_regimens",
    "list_variants",
    "regimen_catalogue_statement",
    "search_conditions",
    "variant_catalogue_statement",
]
