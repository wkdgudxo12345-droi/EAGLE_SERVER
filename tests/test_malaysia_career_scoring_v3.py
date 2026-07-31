from pathlib import Path

import yaml

from eagle.malaysia_career_scoring_v3 import is_individual_url, score_record


PROFILE = yaml.safe_load(Path("profiles/malaysia_korean_ops_v3.yml").read_text(encoding="utf-8"))


def strong_okx_record():
    return {
        "company": "OKX",
        "title": "Senior Agent, Customer Service (Korean Speaker)",
        "location": "Kuala Lumpur, Malaysia",
        "description": "Handle Korean customer inquiries by email chat and voice, escalate issues, use CRM, 24x7 shift, crypto platform. Employment Pass will be provided.",
        "posted_age_days": 2,
        "url": "https://www.linkedin.com/jobs/view/3989325287/",
        "salary_min": 10000,
        "salary_max": 12000,
        "visa": "employment pass provided",
        "role_match": 94,
        "seniority_fit": 90,
        "english_fit": 70,
        "source_conf": 95,
        "vacancy_status": "live",
        "employment_type": "full time",
    }


def test_okx_like_role_is_actionable_and_crypto_cv():
    result = score_record(strong_okx_record(), PROFILE)
    assert result.hard_gate is False
    assert result.queue in {"A - Apply First", "B - Apply"}
    assert result.industry_track == "Crypto / Blockchain"
    assert result.cv_variant == "Tech · Fintech · Crypto Operations"


def test_low_salary_generic_bpo_is_rejected():
    record = strong_okx_record()
    record.update({"company": "Generic BPO", "salary_min": 5500, "salary_max": 6500})
    result = score_record(record, PROFILE)
    assert result.hard_gate is True
    assert result.queue == "Reject"


def test_igt_is_excluded_without_both_promotion_and_salary_exception():
    record = strong_okx_record()
    record.update({"company": "IGT Solutions", "title": "Korean Customer Service", "salary_min": 11000, "salary_max": 11500})
    assert score_record(record, PROFILE).queue == "Reject"


def test_igt_clear_high_pay_promotion_can_pass_exclusion_gate():
    record = strong_okx_record()
    record.update({"company": "IGT Solutions", "title": "Korean Operations Team Lead", "salary_min": 12000, "salary_max": 13000})
    assert score_record(record, PROFILE).hard_gate is False


def test_mandarin_mandatory_role_is_rejected():
    record = strong_okx_record()
    record["description"] += " Mandarin required."
    assert score_record(record, PROFILE).queue == "Reject"


def test_non_korean_role_is_rejected_from_best_fit_pipeline():
    record = strong_okx_record()
    record["title"] = "Customer Service Agent"
    record["description"] = "Handle customer inquiries and escalations in English."
    assert score_record(record, PROFILE).queue == "Reject"


def test_search_page_is_not_individual():
    assert is_individual_url("https://my.jobstreet.com/korean-speaker-jobs/in-Malaysia") is False
    assert is_individual_url("https://www.linkedin.com/jobs/search/?keywords=korean") is False
