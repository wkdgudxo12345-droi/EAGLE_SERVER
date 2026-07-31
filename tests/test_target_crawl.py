from eagle.target_crawl import _evaluate, _parse, _route_matches


def test_parser_resolves_job_links_without_emitting_empty_anchors() -> None:
    html = """
    <html><head><title>Harvest Vacancies</title></head><body>
      <a href="/job/123">Grain Sampler</a>
      <a href="">Empty</a>
    </body></html>
    """
    title, text, links = _parse(html, "https://example.com/jobs")
    assert "Harvest Vacancies" in title
    assert "Grain Sampler" in text
    assert [(link.text, link.url) for link in links] == [
        ("Grain Sampler", "https://example.com/job/123")
    ]


def test_grain_route_matches_weighbridge_and_sampling() -> None:
    config = {"grain_terms": ["weighbridge", "grain sampling"]}
    matches = _route_matches(
        "grain",
        "The role covers weighbridge operations and grain sampling.",
        config,
    )
    assert matches == ["weighbridge", "grain sampling"]


def test_food_route_requires_industry_and_function() -> None:
    config = {
        "food_industry_terms": ["meat processing", "food manufacturing"],
        "food_function_terms": ["quality assurance", "despatch"],
    }
    assert _route_matches(
        "food", "Quality assurance officer in a meat processing plant", config
    ) == ["meat processing", "quality assurance"]
    assert _route_matches("food", "Quality assurance officer", config) == []


def test_closed_and_driver_required_are_rejected() -> None:
    config = {
        "closed_terms": ["position has been filled"],
        "hard_reject_terms": ["unrestricted driver's licence"],
        "transport_risk_terms": ["own transport required"],
        "positive_terms": ["training provided"],
    }
    decision, reasons, _, _ = _evaluate(
        "Sorry, this position has been filled. Training provided.", config
    )
    assert decision == "REJECT-CLOSED"
    assert reasons == ["position has been filled"]

    decision, reasons, _, _ = _evaluate(
        "Applicants need an unrestricted driver's licence.", config
    )
    assert decision == "REJECT-HARD-GATE"
    assert reasons == ["unrestricted driver's licence"]


def test_transport_risk_is_held_not_silently_accepted() -> None:
    config = {
        "closed_terms": [],
        "hard_reject_terms": [],
        "transport_risk_terms": ["own transport required"],
        "positive_terms": ["working holiday"],
    }
    decision, _, risks, positives = _evaluate(
        "Working holiday applicants welcome; own transport required.", config
    )
    assert decision == "HOLD-TRANSPORT"
    assert risks == ["own transport required"]
    assert positives == ["working holiday"]
