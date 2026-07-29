from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import requests

from .evidence_rag_v2 import run_evidence_rag
from .main import check_url, env_bool, env_int, load_config
from .notion import DEFAULT_NOTION_VERSION, NotionClient, normalize_notion_id
from .policy import evaluate_policy
from .properties import plain_text
from .record import extract_record, schema_health
from .scoring import normalize_url, score

REPORT_COLUMNS = [
    "id",
    "opportunity",
    "company",
    "location",
    "role_family",
    "canonical_url",
    "source_job_id",
    "fit",
    "decision",
    "promotion_allowed",
    "apply_ready",
    "proof_gate",
    "red_team_status",
    "second_visa_state",
    "cv_ready",
    "cv_filename",
    "ccstm",
    "hr",
    "reality",
    "rag_priority",
    "rag_verdict",
    "rag_proof_score",
    "rag_provider",
    "live",
    "individual_url",
    "duplicate",
    "duplicate_key",
    "reasons",
]


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _truthy(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "ready", "__yes__"}


def _first_text(properties: Mapping[str, Mapping[str, Any]], *aliases: str) -> str:
    for alias in aliases:
        value = plain_text(properties.get(alias))
        if value.strip():
            return value.strip()
    return ""


def _build_incremental_filter(
    schema: Mapping[str, Mapping[str, Any]], statuses: list[str]
) -> dict[str, Any] | None:
    conditions: list[dict[str, Any]] = []
    audit_name = "Audit Status" if "Audit Status" in schema else None
    if audit_name:
        prop_type = str(schema[audit_name].get("type") or "select")
        if prop_type not in {"select", "status"}:
            prop_type = "select"
        for status in statuses:
            conditions.append({"property": audit_name, prop_type: {"equals": status}})
    if "Today Only" in schema and schema["Today Only"].get("type") == "checkbox":
        conditions.append({"property": "Today Only", "checkbox": {"equals": True}})
    if not conditions:
        return None
    return conditions[0] if len(conditions) == 1 else {"or": conditions}


def _iter_filtered_pages(
    client: NotionClient,
    data_source_id: str,
    *,
    filter_payload: dict[str, Any] | None,
    max_rows: int | None,
) -> list[dict[str, Any]]:
    data_source_id = normalize_notion_id(data_source_id)
    cursor: str | None = None
    rows: list[dict[str, Any]] = []
    while True:
        payload: dict[str, Any] = {"page_size": 100, "result_type": "page"}
        if filter_payload:
            payload["filter"] = filter_payload
        if cursor:
            payload["start_cursor"] = cursor
        data = client._request("POST", f"/data_sources/{data_source_id}/query", json=payload)
        for page in data.get("results") or []:
            if isinstance(page, dict) and page.get("object") == "page":
                rows.append(page)
                if max_rows is not None and len(rows) >= max_rows:
                    return rows
        if not data.get("has_more"):
            return rows
        cursor = data.get("next_cursor")
        if not cursor:
            return rows


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _url_status(
    url: str,
    *,
    cache: dict[str, Any],
    now: float,
    timeout_seconds: int,
    enabled: bool,
) -> tuple[bool | None, bool]:
    if not enabled:
        return None, False
    normalized = normalize_url(url)
    if not normalized:
        return False, False
    key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    entry = cache.get(key) if isinstance(cache.get(key), dict) else None
    if entry and float(entry.get("expires_at", 0)) > now:
        state = str(entry.get("state"))
        return {"live": True, "closed": False}.get(state), True
    live = check_url(url, timeout_seconds=timeout_seconds)
    if live is True:
        ttl = int(os.getenv("URL_CACHE_LIVE_SECONDS", "86400"))
        state = "live"
    elif live is False:
        ttl = int(os.getenv("URL_CACHE_CLOSED_SECONDS", "21600"))
        state = "closed"
    else:
        ttl = int(os.getenv("URL_CACHE_UNKNOWN_SECONDS", "10800"))
        state = "unknown"
    cache[key] = {
        "url": normalized,
        "state": state,
        "checked_at": int(now),
        "expires_at": int(now + max(ttl, 60)),
    }
    return live, False


def _is_individual_url(url: str, search_patterns: list[str]) -> bool:
    normalized = normalize_url(url)
    return bool(normalized) and not any(
        pattern.lower() in normalized.lower() for pattern in search_patterns
    )


