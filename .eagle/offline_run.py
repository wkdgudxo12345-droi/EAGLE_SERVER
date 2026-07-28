from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from eagle.main import check_url, env_bool, env_int, load_config, write_reports
from eagle.scoring import score

COMPACT_FIELDS = {
    "o": "Opportunity",
    "c": "Company",
    "r": "Region",
    "f": "Role Family",
    "u": "Canonical URL",
    "d": "Freshness",
    "l": "Car/Licence",
    "a": "Accommodation",
    "v": "WHV/88 Days",
    "s": "Application Status",
    "h": "Evidence Text",
}


def expand_record(item: dict[str, object]) -> dict[str, object]:
    if "o" not in item:
        return {str(key): value for key, value in item.items()}
    record: dict[str, object] = {"id": item.get("id", "")}
    for compact, full in COMPACT_FIELDS.items():
        record[full] = item.get(compact)
    record["Source"] = ""
    record["Source Job ID"] = ""
    return record


def load_records() -> list[dict[str, object]]:
    configured = os.getenv("EAGLE_SNAPSHOT")
    if configured:
        paths = [Path(configured)]
    else:
        paths = [Path(".eagle/notion_snapshot.json")]
        paths.extend(sorted(Path(".eagle").glob("notion_snapshot_part*.json")))

    records: list[dict[str, object]] = []
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"Snapshot not found: {path}")
        batch = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(batch, list):
            raise ValueError(f"Snapshot must be a JSON array: {path}")
        for item in batch:
            if not isinstance(item, dict):
                raise ValueError(f"Snapshot row is not an object: {path}")
            records.append(expand_record(item))
    return records


def main() -> int:
    records = load_records()
    max_rows = env_int("MAX_ROWS")
    if max_rows:
        records = records[:max_rows]

    config = load_config()
    url_checks = env_bool("URL_CHECK_ENABLED", True)
    seen: dict[str, str] = {}
    report: list[dict[str, object]] = []

    print(
        f"Loaded {len(records)} snapshot rows | apply_changes=false "
        f"archive_rejected=false url_checks={url_checks}"
    )

    for index, record in enumerate(records, 1):
        url = str(record.get("Canonical URL") or record.get("Source") or "")
        live = check_url(url) if url_checks else None
        result = score(record, config, live)

        duplicate = bool(result.duplicate_key and result.duplicate_key in seen)
        if duplicate:
            result.fit = "Reject"
            result.verdict = "DELETE CANDIDATE"
            result.hard_gate = True
            result.reasons.append("duplicate job")
        elif result.duplicate_key:
            seen[result.duplicate_key] = str(record.get("id", ""))

        row = {
            "id": str(record.get("id", "")),
            "opportunity": str(record.get("Opportunity", "")),
            "company": str(record.get("Company", "")),
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
        print(
            f"[{index}/{len(records)}] {result.fit:6} {result.rag:5.1f} "
            f"{str(record.get('Opportunity', ''))[:60]}"
        )

    write_reports(report, Path(os.getenv("OUTPUT_DIR", "output")))
    summary = {
        fit: sum(1 for row in report if row["fit"] == fit)
        for fit in ("A", "B", "C", "Reject")
    }
    print("SUMMARY", json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
