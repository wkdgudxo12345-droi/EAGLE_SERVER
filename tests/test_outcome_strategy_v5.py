from pathlib import Path

import yaml

from eagle.gmail_feedback import classify_outcome, classify_role_signal
from eagle.outcome_strategy import build_feedback_strategy
from eagle.scoring import score


def _config() -> dict:
    return yaml.safe_load(Path("config/scoring.yml").read_text(encoding="utf-8"))


def _base_record() -> dict[str, str]:
    return {
        "Company": "Example Regional Employer",
        "Role Family": "Operations",
        "Region": "Regional Australia",
        "Canonical URL": "https://example.com/job/123",
        "Car/Licence": "Not required",
        "Accommodation": "Provided",
        "WHV/88 Days": "Likely",
        "Freshness": "2 days",
        "Application Status": "LIVE",
    }


def test_gmail_classifier_detects_incomplete_right_to_work_verification() -> None:
    code, stage, reason = classify_outcome(
        "Right to Work verification",
        "Unable to verify your Right to Work because Document Number and Issuing Country are missing.",
    )
    assert (code, stage) == ("R02", "AUTO_FILTER")
    assert "incomplete" in reason


def test_gmail_classifier_detects_high_competition() -> None:
    assert classify_outcome(
        "Application Outcome",
        "We received a larger than expected pool of candidates and will not progress your application.",
    )[0] == "R06"


def test_role_signal_marks_managerial_overreach_without_storing_email() -> None:
    band, family, flags = classify_role_signal(
        "Application Outcome - Accommodation Manager",
        "Thank you for applying.",
    )
    assert band == "MANAGERIAL_OR_CREDENTIALLED"
    assert family == "HOSPITALITY"
    assert "LEVEL_OVERREACH" in flags


def test_feedback_strategy_blocks_false_work_rights_answers_and_limits_stretch() -> None:
    value = build_feedback_strategy(
        [
            {"outcome_code": "R01", "role_band": "ENTRY_OR_OPERATIONAL", "risk_flags": []},
            {"outcome_code": "R07", "role_band": "ENTRY_OR_OPERATIONAL", "risk_flags": []},
            {"outcome_code": "R05", "role_band": "MANAGERIAL_OR_CREDENTIALLED", "risk_flags": ["LEVEL_OVERREACH"]},
        ],
        work_rights="application_in_progress",
    )
    assert "WORK_RIGHTS_BLOCKER_ACTIVE" in value["alerts"]
    assert "INTERVIEW_CONVERSION_GAP" in value["alerts"]
    assert value["application_portfolio_percent"]["stretch_managerial_or_specialist"] == 5


def test_overlevel_role_is_held_without_management_evidence() -> None:
    record = _base_record()
    record.update(
        {
            "Opportunity": "Accommodation Manager",
            "Evidence Text": "Three years customer service operations, escalation handling and staff training support.",
        }
    )
    result = score(record, _config(), True)
    assert result.fit == "C"
    assert result.verdict == "RECHECK"
    assert any("level mismatch" in reason for reason in result.reasons)


def test_light_duty_operational_role_can_pass_level_gate() -> None:
    record = _base_record()
    record.update(
        {
            "Opportunity": "Weighbridge Data Entry Operator",
            "Evidence Text": "Operations, data entry, documentation, reconciliation, customer communication, shift roster and training provided.",
        }
    )
    result = score(record, _config(), True)
    assert result.fit in {"A", "B"}
    assert result.verdict == "APPLY NOW"
    assert not any("level mismatch" in reason for reason in result.reasons)
