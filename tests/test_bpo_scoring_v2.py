import copy

from eagle.bpo_scoring_v2 import is_individual_url, score_record


PROFILE = {
    "weights": {
        "final": {
            "hiring_probability": 35,
            "salary": 30,
            "career_fit": 20,
            "english_feasibility": 10,
            "visa": 5,
        },
        "hiring_probability": {
            "role_match": 42,
            "seniority_fit": 18,
            "english_feasibility": 18,
            "freshness": 12,
            "source_confidence": 10,
        },
    },
    "salary_bands_myr_monthly": {
        "undisclosed_score": 42,
        "bands": [
            {"minimum": 10500, "score": 92},
            {"minimum": 9500, "score": 82},
            {"minimum": 8500, "score": 72},
            {"minimum": 0, "score": 20},
        ],
    },
    "visa_scores": {"supported": 95, "unknown": 50, "local_only": 0},
    "thresholds": {"apply_first": 75, "apply": 65, "verify_hold": 55},
    "hard_gates": {
        "reject_statuses": ["closed", "expired"],
        "reject_terms": ["unpaid", "commission only"],
        "reject_local_only": True,
    },
}


def strong_record():
    return {
        "company": "Example",
        "title": "Korean BPO Operations Specialist",
        "location": "Kuala Lumpur",
        "posted_age_days": 1,
        "url": "https://jobs.tdcx.com/job/korean-specialist/12345",
        "salary_min": 10000,
        "salary_max": 12000,
        "visa": "Unknown",
        "role_match": 92,
        "seniority_fit": 88,
        "english_fit": 72,
        "source_conf": 95,
        "vacancy_status": "live",
    }


def test_jobs_subdomain_individual_url_is_not_misclassified():
    assert is_individual_url("https://jobs.tdcx.com/job/korean-specialist/12345") is True


def test_search_page_is_not_individual():
    assert is_individual_url("https://www.linkedin.com/jobs/search/?keywords=korean") is False
    assert is_individual_url("https://my.jobstreet.com/korean-speaker-jobs") is False


def test_salary_has_more_weight_than_unknown_visa():
    high_salary = strong_record()
    low_salary = copy.deepcopy(high_salary)
    low_salary["salary_min"] = 5000
    low_salary["salary_max"] = 5500
    high_salary["visa"] = "Unknown"
    low_salary["visa"] = "supported"
    assert score_record(high_salary, PROFILE).final_score > score_record(low_salary, PROFILE).final_score


def test_b1_b2_manager_risk_reduces_score_without_hard_reject():
    record = strong_record()
    record["title"] = "Customer Service Manager"
    record["english_fit"] = 45
    result = score_record(record, PROFILE)
    assert result.hard_gate is False
    assert any("English B1-B2" in reason for reason in result.reasons)


def test_explicit_local_only_is_rejected():
    record = strong_record()
    record["visa"] = "local only"
    result = score_record(record, PROFILE)
    assert result.hard_gate is True
    assert result.queue == "Reject"
