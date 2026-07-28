from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import Any

import requests

from .evidence_rag_v2 import run_evidence_rag
from .main import check_url, env_bool, env_int, load_config
from .notion import DEFAULT_NOTION_VERSION, NotionClient
from .policy import evaluate_policy
from .record import extract_record, schema_health
from .scoring import normalize_url, score


REPORT_COLUMNS = [
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
    "duplicate_key",
    "reasons",
]


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


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                # A terminated process can leave one partial final line. Earlier
                # fsync-ed rows remain valid and are safe to resume.
                break
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _write_reports(report: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(output_dir / "report.json", report)
    with (output_dir / "report.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(report)


def _sync_state_artifacts(
    *, state_jsonl: Path, checkpoint_path: Path, output_dir: Path
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if state_jsonl.exists():
        shutil.copy2(state_jsonl, output_dir / "report.jsonl")
    if checkpoint_path.exists():
        shutil.copy2(checkpoint_path, output_dir / "checkpoint.json")


def _run_fingerprint(
    *,
    database_id: str,
    config: dict[str, Any],
    evidence_path: Path,
    run_key: str,
    code_sha: str,
    url_checks: bool,
    use_llm: bool,
    require_llm: bool,
    max_rows: int | None,
) -> str:
    digest = hashlib.sha256()
    digest.update(database_id.encode("utf-8"))
    digest.update(json.dumps(config, sort_keys=True).encode("utf-8"))
    digest.update(run_key.encode("utf-8"))
    digest.update(code_sha.encode("utf-8"))
    digest.update(str(url_checks).encode("ascii"))
    digest.update(str(use_llm).encode("ascii"))
    digest.update(str(require_llm).encode("ascii"))
    digest.update(str(max_rows).encode("ascii"))
    if evidence_path.exists():
        digest.update(evidence_path.read_bytes())
    return digest.hexdigest()


def _checkpoint(
    path: Path,
    *,
    fingerprint: str,
    run_key: str,
    completed: int,
    total_hint: int | None,
    last_page_id: str,
    status: str,
    error: str | None = None,
) -> None:
    value: dict[str, Any] = {
        "fingerprint": fingerprint,
        "run_key": run_key,
        "completed": completed,
        "total_hint": total_hint,
        "last_page_id": last_page_id,
        "status": status,
        "updated_at_epoch": int(time.time()),
    }
    if error:
        value["error"] = error
    _atomic_json(path, value)


def _summary(report: list[dict[str, Any]], status: str) -> dict[str, Any]:
    return {
        "status": status,
        "processed": len(report),
        "apply_now": sum(1 for row in report if row["decision"] == "APPLY NOW"),
        "verify": sum(
            1 for row in report if row["decision"] == "VERIFY THEN APPLY"
        ),
        "hold": sum(1 for row in report if row["decision"] == "HOLD"),
        "rag_providers": sorted({str(row["rag_provider"]) for row in report}),
    }


def main() -> int:
    token = os.getenv("NOTION_TOKEN", "").strip()
    database_id = os.getenv("NOTION_DATABASE_ID", "").strip()
    requested_data_source_id = os.getenv("NOTION_DATA_SOURCE_ID", "").strip()
    notion_version = os.getenv("NOTION_VERSION", DEFAULT_NOTION_VERSION).strip()
    apply_changes = env_bool("APPLY_CHANGES", False)
    archive_rejected = env_bool("ARCHIVE_REJECTED", False)
    strict_schema = env_bool("STRICT_SCHEMA", True)
    url_checks = env_bool("URL_CHECK_ENABLED", True)
    use_llm = env_bool("RAG_USE_LLM", False)
    require_llm = env_bool("REQUIRE_LLM_RAG", False)
    resume_enabled = env_bool("RESUME_ENABLED", True)
    max_rows = env_int("MAX_ROWS")
    url_timeout = env_int("URL_CHECK_TIMEOUT_SECONDS") or 18
    soft_deadline_seconds = env_int("SOFT_DEADLINE_SECONDS") or 3000
    output_dir = Path(os.getenv("OUTPUT_DIR", "output"))
    state_dir = Path(os.getenv("STATE_DIR", "state"))
    evidence_path = Path(
        os.getenv("EAGLE_EVIDENCE_FILE", "data/policy_evidence.json")
    )
    run_key = os.getenv("EAGLE_RUN_KEY", "local").strip() or "local"
    code_sha = os.getenv("EAGLE_CODE_SHA", os.getenv("GITHUB_SHA", "local"))

    output_dir.mkdir(parents=True, exist_ok=True)

    if not token or not (database_id or requested_data_source_id):
        print(
            "Missing NOTION_TOKEN and/or Notion database/data source ID",
            file=sys.stderr,
        )
        return 2
    if not evidence_path.exists():
        message = f"Evidence file not found: {evidence_path}"
        _atomic_json(
            output_dir / "preflight.json",
            {"status": "failed", "error": message},
        )
        print(message, file=sys.stderr)
        return 2

    # The user's project rule is append-only: existing Stage 1/2/3/Final rows
    # must not be modified or archived. Promotion to Final remains a separate,
    # deduplicated append-only command after report validation.
    if apply_changes or archive_rejected:
        print(
            "Existing-row mutation is disabled by Eagle V4 policy. "
            "Run report-only and promote verified new rows through an append-only "
            "command.",
            file=sys.stderr,
        )
        return 2

    try:
        config = load_config()
        client = NotionClient(token, notion_version=notion_version)
        data_source_id = client.resolve_data_source_id(
            database_id=database_id or None,
            data_source_id=requested_data_source_id or None,
        )
        schema = client.data_source_properties(data_source_id)
        schema_report = schema_health(schema)
    except (OSError, ValueError, RuntimeError, requests.RequestException) as exc:
        _atomic_json(
            output_dir / "preflight.json",
            {"status": "failed", "error": str(exc)},
        )
        print(f"Startup failed: {exc}", file=sys.stderr)
        return 2

    preflight = {
        "status": "ready" if schema_report["ready"] else "schema_warning",
        "notion_version": notion_version,
        "database_id_supplied": bool(database_id),
        "data_source_id": data_source_id,
        "strict_schema": strict_schema,
        "schema": schema_report,
    }
    _atomic_json(output_dir / "preflight.json", preflight)

    missing_fatal = schema_report["missing_fatal"]
    missing_promotion = schema_report["missing_promotion"]
    if missing_fatal or (strict_schema and missing_promotion):
        message = (
            f"Notion schema preflight failed: fatal={missing_fatal}; "
            f"promotion={missing_promotion}"
        )
        print(message, file=sys.stderr)
        return 2

    filter_properties = sorted(
        {
            str(alias)
            for alias in schema_report["resolved_aliases"].values()
            if alias
        }
    )
    fingerprint = _run_fingerprint(
        database_id=data_source_id,
        config=config,
        evidence_path=evidence_path,
        run_key=run_key,
        code_sha=code_sha,
        url_checks=url_checks,
        use_llm=use_llm,
        require_llm=require_llm,
        max_rows=max_rows,
    )

    state_dir.mkdir(parents=True, exist_ok=True)
    state_jsonl = state_dir / "report.jsonl"
    checkpoint_path = state_dir / "checkpoint.json"
    prior_checkpoint = _load_json(checkpoint_path)
    can_resume = (
        resume_enabled
        and prior_checkpoint.get("fingerprint") == fingerprint
        and prior_checkpoint.get("status")
        in {"running", "paused", "failed", "interrupted"}
    )

    if can_resume:
        report = _load_jsonl(state_jsonl)
        print(
            f"Resuming run_key={run_key} from {len(report)} durable rows | "
            f"last_page_id={prior_checkpoint.get('last_page_id', '')}"
        )
    else:
        state_jsonl.write_text("", encoding="utf-8")
        report = []
        _checkpoint(
            checkpoint_path,
            fingerprint=fingerprint,
            run_key=run_key,
            completed=0,
            total_hint=max_rows,
            last_page_id="",
            status="running",
        )

    completed_ids = {str(row.get("id", "")) for row in report if row.get("id")}
    seen = {
        str(row["duplicate_key"]): str(row.get("id", ""))
        for row in report
        if row.get("duplicate_key")
    }
    search_patterns = [
        str(term).lower() for term in config.get("search_url_patterns", [])
    ]

    stop = {"requested": False, "signal": None}

    def _request_stop(signum: int, _frame: Any) -> None:
        stop["requested"] = True
        stop["signal"] = signum

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    started = time.monotonic()
    last_page_id = (
        str(prior_checkpoint.get("last_page_id", "")) if can_resume else ""
    )
    status = "completed"
    exit_code = 0

    print(
        f"Starting report-only run | data_source={data_source_id} "
        f"resume={can_resume} url_checks={url_checks} "
        f"rag_use_llm={use_llm} require_llm={require_llm} max_rows={max_rows}"
    )

    try:
        pages = client.iter_data_source(
            data_source_id,
            max_rows=max_rows,
            filter_properties=filter_properties,
        )
        for source_index, page in enumerate(pages, 1):
            page_id = str(page.get("id", ""))
            if page_id in completed_ids:
                continue

            if stop["requested"]:
                status = "interrupted"
                exit_code = 130
                break
            if time.monotonic() - started >= soft_deadline_seconds:
                status = "paused"
                exit_code = 75
                break

            record = extract_record(page.get("properties", {}))
            url = record.get("Canonical URL", "")
            live = (
                check_url(url, timeout_seconds=url_timeout) if url_checks else None
            )
            individual_url = _is_individual_url(url, search_patterns)
            scoring = score(record, config, live)

            duplicate = bool(
                scoring.duplicate_key and scoring.duplicate_key in seen
            )
            if duplicate:
                scoring.hard_gate = True
                scoring.reasons.append("duplicate job")
            elif scoring.duplicate_key:
                seen[scoring.duplicate_key] = page_id

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

            promotion_allowed = (
                policy.promotion_allowed and scoring.fit in {"A", "B"}
            )
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
                "id": page_id,
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
                "duplicate_key": scoring.duplicate_key,
                "reasons": "; ".join(reasons),
            }
            report.append(row)
            completed_ids.add(page_id)
            last_page_id = page_id
            _append_jsonl(state_jsonl, row)
            _checkpoint(
                checkpoint_path,
                fingerprint=fingerprint,
                run_key=run_key,
                completed=len(report),
                total_hint=max_rows,
                last_page_id=last_page_id,
                status="running",
            )
            print(
                f"[{source_index}] {final_fit:6} {decision:18} "
                f"RAG={rag.verdict}/{rag.proof_score} "
                f"{record.get('Opportunity', '')[:48]}"
            )

    except (OSError, ValueError, RuntimeError, requests.RequestException) as exc:
        status = "failed"
        exit_code = 2
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        _checkpoint(
            checkpoint_path,
            fingerprint=fingerprint,
            run_key=run_key,
            completed=len(report),
            total_hint=max_rows,
            last_page_id=last_page_id,
            status=status,
            error=str(exc),
        )
    else:
        _checkpoint(
            checkpoint_path,
            fingerprint=fingerprint,
            run_key=run_key,
            completed=len(report),
            total_hint=max_rows,
            last_page_id=last_page_id,
            status=status,
            error=(
                f"received signal {stop['signal']}"
                if status == "interrupted"
                else None
            ),
        )

    _write_reports(report, output_dir)
    _sync_state_artifacts(
        state_jsonl=state_jsonl,
        checkpoint_path=checkpoint_path,
        output_dir=output_dir,
    )
    summary = _summary(report, status)
    _atomic_json(output_dir / "summary.json", summary)
    print("SUMMARY", json.dumps(summary, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
