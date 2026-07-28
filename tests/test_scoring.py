from eagle.scoring import duplicate_key, normalize_url, score


CONFIG = {
    "require_visa_eligibility": True,
    "thresholds": {
        "fit_a": 82,
        "fit_b": 68,
        "min_reality": 55,
        "min_hr": 60,
        "min_ccstm": 68,
    },
    "weights": {
        "ccstm": {
            "role_match": 35,
            "experience": 25,
            "no_car": 15,
            "accommodation": 10,
            "visa": 10,
            "freshness": 5,
        },
        "hr": {
            "direct_experience": 30,
            "transferable_ops": 25,
            "shift_reliability": 15,
            "language": 10,
            "location_commitment": 10,
            "requirements": 10,
        },
        "reality": {
            "live_link": 25,
            "individual_job_url": 20,
            "no_hard_gate": 25,
            "accommodation": 10,
            "evidence_quality": 10,
            "freshness": 10,
        },
    },
    "hard_reject_terms": ["own reliable vehicle", "unpaid volunteer"],
    "preferred_terms": ["guest service", "reservations", "training provided"],
    "experience_terms": ["customer service", "reservations", "operations"],
    "search_url_patterns": ["seek.com.au/jobs", "/jobs?", "jora.com/"],
}


def base_record() -> dict[str, str]:
    return {
        "Opportunity": "Guest Service Agent",
        "Company": "Example Lodge",
        "Region": "Yulara NT",
        "Role Family": "Guest Services",
        "Canonical URL": "https://example.com/careers/jobs/123",
        "Source": "",
        "Source Job ID": "123",
        "Evidence Text": (
            "Customer service and reservations operations. "
            "Training provided. Night roster."
        ),
        "Freshness": "3",
        "Car/Licence": "Not required",
        "Accommodation": "Provided",
        "WHV/88 Days": "Likely",
        "Application Status": "",
    }


def test_strong_live_individual_job_is_apply_ready() -> None:
    result = score(base_record(), CONFIG, True)
    assert result.fit in {"A", "B"}
    assert result.verdict == "APPLY NOW"


def test_hard_gate_rejects_role() -> None:
    record = base_record()
    record["Evidence Text"] += " Own reliable vehicle required."
    result = score(record, CONFIG, True)
    assert result.fit == "Reject"
    assert result.hard_gate is True


def test_punctuation_does_not_bypass_unpaid_hard_gate() -> None:
    record = base_record()
    record["Evidence Text"] = "UNPAID/VOLUNTEER accommodation arrangement"
    result = score(record, CONFIG, True)
    assert result.fit == "Reject"
    assert "unpaid volunteer" in result.reasons[0]


def test_closed_application_status_rejects_even_when_url_is_live() -> None:
    record = base_record()
    record["Application Status"] = "CLOSED"
    result = score(record, CONFIG, True)
    assert result.fit == "Reject"
    assert "application status is closed" in result.reasons


def test_negative_specified_work_status_is_a_hard_gate() -> None:
    record = base_record()
    record["WHV/88 Days"] = "No"
    result = score(record, CONFIG, True)
    assert result.fit == "Reject"
    assert "specified-work visa eligibility is negative" in result.reasons


def test_search_page_never_becomes_apply_ready() -> None:
    record = base_record()
    record["Canonical URL"] = "https://www.seek.com.au/jobs?keywords=guest"
    result = score(record, CONFIG, True)
    assert result.fit == "C"
    assert result.verdict == "RECHECK"


def test_jora_search_page_is_not_an_individual_vacancy() -> None:
    record = base_record()
    record["Canonical URL"] = "https://au.jora.com/Hotel-Reception-jobs"
    result = score(record, CONFIG, True)
    assert result.fit == "C"
    assert "individual job URL not verified" in result.reasons


def test_closed_url_rejects_role() -> None:
    result = score(base_record(), CONFIG, False)
    assert result.fit == "Reject"


def test_url_normalization_removes_tracking_and_duplicate_key_matches() -> None:
    first = base_record()
    second = base_record()
    first["Canonical URL"] = "https://Example.com/job/123/?utm_source=x"
    second["Canonical URL"] = "https://example.com/job/123"
    assert normalize_url(first["Canonical URL"]) == "https://example.com/job/123"
    assert duplicate_key(first) == duplicate_key(second)
