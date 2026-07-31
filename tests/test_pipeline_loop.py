from datetime import date, timedelta

from eagle.pipeline_loop import (
    _has_food_industry_evidence,
    _lifecycle_values,
    _stale_due,
    pre_gate_candidates,
)


def _date_property(value: str) -> dict:
    return {"type": "date", "date": {"start": value, "end": None}}


def _number_property(value: float) -> dict:
    return {"type": "number", "number": value}


def test_food_gate_requires_industry_context() -> None:
    config = {"food_industry_terms": ["food manufacturing", "meat processing"]}
    item = {
        "route": "FOOD",
        "title": "Quality Assurance Officer",
        "job_url": "https://example.com/job/1",
        "matched_terms": ["quality assurance"],
    }
    assert _has_food_industry_evidence(item, config) is False

    trusted = dict(item, trusted_industry_context=True)
    assert _has_food_industry_evidence(trusted, config) is True

    explicit = dict(item, title="Quality Assurance - Meat Processing")
    assert _has_food_industry_evidence(explicit, config) is True


def test_pre_gate_keeps_only_live_verified_rows() -> None:
    items = [
        {
            "company": "Bunge",
            "title": "Harvest Casual",
            "route": "GRAIN",
            "source_id": "official",
            "job_url": "https://example.com/live",
            "decision": "KEEP",
        },
        {
            "company": "Bunge",
            "title": "Closed Harvest Casual",
            "route": "GRAIN",
            "source_id": "official",
            "job_url": "https://example.com/closed",
            "decision": "KEEP",
        },
        {
            "company": "Market",
            "title": "Needs transport",
            "route": "GRAIN",
            "source_id": "market",
            "job_url": "https://example.com/hold",
            "decision": "HOLD-TRANSPORT",
        },
    ]

    def checker(url: str, *, timeout_seconds: int = 12):
        assert timeout_seconds == 12
        return not url.endswith("closed")

    passed, report = pre_gate_candidates(
        items,
        {"official": {"location": "Regional WA"}},
        {"food_industry_terms": []},
        url_checker=checker,
    )

    assert [row["title"] for row in passed] == ["Harvest Casual"]
    assert passed[0]["location"] == "Regional WA"
    assert [row["gate"] for row in report] == [
        "PASS_TO_SCORE",
        "REJECT_CLOSED",
        "REJECT_CRAWL_GATE",
    ]


def test_lifecycle_moves_new_to_active_and_increments_seen_count() -> None:
    new_values = _lifecycle_values(
        None,
        run_id="EAGLE-1-1",
        today="2026-07-31",
    )
    assert new_values["Lifecycle"] == "NEW"
    assert new_values["Seen Count"] == 1
    assert new_values["First Seen"] == "2026-07-31"
    assert new_values["Last Seen"] == "2026-07-31"

    existing = {
        "Seen Count": _number_property(3),
        "First Seen": _date_property("2026-07-20"),
    }
    active_values = _lifecycle_values(
        existing,
        run_id="EAGLE-2-1",
        today="2026-08-01",
    )
    assert active_values["Lifecycle"] == "ACTIVE"
    assert active_values["Seen Count"] == 4
    assert "First Seen" not in active_values


def test_stale_requires_last_seen_older_than_threshold() -> None:
    old = (date.today() - timedelta(days=15)).isoformat()
    recent = (date.today() - timedelta(days=3)).isoformat()

    assert _stale_due({"Last Seen": _date_property(old)}, 14) is True
    assert _stale_due({"Last Seen": _date_property(recent)}, 14) is False
    assert _stale_due({}, 14) is False
