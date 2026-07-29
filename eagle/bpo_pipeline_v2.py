from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import yaml

from .bpo_scoring_v2 import score_record


def load_profile(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError("Profile must be a YAML mapping")
    return loaded


def load_records(path: Path) -> list[dict[str, Any]]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, list):
        raise ValueError("Input must be a JSON array")
    return [{str(k): v for k, v in row.items()} for row in loaded if isinstance(row, dict)]


def run(input_path: Path, profile_path: Path, output_dir: Path) -> list[dict[str, Any]]:
    profile = load_profile(profile_path)
    records = load_records(input_path)
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []

    for record in records:
        result = score_record(record, profile)
        duplicate = bool(result.canonical_key and result.canonical_key in seen)
        if result.canonical_key and not duplicate:
            seen.add(result.canonical_key)
        row = dict(record)
        row.update({
            "hiring_probability_score": result.hiring_probability_score,
            "estimated_hire_range": result.estimated_hire_range,
            "salary_score": result.salary_score,
            "career_fit_score": result.career_fit_score,
            "english_fit": result.english_fit,
            "visa_score": result.visa_score,
            "final_score": result.final_score,
            "queue": "Reject" if duplicate else result.queue,
            "hard_gate": result.hard_gate or duplicate,
            "duplicate": duplicate,
            "canonical_key": result.canonical_key,
            "individual_url": result.individual_url,
            "reasons": "; ".join(result.reasons + (["duplicate vacancy"] if duplicate else [])),
        })
        rows.append(row)

    order = {"A - Apply First": 0, "B - Apply": 1, "C - Verify/Hold": 2, "D - Low Priority": 3, "Reject": 4}
    rows.sort(key=lambda row: (order.get(str(row.get("queue")), 9), -float(row.get("final_score", 0))))
    for index, row in enumerate(rows, 1):
        row["rank"] = index

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "bpo_v2_report.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    columns = sorted({key for row in rows for key in row})
    with (output_dir / "bpo_v2_report.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Korean BPO Eagle V2")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--profile", type=Path, default=Path("profiles/korean_bpo_v2.yml"))
    parser.add_argument("--output", type=Path, default=Path("output/bpo_v2"))
    args = parser.parse_args()
    rows = run(args.input, args.profile, args.output)
    summary: dict[str, int] = {}
    for row in rows:
        summary[row["queue"]] = summary.get(row["queue"], 0) + 1
    print(json.dumps({"rows": len(rows), "summary": summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
