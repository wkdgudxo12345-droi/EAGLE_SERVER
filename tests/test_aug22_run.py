from datetime import date

from eagle.aug22_run import (
    _specified_work_confidence,
    _target_group,
    _timing_status,
)


CONFIG = {
    "target_groups": {
        "hospitality": ["guest service", "night auditor"],
        "grain_harvest": ["grain sampler", "weighbridge operator"],
        "food_processing_ops": ["quality assurance", "dispatch clerk"],
    }
}


def test_grain_sampler_is_classified_as_grain_harvest() -> None:
    group, matches = _target_group(
        "seasonal grain sampler and weighbridge operator", CONFIG
    )
    assert group == "GRAIN_HARVEST"
    assert matches == 2


def test_immediate_start_before_august_22_is_held() -> None:
    status, penalty, reason = _timing_status(
        "immediate start required", date(2026, 8, 22)
    )
    assert status == "START_BEFORE_AVAILABLE"
    assert penalty > 0
    assert "2026-08-22" in str(reason)


def test_harvest_season_is_timing_aligned() -> None:
    status, penalty, reason = _timing_status(
        "harvest casual 2026/2027 commencing in october", date(2026, 8, 22)
    )
    assert status == "ALIGNED"
    assert penalty == 0
    assert reason is None


def test_generic_weighbridge_is_not_visa_guaranteed() -> None:
    record = {"Second Visa": "Unknown"}
    confidence, reason = _specified_work_confidence(
        record,
        "GRAIN_HARVEST",
        "weighbridge operator at a recycling transfer station",
    )
    assert confidence == "VERIFY"
    assert "not enough" in reason


def test_food_qa_dispatch_requires_more_evidence() -> None:
    record = {"Second Visa": "Unknown"}
    confidence, reason = _specified_work_confidence(
        record,
        "FOOD_PROCESSING_OPS",
        "quality assurance and dispatch clerk in food manufacturing",
    )
    assert confidence == "VERIFY"
    assert "not automatic" in reason
