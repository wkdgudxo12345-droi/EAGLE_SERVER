from __future__ import annotations

import csv
import json
import os
import re
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

import requests

from .main import check_url, load_config
from .notion import DEFAULT_NOTION_VERSION, NotionClient
from .properties import plain_text
from .record import extract_record
from .scoring import score


OUTPUT_COLUMNS = [
    "rank",
    "page_id",
    "opportunity",
    "company",
    "location",
    "posted_date",
    "freshness_days",
    "target_group",
    "specified_work_confidence",
    "timing_status",
    "base_ccstm",
    "base_hr",
    "base_reality",
    "base_rag",
    "aug22_score",
    "decision",
    "live",
    "job_url",
    "reasons",
]


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _first_text(properties: Mapping[str, Mapping[str, Any]], *names: str) -> str:
    for name in names:
        value = plain_text(properties.get(name))
        if value.strip():
            return value.strip()
    return ""


def _parse_date(value: str) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _target_group(text: str, config: dict[str, Any]) -> tuple[str, int]:
    groups = config.get("target_groups", {})
    best_name = "OTHER"
    best_matches = 0
    for name, raw_terms in groups.items():
        terms = [_text(term) for term in raw_terms or []]
        matches = sum(1 for term in terms if term and term in text)
        if matches > best_matches:
            best_name = str(name).upper()
            best_matches = matches
    return best_name, best_matches


def _timing_status(text: str, available_start: date) -> tuple[str, float, str | None]:
    seasonal_terms = (
        "harvest 2026/2027",
        "2026/27 harvest",
        "october",
        "november",
        "december",
        "seasonal harvest",
        "harvest casual",
    )
    if any(term in text for term in seasonal_terms):
        return "ALIGNED", 0.0, None

    immediate_terms = (
        "immediate start",
        "start immediately",
        "available immediately",
        "start asap",
        "commence immediately",
    )
    if any(term in text for term in immediate_terms):
        return (
            "START_BEFORE_AVAILABLE",
            12.0,
            f"advertised for immediate commencement before {available_start.isoformat()}",
        )

    explicit_dates = re.findall(r"20\d{2}-\d{2}-\d{2}", text)
    parsed = [_parse_date(item) for item in explicit_dates]
    parsed = [item for item in parsed if item is not None]
    if parsed and min(parsed) < available_start:
        return (
            "START_BEFORE_AVAILABLE",
            12.0,
            f"advertised start date precedes {available_start.isoformat()}",
        )
    return "VERIFY", 3.0, "start-date compatibility is not confirmed"


def _specified_work_confidence(
    record: dict[str, str], target_group: str, combined_text: str
) -> tuple[str, str]:
    current = _text(record.get("Second Visa"))
    if current in {"no", "unlikely", "ineligible"}:
        return "NO", "existing evidence says specified work is ineligible"

    if target_group == "GRAIN_HARVEST":
        direct_terms = (
            "grain sampling",
            "grain sampler",
            "receival point operator",
            "grain receivals",
            "silo operator",
        )
        if any(term in combined_text for term in direct_terms):
            return "VERIFY-LIKELY", "confirm regional grain site and actual paid harvest duties"
        return "VERIFY", "generic weighbridge title is not enough to prove grain-harvest eligibility"

    if target_group == "FOOD_PROCESSING_OPS":
        direct_terms = (
            "abattoir",
            "slaughter",
            "butchery",
            "meat packing",
            "immediate processing",
            "animal product",
        )
        if any(term in combined_text for term in direct_terms):
            return "VERIFY-LIKELY", "confirm immediate animal-product processing and eligible location"
        return "VERIFY", "QA, data entry or dispatch alone is not automatic specified-work proof"

    if target_group == "HOSPITALITY":
        if current in {"likely", "eligible", "yes", "verified yes"}:
            return "VERIFY-LIKELY", "confirm Northern or Remote/Very Remote postcode and actual duties"
        return "VERIFY", "hospitality requires an eligible Northern or remote postcode"

    return "UNKNOWN", "role is outside the three August target groups"


def _decision(base_fit: str, live: bool | None, target: str, timing: str, visa: str) -> str:
    if live is False:
        return "REJECT-CLOSED"
    if target == "OTHER":
        return "LOW PRIORITY"
    if timing == "START_BEFORE_AVAILABLE":
        return "HOLD-TIMING"
    if visa in {"NO", "UNKNOWN"}:
        return "HOLD-VISA"
    if live is not True:
        return "VERIFY-LIVE"
    if base_fit in {"A", "B"} and visa == "VERIFY-LIKELY":
        return "VERIFY THEN APPLY"
    return "RECHECK"


