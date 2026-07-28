from pathlib import Path

import pytest

from eagle.evidence_rag_v2 import run_evidence_rag
from eagle.policy import evaluate_policy
from eagle.record import extract_record


def base_record() -> dict[str, str]:
    return {
        "Opportunity": "Guest Experience Agent",
        "Company": "Example Remote Lodge",
        "Location": "Yulara NT 0872",
        "Role Family": "Hospitality",
        "Canonical URL": "https://employer.example/jobs/123",
        "Source": "Employer",
        "Source Job ID": "123",
        "Evidence Text": (
            "Individual employer vacancy, paid guest service duties, exact worksite "
            "and official specified-work rule checked."
        ),
        "Freshness": "2",
        "Car/Licence": "Not required",
        "Accommodation": "Provided",
        "Second Visa": "Likely",
        "Audit Status": "VERIFIED",
        "Evidence Grade": "A",
        "Verification Level": "Individual verified",
        "Vacancy Status": "LIVE",
        "Operational Decision": "",
    }


def run_rag(record: dict[str, str]):
    return run_evidence_rag(
        record,
        live=True,
        individual_url=True,
        evidence_path=Path("data/policy_evidence.json"),
    )


def evaluate(record: dict[str, str], *, scoring_hard_gate: bool = False):
    rag = run_rag(record)
    return rag, evaluate_policy(
        record,
        live=True,
        individual_url=True,
        duplicate=False,
        scoring_hard_gate=scoring_hard_gate,
        rag_verdict=rag.verdict,
    )


def test_verified_likely_role_can_pass_policy_and_rag() -> None:
    rag, policy = evaluate(base_record())
    assert rag.verdict == "PASS"
    assert rag.provider == "deterministic-hybrid-rag-v2"
    assert policy.proof_gate == "PASS"
    assert policy.final_decision == "APPLY NOW"
    assert policy.promotion_allowed is True


def test_final_db_without_verification_level_can_pass_from_runtime_proof() -> None:
    record = base_record()
    record["Verification Level"] = ""
    rag, policy = evaluate(record)
    assert rag.verdict == "PASS"
    assert policy.proof_gate == "PASS"
    assert policy.promotion_allowed is True


def test_explicit_conflicting_verification_level_remains_hold() -> None:
    record = base_record()
    record["Verification Level"] = "Search page only"
    rag, policy = evaluate(record)
    assert rag.verdict == "PASS"
    assert policy.proof_gate == "HOLD"
    assert policy.promotion_allowed is False
    assert any("conflicts" in reason for reason in policy.reasons)


def test_unknown_second_visa_is_hold_not_false_no() -> None:
    record = base_record()
    record["Second Visa"] = "Unknown"
    rag, policy = evaluate(record)
    assert rag.verdict == "HOLD"
    assert policy.second_visa_state == "UNKNOWN"
    assert policy.proof_gate == "HOLD"
    assert policy.final_decision == "VERIFY THEN APPLY"
    assert policy.promotion_allowed is False


def test_second_visa_no_is_a_hard_reject_even_with_strong_hr_fit() -> None:
    record = base_record()
    record["Second Visa"] = "No"
    rag, policy = evaluate(record)
    assert rag.verdict == "REJECT"
    assert policy.proof_gate == "REJECT"
    assert policy.red_team_status == "REJECT"
    assert policy.promotion_allowed is False


def test_driver_licence_required_is_a_hard_reject() -> None:
    record = base_record()
    record["Car/Licence"] = "Required"
    rag, policy = evaluate(record)
    assert rag.verdict == "REJECT"
    assert policy.proof_gate == "REJECT"
    assert policy.promotion_allowed is False


def test_not_stated_transport_is_hold_without_accommodation() -> None:
    record = base_record()
    record["Car/Licence"] = "Not stated"
    record["Accommodation"] = "Unknown"
    rag, policy = evaluate(record)
    assert rag.verdict == "HOLD"
    assert policy.proof_gate == "HOLD"
    assert policy.promotion_allowed is False


def test_unverified_audit_cannot_pass() -> None:
    record = base_record()
    record["Audit Status"] = "RECHECK"
    record["Evidence Grade"] = "C"
    rag, policy = evaluate(record)
    assert rag.verdict == "HOLD"
    assert policy.proof_gate == "HOLD"
    assert policy.promotion_allowed is False


def test_existing_notion_schema_aliases_are_normalized() -> None:
    properties = {
        "Opportunity": {
            "type": "title",
            "title": [{"plain_text": "Room Attendant"}],
        },
        "Location": {
            "type": "rich_text",
            "rich_text": [{"plain_text": "Darwin NT"}],
        },
        "Job URL": {
            "type": "url",
            "url": "https://employer.example/job/1",
        },
        "Second Visa": {
            "type": "select",
            "select": {"name": "Likely"},
        },
        "Freshness Days": {"type": "number", "number": 3},
    }
    record = extract_record(properties)
    assert record["Opportunity"] == "Room Attendant"
    assert record["Location"] == "Darwin NT"
    assert record["Region"] == "Darwin NT"
    assert record["Canonical URL"] == "https://employer.example/job/1"
    assert record["Second Visa"] == "Likely"
    assert record["WHV/88 Days"] == "Likely"
    assert record["Freshness"] == "3"
    assert record["Verification Level"] == ""


def test_required_llm_mode_fails_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        run_evidence_rag(
            base_record(),
            live=True,
            individual_url=True,
            evidence_path=Path("data/policy_evidence.json"),
            require_llm=True,
        )
