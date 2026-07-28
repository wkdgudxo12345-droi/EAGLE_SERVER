from eagle.bpo_scoring import score_bpo
from tests.test_bpo_scoring import PROFILE, strong_record


def test_jobs_subdomain_individual_vacancy_is_allowed() -> None:
    record = strong_record()
    record["Source URL"] = (
        "https://jobs.tdcx.com/job/"
        "Technical-Customer-Service-Specialist-Korean-Speaking/1357829166/"
    )
    result = score_bpo(record, PROFILE, True)
    assert "individual vacancy URL is not verified" not in result.reasons
    assert result.fit in {"A", "B"}


def test_jobstreet_search_results_page_requires_research() -> None:
    record = strong_record()
    record["Source URL"] = (
        "https://my.jobstreet.com/korean-speaker-jobs/in-Kuala-Lumpur"
    )
    result = score_bpo(record, PROFILE, True)
    assert result.fit == "C"
    assert result.verdict == "RESEARCH"
    assert "individual vacancy URL is not verified" in result.reasons
