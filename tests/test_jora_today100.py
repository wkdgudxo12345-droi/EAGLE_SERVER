import eagle.jora_today100 as jora


def test_current_jora_detail_dom_is_parsed(monkeypatch) -> None:
    monkeypatch.setattr(jora, "RUN_DATE", "2026-07-29")
    page = '''
    <html><head><meta name="description" content="Fallback summary"></head><body>
    <div id="job-view">
      <div class="-desktop-no-padding-top">
        <h1 class="job-title heading">Guest Service Agent</h1>
        <span class="company">Remote Resort</span>
        <span class="location">Jabiru NT 0886</span>
        <span class="listed-date">2h ago</span>
      </div>
      <div class="job-view-actions-container">Apply</div>
      <div class="-desktop-no-padding-top">
        Paid full-time hotel reception and reservations role. Staff accommodation provided.
        Check-in, booking amendments, guest enquiries and rotating shifts.
      </div>
    </div></body></html>
    '''
    parser = jora._JoraDetailParser()
    parser.feed(page)
    assert parser.title == "Guest Service Agent"
    assert parser.company == "Remote Resort"
    assert parser.location == "Jabiru NT 0886"
    assert parser.listed == "2h ago"
    assert "Staff accommodation provided" in parser.description
    assert jora._relative_posted_date(parser.listed) == "2026-07-29"


def test_one_day_relative_date_is_previous_calendar_day(monkeypatch) -> None:
    monkeypatch.setattr(jora, "RUN_DATE", "2026-07-29")
    assert jora._relative_posted_date("1d ago") == "2026-07-28"


def test_job_links_are_canonicalised_and_deduplicated() -> None:
    page = '''
    <a href="/job/Guest-Service-Agent-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa?x=1">One</a>
    <a href="https://au.jora.com/job/Guest-Service-Agent-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa?x=2">Two</a>
    '''
    assert jora._job_links(page) == [
        "https://au.jora.com/job/Guest-Service-Agent-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    ]
