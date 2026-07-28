from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .properties import plain_text


FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "Opportunity": ("Opportunity", "Name"),
    "Company": ("Company",),
    "Location": ("Location", "Region"),
    "Role Family": ("Department", "Role Family"),
    "Canonical URL": (
        "Job URL",
        "Official URL",
        "Apply URL",
        "Canonical URL",
        "Source",
    ),
    "Source": ("Source Site", "Source"),
    "Source Job ID": ("Source Job ID",),
    "Evidence Text": (
        "RAG Evidence",
        "Evidence Text",
        "Reality Note",
        "Hard Gate Reason",
    ),
    "Freshness": ("Freshness Days", "Freshness"),
    "Car/Licence": ("Car/Licence",),
    "Accommodation": ("Accommodation",),
    "Second Visa": ("Second Visa", "WHV/88 Days"),
    "Audit Status": ("Audit Status",),
    "Evidence Grade": ("Evidence Grade",),
    "Verification Level": ("Verification Level",),
    "Vacancy Status": ("Vacancy Status",),
    "Operational Decision": ("Operational Decision", "Application Status"),
}

FATAL_SCHEMA_FIELDS = ("Opportunity", "Canonical URL")
PROMOTION_SCHEMA_FIELDS = (
    "Location",
    "Freshness",
    "Car/Licence",
    "Accommodation",
    "Second Visa",
    "Audit Status",
    "Evidence Grade",
    "Verification Level",
)


def _first_text(
    properties: Mapping[str, Mapping[str, Any]], aliases: tuple[str, ...]
) -> str:
    for alias in aliases:
        value = plain_text(properties.get(alias))
        if value.strip():
            return value.strip()
    return ""


def schema_health(schema: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Report whether an existing Notion data source can support Eagle V4.

    Missing title/URL fields make the run meaningless and are fatal. Missing
    promotion fields would silently turn the whole database into HOLD, so strict
    production mode rejects them before spending time checking hundreds of URLs.
    """

    names = set(schema)
    resolved = {
        canonical: next((alias for alias in aliases if alias in names), None)
        for canonical, aliases in FIELD_ALIASES.items()
    }
    missing_fatal = [
        field for field in FATAL_SCHEMA_FIELDS if resolved.get(field) is None
    ]
    missing_promotion = [
        field for field in PROMOTION_SCHEMA_FIELDS if resolved.get(field) is None
    ]
    return {
        "resolved_aliases": resolved,
        "missing_fatal": missing_fatal,
        "missing_promotion": missing_promotion,
        "ready": not missing_fatal and not missing_promotion,
    }


def extract_record(properties: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    """Normalize the existing Eagle Notion schemas into one internal record.

    The project has used different property names across Stage 1, Stage 2, Stage 3
    and Final databases. The pipeline must read the existing database rather than
    silently scoring blank fields or creating a replacement schema.
    """

    record = {
        canonical: _first_text(properties, aliases)
        for canonical, aliases in FIELD_ALIASES.items()
    }

    # The restored deterministic scorer still uses the historical canonical keys.
    # Keep those aliases populated so the transition to the V4 policy runner does
    # not silently zero the visa or location components.
    record["Region"] = record["Location"]
    record["WHV/88 Days"] = record["Second Visa"]
    record["Application Status"] = record["Operational Decision"]
    return record
