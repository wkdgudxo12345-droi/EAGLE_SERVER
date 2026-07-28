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


def main() -> int:
    snapshot_path = Path(os.getenv("EAGLE_SNAPSHOT", ".eagle/notion_snapshot.json"))
    if not snapshot_path.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot_path}")

    records = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("Snapshot must be a JSON array")

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

    for index, item in enumerate(records, 1):
        if not isinstance(item, dict):
            raise ValueError(f"Snapshot row {index} is not an object")
        record = {str(key): value for key, value in item.items()}
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
