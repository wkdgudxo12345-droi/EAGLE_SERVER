from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import yaml

from .malaysia_career_scoring_v3 import score_record


def load_profile(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError("Profile must be a YAML mapping")
    return loaded


def load_records(path: Path) -> list[dict[str, Any]]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, list):
        raise ValueError("Input must be a JSON array")
    return [{str(key): value for key, value in row.items()} for row in loaded if isinstance(row, dict)]


def run(input_path: Path, profile_path: Path, output_dir: Path) -> dict[str, list[dict[str, Any]]]:
    profile = load_profile(profile_path)
    records = load_records(input_path)
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []

    for record in records:
        result = score_record(record, profile)
        duplicate = bool(result.canonical_key and result.canonical_key in seen)
        if result.canonical_key and not duplicate:
            seen.add(result.canonical_key)
        queue = "Reject" if duplicate else result.queue
        reasons = list(result.reasons)
        if duplicate:
            reasons.append("duplicate vacancy")
        row = dict(record)
        row.update({
            "industry_track": result.industry_track,
            "role_track": result.role_track,
            "hiring_reality_score": result.hiring_reality_score,
            "career_transfer_score": result.career_transfer_score,
            "salary_score": result.salary_score,
            "career_upside_score": result.career_upside_score,
            "authorization_stability_score": result.authorization_stability_score,
            "final_score": result.final_score,
            "queue": queue,
            "hard_gate": result.hard_gate or duplicate,
            "duplicate": duplicate,
            "canonical_key": result.canonical_key,
            "individual_url": result.individual_url,
            "cv_variant": result.cv_variant,
            "reasons": "; ".join(reasons),
        })
        rows.append(row)

    order = {"A - Apply First": 0, "B - Apply": 1, "C - Verify/Hold": 2, "Reject": 3}
    rows.sort(key=lambda row: (order.get(str(row.get("queue")), 9), -float(row.get("final_score", 0))))
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank

    thresholds = profile.get("thresholds", {})
    max_shortlist = int(thresholds.get("max_shortlist", 20))
    report_top = int(thresholds.get("report_top", 5))
    shortlist = [row for row in rows if row["queue"] in {"A - Apply First", "B - Apply"}][:max_shortlist]
    top = shortlist[:report_top]

    output_dir.mkdir(parents=True, exist_ok=True)
    payloads = {"all": rows, "shortlist": shortlist, "top": top}
    for name, payload in payloads.items():
        (output_dir / f"malaysia_career_v3_{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    columns = sorted({key for row in rows for key in row})
    with (output_dir / "malaysia_career_v3_all.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    with (output_dir / "malaysia_career_v3_shortlist.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(shortlist)

    summary = {
        "rows": len(rows),
        "shortlist": len(shortlist),
        "top_report": len(top),
        "queues": {queue: sum(1 for row in rows if row["queue"] == queue) for queue in order},
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return payloads


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Malaysia Korean Operations Eagle V3")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--profile", type=Path, default=Path("profiles/malaysia_korean_ops_v3.yml"))
    parser.add_argument("--output", type=Path, default=Path("output/malaysia_career_v3"))
    args = parser.parse_args()
    payloads = run(args.input, args.profile, args.output)
    print(json.dumps({"shortlist": len(payloads["shortlist"]), "top": len(payloads["top"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
