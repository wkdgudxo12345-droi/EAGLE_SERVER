from __future__ import annotations
import json, os, sys, time
from pathlib import Path
from typing import Any
import requests, yaml
from .notion import NotionClient
from .properties import plain_text, text_value, number_value, select_value, checkbox_value
from .scoring import score

FIELDS = ["Opportunity","Company","Region","Role Family","Canonical URL","Source","Source Job ID","Evidence Text","Freshness","Car/Licence","Accommodation","WHV/88 Days","Application Status"]

def check_url(url: str) -> bool | None:
    if not url: return False
    headers = {"User-Agent": "Mozilla/5.0 EagleJobVerifier/1.0"}
    try:
        r = requests.get(url, headers=headers, timeout=18, allow_redirects=True)
        if r.status_code in (401,403,429): return None
        if r.status_code >= 400: return False
        low = r.text[:200000].lower()
        if any(x in low for x in ["job is no longer available", "position has been filled", "job has expired"]): return False
        return True
    except requests.RequestException:
        return None

def main() -> int:
    token = os.environ.get("NOTION_TOKEN")
    database_id = os.environ.get("NOTION_DATABASE_ID")
    apply_changes = os.environ.get("APPLY_CHANGES", "false").lower() == "true"
    archive_rejected = os.environ.get("ARCHIVE_REJECTED", "true").lower() == "true"
    if not token or not database_id:
        print("Missing NOTION_TOKEN or NOTION_DATABASE_ID", file=sys.stderr); return 2
    cfg = yaml.safe_load(Path("config/scoring.yml").read_text(encoding="utf-8"))
    client = NotionClient(token)
    pages = list(client.iter_database(database_id))
    print(f"Loaded {len(pages)} rows")

    seen: dict[str,str] = {}
    report: list[dict[str,Any]] = []
    for i, page in enumerate(pages, 1):
        props = page.get("properties", {})
        rec = {f: plain_text(props.get(f)) for f in FIELDS}
        live = check_url(rec.get("Canonical URL") or rec.get("Source") or "")
        result = score(rec, cfg, live)
        duplicate = bool(result.duplicate_key and result.duplicate_key in seen)
        if duplicate:
            result.fit, result.verdict = "Reject", "DELETE CANDIDATE"
            result.reasons.append("중복 공고")
        elif result.duplicate_key:
            seen[result.duplicate_key] = page["id"]

        update = {
            "CCSTM": number_value(result.ccstm),
            "HR Score": number_value(result.hr),
            "Reality Score": number_value(result.reality),
            "RAG Priority": number_value(result.rag),
            "RAG Confidence": number_value(95 if live is not None else 70),
            "Fit": select_value(result.fit),
            "RAG Verdict": select_value(result.verdict),
            "Red Team Status": select_value("PASS" if result.fit in ("A","B") else "REJECT"),
            "Proof Gate": select_value("PASS" if live is True and result.fit in ("A","B") else "REJECT"),
            "Vacancy Status": select_value("Live" if live is True else ("Closed" if live is False else "Needs recheck")),
            "Main DB": checkbox_value(result.fit in ("A","B")),
            "Duplicate Key": text_value(result.duplicate_key),
            "RAG Review Note": text_value("; ".join(result.reasons) or "통과"),
            "Next Action": text_value("지원" if result.fit in ("A","B") else "제출 DB 제외"),
        }
        if apply_changes:
            client.update_page(page["id"], update)
            if archive_rejected and result.fit not in ("A","B"):
                client.archive_page(page["id"])
            time.sleep(0.36)
        report.append({"id":page["id"],"opportunity":rec["Opportunity"],"fit":result.fit,"ccstm":result.ccstm,"hr":result.hr,"reality":result.reality,"rag":result.rag,"live":live,"reasons":result.reasons})
        print(f"[{i}/{len(pages)}] {result.fit:6} {result.rag:5.1f} {rec['Opportunity'][:70]}")

    Path("output").mkdir(exist_ok=True)
    Path("output/report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {k: sum(1 for r in report if r["fit"] == k) for k in ["A","B","C","Reject"]}
    print("SUMMARY", json.dumps(summary, ensure_ascii=False))
    return 0

if __name__ == "__main__": raise SystemExit(main())
