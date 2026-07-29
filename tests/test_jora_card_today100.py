from dataclasses import dataclass

import eagle.jora_card_today100 as collector


def test_jora_search_card_is_auditable() -> None:
    page = '''
    <div id="r_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" class="job-card result organic-job"
      data-braze-job-panel-view="{&quot;job_id&quot;:&quot;aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa&quot;,&quot;job_title&quot;:&quot;Laundry Attendant&quot;,&quot;location&quot;:&quot;Darwin NT&quot;,&quot;company_name&quot;:&quot;Territory Laundry&quot;}">
      <h2 class="job-title"><a class="job-link" href="/job/Laundry-Attendant-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa?x=1">Laundry Attendant</a></h2>
      <span class="job-company">Territory Laundry</span>
      <a class="job-location" href="/jobs-in-Darwin-NT">Darwin NT</a>
      <div class="job-abstract"><ul><li>Physically active laundry work with training provided.</li></ul></div>
      <span class="job-listed-date">Posted 2h ago</span>
    </div>
    '''
    parser = collector._JoraSearchCardParser()
    parser.feed(page)
    parser.close()
    assert len(parser.cards) == 1
    card = parser.cards[0]
    assert card["source_id"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert card["title"] == "Laundry Attendant"
    assert card["company"] == "Territory Laundry"
    assert card["location"] == "Darwin NT"
    assert card["listed"] == "Posted 2h ago"
    assert card["url"] == "https://au.jora.com/job/Laundry-Attendant-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert "training provided" in card["description"]


def test_strict_industry_does_not_turn_local_area_prose_into_mining() -> None:
    assert collector._strict_industry(
        "Psychiatry Registrar",
        "Work in a regional mining town with a modern hospital.",
    ) == "Other/Unverified"
    assert collector._strict_industry(
        "Drillers Offsider",
        "Entry-level field role supporting a drill crew.",
    ) == "Mining"
    assert collector._strict_industry(
        "Guest Service Agent",
        "Hotel reception, reservations and guest support.",
    ) == "Tourism/Hospitality"


@dataclass
class _Response:
    status_code: int
    text: str = "rate limited"


class _Session:
    def get(self, *_args, **_kwargs):
        return _Response(status_code=429)


def test_rate_limited_detail_is_live_recheck_not_closed(monkeypatch) -> None:
    monkeypatch.setattr(collector, "RUN_DATE", "2026-07-29")
    monkeypatch.setattr(collector, "DELAY", 0)
    monkeypatch.setattr(collector.today100, "RUN_DATE", "2026-07-29")
    monkeypatch.setattr(collector.today100, "_industry", collector._strict_industry)
    card = {
        "source_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "title": "Guest Service Agent",
        "company": "Remote Resort",
        "location": "Jabiru NT 0886",
        "url": "https://au.jora.com/job/Guest-Service-Agent-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "listed": "Posted 2h ago",
        "description": (
            "Paid full-time hotel reception and reservations role. "
            "Staff accommodation provided. Check-in, booking amendments, "
            "guest enquiries and rotating shifts."
        ),
    }
    record = collector._enrich_or_fallback(_Session(), card)
    assert record.vacancy_status == "LIVE"
    assert record.second_visa == "Likely"
    assert record.evidence_grade == "B"
    assert record.audit_status == "RECHECK"
    assert record.decision == "VERIFY THEN APPLY"
    assert "detail-http=429" in record.today_evidence
    assert "vacancy URL is not live" not in record.hard_gate_reason
