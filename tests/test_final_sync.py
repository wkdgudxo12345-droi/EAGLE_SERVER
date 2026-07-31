from datetime import date

from eagle.final_sync import (
    _build_payload,
    _canonical_key,
    _option,
    candidate_record,
    evaluate_candidates,
)
from eagle.scoring import ScoreResult


def _score(*, fit: str = "B", rag: float = 78.0) -> ScoreResult:
    return ScoreResult(
        ccstm=76.0,
        hr=72.0,
        reality=91.0,
        rag=rag,
        fit=fit,
        verdict="APPLY NOW" if fit in {"A", "B"} else "RECHECK",
        duplicate_key="url:https://example.com/job/1",
        hard_gate=False,
        reasons=["test score"],
    )


def test_candidate_record_extracts_operational_signals() -> None:
    item = {
        "company": "Bunge / Viterra",
        "title": "Harvest Casual - Grain Sampler",
        "route": "GRAIN",
        "job_url": "https://example.com/page.php?AdvertID=918201&pageID=160",
        "source_url": "https://example.com/harvest",
        "source_id": "bunge_sa_vic_harvest",
        "date_hint": "31/07/2026",
        "decision": "KEEP",
        "matched_terms": ["grain sampling"],
        "positive_signals": [
            "accommodation provided",
            "working holiday",
        ],
        "transport_risks": [],
        "hard_gate_reasons": [],
        "fetched_at": "2026-07-31T10:00:00+00:00",
    }

    record = candidate_record(item)

    assert record["Source Job ID"] == "918201"
    assert record["Accommodation"] == "Provided"
    assert record["Car/Licence"] == "Not stated"
    assert record["WHV/88 Days"] == "Likely"
    assert record["Freshness"] == str(
        float(max((date.today() - date(2026, 7, 31)).days, 0))
    )


def test_canonical_key_normalizes_tracking_parameters() -> None:
    item = {
        "job_url": "https://EXAMPLE.com/job/123/?utm_source=test&ref=feed",
        "company": "Example",
        "title": "Role",
        "source_id": "source",
    }
    assert _canonical_key(item) == "url:https://example.com/job/123"


def test_evaluate_candidates_deduplicates_and_keeps_only_finalists(monkeypatch) -> None:
    monkeypatch.setattr("eagle.final_sync.score", lambda record, config, live: _score())
    base = {
        "company": "Bunge / Viterra",
        "title": "Harvest Casual - Grain Sampler",
        "route": "GRAIN",
        "job_url": "https://example.com/job/1",
        "source_url": "https://example.com/harvest",
        "source_id": "official_harvest",
        "date_hint": "2026-07-31",
        "decision": "KEEP",
        "official_source": True,
        "matched_terms": ["grain sampling"],
        "positive_signals": ["accommodation provided", "working holiday"],
        "transport_risks": [],
        "hard_gate_reasons": [],
    }
    duplicate = dict(base)
    hold = dict(base, job_url="https://example.com/job/2", decision="HOLD-TRANSPORT")

    rows = evaluate_candidates([base, duplicate, hold], {}, max_final_rows=15)

    assert len(rows) == 1
    assert rows[0]["decision"] == "APPLY NOW"


def test_schema_option_matching_and_date_payload() -> None:
    schema = {
        "Vacancy Status": {
            "type": "select",
            "select": {"options": [{"name": "LIVE"}, {"name": "CLOSED"}]},
        },
        "Last Verified": {"type": "date", "date": {}},
        "Company": {"type": "rich_text", "rich_text": {}},
    }
    assert _option(schema, "Vacancy Status", "Live") == "LIVE"

    payload, skipped = _build_payload(
        schema,
        {
            "Vacancy Status": "LIVE",
            "Last Verified": "2026-07-31",
            "Company": "Example",
        },
    )

    assert skipped == []
    assert payload["Last Verified"] == {"date": {"start": "2026-07-31"}}
    assert payload["Company"]["rich_text"][0]["text"]["content"] == "Example"
