from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import requests
import yaml

from .final_sync import (
    PROTECTED_APPLY_STATUSES,
    SyncRow,
    _build_payload,
    _canonical_key,
    _clean,
    _create_page,
    _existing_indexes,
    _float_text,
    _get_text,
    _load_crawl,
    _option,
    _values_for_final,
    evaluate_candidates,
)
from .main import check_url, load_config
from .notion import DEFAULT_NOTION_VERSION, NotionClient
from .scoring import normalize_url


DEFAULT_FINAL_SOURCE_ID = "2403ff84-448e-4b24-b30d-3ced754b5450"
DEFAULT_CRAWL_CONFIG = "config/crawl_aug22_2026.yml"
RULE_VERSION = "EAGLE-V4.0-20260728"


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_iso_date(value: str) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _source_map(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = {
        str(item.get("id")): dict(item)
        for item in loaded.get("sources", [])
        if isinstance(item, dict) and item.get("id")
    }
    return sources, loaded


def _enrich_item(item: dict[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    enriched = dict(item)
    if not _clean(enriched.get("location")):
        enriched["location"] = _clean(source.get("location"))
    if source.get("industry_context"):
        enriched["industry_context"] = _clean(source.get("industry_context"))
    enriched["trusted_industry_context"] = bool(
        source.get("trusted_industry_context")
    )
    return enriched


def _has_food_industry_evidence(
    item: Mapping[str, Any], crawl_config: Mapping[str, Any]
) -> bool:
    if str(item.get("route", "")).upper() != "FOOD":
        return True
    if bool(item.get("trusted_industry_context")):
        return True
    text = " ".join(
        [
            _clean(item.get("title")),
            _clean(item.get("job_url")),
            _clean(item.get("industry_context")),
            " ".join(str(value) for value in item.get("matched_terms", []) or []),
        ]
    ).lower()
    return any(
        str(term).lower() in text
        for term in crawl_config.get("food_industry_terms", []) or []
    )


def pre_gate_candidates(
    items: list[dict[str, Any]],
    sources: Mapping[str, Mapping[str, Any]],
    crawl_config: Mapping[str, Any],
    *,
    url_checker=check_url,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    passed: list[dict[str, Any]] = []
    report: list[dict[str, Any]] = []
    live_cache: dict[str, bool | None] = {}

    for raw in items:
        source = sources.get(str(raw.get("source_id", "")), {})
        item = _enrich_item(raw, source)
        url = _clean(item.get("job_url"))
        gate = "PASS_TO_SCORE"
        reason = "individual URL is live and route evidence is sufficient"

        if _clean(item.get("decision")) != "KEEP":
            gate = "REJECT_CRAWL_GATE"
            reason = f"crawler decision={_clean(item.get('decision'))}"
        elif not url:
            gate = "REJECT_NO_URL"
            reason = "missing individual job URL"
        elif not _has_food_industry_evidence(item, crawl_config):
            gate = "REJECT_FOOD_CONTEXT"
            reason = "food function found without reliable food-processing context"
        else:
            normalized = normalize_url(url)
            if normalized not in live_cache:
                live_cache[normalized] = url_checker(url, timeout_seconds=12)
            live = live_cache[normalized]
            if live is False:
                gate = "REJECT_CLOSED"
                reason = "individual URL appears closed"
            elif live is None:
                gate = "REJECT_UNVERIFIED_URL"
                reason = "individual URL could not be verified"

        report.append(
            {
                "company": _clean(item.get("company")),
                "title": _clean(item.get("title")),
                "source_id": _clean(item.get("source_id")),
                "job_url": url,
                "gate": gate,
                "reason": reason,
            }
        )
        if gate == "PASS_TO_SCORE":
            passed.append(item)

    return passed, report


def _run_id() -> str:
    configured = os.getenv("PIPELINE_RUN_ID", "").strip()
    if configured:
        return configured
    return "EAGLE-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _lifecycle_values(
    existing_properties: Mapping[str, Mapping[str, Any]] | None,
    *,
    run_id: str,
    today: str,
) -> dict[str, Any]:
    existing_properties = existing_properties or {}
    is_new = not bool(existing_properties)
    seen_count = _float_text(existing_properties, "Seen Count") + 1
    values: dict[str, Any] = {
        "Pipeline Run ID": run_id,
        "V4 Run ID": run_id,
        "Last Seen": today,
        "Seen Count": seen_count,
        "Lifecycle": "NEW" if is_new else "ACTIVE",
        "Rule Version": RULE_VERSION,
        "Track": "Second Visa",
    }
    if is_new:
        values["First Seen"] = today
    return values


def _recommendation_values(fit: str) -> dict[str, str]:
    return {
        "RAG Verdict": "STRONG RECOMMEND" if fit == "A" else "RECOMMEND",
        "Red Team Verdict": "PASS",
    }


def _stale_due(properties: Mapping[str, Mapping[str, Any]], days: int) -> bool:
    last_seen = _parse_iso_date(_get_text(properties, "Last Seen"))
    if last_seen is None:
        return False
    return (date.today() - last_seen).days >= days


def reconcile_existing(
    client: NotionClient,
    schema: Mapping[str, Mapping[str, Any]],
    pages: list[dict[str, Any]],
    current_keys: set[str],
    *,
    max_checks: int,
    stale_days: int,
    apply_changes: bool,
) -> list[SyncRow]:
    rows: list[SyncRow] = []
    checks = 0
    today = date.today().isoformat()

    for page in pages:
        if checks >= max_checks:
            break
        properties = page.get("properties") or {}
        status = _get_text(properties, "Apply Status")
        if status in PROTECTED_APPLY_STATUSES:
            continue
        key = _get_text(properties, "Canonical Key")
        if key and key in current_keys:
            continue
        url = _get_text(properties, "Apply URL")
        if not url:
            continue

        checks += 1
        live = check_url(url, timeout_seconds=12)
        action = ""
        reason = ""
        values: dict[str, Any] = {"Last Verified": today}

        if live is False:
            action = "MARK_CLOSED"
            reason = "individual URL closed"
            values.update(
                {
                    "Apply Status": _option(
                        schema, "Apply Status", "CLOSED", "Closed"
                    ),
                    "Audit Status": _option(schema, "Audit Status", "FAILED"),
                    "Operational Decision": _option(
                        schema, "Operational Decision", "DO NOT APPLY"
                    ),
                    "Lifecycle": _option(schema, "Lifecycle", "CLOSED"),
                    "Final Recommendation": (
                        "자동 URL 점검에서 종료 확인. 지원 이력 보존을 위해 CLOSED 처리."
                    ),
                }
            )
        elif live is None and _stale_due(properties, stale_days):
            action = "MARK_STALE"
            reason = f"URL unverifiable and not rediscovered for {stale_days}+ days"
            values.update(
                {
                    "Lifecycle": _option(schema, "Lifecycle", "STALE"),
                    "Audit Status": _option(schema, "Audit Status", "RECHECK"),
                }
            )
        elif live is True:
            action = "VERIFY_ACTIVE"
            reason = "URL remains live"
            if not _get_text(properties, "Lifecycle"):
                values["Lifecycle"] = _option(schema, "Lifecycle", "ACTIVE")
        else:
            continue

        payload, skipped = _build_payload(schema, values)
        if apply_changes and payload:
            client.update_page(str(page.get("id", "")), payload)
        rows.append(
            SyncRow(
                action=action if apply_changes else f"WOULD_{action}",
                page_id=str(page.get("id", "")),
                title=_get_text(properties, "Opportunity"),
                company=_get_text(properties, "Company"),
                canonical_key=key,
                decision=_get_text(properties, "Operational Decision"),
                fit=_get_text(properties, "Fit"),
                ccstm=_float_text(properties, "CCSTM"),
                hr=_float_text(properties, "HR Score"),
                reality=_float_text(properties, "Reality Score"),
                rag=_float_text(properties, "Strategy Score"),
                estimated_hire=_float_text(properties, "Estimated Hire %"),
                reason=reason
                + (f"; skipped fields: {', '.join(skipped)}" if skipped else ""),
                job_url=url,
            )
        )

    return rows


def _write_reports(
    output_dir: Path,
    rows: list[SyncRow],
    gate_report: list[dict[str, Any]],
    summary: Mapping[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    row_dicts = [asdict(row) for row in rows]
    (output_dir / "sync_report.json").write_text(
        json.dumps(row_dicts, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "gate_report.json").write_text(
        json.dumps(gate_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "summary.json").write_text(
        json.dumps(dict(summary), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    with (output_dir / "sync_report.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SyncRow.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(row_dicts)

    gate_columns = ["company", "title", "source_id", "job_url", "gate", "reason"]
    with (output_dir / "gate_report.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=gate_columns)
        writer.writeheader()
        writer.writerows(gate_report)


def run() -> int:
    token = os.getenv("NOTION_TOKEN", "").strip()
    source_id = os.getenv(
        "FINAL_NOTION_DATA_SOURCE_ID", DEFAULT_FINAL_SOURCE_ID
    ).strip()
    notion_version = os.getenv("NOTION_VERSION", DEFAULT_NOTION_VERSION).strip()
    crawl_path = Path(os.getenv("CRAWL_REPORT", "output/crawl/crawl_report.json"))
    crawl_config_path = Path(os.getenv("EAGLE_CRAWL_CONFIG", DEFAULT_CRAWL_CONFIG))
    output_dir = Path(os.getenv("OUTPUT_DIR", "output/final_sync"))
    max_final_rows = int(os.getenv("MAX_FINAL_ROWS", "15"))
    max_rechecks = int(os.getenv("MAX_EXISTING_RECHECKS", "100"))
    stale_days = int(os.getenv("STALE_AFTER_DAYS", "14"))
    apply_changes = _bool_env("APPLY_CHANGES", True)
    run_id = _run_id()
    today = date.today().isoformat()

    if not token:
        print("Missing NOTION_TOKEN", file=sys.stderr)
        return 2
    if not crawl_path.exists() or not crawl_config_path.exists():
        print("Missing crawl report or crawl config", file=sys.stderr)
        return 2

    try:
        scoring_config = load_config()
        raw_items = _load_crawl(crawl_path)
        sources, crawl_config = _source_map(crawl_config_path)
        passed_items, gate_report = pre_gate_candidates(
            raw_items, sources, crawl_config
        )
        finalists = evaluate_candidates(
            passed_items, scoring_config, max_final_rows=max_final_rows
        )
        client = NotionClient(token, notion_version=notion_version)
        resolved = client.resolve_data_source_id(data_source_id=source_id)
        schema = client.data_source_properties(resolved)
        pages = list(client.iter_data_source(resolved, page_size=100))
    except (OSError, ValueError, RuntimeError, requests.RequestException) as exc:
        print(f"Pipeline startup failed: {exc}", file=sys.stderr)
        return 2

    by_key, by_url = _existing_indexes(pages)
    rows: list[SyncRow] = []
    current_keys: set[str] = set()

    for evaluated in finalists:
        item = evaluated["item"]
        key = _canonical_key(item)
        current_keys.add(key)
        normalized_url = normalize_url(_clean(item.get("job_url")))
        existing = by_key.get(key) or by_url.get(normalized_url)
        properties = existing.get("properties") or {} if existing else {}
        preserved_status = _get_text(properties, "Apply Status")

        values = _values_for_final(
            evaluated, schema, preserve_status=preserved_status
        )
        values.update(
            _lifecycle_values(properties, run_id=run_id, today=today)
        )
        values.update(_recommendation_values(evaluated["score"].fit))
        payload, skipped = _build_payload(schema, values)

        action = "UPDATE" if existing else "CREATE"
        page_id = str(existing.get("id", "")) if existing else ""
        if apply_changes and payload:
            if existing:
                client.update_page(page_id, payload)
            else:
                created = _create_page(client, resolved, payload)
                page_id = str(created.get("id", ""))

        result = evaluated["score"]
        rows.append(
            SyncRow(
                action=action if apply_changes else f"WOULD_{action}",
                page_id=page_id,
                title=evaluated["record"]["Opportunity"],
                company=evaluated["record"]["Company"],
                canonical_key=key,
                decision=evaluated["decision"],
                fit=result.fit,
                ccstm=result.ccstm,
                hr=result.hr,
                reality=result.reality,
                rag=result.rag,
                estimated_hire=float(evaluated["estimated_hire"]),
                reason="; ".join(result.reasons)
                + (f"; skipped fields: {', '.join(skipped)}" if skipped else ""),
                job_url=_clean(item.get("job_url")),
            )
        )

    rows.extend(
        reconcile_existing(
            client,
            schema,
            pages,
            current_keys,
            max_checks=max_rechecks,
            stale_days=stale_days,
            apply_changes=apply_changes,
        )
    )

    summary = {
        "run_id": run_id,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "apply_changes": apply_changes,
        "raw_rows": len(raw_items),
        "passed_pre_gate": len(passed_items),
        "finalists": len(finalists),
        "created": sum(row.action == "CREATE" for row in rows),
        "updated": sum(row.action == "UPDATE" for row in rows),
        "closed": sum(row.action == "MARK_CLOSED" for row in rows),
        "stale": sum(row.action == "MARK_STALE" for row in rows),
        "verified_active": sum(row.action == "VERIFY_ACTIVE" for row in rows),
        "protected_apply_statuses": sorted(PROTECTED_APPLY_STATUSES),
        "final_db_source_id": resolved,
    }
    _write_reports(output_dir, rows, gate_report, summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
