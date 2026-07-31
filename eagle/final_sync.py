from __future__ import annotations

import csv
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit

import requests

from .main import check_url, load_config
from .notion import DEFAULT_NOTION_VERSION, NotionClient
from .properties import build_update_payload, plain_text
from .scoring import ScoreResult, normalize_url, score


PROTECTED_APPLY_STATUSES = {"APPLIED", "INTERVIEW"}
FINAL_DECISIONS = {"APPLY NOW", "VERIFY THEN APPLY"}


@dataclass
class SyncRow:
    action: str
    page_id: str
    title: str
    company: str
    canonical_key: str
    decision: str
    fit: str
    ccstm: float
    hr: float
    reality: float
    rag: float
    estimated_hire: float
    reason: str
    job_url: str


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _lower(value: Any) -> str:
    return _clean(value).lower()


def _list_text(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_clean(item) for item in value if _clean(item)]
    return [_clean(value)] if _clean(value) else []


def _source_job_id(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    for key in ("AdvertID", "advertid", "jobId", "jobid"):
        values = query.get(key)
        if values:
            return _clean(values[0])
    matches = re.findall(r"(?<!\d)(\d{6,})(?!\d)", parts.path)
    return matches[-1] if matches else ""


def _canonical_key(item: Mapping[str, Any]) -> str:
    url = normalize_url(_clean(item.get("job_url")))
    if url:
        return f"url:{url}"
    identity = "|".join(
        _lower(item.get(name)) for name in ("company", "title", "source_id")
    )
    return f"identity:{identity}" if identity.replace("|", "") else ""


def _department(route: str) -> str:
    return "Meat Processing & Factory" if route.upper() == "FOOD" else "Operations"


def _accommodation(item: Mapping[str, Any]) -> str:
    positives = " ".join(_list_text(item.get("positive_signals"))).lower()
    risks = " ".join(_list_text(item.get("transport_risks"))).lower()
    if any(term in positives for term in ("accommodation provided", "available on site")):
        return "Provided"
    if "own accommodation" in risks:
        return "No"
    return "Unknown"


def _car_licence(item: Mapping[str, Any]) -> str:
    risks = " ".join(_list_text(item.get("transport_risks"))).lower()
    hard = " ".join(_list_text(item.get("hard_gate_reasons"))).lower()
    combined = f"{risks} {hard}"
    if any(
        term in combined
        for term in ("own transport", "driver", "vehicle", "travel between sites")
    ):
        return "Required"
    return "Not stated"


def _whv_signal(item: Mapping[str, Any]) -> str:
    text = " ".join(
        _list_text(item.get("positive_signals"))
        + _list_text(item.get("matched_terms"))
        + [_clean(item.get("title"))]
    ).lower()
    if any(
        term in text
        for term in ("working holiday", "subclass 417", "second-year", "88 days")
    ):
        return "Likely"
    return "Unknown"


def _evidence_text(item: Mapping[str, Any]) -> str:
    fragments = [
        f"Source route: {_clean(item.get('source_id'))}",
        f"Matched: {', '.join(_list_text(item.get('matched_terms')))}",
        f"Positive signals: {', '.join(_list_text(item.get('positive_signals')))}",
        f"Transport risks: {', '.join(_list_text(item.get('transport_risks')))}",
        f"Crawl decision: {_clean(item.get('decision'))}",
        f"Fetched: {_clean(item.get('fetched_at'))}",
    ]
    excerpt = _clean(item.get("evidence_excerpt"))
    if excerpt:
        fragments.append(f"Evidence excerpt: {excerpt}")
    return "; ".join(part for part in fragments if not part.endswith(": "))


def _parse_date_hint(value: Any) -> date | None:
    raw = _clean(value)
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _freshness_days(item: Mapping[str, Any], today: date | None = None) -> float:
    parsed = _parse_date_hint(item.get("date_hint"))
    if parsed is None:
        return 0.0
    today = today or date.today()
    return float(max((today - parsed).days, 0))


def candidate_record(item: Mapping[str, Any]) -> dict[str, Any]:
    route = _clean(item.get("route")).upper()
    return {
        "Opportunity": _clean(item.get("title")) or "Untitled vacancy",
        "Company": _clean(item.get("company")),
        "Region": _clean(item.get("location")),
        "Role Family": (
            "Food Processing Operations" if route == "FOOD" else "Grain Harvest Operations"
        ),
        "Canonical URL": _clean(item.get("job_url")),
        "Source": _clean(item.get("source_url")),
        "Source Job ID": _source_job_id(_clean(item.get("job_url"))),
        "Evidence Text": _evidence_text(item),
        "Freshness": str(_freshness_days(item)),
        "Car/Licence": _car_licence(item),
        "Accommodation": _accommodation(item),
        "WHV/88 Days": _whv_signal(item),
        "Application Status": "NEW",
    }


def _estimated_hire(result: ScoreResult, official: bool) -> float:
    value = 0.45 * result.ccstm + 0.30 * result.hr + 0.25 * result.reality
    if official:
        value += 3.0
    return round(max(5.0, min(75.0, value * 0.72)), 1)


def _hire_band(value: float) -> str:
    if value >= 55:
        return "A"
    if value >= 42:
        return "B"
    if value >= 28:
        return "C"
    return "D"


def _final_decision(item: Mapping[str, Any], result: ScoreResult) -> str:
    if _clean(item.get("decision")) != "KEEP":
        return "DO NOT APPLY"
    if result.hard_gate or result.fit not in {"A", "B"}:
        return "DO NOT APPLY"
    if _car_licence(item) == "Required":
        return "DO NOT APPLY"
    if _accommodation(item) == "Provided" and _whv_signal(item) == "Likely":
        return "APPLY NOW"
    return "VERIFY THEN APPLY"


def evaluate_candidates(
    items: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    max_final_rows: int = 15,
) -> list[dict[str, Any]]:
    evaluated: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for item in items:
        if _clean(item.get("decision")) != "KEEP":
            continue
        key = _canonical_key(item)
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        record = candidate_record(item)
        result = score(record, config, True)
        decision = _final_decision(item, result)
        if decision not in FINAL_DECISIONS:
            continue
        evaluated.append(
            {
                "item": item,
                "record": record,
                "score": result,
                "decision": decision,
                "estimated_hire": _estimated_hire(
                    result, bool(item.get("official_source"))
                ),
            }
        )
    evaluated.sort(
        key=lambda row: (
            row["decision"] != "APPLY NOW",
            not bool(row["item"].get("official_source")),
            -float(row["score"].rag),
            -float(row["estimated_hire"]),
        )
    )
    return evaluated[: max(max_final_rows, 1)]


def _get_text(properties: Mapping[str, Mapping[str, Any]], *names: str) -> str:
    for name in names:
        value = plain_text(properties.get(name))
        if value:
            return value
    return ""


def _existing_indexes(
    pages: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_key: dict[str, dict[str, Any]] = {}
    by_url: dict[str, dict[str, Any]] = {}
    for page in pages:
        properties = page.get("properties") or {}
        key = _get_text(properties, "Canonical Key", "Duplicate Key")
        url = normalize_url(
            _get_text(properties, "Apply URL", "Canonical URL", "Job URL")
        )
        if key:
            by_key[key] = page
        if url:
            by_url[url] = page
    return by_key, by_url


def _title_property(schema: Mapping[str, Mapping[str, Any]]) -> str:
    for name, definition in schema.items():
        if definition.get("type") == "title":
            return name
    raise RuntimeError("Final DB has no title property")


def _option(
    schema: Mapping[str, Mapping[str, Any]], property_name: str, *candidates: str
) -> str:
    definition = schema.get(property_name) or {}
    prop_type = str(definition.get("type") or "")
    config = definition.get(prop_type) or {}
    options = [
        str(item.get("name"))
        for item in config.get("options", [])
        if item.get("name")
    ]
    by_lower = {item.lower(): item for item in options}
    for candidate in candidates:
        if candidate.lower() in by_lower:
            return by_lower[candidate.lower()]
    return candidates[0]


def _build_payload(
    schema: Mapping[str, Mapping[str, Any]], values: Mapping[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    non_dates = {
        name: value
        for name, value in values.items()
        if (schema.get(name) or {}).get("type") != "date"
    }
    payload, skipped = build_update_payload(schema, non_dates)
    for name, value in values.items():
        if (schema.get(name) or {}).get("type") != "date":
            continue
        if value:
            payload[name] = {"date": {"start": str(value)}}
        elif value is None:
            payload[name] = {"date": None}
    return payload, skipped


def _values_for_final(
    evaluated: Mapping[str, Any],
    schema: Mapping[str, Mapping[str, Any]],
    *,
    preserve_status: str = "",
) -> dict[str, Any]:
    item = evaluated["item"]
    record = evaluated["record"]
    result: ScoreResult = evaluated["score"]
    decision = evaluated["decision"]
    hire = float(evaluated["estimated_hire"])
    key = _canonical_key(item)
    title_name = _title_property(schema)
    parsed_posted = _parse_date_hint(item.get("date_hint"))

    values: dict[str, Any] = {
        title_name: record["Opportunity"],
        "Company": record["Company"],
        "Location": record["Region"],
        "Department": _option(
            schema, "Department", _department(_clean(item.get("route")))
        ),
        "Apply URL": record["Canonical URL"],
        "Canonical URL": record["Canonical URL"],
        "Canonical Key": key,
        "Duplicate Key": key,
        "Source Job ID": record["Source Job ID"],
        "Source": _clean(item.get("source_id")),
        "Audit Status": _option(
            schema,
            "Audit Status",
            "VERIFIED" if decision == "APPLY NOW" else "RECHECK",
        ),
        "Vacancy Status": _option(schema, "Vacancy Status", "LIVE", "Live"),
        "Verification Level": _option(
            schema, "Verification Level", "Individual verified"
        ),
        "Evidence Grade": _option(
            schema,
            "Evidence Grade",
            "A" if bool(item.get("official_source")) else "B",
        ),
        "Car/Licence": _option(schema, "Car/Licence", record["Car/Licence"]),
        "Accommodation": _option(
            schema, "Accommodation", record["Accommodation"]
        ),
        "Second Visa": _option(schema, "Second Visa", record["WHV/88 Days"]),
        "WHV/88 Days": _option(schema, "WHV/88 Days", record["WHV/88 Days"]),
        "Hard Gate": _option(
            schema, "Hard Gate", "CLEAR" if decision == "APPLY NOW" else "RECHECK"
        ),
        "Hard Gate Reason": (
            ""
            if decision == "APPLY NOW"
            else "Confirm accommodation, transport, exact site and 417/88-day eligibility before accepting."
        ),
        "Fit": _option(schema, "Fit", result.fit),
        "CCSTM": result.ccstm,
        "HR Score": result.hr,
        "Reality Score": result.reality,
        "RAG Priority": result.rag,
        "Strategy Score": result.rag,
        "Estimated Hire %": hire,
        "Hire Chance Band": _option(
            schema, "Hire Chance Band", _hire_band(hire)
        ),
        "Operational Decision": _option(
            schema, "Operational Decision", decision
        ),
        "Final Recommendation": (
            "지원 우선순위 상위. 개별 공고·차량·숙소·비자 조건 확인 완료."
            if decision == "APPLY NOW"
            else "Final DB 유지. 지원 전 숙소·교통·배정 사이트·417/88일 적격성 확인."
        ),
        "Apply Priority": round(100.0 - result.rag, 1),
        "Freshness Days": _freshness_days(item),
        "Last Verified": date.today().isoformat(),
        "Posted Date": parsed_posted.isoformat() if parsed_posted else None,
    }
    values["Apply Status"] = _option(
        schema,
        "Apply Status",
        preserve_status
        if preserve_status in PROTECTED_APPLY_STATUSES
        else ("READY NOW" if decision == "APPLY NOW" else "RECHECK"),
    )
    return values


def _load_crawl(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("crawl report must be a JSON list")
    return [item for item in raw if isinstance(item, dict)]


def _create_page(
    client: NotionClient, data_source_id: str, properties: Mapping[str, Any]
) -> dict[str, Any]:
    return client._request(
        "POST",
        "/pages",
        json={
            "parent": {
                "type": "data_source_id",
                "data_source_id": data_source_id,
            },
            "properties": dict(properties),
        },
    )


def _float_text(properties: Mapping[str, Mapping[str, Any]], *names: str) -> float:
    try:
        return float(_get_text(properties, *names) or 0)
    except ValueError:
        return 0.0


def _reconcile_existing(
    client: NotionClient,
    schema: Mapping[str, Mapping[str, Any]],
    pages: list[dict[str, Any]],
    current_keys: set[str],
    *,
    max_checks: int,
    apply_changes: bool,
) -> list[SyncRow]:
    rows: list[SyncRow] = []
    checks = 0
    for page in pages:
        if checks >= max_checks:
            break
        properties = page.get("properties") or {}
        status = _get_text(properties, "Apply Status")
        if status in PROTECTED_APPLY_STATUSES:
            continue
        key = _get_text(properties, "Canonical Key", "Duplicate Key")
        url = _get_text(properties, "Apply URL", "Canonical URL", "Job URL")
        if key and key in current_keys:
            continue
        if not url:
            continue
        checks += 1
        live = check_url(url, timeout_seconds=12)
        if live is not False:
            continue
        values = {
            "Apply Status": _option(
                schema, "Apply Status", "CLOSED", "Closed"
            ),
            "Audit Status": _option(schema, "Audit Status", "FAILED"),
            "Vacancy Status": _option(
                schema, "Vacancy Status", "CLOSED", "Closed"
            ),
            "Operational Decision": _option(
                schema, "Operational Decision", "DO NOT APPLY"
            ),
            "Final Recommendation": "자동 점검에서 공고 종료 확인. 이력 보존을 위해 Final DB에서 CLOSED 처리.",
            "Last Verified": date.today().isoformat(),
        }
        payload, skipped = _build_payload(schema, values)
        if apply_changes and payload:
            client.update_page(str(page.get("id", "")), payload)
        rows.append(
            SyncRow(
                action="MARK_CLOSED" if apply_changes else "WOULD_MARK_CLOSED",
                page_id=str(page.get("id", "")),
                title=_get_text(properties, "Opportunity"),
                company=_get_text(properties, "Company"),
                canonical_key=key,
                decision="DO NOT APPLY",
                fit=_get_text(properties, "Fit"),
                ccstm=_float_text(properties, "CCSTM"),
                hr=_float_text(properties, "HR Score"),
                reality=_float_text(properties, "Reality Score"),
                rag=_float_text(
                    properties, "RAG Priority", "Strategy Score"
                ),
                estimated_hire=_float_text(
                    properties, "Estimated Hire %"
                ),
                reason=f"URL closed; skipped fields: {', '.join(skipped)}",
                job_url=url,
            )
        )
    return rows


def run() -> int:
    token = os.getenv("NOTION_TOKEN", "").strip()
    source_id = os.getenv("FINAL_NOTION_DATA_SOURCE_ID", "").strip()
    notion_version = os.getenv("NOTION_VERSION", DEFAULT_NOTION_VERSION).strip()
    crawl_path = Path(
        os.getenv("CRAWL_REPORT", "output/crawl/crawl_report.json")
    )
    output_dir = Path(os.getenv("OUTPUT_DIR", "output/final_sync"))
    max_final_rows = int(os.getenv("MAX_FINAL_ROWS", "15"))
    max_rechecks = int(os.getenv("MAX_EXISTING_RECHECKS", "100"))
    apply_changes = _lower(os.getenv("APPLY_CHANGES", "true")) in {
        "1",
        "true",
        "yes",
        "on",
    }

    if not token or not source_id:
        print(
            "Missing NOTION_TOKEN or FINAL_NOTION_DATA_SOURCE_ID",
            file=sys.stderr,
        )
        return 2
    if not crawl_path.exists():
        print(f"Crawl report not found: {crawl_path}", file=sys.stderr)
        return 2

    try:
        config = load_config()
        items = _load_crawl(crawl_path)
        client = NotionClient(token, notion_version=notion_version)
        resolved = client.resolve_data_source_id(data_source_id=source_id)
        schema = client.data_source_properties(resolved)
        pages = list(client.iter_data_source(resolved, page_size=100))
        finalists = evaluate_candidates(
            items, config, max_final_rows=max_final_rows
        )
    except (
        OSError,
        ValueError,
        RuntimeError,
        requests.RequestException,
    ) as exc:
        print(f"Final sync startup failed: {exc}", file=sys.stderr)
        return 2

    by_key, by_url = _existing_indexes(pages)
    report: list[SyncRow] = []
    current_keys: set[str] = set()

    for evaluated in finalists:
        item = evaluated["item"]
        key = _canonical_key(item)
        url = normalize_url(_clean(item.get("job_url")))
        current_keys.add(key)
        existing = by_key.get(key) or by_url.get(url)
        existing_status = (
            _get_text(existing.get("properties") or {}, "Apply Status")
            if existing
            else ""
        )
        values = _values_for_final(
            evaluated, schema, preserve_status=existing_status
        )
        payload, skipped = _build_payload(schema, values)
        page_id = str(existing.get("id", "")) if existing else ""
        action = "UPDATE" if existing else "CREATE"
        if apply_changes and payload:
            if existing:
                client.update_page(page_id, payload)
            else:
                created = _create_page(client, resolved, payload)
                page_id = str(created.get("id", ""))
        result: ScoreResult = evaluated["score"]
        report.append(
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
                reason=(
                    "; ".join(result.reasons)
                    + (
                        f"; skipped schema fields: {', '.join(skipped)}"
                        if skipped
                        else ""
                    )
                ),
                job_url=_clean(item.get("job_url")),
            )
        )

    report.extend(
        _reconcile_existing(
            client,
            schema,
            pages,
            current_keys,
            max_checks=max_rechecks,
            apply_changes=apply_changes,
        )
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [asdict(row) for row in report]
    (output_dir / "sync_report.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    columns = list(SyncRow.__dataclass_fields__)
    with (output_dir / "sync_report.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "apply_changes": apply_changes,
        "crawl_rows": len(items),
        "finalists": len(finalists),
        "created": sum(1 for row in report if row.action == "CREATE"),
        "updated": sum(1 for row in report if row.action == "UPDATE"),
        "closed": sum(
            1 for row in report if row.action == "MARK_CLOSED"
        ),
        "protected_statuses": sorted(PROTECTED_APPLY_STATUSES),
        "final_db_source_id": resolved,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