def _iter_rows(client: NotionClient, source_id: str) -> list[dict[str, Any]]:
    return list(client.iter_data_source(source_id, page_size=100))


def run() -> int:
    token = os.getenv("NOTION_TOKEN", "").strip()
    source_id = os.getenv("SOURCE_NOTION_DATA_SOURCE_ID", "").strip()
    notion_version = os.getenv("NOTION_VERSION", DEFAULT_NOTION_VERSION).strip()
    output_dir = Path(os.getenv("OUTPUT_DIR", "output/aug22"))
    max_rows = int(os.getenv("MAX_ROWS", "50"))
    available_start = _parse_date(os.getenv("AVAILABLE_START_DATE", "2026-08-22"))
    arrival_date = _parse_date(os.getenv("AUSTRALIA_ARRIVAL_DATE", "2026-08-15"))
    url_checks = _text(os.getenv("URL_CHECK_ENABLED", "true")) in {"1", "true", "yes", "on"}

    if not token or not source_id or available_start is None or arrival_date is None:
        print("Missing Notion source, token, or valid arrival/start dates", file=sys.stderr)
        return 2

    try:
        config = load_config()
        client = NotionClient(token, notion_version=notion_version)
        resolved = client.resolve_data_source_id(data_source_id=source_id)
        pages = _iter_rows(client, resolved)
    except (OSError, ValueError, RuntimeError, requests.RequestException) as exc:
        print(f"AUG22 startup failed: {exc}", file=sys.stderr)
        return 2

    candidates: list[dict[str, Any]] = []
    for page in pages:
        properties = page.get("properties") or {}
        record = extract_record(properties)
        posted_date = _first_text(properties, "Posted Date")
        posted = _parse_date(posted_date)
        freshness_text = record.get("Freshness", "")
        try:
            freshness_days = float(freshness_text) if freshness_text else None
        except ValueError:
            freshness_days = None
        combined = _text(" ".join(record.values()))
        target, matches = _target_group(combined, config)
        if target == "OTHER":
            continue
        url = record.get("Canonical URL", "")
        live = check_url(url, timeout_seconds=12) if url_checks else None
        base = score(record, config, live)
        timing, timing_penalty, timing_reason = _timing_status(combined, available_start)
        visa_confidence, visa_reason = _specified_work_confidence(record, target, combined)
        target_bonus = min(10.0, 4.0 + matches * 2.0)
        visa_penalty = {"VERIFY-LIKELY": 2.0, "VERIFY": 7.0, "UNKNOWN": 10.0, "NO": 25.0}[visa_confidence]
        aug22_score = round(max(0.0, min(100.0, base.rag + target_bonus - timing_penalty - visa_penalty)), 1)
        reasons = list(base.reasons)
        if timing_reason:
            reasons.append(timing_reason)
        reasons.append(visa_reason)
        candidates.append(
            {
                "page_id": str(page.get("id", "")),
                "opportunity": record.get("Opportunity", ""),
                "company": record.get("Company", ""),
                "location": record.get("Location", ""),
                "posted_date": posted_date,
                "freshness_days": freshness_days,
                "target_group": target,
                "specified_work_confidence": visa_confidence,
                "timing_status": timing,
                "base_ccstm": base.ccstm,
                "base_hr": base.hr,
                "base_reality": base.reality,
                "base_rag": base.rag,
                "aug22_score": aug22_score,
                "decision": _decision(base.fit, live, target, timing, visa_confidence),
                "live": live,
                "job_url": url,
                "reasons": "; ".join(reasons),
                "_posted_sort": posted or date.min,
                "_created_sort": str(page.get("created_time", "")),
            }
        )

    candidates.sort(
        key=lambda row: (
            row["decision"] not in {"VERIFY THEN APPLY", "RECHECK"},
            -float(row["aug22_score"]),
            row["_posted_sort"],
            row["_created_sort"],
        )
    )
    candidates = candidates[: max(max_rows, 1)]
    for index, row in enumerate(candidates, 1):
        row["rank"] = index
        row.pop("_posted_sort", None)
        row.pop("_created_sort", None)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "aug22_report.json").write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (output_dir / "aug22_report.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(candidates)

    summary = {
        "run_label": config.get("candidate_context", {}).get("run_label", "RUN50-AUG22-20260731"),
        "arrival_date": arrival_date.isoformat(),
        "available_start_date": available_start.isoformat(),
        "source_rows": len(pages),
        "selected_rows": len(candidates),
        "decisions": {},
        "target_groups": {},
    }
    for row in candidates:
        summary["decisions"][row["decision"]] = summary["decisions"].get(row["decision"], 0) + 1
        summary["target_groups"][row["target_group"]] = summary["target_groups"].get(row["target_group"], 0) + 1
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
