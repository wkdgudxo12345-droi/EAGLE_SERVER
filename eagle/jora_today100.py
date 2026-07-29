from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

from . import today100
from .whv_regions import regional_industry_postcode, remote_tourism_postcode

RUN_DATE = os.getenv("EAGLE_RUN_DATE", "2026-07-29")
TARGET_COUNT = int(os.getenv("TARGET_COUNT", "100"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output/today100"))
TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
DELAY = float(os.getenv("REQUEST_DELAY", "0.18"))

LOCATIONS = [
    "Darwin-NT", "Northern-Territory", "Alice-Springs-NT", "Katherine-NT",
    "Cairns-QLD", "Cairns-City-QLD", "Port-Douglas-QLD", "Townsville-QLD",
    "Mackay-QLD", "Mount-Isa-QLD", "Broome-WA", "Karratha-WA",
    "Port-Hedland-WA", "Newman-WA", "Kalgoorlie-WA", "Esperance-WA",
    "Tasmania-TAS", "Hobart-TAS", "Launceston-TAS", "Port-Lincoln-SA",
    "Kangaroo-Island-SA", "Coober-Pedy-SA",
]

SEARCHES = [
    "Hospitality", "Hotel", "Guest-Service", "Receptionist", "Front-Office",
    "Reservations", "Housekeeping", "Room-Attendant", "Kitchen-Hand",
    "Food-And-Beverage", "Hospitality-All-Rounder", "Cleaner",
    "Site-Administrator", "Operations-Administrator", "Project-Support",
    "Accommodation-Officer", "Village-Services", "Utility-All-Rounder",
    "Food-Processing", "Production-Worker", "Process-Worker", "Warehouse",
    "Farm-Hand", "Construction-Labourer", "Trade-Assistant",
]

SEARCH_URLS = [
    f"https://au.jora.com/{query}-jobs-in-{location}?since=1&sort=date"
    for location in LOCATIONS
    for query in SEARCHES
]


def _normalise_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _job_links(html: str) -> list[str]:
    links = re.findall(r'href=["\']([^"\']*/job/[^"\']+)["\']', html, flags=re.I)
    output: list[str] = []
    for link in links:
        full = _normalise_url(urljoin("https://au.jora.com", link.replace("&amp;", "&")))
        if re.search(r"/job/[^/?]+-[0-9a-f]{24,40}$", full, flags=re.I):
            output.append(full)
    return list(dict.fromkeys(output))


def _source_id(url: str) -> str:
    match = re.search(r"-([0-9a-f]{24,40})$", urlsplit(url).path, flags=re.I)
    return match.group(1) if match else urlsplit(url).path.rsplit("/", 1)[-1]


def _detail(session: requests.Session, url: str, *, sample: bool = False):
    try:
        response = session.get(url, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException:
        return None
    time.sleep(DELAY)
    if sample:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "sample_detail.html").write_text(response.text, encoding="utf-8", errors="replace")
        (OUTPUT_DIR / "sample_detail_meta.json").write_text(
            json.dumps(
                {
                    "requested_url": url,
                    "final_url": response.url,
                    "status": response.status_code,
                    "length": len(response.text),
                    "content_type": response.headers.get("content-type", ""),
                    "json_ld_count": len(list(today100._json_ld_objects(response.text))),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    if response.status_code != 200 or len(response.text) < 700:
        return None
    posting = today100._find_job_posting(response.text)
    if not posting:
        return None
    organisation = posting.get("hiringOrganization")
    company = organisation.get("name", "") if isinstance(organisation, dict) else ""
    title = today100._clean_text(posting.get("title"))
    description = today100._clean_text(posting.get("description"))
    location = today100._extract_location(posting, response.text)
    date_posted = today100._clean_text(posting.get("datePosted"))
    if not title or not description or not location:
        return None
    source_id = _source_id(url)
    record = today100._classify(
        title=title,
        company=today100._clean_text(company),
        location=location,
        description=description,
        url=url,
        source_id=source_id,
        date_posted=date_posted,
        status_code=response.status_code,
    )
    record.source = "JORA"
    record.source_job_id = f"JORA:{source_id}"
    record.apply_url = url
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
    detail_urls: list[str] = []
    diagnostics: list[dict[str, object]] = []
    sample_search_written = False
    for base_url in SEARCH_URLS:
        for page in (1, 2):
            url = f"{base_url}&p={page}"
            try:
                response = session.get(url, timeout=TIMEOUT)
                time.sleep(DELAY)
                if not sample_search_written:
                    (OUTPUT_DIR / "sample_search.html").write_text(
                        response.text, encoding="utf-8", errors="replace"
                    )
                    (OUTPUT_DIR / "sample_search_meta.json").write_text(
                        json.dumps(
                            {
                                "url": url,
                                "final_url": response.url,
                                "status": response.status_code,
                                "length": len(response.text),
                                "content_type": response.headers.get("content-type", ""),
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    sample_search_written = True
                found = _job_links(response.text)
                diagnostics.append({"url": url, "status": response.status_code, "links": len(found)})
                detail_urls.extend(found)
            except requests.RequestException as exc:
                diagnostics.append({"url": url, "status": "error", "error": str(exc)})
            detail_urls = list(dict.fromkeys(detail_urls))
            if len(detail_urls) >= max(TARGET_COUNT * 5, 500):
                break
        if len(detail_urls) >= max(TARGET_COUNT * 5, 500):
            break

    print(f"jora_detail_urls={len(detail_urls)}")
    records = []
    for index, url in enumerate(detail_urls, 1):
        record = _detail(session, url, sample=index == 1)
        if record is None:
            continue
        records.append(record)
        print(
            f"[{index}/{len(detail_urls)}] {record.decision:18} visa={record.second_visa:7} "
            f"fresh={record.freshness_days} {record.opportunity[:55]}"
        )
        if len(records) >= TARGET_COUNT * 2:
            break

    records.sort(key=today100._rank_key)
    selected = records[:TARGET_COUNT]
    today100._write(selected, diagnostics)
    (OUTPUT_DIR / "jora_all_auditable.json").write_text(
        json.dumps([asdict(row) for row in records], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if len(selected) < TARGET_COUNT:
        print(f"Only {len(selected)} auditable Jora detail pages were collected.")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
