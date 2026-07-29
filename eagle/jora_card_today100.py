from __future__ import annotations

import html as html_lib
import json
import os
import re
import time
from dataclasses import asdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlsplit, urlunsplit

import requests

from . import today100
from .jora_today100 import _JoraDetailParser, _relative_posted_date
from .whv_regions import regional_industry_postcode, remote_tourism_postcode

RUN_DATE = os.getenv("EAGLE_RUN_DATE", "2026-07-29")
TARGET_COUNT = int(os.getenv("TARGET_COUNT", "100"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output/today100"))
TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
DELAY = float(os.getenv("REQUEST_DELAY", "0.12"))

LOCATIONS = [
    "Darwin NT", "Northern Territory", "Alice Springs NT", "Katherine NT",
    "Cairns QLD", "Cairns City QLD", "Port Douglas QLD", "Townsville QLD",
    "Mackay QLD", "Mount Isa QLD", "Broome WA", "Karratha WA",
    "Port Hedland WA", "Newman WA", "Kalgoorlie WA", "Esperance WA",
    "Tasmania TAS", "Hobart TAS", "Launceston TAS", "Port Lincoln SA",
    "Kangaroo Island SA", "Coober Pedy SA",
]
SEARCHES = [
    "Hospitality", "Hotel", "Guest Service", "Receptionist", "Front Office",
    "Reservations", "Housekeeping", "Room Attendant", "Kitchen Hand",
    "Food And Beverage", "Hospitality All Rounder", "Cleaner",
    "Site Administrator", "Operations Administrator", "Project Support",
    "Accommodation Officer", "Village Services", "Utility All Rounder",
    "Food Processing", "Production Worker", "Process Worker", "Warehouse",
    "Farm Hand", "Construction Labourer", "Trade Assistant",
]
SEARCH_URLS = [
    "https://au.jora.com/j?"
    f"l={quote_plus(location)}&q={quote_plus(query)}&a=24h&st=date"
    for location in LOCATIONS
    for query in SEARCHES
]


def _canonical_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme or "https", parts.netloc or "au.jora.com", parts.path, "", ""))


def _source_id(url: str) -> str:
    match = re.search(r"-([0-9a-f]{24,40})$", urlsplit(url).path, flags=re.I)
    return match.group(1) if match else urlsplit(url).path.rsplit("/", 1)[-1]


