from __future__ import annotations

from typing import Any

from . import jora_card_today100 as collector
from . import today100


EXTRA_HARD_MISMATCH_TERMS = (
    "australian citizenship",
    "australian citizen only",
    "must be australian citizen",
    "permanent residents only",
    "australian permanent residency required",
)

EXTRA_LICENCE_TERMS = (
    "driver licence",
    "drivers licence",
    "driver's licence",
    "driver license",
    "drivers license",
    "driver's license",
    "hr licence",
    "hr license",
    "mr licence",
    "mr license",
    "lr licence",
    "lr license",
    "hc licence",
    "hc license",
    "mc licence",
    "mc license",
    "c class licence",
    "c-class licence",
    "c class license",
    "c-class license",
)

PLANT_TITLE_TERMS = (
    "farm hand", "farm worker", "stationhand", "station hand", "harvest",
    "fruit picker", "vegetable", "meat process", "food process",
    "process worker", "production worker", "packer", "packing shed",
    "poultry", "dairy", "seafood", "abattoir", "mill labourer",
)
CONSTRUCTION_TITLE_TERMS = (
    "construction", "civil labour", "civil worker", "labourer", "trade assistant",
    "concreter", "formworker", "scaffolder", "carpenter", "bricklayer",
)
MINING_TITLE_TERMS = (
    "mining", "miner", "drill", "driller", "offsider", "dump truck",
    "haul truck", "excavator operator", "underground", "fixed plant",
    "blast crew", "shutdown", "mine site utility",
)
DIRECT_TOURISM_TITLE_TERMS = (
    "hotel", "resort", "hostel", "housekeeping", "room attendant",
    "kitchen hand", "food and beverage", "waiter", "waitstaff",
    "bar attendant", "hospitality", "lodge", "roadhouse", "night auditor",
    "reservations agent", "accommodation attendant", "chef", "cook", "culinary",
)
CONTEXT_TOURISM_TITLE_TERMS = (
    "guest service", "receptionist", "front office", "all-rounder",
    "all rounder", "cleaner", "security officer & receptionist",
)
TOURISM_CONTEXT_TERMS = (
    "hotel", "resort", "hostel", "lodge", "roadhouse", "village",
    "accommodation", "tourism", "hospitality", "guest rooms", "casino resort",
)
ADMIN_TITLE_TERMS = (
    "administrator", "administration", "coordinator", "project support",
    "mobilisation", "workforce", "roster", "document controller",
)


def strict_industry(title: str, description: str) -> str:
    heading = title.lower()
    body = description.lower()
    if any(term in heading for term in PLANT_TITLE_TERMS):
        return "Plant/Animal or Food Processing"
    if any(term in heading for term in CONSTRUCTION_TITLE_TERMS):
        return "Construction"
    if any(term in heading for term in MINING_TITLE_TERMS):
        return "Mining"
    if any(term in heading for term in DIRECT_TOURISM_TITLE_TERMS):
        return "Tourism/Hospitality"
    if any(term in heading for term in CONTEXT_TOURISM_TITLE_TERMS) and any(
        term in body for term in TOURISM_CONTEXT_TERMS
    ):
        return "Tourism/Hospitality"
    return "Other/Unverified"


def _install_hard_gates() -> None:
    today100.HARD_MISMATCH_TERMS = tuple(
        dict.fromkeys(today100.HARD_MISMATCH_TERMS + EXTRA_HARD_MISMATCH_TERMS)
    )
    today100.LICENCE_REQUIRED_TERMS = tuple(
        dict.fromkeys(today100.LICENCE_REQUIRED_TERMS + EXTRA_LICENCE_TERMS)
    )
    collector._strict_industry = strict_industry


def _cv_cluster(record: Any) -> str:
    title = str(record.opportunity).lower()
    if record.industry in {"Mining", "Construction"}:
        if any(term in title for term in ADMIN_TITLE_TERMS):
            return "CV_OPERATIONS_ADMIN"
        return "CV_GENERAL_LABOUR"
    if record.role_family == "front_office":
        return "CV_FRONT_OFFICE"
    if record.role_family == "housekeeping":
        return "CV_HOUSEKEEPING"
    if record.role_family == "food_beverage":
        return "CV_HOSPITALITY_ALLROUNDER"
    if record.role_family == "operations_admin":
        return "CV_OPERATIONS_ADMIN"
    if record.role_family == "food_processing":
        return "CV_FOOD_PROCESSING"
    if record.role_family == "construction_mining":
        return "CV_GENERAL_LABOUR"
    return "CV_GENERAL"


def main() -> int:
    _install_hard_gates()
    original_enrich = collector._enrich_or_fallback

    def final_enrich(session: Any, card: dict[str, str]):
        record = original_enrich(session, card)
        record.cv_cluster = _cv_cluster(record)
        return record

    collector._enrich_or_fallback = final_enrich
    return collector.main()


if __name__ == "__main__":
    raise SystemExit(main())
