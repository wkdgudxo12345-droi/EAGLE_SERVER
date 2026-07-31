from __future__ import annotations

import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests
import yaml

from .notion import NotionClient
from .properties import build_update_payload, plain_text
from .scoring import ScoreResult, score

FIELDS = [
    "Opportunity",
    "Company",
    "Region",
    "Role Family",
    "Canonical URL",
    "Source",
    "Source Job ID",
    "Evidence Text",
    "Freshness",
    "Car/Licence",
    "Accommodation",
    "WHV/88 Days",
    "Application Status",
]
CLOSED_MARKERS = (
    "job is no longer available",
    "position has been filled",
    "job has expired",
    "this job has closed",
    "no longer accepting applications",
)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None


def check_url(url: str, *, timeout_seconds: int = 18) -> bool | None:
    """Return True for live, False for confirmed closed, and None for uncertainty.

    Temporary server failures, access controls and rate limits must not close a
    vacancy in the Final DB. Only clear client-side absence or an explicit closed
    marker is treated as confirmed closure.
    """

    if not url:
        return False
    headers = {"User-Agent": "Mozilla/5.0 EagleJobVerifier/1.2"}
    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=timeout_seconds,
            allow_redirects=True,
        )
    except requests.RequestException:
        return None
    try:
        if response.status_code in {401, 403, 408, 425, 429}:
            return None
        if response.status_code >= 500:
            return None
        if response.status_code in {404, 410}:
            return False
        if response.status_code >= 400:
            return None
        body = response.content[:200_000].decode(
            response.encoding or "utf-8", errors="ignore"
        ).lower()
        return not any(marker in body for marker in CLOSED_MARKERS)
    finally:
        response.close()


def _config_path() -> Path:
    configured = os.getenv("EAGLE_CONFIG")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[1] / "config" / "scoring.yml"


def load_config() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        raise FileNotFoundError(f"Scoring config not found: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError("Scoring config must be a YAML mapping")
    return loaded


def _result_values(result: ScoreResult, live: bool | None) -> dict[str, Any]:
    passed = result.fit in {"A", "B"}
    return {
        "CCSTM": result.ccstm,
        "HR Score": result.hr,
        "Reality Score": result.reality,
        "RAG Priority": result.rag,
        "RAG Confidence": 95 if live is True else (70 if live is None else 40),
        "Fit": result.fit,
        "RAG Verdict": result.verdict,
        "Red Team Status": (
            "PASS" if passed else ("REJECT" if result.fit == "Reject" else "HOLD")
        ),
        "Proof Gate": "PASS" if passed and live is True else "REJECT",
        "Vacancy Status": (
            "Live" if live is True else ("Closed" if live is False else "Needs recheck")
        ),
        "Main DB": passed,
        "Duplicate Key": result.duplicate_key,
        "RAG Review Note": "; ".join(result.reasons),
        "Next Action": (
            "지원"
            if passed
            else ("제출 DB 제외" if result.fit == "Reject" else "재검증")
        ),
    }


def write_reports(report: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    columns = [
        "id",
        "opportunity",
        "company",
        "fit",
        "verdict",
        "ccstm",
        "hr",
        "reality",
        "rag",
        "live",
        "duplicate",
        "reasons",
    ]
    with (output_dir / "report.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(report)


def main() -> int:
    token = os.getenv("NOTION_TOKEN", "").strip()
    database_id = os.getenv("NOTION_DATABASE_ID", "").strip()
    apply_changes = env_bool("APPLY_CHANGES", False)
    archive_rejected = env_bool("ARCHIVE_REJECTED", False)
    url_checks = env_bool("URL_CHECK_ENABLED", True)
    max_rows = env_int("MAX_ROWS")

    if not token or not database_id:
        print("Missing NOTION_TOKEN or NOTION_DATABASE_ID", file=sys.stderr)
        return 2
    if archive_rejected and not apply_changes:
        print(
            "ARCHIVE_REJECTED ignored because APPLY_CHANGES is false",
            file=sys.stderr,
        )
        archive_rejected = False

    try:
        config = load_config()
        client = NotionClient(
            token,
            notion_version=os.getenv("NOTION_VERSION", "2022-06-28"),
        )
        schema = client.database_properties(database_id)
        pages = list(client.iter_database(database_id, max_rows=max_rows))
    except (OSError, ValueError, RuntimeError, requests.RequestException) as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        return 2

    print(
        f"Loaded {len(pages)} rows | apply_changes={apply_changes} "
        f"archive_rejected={archive_rejected} url_checks={url_checks}"
    )
    seen: dict[str, str] = {}
    report: list[dict[str, Any]] = []

    for index, page in enumerate(pages, 1):
        props = page.get("properties", {})
        record = {field: plain_text(props.get(field)) for field in FIELDS}
        url = record.get("Canonical URL") or record.get("Source") or ""
        live = check_url(url) if url_checks else None
        result = score(record, config, live)

        duplicate = bool(result.duplicate_key and result.duplicate_key in seen)
        if duplicate:
            result.fit = "Reject"
            result.verdict = "DELETE CANDIDATE"
            result.hard_gate = True
            result.reasons.append("duplicate job")
        elif result.duplicate_key:
            seen[result.duplicate_key] = str(page.get("id", ""))

        values = _result_values(result, live)
        payload, skipped = build_update_payload(schema, values)
        if apply_changes:
            try:
                client.update_page(str(page["id"]), payload)
                if archive_rejected and result.fit == "Reject":
                    client.archive_page(str(page["id"]))
                time.sleep(0.35)
            except (RuntimeError, requests.RequestException) as exc:
                result.reasons.append(f"Notion write failed: {exc}")

        row = {
            "id": str(page.get("id", "")),
            "opportunity": record.get("Opportunity", ""),
            "company": record.get("Company", ""),
            "fit": result.fit,
            "verdict": result.verdict,
            "ccstm": result.ccstm,
            "hr": result.hr,
            "reality": result.reality,
            "rag": result.rag,
            "live": live,
            "duplicate": duplicate,
            "reasons": "; ".join(result.reasons),
        }
        report.append(row)
        skipped_note = f" | skipped={len(skipped)}" if skipped else ""
        print(
            f"[{index}/{len(pages)}] {result.fit:6} {result.rag:5.1f} "
            f"{record.get('Opportunity', '')[:60]}{skipped_note}"
        )

    output_dir = Path(os.getenv("OUTPUT_DIR", "output"))
    write_reports(report, output_dir)
    summary = {
        fit: sum(1 for row in report if row["fit"] == fit)
        for fit in ("A", "B", "C", "Reject")
    }
    print("SUMMARY", json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
