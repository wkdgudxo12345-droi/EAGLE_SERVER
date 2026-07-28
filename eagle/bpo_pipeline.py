from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import yaml

from .bpo_scoring import BpoScoreResult, score_bpo


def load_profile(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError("BPO profile must be a YAML mapping")
    return loaded


def load_records(path: Path) -> list[dict[str, Any]]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, list):
        raise ValueError("BPO input must be a JSON array")
    records: list[dict[str, Any]] = []
    for index, item in enumerate(loaded, 1):
        if not isinstance(item, dict):
            raise ValueError(f"BPO input row {index} is not an object")
        records.append({str(key): value for key, value in item.items()})
    return records


def infer_live(record: dict[str, Any]) -> bool | None:
    status = str(record.get("Vacancy Status") or "").strip().lower()
    if status == "live":
        return True
    if status in {"closed", "expired", "filled", "cancelled"}:
        return False
    return None


def report_row(record: dict[str, Any], result: BpoScoreResult, duplicate: bool) -> dict[str, Any]:
    return {
        "opportunity": record.get("Opportunity", ""),
        "company": record.get("Company", ""),
        "country": record.get("Country", ""),
        "city": record.get("City", ""),
        "role_family": record.get("Role Family", ""),
        "career_transfer": result.career_transfer,
        "hiring_reality": result.hiring_reality,
        "strategic_value": result.strategic_value,
        "final_priority": result.final_priority,
        "fit": result.fit,
        "verdict": result.verdict,
        "hard_gate": result.hard_gate,
        "duplicate": duplicate,
        "canonical_key": result.canonical_key,
        "source_url": record.get("Source URL", ""),
        "reasons": "; ".join(result.reasons),
    }


def write_reports(rows: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "bpo_report.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    columns = [
        "opportunity",
        "company",
        "country",
        "city",
        "role_family",
        "career_transfer",
        "hiring_reality",
        "strategic_value",
        "final_priority",
        "fit",
        "verdict",
        "hard_gate",
        "duplicate",
        "canonical_key",
        "source_url",
        "reasons",
    ]
    with (output_dir / "bpo_report.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def run(input_path: Path, profile_path: Path, output_dir: Path) -> list[dict[str, Any]]:
    profile = load_profile(profile_path)
    records = load_records(input_path)
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []

    for record in records:
        result = score_bpo(record, profile, infer_live(record))
        duplicate = bool(result.canonical_key and result.canonical_key in seen)
        if duplicate:
            result.fit = "Reject"
            result.verdict = "DO NOT APPLY"
            result.hard_gate = True
            result.reasons.append("duplicate vacancy")
        elif result.canonical_key:
            seen.add(result.canonical_key)
        rows.append(report_row(record, result, duplicate))

    rows.sort(
        key=lambda row: (
            0 if row["fit"] == "A" else 1 if row["fit"] == "B" else 2 if row["fit"] == "C" else 3,
            -float(row["final_priority"]),
        )
    )
    write_reports(rows, output_dir)
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Eagle Korean BPO model")
    parser.add_argument("--input", required=True, type=Path, help="JSON array of normalized BPO vacancies")
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path("profiles/korean_bpo.yml"),
        help="BPO profile YAML",
    )
    parser.add_argument("--output", type=Path, default=Path("output/bpo"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    rows = run(args.input, args.profile, args.output)
    summary = {
        fit: sum(1 for row in rows if row["fit"] == fit)
        for fit in ("A", "B", "C", "Reject")
    }
    print(json.dumps({"rows": len(rows), "summary": summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
