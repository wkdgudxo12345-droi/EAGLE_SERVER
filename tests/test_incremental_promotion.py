from eagle.gmail_feedback import classify_outcome
from eagle.incremental import _build_incremental_filter, _truthy
from eagle.promote import candidate_identity


def test_rejection_classifier_separates_work_rights_from_cv_failure() -> None:
    code, stage, reason = classify_outcome(
        "Job Application",
        "You indicated that you are not currently legally eligible to work in this country.",
    )
    assert (code, stage) == ("R01", "AUTO_FILTER")
    assert "work-rights" in reason


def test_rejection_classifier_detects_dob_screening() -> None:
    assert classify_outcome("Birthday goals", "You do not meet the minimum age requirement")[0] == "R03"


def test_incremental_filter_targets_recheck_and_today_rows() -> None:
    schema = {
        "Audit Status": {"type": "select"},
        "Today Only": {"type": "checkbox"},
    }
    value = _build_incremental_filter(schema, ["PENDING", "RECHECK"])
    assert value == {
        "or": [
            {"property": "Audit Status", "select": {"equals": "PENDING"}},
            {"property": "Audit Status", "select": {"equals": "RECHECK"}},
            {"property": "Today Only", "checkbox": {"equals": True}},
        ]
    }


def test_candidate_identity_prefers_stable_canonical_key() -> None:
    candidate = {
        "duplicate_key": "url:https://example.com/job/123",
        "source_job_id": "SEEK:123",
        "canonical_url": "https://example.com/job/123",
    }
    assert candidate_identity(candidate) == "canonical:url:https://example.com/job/123"


def test_truthy_accepts_notion_checkbox_export() -> None:
    assert _truthy("__YES__") is True
    assert _truthy("false") is False