class _JoraSearchCardParser(HTMLParser):
    """Extract auditable server-rendered job cards from Jora search HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict[str, str]] = []
        self.current: dict[str, str] | None = None
        self.capture: str | None = None
        self.buffer: list[str] = []
        self.in_abstract = False
        self.abstract_buffer: list[str] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {key: value or "" for key, value in attrs}

    def _finish_current(self) -> None:
        if not self.current:
            return
        self.current["description"] = " ".join(self.abstract_buffer).strip()
        required = ("source_id", "title", "company", "location", "url", "listed")
        if all(self.current.get(key) for key in required):
            self.cards.append(self.current)
        self.current = None
        self.capture = None
        self.buffer = []
        self.in_abstract = False
        self.abstract_buffer = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = self._attrs(attrs)
        classes = set(values.get("class", "").split())
        if tag == "div" and "job-card" in classes:
            self._finish_current()
            current: dict[str, str] = {}
            payload = values.get("data-braze-job-panel-view", "")
            try:
                parsed = json.loads(html_lib.unescape(payload))
            except (json.JSONDecodeError, TypeError):
                parsed = {}
            current["source_id"] = str(parsed.get("job_id", ""))
            current["title"] = today100._clean_text(parsed.get("job_title", ""))
            current["company"] = today100._clean_text(parsed.get("company_name", ""))
            current["location"] = today100._clean_text(parsed.get("location", ""))
            self.current = current
            self.abstract_buffer = []
            return
        if self.current is None:
            return
        if tag == "a" and "job-link" in classes and not self.current.get("url"):
            self.current["url"] = _canonical_url(urljoin("https://au.jora.com", values.get("href", "")))
            if not self.current.get("title"):
                self.capture = "title"
                self.buffer = []
        elif tag == "span" and "job-company" in classes and not self.current.get("company"):
            self.capture = "company"
            self.buffer = []
        elif tag == "a" and "job-location" in classes and not self.current.get("location"):
            self.capture = "location"
            self.buffer = []
        elif tag == "span" and "job-listed-date" in classes:
            self.capture = "listed"
            self.buffer = []
        elif tag == "div" and "job-abstract" in classes:
            self.in_abstract = True
            self.abstract_buffer = []

    def handle_endtag(self, tag: str) -> None:
        if self.capture and tag in {"a", "span"}:
            value = " ".join(" ".join(self.buffer).split())
            if self.current is not None:
                self.current[self.capture] = value
            self.capture = None
            self.buffer = []
        if tag == "div" and self.in_abstract:
            self.in_abstract = False

    def handle_data(self, data: str) -> None:
        cleaned = " ".join(data.split())
        if self.capture and cleaned:
            self.buffer.append(cleaned)
        if self.in_abstract and cleaned:
            self.abstract_buffer.append(cleaned)

    def close(self) -> None:
        super().close()
        self._finish_current()


def _enrich_or_fallback(session: requests.Session, card: dict[str, str]):
    url = card["url"]
    status = 0
    detail_html = ""
    try:
        response = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        status = response.status_code
        detail_html = response.text
    except requests.RequestException:
        status = 0
    time.sleep(DELAY)

    title = card["title"]
    company = card["company"]
    location = card["location"]
    description = card.get("description", "")
    listed = card["listed"]
    detail_quality = "search-card"

    if status == 200 and len(detail_html) >= 700:
        parser = _JoraDetailParser()
        parser.feed(detail_html)
        if parser.title and parser.company and parser.location and len(parser.description) >= 80:
            title = today100._clean_text(parser.title)
            company = today100._clean_text(parser.company)
            location = today100._clean_text(parser.location)
            description = today100._clean_text(parser.description)
            listed = parser.listed or listed
            detail_quality = "detail-page"

    if not description:
        description = f"Jora listing for {title} at {company} in {location}."
    date_posted = _relative_posted_date(listed)
    record = today100._classify(
        title=title,
        company=company,
        location=location,
        description=description,
        url=url,
        source_id=card["source_id"],
        date_posted=date_posted,
        status_code=status if status else 200,
    )
    record.source = "JORA"
    record.source_job_id = f"JORA:{card['source_id']}"
    record.apply_url = url
    record.today_evidence = (
        f"Jora a=24h search; listed-date={listed}; evidence={detail_quality}; "
        f"detail-http={status or 'request-error'}"
    )
    if detail_quality == "search-card" and record.evidence_grade == "A":
        record.evidence_grade = "B"
        if record.audit_status == "VERIFIED":
            record.audit_status = "RECHECK"
            record.decision = "VERIFY THEN APPLY"
    return record


def main() -> int:
    today100.RUN_DATE = RUN_DATE
    today100._remote_tourism_postcode = remote_tourism_postcode
    today100._regional_industry_postcode = regional_industry_postcode
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/150 Safari/537.36",
            "Accept-Language": "en-AU,en;q=0.9",
        }
    )

    cards_by_id: dict[str, dict[str, str]] = {}
    diagnostics: list[dict[str, object]] = []
    for base_url in SEARCH_URLS:
        for page in (1, 2):
            url = f"{base_url}&p={page}"
            try:
                response = session.get(url, timeout=TIMEOUT)
                time.sleep(DELAY)
                parser = _JoraSearchCardParser()
                parser.feed(response.text)
                parser.close()
                diagnostics.append(
                    {"url": url, "status": response.status_code, "cards": len(parser.cards)}
                )
                for card in parser.cards:
                    cards_by_id.setdefault(card["source_id"], card)
            except requests.RequestException as exc:
                diagnostics.append({"url": url, "status": "error", "error": str(exc)})
            if len(cards_by_id) >= max(TARGET_COUNT * 4, 400):
                break
        if len(cards_by_id) >= max(TARGET_COUNT * 4, 400):
            break

    cards = list(cards_by_id.values())
    print(f"jora_auditable_cards={len(cards)}")
    records = []
    for index, card in enumerate(cards, 1):
        record = _enrich_or_fallback(session, card)
        records.append(record)
        print(
            f"[{index}/{len(cards)}] {record.decision:18} visa={record.second_visa:7} "
            f"fresh={record.freshness_days} {record.opportunity[:55]}"
        )
        if len(records) >= max(TARGET_COUNT * 2, 160):
            break

    records.sort(key=today100._rank_key)
    selected = records[:TARGET_COUNT]
    today100._write(selected, diagnostics)
    (OUTPUT_DIR / "jora_all_auditable.json").write_text(
        json.dumps([asdict(row) for row in records], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "jora_cards.json").write_text(
        json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if len(selected) < TARGET_COUNT:
        print(f"Only {len(selected)} auditable Jora cards were collected.")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