def _feedback_summary(path: Path, work_rights: str) -> dict[str, Any]:
    value = _load_json(path)
    outcomes = value.get("outcomes") if isinstance(value.get("outcomes"), list) else []
    counts = Counter(str(row.get("outcome_code")) for row in outcomes if isinstance(row, dict))
    alerts: list[str] = []
    if counts.get("R01") and work_rights != "granted":
        alerts.append("BLOCK_ATS_WORK_RIGHTS_UNTIL_VISA_GRANTED")
    if counts.get("R03"):
        alerts.append("VERIFY_DOB_AND_OVER_18_SCREENING_ANSWERS")
    if counts.get("R07"):
        alerts.append("INTERVIEW_COACHING_REQUIRED_CV_ALREADY_PASSED")
    return {"counts": dict(sorted(counts.items())), "alerts": alerts}


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    token = os.getenv("NOTION_TOKEN", "").strip()
    database_id = os.getenv("NOTION_DATABASE_ID", "").strip()
    requested_data_source_id = os.getenv("NOTION_DATA_SOURCE_ID", "").strip()
    notion_version = os.getenv("NOTION_VERSION", DEFAULT_NOTION_VERSION).strip()
    strict_schema = env_bool("STRICT_SCHEMA", True)
    max_rows = env_int("MAX_ROWS")
    url_checks = env_bool("URL_CHECK_ENABLED", True)
    url_timeout = env_int("URL_CHECK_TIMEOUT_SECONDS") or 12
    require_cv_ready = env_bool("PROMOTION_REQUIRE_CV_READY", True)
    use_llm = env_bool("RAG_USE_LLM", False)
    require_llm = env_bool("REQUIRE_LLM_RAG", False)
    work_rights = os.getenv("CANDIDATE_WORK_RIGHTS", "application_in_progress").strip().lower()
    statuses = [
        item.strip()
        for item in os.getenv("INCREMENTAL_AUDIT_STATUSES", "PENDING,RECHECK").split(",")
        if item.strip()
    ]
    output_dir = Path(os.getenv("OUTPUT_DIR", "output"))
    state_dir = Path(os.getenv("STATE_DIR", "state"))
    cache_path = state_dir / "url_cache.json"
    feedback_path = Path(os.getenv("OUTCOME_FEEDBACK_FILE", "output/gmail_outcomes.json"))
    evidence_path = Path(os.getenv("EAGLE_EVIDENCE_FILE", "data/policy_evidence.json"))
    run_id = os.getenv("EAGLE_RUN_KEY", "local")

    output_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    if not token or not (database_id or requested_data_source_id):
        print("Missing NOTION_TOKEN and source Notion ID", file=sys.stderr)
        return 2
    if not evidence_path.exists():
        print(f"Evidence file not found: {evidence_path}", file=sys.stderr)
        return 2

    try:
        config = load_config()
        client = NotionClient(token, notion_version=notion_version)
        data_source_id = client.resolve_data_source_id(
            database_id=database_id or None,
            data_source_id=requested_data_source_id or None,
        )
        schema = client.data_source_properties(data_source_id)
        health = schema_health(schema)
        if health["missing_fatal"] or (strict_schema and health["missing_promotion"]):
            raise RuntimeError(
                f"schema preflight failed: fatal={health['missing_fatal']} promotion={health['missing_promotion']}"
            )
        filter_payload = _build_incremental_filter(schema, statuses)
        pages = _iter_filtered_pages(
            client,
            data_source_id,
            filter_payload=filter_payload,
            max_rows=max_rows,
        )
    except (OSError, ValueError, RuntimeError, requests.RequestException) as exc:
        _atomic_json(output_dir / "preflight.json", {"status": "failed", "error": str(exc)})
        print(f"Incremental startup failed: {exc}", file=sys.stderr)
        return 2

    _atomic_json(
        output_dir / "preflight.json",
        {
            "status": "ready",
            "data_source_id": data_source_id,
            "filter": filter_payload,
            "selected_rows": len(pages),
            "schema": health,
        },
    )

    cache = _load_json(cache_path)
    report: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    search_patterns = [str(value) for value in config.get("search_url_patterns", [])]
    feedback = _feedback_summary(feedback_path, work_rights)
    cache_hits = 0

    for index, page in enumerate(pages, 1):
        properties = page.get("properties") or {}
        record = extract_record(properties)
        cv_ready = _truthy(_first_text(properties, "CV Ready"))
        cv_filename = _first_text(properties, "CV Filename")
        url = record.get("Canonical URL", "")
        live, cache_hit = _url_status(
            url,
            cache=cache,
            now=time.time(),
            timeout_seconds=url_timeout,
            enabled=url_checks,
        )
        cache_hits += int(cache_hit)
        individual_url = _is_individual_url(url, search_patterns)
        scoring = score(record, config, live)
        duplicate = bool(scoring.duplicate_key and scoring.duplicate_key in seen)
        if scoring.duplicate_key:
            seen.add(scoring.duplicate_key)
        if duplicate:
            scoring.hard_gate = True
            scoring.reasons.append("duplicate job in current incremental batch")

        rag = run_evidence_rag(
            record,
            live=live,
            individual_url=individual_url,
            evidence_path=evidence_path,
            use_llm=use_llm,
            require_llm=require_llm,
        )
        policy = evaluate_policy(
            record,
            live=live,
            individual_url=individual_url,
            duplicate=duplicate,
            scoring_hard_gate=scoring.hard_gate,
            rag_verdict=rag.verdict,
        )

        audit_verified = record.get("Audit Status", "").upper() == "VERIFIED"
        evidence_grade = record.get("Evidence Grade", "").upper()
        base_promotion = (
            policy.promotion_allowed
            and scoring.fit in {"A", "B"}
            and audit_verified
            and evidence_grade in {"A", "B"}
        )
        promotion_allowed = base_promotion and (cv_ready or not require_cv_ready)
        apply_ready = promotion_allowed and work_rights == "granted"

        reasons = list(dict.fromkeys(scoring.reasons + rag.reasons + policy.reasons))
        if base_promotion and require_cv_ready and not cv_ready:
            reasons.append("verified vacancy held until a reviewed CV is ready")
        if promotion_allowed and not apply_ready:
            reasons.append("verified vacancy held from application until work rights are granted")

        if policy.proof_gate == "REJECT":
            final_fit = "Reject"
            decision = "HOLD"
        elif apply_ready:
            final_fit = scoring.fit
            decision = "APPLY NOW"
        elif promotion_allowed:
            final_fit = scoring.fit
            decision = "VERIFIED - WAIT FOR VISA"
        else:
            final_fit = "C"
            decision = "VERIFY THEN APPLY"

        row = {
            "id": str(page.get("id") or ""),
            "opportunity": record.get("Opportunity", ""),
            "company": record.get("Company", ""),
            "location": record.get("Location", ""),
            "role_family": record.get("Role Family", ""),
            "canonical_url": url,
            "source_job_id": record.get("Source Job ID", ""),
            "fit": final_fit,
            "decision": decision,
            "promotion_allowed": promotion_allowed,
            "apply_ready": apply_ready,
            "proof_gate": policy.proof_gate,
            "red_team_status": policy.red_team_status,
            "second_visa_state": policy.second_visa_state,
            "cv_ready": cv_ready,
            "cv_filename": cv_filename,
            "ccstm": scoring.ccstm,
            "hr": scoring.hr,
            "reality": scoring.reality,
            "rag_priority": scoring.rag,
            "rag_verdict": rag.verdict,
            "rag_proof_score": rag.proof_score,
            "rag_provider": rag.provider,
            "live": live,
            "individual_url": individual_url,
            "duplicate": duplicate,
            "duplicate_key": scoring.duplicate_key,
            "reasons": "; ".join(reasons),
        }
        report.append(row)

        if promotion_allowed:
            candidates.append(
                {
                    **row,
                    "audit_status": record.get("Audit Status", ""),
                    "evidence_grade": record.get("Evidence Grade", ""),
                    "car_licence": record.get("Car/Licence", ""),
                    "accommodation": record.get("Accommodation", ""),
                    "second_visa": record.get("Second Visa", ""),
                    "freshness_days": record.get("Freshness", ""),
                    "source": record.get("Source", ""),
                    "evidence_text": record.get("Evidence Text", ""),
                    "apply_status": "READY NOW" if apply_ready else "WAIT FOR VISA",
                    "last_verified": datetime.now(timezone.utc).date().isoformat(),
                    "run_id": run_id,
                }
            )
        print(f"[{index}/{len(pages)}] {decision:24} {row['opportunity'][:56]}")

    _atomic_json(cache_path, cache)
    _atomic_json(output_dir / "report.json", report)
    _write_csv(output_dir / "report.csv", report)
    _atomic_json(output_dir / "promotion_candidates.json", candidates)
    summary = {
        "status": "completed",
        "source_rows_selected": len(pages),
        "processed": len(report),
        "promotion_candidates": len(candidates),
        "apply_now": sum(1 for row in report if row["decision"] == "APPLY NOW"),
        "verified_wait_visa": sum(
            1 for row in report if row["decision"] == "VERIFIED - WAIT FOR VISA"
        ),
        "verify": sum(1 for row in report if row["decision"] == "VERIFY THEN APPLY"),
        "hold": sum(1 for row in report if row["decision"] == "HOLD"),
        "url_cache_hits": cache_hits,
        "gmail_feedback": feedback,
    }
    _atomic_json(output_dir / "summary.json", summary)
    print("SUMMARY", json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
