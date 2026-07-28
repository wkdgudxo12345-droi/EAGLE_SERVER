from __future__ import annotations

import json
from pathlib import Path

from .evidence_rag_v2 import run_evidence_rag
from .main import load_config
from .policy import evaluate_policy
from .scoring import score


def _record() -> dict[str, str]:
    return {
        "Opportunity": "Guest Experience Agent",
        "Company": "Example Remote Lodge",
        "Location": "Yulara NT 0872",
        "Region": "Yulara NT 0872",
        "Role Family": "Guest Services",
        "Canonical URL": "https://employer.example/careers/job/123",
        "Source": "Employer",
        "Source Job ID": "123",
        "Evidence Text": (
            "Individual paid guest service vacancy. Reservations and customer "
            "operations. Training provided. Exact worksite and official "
            "specified-work rule checked. Night roster."
        ),
        "Freshness": "2",
        "Car/Licence": "Not required",
        "Accommodation": "Provided",
        "Second Visa": "Likely",
        "WHV/88 Days": "Likely",
        "Audit Status": "VERIFIED",
        "Evidence Grade": "A",
        "Verification Level": "Individual verified",
        "Vacancy Status": "LIVE",
        "Operational Decision": "",
        "Application Status": "",
    }


def _evaluate(record: dict[str, str]) -> dict[str, object]:
    config = load_config()
    scoring = score(record, config, live=True)
    rag = run_evidence_rag(
        record,
        live=True,
        individual_url=True,
        evidence_path=Path("data/policy_evidence.json"),
    )
    policy = evaluate_policy(
        record,
        live=True,
        individual_url=True,
        duplicate=False,
        scoring_hard_gate=scoring.hard_gate,
        rag_verdict=rag.verdict,
    )
    return {
        "fit": scoring.fit,
        "rag": rag.verdict,
        "proof_gate": policy.proof_gate,
        "decision": policy.final_decision,
        "promotion_allowed": policy.promotion_allowed,
    }


def main() -> int:
    cases: dict[str, dict[str, object]] = {}

    passing = _record()
    cases["verified_likely"] = _evaluate(passing)
    assert cases["verified_likely"]["rag"] == "PASS"
    assert cases["verified_likely"]["proof_gate"] == "PASS"
    assert cases["verified_likely"]["promotion_allowed"] is True

    unknown = _record()
    unknown["Second Visa"] = "Unknown"
    unknown["WHV/88 Days"] = "Unknown"
    cases["unknown_visa"] = _evaluate(unknown)
    assert cases["unknown_visa"]["rag"] == "HOLD"
    assert cases["unknown_visa"]["decision"] == "VERIFY THEN APPLY"
    assert cases["unknown_visa"]["promotion_allowed"] is False

    licence = _record()
    licence["Car/Licence"] = "Required"
    licence["Accommodation"] = "Unknown"
    cases["licence_required"] = _evaluate(licence)
    assert cases["licence_required"]["rag"] == "REJECT"
    assert cases["licence_required"]["proof_gate"] == "REJECT"
    assert cases["licence_required"]["promotion_allowed"] is False

    print(json.dumps({"status": "ok", "cases": cases}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
