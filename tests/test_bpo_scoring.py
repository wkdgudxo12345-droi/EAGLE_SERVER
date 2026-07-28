from eagle.bpo_scoring import canonical_key, normalize_url, score_bpo


PROFILE = {
    "candidate": {
        "total_bpo_years": 3.25,
        "domains": [
            "hotel operations",
            "flight operations",
            "reservations",
            "refunds and reissues",
            "overbooking resolution",
            "escalation handling",
            "quality assurance",
            "SME support",
            "new-hire training",
            "KPI and SLA operations",
        ],
    },
    "hard_gates": {
        "reject_terms": [
            "unpaid",
            "volunteer only",
            "commission only",
            "citizenship required",
            "permanent resident only",
            "local nationals only",
        ],
        "reject_statuses": ["closed", "expired", "filled", "cancelled"],
        "non_individual_url_patterns": [
            "/jobs?",
            "/search?",
            "linkedin.com/jobs/search",
            "indeed.com/jobs",
            "jobstreet.com/jobs",
        ],
        "work_authorization": {
            "sponsorship_positive_values": [
                "available",
                "yes",
                "supported",
                "employment pass provided",
            ]
        },
    },
    "thresholds": {
        "apply_now": 78,
        "priority_recheck": 64,
        "minimum_hiring_reality": 55,
        "minimum_evidence": 45,
    },
    "weights": {
        "career_transfer": {
            "agoda_domain_match": 30,
            "operations_match": 20,
            "escalation_qa_training": 20,
            "korean_language_value": 15,
            "seniority_match": 10,
            "tool_process_match": 5,
        },
        "hiring_reality": {
            "vacancy_live": 20,
            "individual_url": 15,
            "work_authorization": 25,
            "experience_requirement": 15,
            "location_and_work_mode": 10,
            "salary_and_contract": 5,
            "evidence_quality": 10,
        },
        "strategic_value": {
            "career_progression": 30,
            "compensation": 20,
            "brand_value": 15,
            "transferable_scope": 20,
            "stability": 15,
        },
    },
}


def strong_record() -> dict[str, object]:
    return {
        "Opportunity": "Korean Senior Travel Operations Specialist",
        "Company": "Example Travel Platform",
        "Country": "Malaysia",
        "City": "Kuala Lumpur",
        "Role Family": "Korean Travel Operations",
        "Seniority": "Senior Specialist",
        "Korean Requirement": "Native Korean required",
        "English Requirement": "Business English",
        "Work Authorization": "Employment pass supported",
        "Candidate Eligible": False,
        "Visa Sponsorship": "Available",
        "Work Mode": "Hybrid",
        "Employment Type": "Permanent full time",
        "Shift Pattern": "24/7 roster",
        "Experience Requirement": "3 years customer operations experience",
        "Salary": "MYR 9,000-12,000",
        "Source URL": "https://example.com/careers/job/kr-travel-123",
        "Posted Date": "2026-07-28",
        "Vacancy Status": "Live",
        "Evidence Text": (
            "Korean customer support for hotel and flight reservations, refunds, "
            "reissues, overbooking escalation, partner negotiation, SLA and KPI "
            "management, quality assurance, SME floor support and new-hire training. "
            "Uses CRM, Excel, ticketing tools, SOPs and a knowledge base."
        ),
    }


def test_strong_korean_travel_role_is_applyable() -> None:
    result = score_bpo(strong_record(), PROFILE, True)
    assert result.fit in {"A", "B"}
    assert result.verdict in {"APPLY NOW", "VERIFY THEN APPLY"}
    assert result.hard_gate is False
    assert result.career_transfer >= 70


def test_local_only_without_sponsorship_is_rejected() -> None:
    record = strong_record()
    record["Work Authorization"] = "Local nationals only"
    record["Visa Sponsorship"] = "No"
    result = score_bpo(record, PROFILE, True)
    assert result.fit == "Reject"
    assert result.verdict == "DO NOT APPLY"
    assert any("work authorization" in reason for reason in result.reasons)


def test_unknown_authorization_requires_research() -> None:
    record = strong_record()
    record["Work Authorization"] = ""
    record["Visa Sponsorship"] = "Unknown"
    record["Candidate Eligible"] = False
    result = score_bpo(record, PROFILE, None)
    assert result.fit == "C"
    assert result.verdict == "RESEARCH"
    assert any("unverified" in reason for reason in result.reasons)


def test_search_results_page_never_enters_apply_queue() -> None:
    record = strong_record()
    record["Source URL"] = "https://www.linkedin.com/jobs/search/?keywords=korean"
    result = score_bpo(record, PROFILE, True)
    assert result.fit == "C"
    assert result.verdict == "RESEARCH"
    assert "individual vacancy URL is not verified" in result.reasons


def test_closed_vacancy_is_rejected() -> None:
    record = strong_record()
    record["Vacancy Status"] = "Closed"
    result = score_bpo(record, PROFILE, True)
    assert result.fit == "Reject"
    assert result.hard_gate is True


def test_unpaid_or_commission_only_is_rejected() -> None:
    record = strong_record()
    record["Evidence Text"] = "This is an unpaid commission only opportunity."
    result = score_bpo(record, PROFILE, True)
    assert result.fit == "Reject"
    assert any("hard gate terms" in reason for reason in result.reasons)


def test_tracking_parameters_do_not_change_canonical_key() -> None:
    first = strong_record()
    second = strong_record()
    first["Source URL"] = "https://Example.com/careers/job/123/?utm_source=x"
    second["Source URL"] = "https://example.com/careers/job/123"
    assert normalize_url(str(first["Source URL"])) == "https://example.com/careers/job/123"
    assert canonical_key(first) == canonical_key(second)
