import eagle.today100 as today100
from eagle.whv_regions import regional_industry_postcode, remote_tourism_postcode


def setup_module() -> None:
    today100._remote_tourism_postcode = remote_tourism_postcode
    today100._regional_industry_postcode = regional_industry_postcode


def test_seek_ids_are_deduplicated() -> None:
    page = '''
    <a href="/job/12345678">One</a>
    <a href="https://www.seek.com.au/job/87654321">Two</a>
    <script>{"jobId":"12345678"}</script>
    '''
    assert today100._seek_ids(page) == ["12345678", "87654321"]


def test_json_ld_job_posting_is_found() -> None:
    page = '''
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"JobPosting","title":"Receptionist"}
    </script>
    '''
    assert today100._find_job_posting(page)["title"] == "Receptionist"


def test_official_remote_tourism_postcodes() -> None:
    assert remote_tourism_postcode(800)   # Darwin/NT
    assert remote_tourism_postcode(870)   # Alice Springs/NT
    assert remote_tourism_postcode(4870)  # Cairns/QLD
    assert remote_tourism_postcode(6753)  # Newman/WA
    assert remote_tourism_postcode(5606)  # Port Lincoln/SA
    assert not remote_tourism_postcode(2000)  # Sydney
    assert not remote_tourism_postcode(5600)  # Whyalla hospitality is not listed


def test_official_regional_industry_postcodes() -> None:
    assert regional_industry_postcode(5600)  # SA all postcodes for eligible industries
    assert regional_industry_postcode(7250)  # Tasmania all postcodes
    assert regional_industry_postcode(4825)  # Mount Isa
    assert regional_industry_postcode(6753)  # Newman
    assert not regional_industry_postcode(2000)
    assert not regional_industry_postcode(3000)


def test_verified_live_in_reception_can_apply_now(monkeypatch) -> None:
    monkeypatch.setattr(today100, "RUN_DATE", "2026-07-29")
    record = today100._classify(
        title="Guest Service Agent",
        company="Remote Resort",
        location="Jabiru NT 0886",
        description=(
            "Paid full-time hotel guest service and reservations role. "
            "Staff accommodation provided. Check-in, booking amendments, "
            "guest enquiries and rotating shifts. " * 4
        ),
        url="https://www.seek.com.au/job/12345678",
        source_id="12345678",
        date_posted="2026-07-29",
        status_code=200,
    )
    assert record.second_visa == "Likely"
    assert record.accommodation == "Provided"
    assert record.decision == "APPLY NOW"
    assert record.audit_status == "VERIFIED"


def test_car_required_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(today100, "RUN_DATE", "2026-07-29")
    record = today100._classify(
        title="Hotel All Rounder",
        company="Remote Hotel",
        location="Cairns QLD 4870",
        description=(
            "Paid hotel position. Current driver's licence required and own reliable vehicle. "
            "Guest service and cleaning duties. " * 4
        ),
        url="https://www.seek.com.au/job/22345678",
        source_id="22345678",
        date_posted="2026-07-29",
        status_code=200,
    )
    assert record.car_licence == "Required"
    assert record.decision == "REJECT"


def test_metro_hospitality_is_not_second_visa_eligible(monkeypatch) -> None:
    monkeypatch.setattr(today100, "RUN_DATE", "2026-07-29")
    record = today100._classify(
        title="Guest Service Agent",
        company="Sydney Hotel",
        location="Sydney NSW 2000",
        description="Paid hotel reception and reservation duties. " * 10,
        url="https://www.seek.com.au/job/32345678",
        source_id="32345678",
        date_posted="2026-07-29",
        status_code=200,
    )
    assert record.second_visa == "No"
    assert record.decision == "REJECT"


def test_non_hospitality_admin_does_not_pass_just_for_remote_location(monkeypatch) -> None:
    monkeypatch.setattr(today100, "RUN_DATE", "2026-07-29")
    record = today100._classify(
        title="Legal Administration Officer",
        company="Government Agency",
        location="Mount Isa QLD 4825",
        description="General legal administration, filing and office support. " * 8,
        url="https://www.seek.com.au/job/42345678",
        source_id="42345678",
        date_posted="2026-07-29",
        status_code=200,
    )
    assert record.second_visa == "Unknown"
    assert record.decision == "HOLD"


def test_regional_construction_support_can_be_likely(monkeypatch) -> None:
    monkeypatch.setattr(today100, "RUN_DATE", "2026-07-29")
    record = today100._classify(
        title="Construction Site Administrator",
        company="Civil Contractor",
        location="Mount Isa QLD 4825",
        description=(
            "Paid administration support directly for an operating civil construction site. "
            "Roster records, site access, travel coordination and document control. " * 4
        ),
        url="https://www.seek.com.au/job/52345678",
        source_id="52345678",
        date_posted="2026-07-29",
        status_code=200,
    )
    assert record.industry == "Construction"
    assert record.second_visa == "Likely"
    assert record.decision in {"VERIFY THEN APPLY", "APPLY NOW"}
