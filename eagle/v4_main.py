from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

from .evidence_rag_v2 import run_evidence_rag
from .main import check_url, env_bool, env_int, load_config
from .notion import NotionClient
from .policy import evaluate_policy
from .record import extract_record
from .scoring import normalize_url, score


def _is_individual_url(url: str, search_patterns: list[str]) -> bool:
    normalized = normalize_url(url)
    return bool(normalized) and not any(
        pattern.lower() in normalized.lower() for pattern in search_patterns
    )


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_reports(report: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(output_dir / "report.json", report)
    columns = [
        "id",
        "opportunity",
        "company",
        "location",
        "fit",
        "decision",
        "promotion_allowed",
        "proof_gate",
        "red_team_status",
        "second_visa_state",
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
    use_llm = env_bool("RAG_USE_LLM", False)
    require_llm = env_bool("REQUIRE_LLM_RAG", False)
    max_rows = env_int("MAX_ROWS")
    output_dir = Path(os.getenv("OUTPUT_DIR", "output"))
    evidence_path = Path(
        os.getenv("EAGLE_EVIDENCE_FILE", "data/policy_evidence.json")
    )

    if not token or not database_id:
        print("Missing NOTION_TOKEN or NOTION_DATABASE_ID", file=sys.stderr)
        return 2

    # The user's project rule is append-only: existing Stage 1/2/3/Final rows
    # must not be modified or archived. Promotion to Final will be a separate,
    # deduplicated append-only command after the audit runner is accepted.
    if apply_changes or archive_rejected:
        print(
            "Existing-row mutation is disabled by Eagle V4 policy. "
            "Run report-only and promote verified new rows through the future "
            "append-only command.",
            file=sys.stderr,
        )
        return 2

    try:
        config = load_config()
        client = NotionClient(
            token,
            notion_version=os.getenv("NOTION_VERSION", "2022-06-28"),
        )
        pages = list(client.iter_database(database_id, max_rows=max_rows))
    except (OSError, ValueError, RuntimeError, requests.RequestException) as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        return 2

    print(
        f"Loaded {len(pages)} rows | report_only=true "
        f"url_checks={url_checks} rag_use_llm={use_llm} "
        f"require_llm={require_llm}"
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / "report.jsonl"
    checkpoint_path = output_dir / "checkpoint.json"
    jsonl_path.write_text("", encoding="utf-8")
    seen: dict[str, str] = {}
    report: list[dict[str, Any]] = []
    search_patterns = [
        str(term).lower() for term in config.get("search_url_patterns", [])
    ]

    for index, page in enumerate(pages, 1):
        properties = page.get("properties", {})
        record = extract_record(properties)
        url = record.get("Canonical URL", "")
        live = check_url(url) if url_checks else None
        individual_url = _is_individual_url(url, search_patterns)
        scoring = score(record, config, live)

        duplicate = bool(
            scoring.duplicate_key and scoring.duplicate_key in seen
        )
        if duplicate:
            scoring.hard_gate = True
            scoring.reasons.append("duplicate job")
        elif scoring.duplicate_key:
            seen[scoring.duplicate_key] = str(page.get("id", ""))

        try:
            rag = run_evidence_rag(
                record,
                live=live,
                individual_url=individual_url,
                evidence_path=evidence_path,
                use_llm=use_llm,
                require_llm=require_llm,
            )
        except (OSError, ValueError, RuntimeError, requests.RequestException) as exc:
            print(f"Evidence RAG failed for row {index}: {exc}", file=sys.stderr)
            _atomic_json(
                checkpoint_path,
                {
                    "completed": index - 1,
                    "total": len(pages),
                    "last_page_id": str(page.get("id", "")),
                    "status": "failed",
                    "error": str(exc),
                },
            )
            return 2

        policy = evaluate_policy(
            record,
            live=live,
            individual_url=individual_url,
            duplicate=duplicate,
            scoring_hard_gate=scoring.hard_gate,
            rag_verdict=rag.verdict,
        )

        promotion_allowed = policy.promotion_allowed and scoring.fit in {"A", "B"}
        if policy.proof_gate == "REJECT":
            final_fit = "Reject"
            decision = "HOLD"
        elif promotion_allowed:
            final_fit = scoring.fit
            decision = "APPLY NOW"
        else:
            final_fit = "C"
            decision = "VERIFY THEN APPLY"

        reasons = list(
            dict.fromkeys(scoring.reasons + rag.reasons + policy.reasons)
        )
        row = {
            "id": str(page.get("id", "")),
            "opportunity": record.get("Opportunity", ""),
            "company": record.get("Company", ""),
            "location": record.get("Location", ""),
            "fit": final_fit,
            "decision": decision,
            "promotion_allowed": promotion_allowed,
            "proof_gate": policy.proof_gate,
            "red_team_status": policy.red_team_status,
            "second_visa_state": policy.second_visa_state,
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
            "reasons": "; ".join(reasons),
        }
        report.append(row)
        _append_jsonl(jsonl_path, row)
        _atomic_json(
            checkpoint_path,
            {
                "completed": index,
                "total": len(pages),
                "last_page_id": row["id"],
                "status": "running" if index < len(pages) else "completed",
            },
        )
        print(
            f"[{index}/{len(pages)}] {final_fit:6} {decision:18} "
            f"RAG={rag.verdict}/{rag.proof_score} "
            f"{record.get('Opportunity', '')[:48]}"
        )

    _write_reports(report, output_dir)
    summary = {
        "apply_now": sum(
            1 for row in report if row["decision"] == "APPLY NOW"
        ),
        "verify": sum(
            1 for row in report if row["decision"] == "VERIFY THEN APPLY"
        ),
        "hold": sum(1 for row in report if row["decision"] == "HOLD"),
        "rag_providers": sorted({row["rag_provider"] for row in report}),
    }
    _atomic_json(output_dir / "summary.json", summary)
    print("SUMMARY", json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
