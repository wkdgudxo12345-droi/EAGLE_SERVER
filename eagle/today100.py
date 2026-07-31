from __future__ import annotations

import csv
import hashlib
import html as html_lib
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote_plus

import requests


RUN_DATE = os.getenv("EAGLE_RUN_DATE", date.today().isoformat())
TARGET_COUNT = int(os.getenv("TARGET_COUNT", "100"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output/today100"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.35"))

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0 Safari/537.36 "
    "EagleJobAudit/2026.07"
)

SEARCH_URLS = [
    # Northern Territory: all postcodes are eligible for northern tourism and hospitality.
    "https://www.seek.com.au/hospitality-tourism-jobs/in-Northern-Territory-NT?daterange=1",
    "https://www.seek.com.au/hospitality-and-tourism-jobs/in-All-Darwin-NT?daterange=1",
    "https://www.seek.com.au/hospitality-tourism-jobs/in-Alice-Springs-NT-0870?daterange=1",
    "https://www.seek.com.au/hospitality-tourism-jobs/in-Katherine-NT-0850?daterange=1",
    "https://www.seek.com.au/administration-office-support-jobs/in-Northern-Territory-NT?daterange=1",
    "https://www.seek.com.au/manufacturing-transport-logistics-jobs/in-Northern-Territory-NT?daterange=1",
    "https://www.seek.com.au/construction-jobs/in-Northern-Territory-NT?daterange=1",
    "https://www.seek.com.au/mining-resources-energy-jobs/in-Northern-Territory-NT?daterange=1",
    # Northern Queensland / FNQ.
    "https://www.seek.com.au/hospitality-jobs/in-Cairns-%26-Far-North-QLD?daterange=1",
    "https://www.seek.com.au/hospitality-tourism-jobs/in-Cairns-QLD-4870?daterange=1",
    "https://www.seek.com.au/hospitality-tourism-jobs/in-Port-Douglas-QLD-4877?daterange=1",
    "https://www.seek.com.au/hospitality-tourism-jobs/in-Townsville-QLD-4810?daterange=1",
    "https://www.seek.com.au/hospitality-tourism-jobs/in-Mackay-QLD-4740?daterange=1",
    "https://www.seek.com.au/hospitality-tourism-jobs/in-Mount-Isa-QLD-4825?daterange=1",
    "https://www.seek.com.au/farming-animals-conservation-jobs/in-Cairns-%26-Far-North-QLD?daterange=1",
    "https://www.seek.com.au/manufacturing-transport-logistics-jobs/in-Cairns-%26-Far-North-QLD?daterange=1",
    "https://www.seek.com.au/construction-jobs/in-Cairns-%26-Far-North-QLD?daterange=1",
    "https://www.seek.com.au/mining-resources-energy-jobs/in-Mount-Isa-%26-North-West-QLD?daterange=1",
    # Remote Western Australia.
    "https://www.seek.com.au/hospitality-tourism-jobs/in-Broome-%26-Kimberley-WA?daterange=1",
    "https://www.seek.com.au/work-and-accommodation-jobs/in-Broome-%26-Kimberley-WA?daterange=1",
    "https://www.seek.com.au/hospitality-tourism-jobs/in-Port-Hedland-Karratha-%26-Pilbara-WA?daterange=1",
    "https://www.seek.com.au/hospitality-tourism-jobs/in-Kalgoorlie-Goldfields-%26-Esperance-WA?daterange=1",
    "https://www.seek.com.au/administration-office-support-jobs/in-Port-Hedland-Karratha-%26-Pilbara-WA?daterange=1",
    "https://www.seek.com.au/mining-resources-energy-jobs/in-Port-Hedland-Karratha-%26-Pilbara-WA?daterange=1",
    "https://www.seek.com.au/manufacturing-transport-logistics-jobs/in-Broome-%26-Kimberley-WA?daterange=1",
    # Tasmania: remote tourism/hospitality and regional specified industries.
    "https://www.seek.com.au/hospitality-tourism-jobs/in-Tasmania-TAS?daterange=1",
    "https://www.seek.com.au/farming-animals-conservation-jobs/in-Tasmania-TAS?daterange=1",
    "https://www.seek.com.au/manufacturing-transport-logistics-jobs/in-Tasmania-TAS?daterange=1",
    "https://www.seek.com.au/construction-jobs/in-Tasmania-TAS?daterange=1",
    # Regional South Australia / remote hospitality and food production.
    "https://www.seek.com.au/hospitality-tourism-jobs/in-Whyalla-%26-Eyre-Peninsula-SA?daterange=1",
    "https://www.seek.com.au/hospitality-tourism-jobs/in-Fleurieu-Peninsula-%26-Kangaroo-Island-SA?daterange=1",
    "https://www.seek.com.au/farming-animals-conservation-jobs/in-South-Australia-SA?daterange=1",
    "https://www.seek.com.au/manufacturing-transport-logistics-jobs/in-South-Australia-SA?daterange=1",
    "https://www.seek.com.au/construction-jobs/in-Port-Augusta-%26-Eyre-Peninsula-SA?daterange=1",
]

ROLE_TERMS = {
    "front_office": (
        "guest service", "reception", "front office", "night auditor", "reservations",
        "concierge", "hostel worker", "accommodation officer", "receptionist",
    ),
    "housekeeping": (
        "housekeeper", "housekeeping", "room attendant", "cleaner", "house person",
        "laundry", "public areas",
    ),
    "food_beverage": (
        "food and beverage", "f&b", "wait staff", "barista", "kitchen hand",
        "catering assistant", "restaurant", "breakfast attendant", "all rounder",
        "all-rounder", "counter", "cook",
    ),
    "operations_admin": (
        "site administrator", "mobilisation", "operations administrator", "project support",
        "roster", "workforce", "village administrator", "travel coordinator",
    ),
    "food_processing": (
        "process worker", "food processing", "meat process", "seafood process", "packer",
        "production worker", "cold store", "fruit", "farm hand", "harvest",
    ),
    "construction_mining": (
        "trade assistant", "labourer", "construction", "shutdown", "mine site",
        "utility", "village", "camp services",
    ),
}

HARD_MISMATCH_TERMS = (
    "australian citizenship required", "must be an australian citizen",
    "security clearance required", "unrestricted drivers licence",
    "unrestricted driver's licence", "own reliable vehicle", "must have own transport",
    "minimum 3 years australian experience", "approved manager", "master v",
    "registered nurse", "australian permanent resident only", "unpaid volunteer",
    "accommodation exchange", "commission only",
)

LICENCE_REQUIRED_TERMS = (
    "driver licence required", "drivers licence required", "driver's licence required",
    "current driver licence", "current drivers licence", "current driver's licence",
    "unrestricted drivers licence", "unrestricted driver's licence", "own reliable vehicle",
    "must have own transport", "manual drivers licence", "manual driver's licence",
)

ACCOM_PROVIDED_TERMS = (
    "accommodation provided", "staff accommodation", "subsidised accommodation",
    "live-in", "live in position", "onsite accommodation", "on-site accommodation",
    "meals and accommodation", "housing provided", "single accommodation",
)

EXPLICIT_NO_LICENCE_TERMS = (
    "no driver licence required", "no drivers licence required", "no car required",
    "transport provided", "staff shuttle", "bus provided", "airport transfer provided",
)

CREDENTIAL_HOLD_TERMS = (
    "rsa required", "must hold rsa", "food safety supervisor", "certificate iii in commercial cookery",
    "qualified chef", "trade qualification", "white card required", "forklift licence required",
    "police clearance required", "working with children check required",
)

TOURISM_TERMS = (
    "hotel", "resort", "motel", "hostel", "restaurant", "cafe", "bar", "tourism",
    "hospitality", "guest", "accommodation", "casino resort", "holiday park",
)
PLANT_ANIMAL_TERMS = (
    "farm", "harvest", "fruit", "vegetable", "meat", "seafood", "abattoir",
    "food processing", "process worker", "packing shed", "dairy", "poultry",
)
CONSTRUCTION_TERMS = (
    "construction", "civil", "labourer", "trade assistant", "building", "roadworks",
)
MINING_TERMS = (
    "mining", "mine site", "resources", "drill", "shutdown", "processing plant",
)

CITY_POSTCODES = {
    "darwin": 800, "palmerston": 830, "alice springs": 870, "yulara": 872,
    "katherine": 850, "jabiru": 886, "tennant creek": 860,
    "cairns": 4870, "cairns north": 4870, "port douglas": 4877, "palm cove": 4879,
    "mareeba": 4880, "atherton": 4883, "innisfail": 4860, "townsville": 4810,
    "mackay": 4740, "mount isa": 4825, "airlie beach": 4802, "bowen": 4805,
    "broome": 6725, "cable beach": 6726, "kununurra": 6743, "derby": 6728,
    "port hedland": 6721, "south hedland": 6722, "karratha": 6714, "newman": 6753,
    "kalgoorlie": 6430, "esperance": 6450, "exmouth": 6707, "carnarvon": 6701,
    "hobart": 7000, "launceston": 7250, "devonport": 7310, "burnie": 7320,
    "queenstown": 7467, "strahan": 7468, "port lincoln": 5606, "coober pedy": 5723,
    "roxby downs": 5725, "kangaroo island": 5223, "kingscote": 5223,
}


@dataclass
class JobRecord:
    source: str
    source_job_id: str
    opportunity: str
    company: str
    location: str
    postcode: str
    apply_url: str
    date_posted: str
    freshness_days: int | None
    today_evidence: str
    description: str
    role_family: str
    industry: str
    second_visa: str
    car_licence: str
    accommodation: str
    vacancy_status: str
    evidence_grade: str
    audit_status: str
    decision: str
    ccstm: int
    hr_score: int
    reality_score: int
    strategy_score: int
    canonical_key: str
    hard_gate_reason: str
    final_recommendation: str
    cv_cluster: str


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html_lib.unescape(str(value))
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _get_nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_nonempty(*values: Any) -> str:
    for value in values:
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned
    return ""


def _json_ld_objects(page_html: str) -> Iterable[dict[str, Any]]:
    scripts = re.findall(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        page_html,
        flags=re.I | re.S,
    )
    for script in scripts:
        try:
            loaded = json.loads(html_lib.unescape(script.strip()))
        except (json.JSONDecodeError, TypeError):
            continue
        values = loaded if isinstance(loaded, list) else [loaded]
        for value in values:
            if isinstance(value, dict):
                if isinstance(value.get("@graph"), list):
                    for item in value["@graph"]:
                        if isinstance(item, dict):
                            yield item
                yield value


def _find_job_posting(page_html: str) -> dict[str, Any]:
    for value in _json_ld_objects(page_html):
        type_value = value.get("@type")
        types = type_value if isinstance(type_value, list) else [type_value]
        if any(str(item).lower() == "jobposting" for item in types):
            return value
    return {}


def _extract_location(posting: dict[str, Any], page_html: str) -> str:
    raw = posting.get("jobLocation")
    locations = raw if isinstance(raw, list) else [raw]
    parts: list[str] = []
    for item in locations:
        if not isinstance(item, dict):
            continue
        address = item.get("address")
        if isinstance(address, dict):
            candidate = ", ".join(
                str(address.get(key, "")).strip()
                for key in ("addressLocality", "addressRegion", "postalCode")
                if str(address.get(key, "")).strip()
            )
            if candidate:
                parts.append(candidate)
    if parts:
        return " / ".join(dict.fromkeys(parts))
    match = re.search(r'"location"\s*:\s*"([^"]+)"', page_html, re.I)
    return _clean_text(match.group(1)) if match else ""


def _extract_postcode(location: str, description: str) -> str:
    combined = f"{location} {description[:1500]}"
    matches = re.findall(r"\b([0-9]{4})\b", combined)
    for match in matches:
        value = int(match)
        if 200 <= value <= 7999:
            return match.zfill(4)
    lowered = location.lower()
    for city, postcode in CITY_POSTCODES.items():
        if city in lowered:
            return f"{postcode:04d}"
    return ""


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    candidate = value.strip()[:10]
    try:
        return date.fromisoformat(candidate)
    except ValueError:
        return None


def _freshness(date_posted: str) -> tuple[int | None, str]:
    posted = _parse_date(date_posted)
    run = _parse_date(RUN_DATE)
    if not posted or not run:
        return None, "date unavailable"
    days = (run - posted).days
    if days < 0:
        return 0, f"future/UTC boundary date {date_posted}"
    return days, f"datePosted={date_posted}"


def _remote_tourism_postcode(postcode: int) -> bool:
    # Conservative project ranges: all NT, Tasmania and remote/northern parts of
    # QLD, WA and SA that are routinely used for WHM tourism/hospitality screening.
    if 800 <= postcode <= 999:
        return True
    if 7000 <= postcode <= 7999:
        return True
    if 4307 <= postcode <= 4499 or 4515 <= postcode <= 4519 or 4522 <= postcode <= 4899:
        return True
    if 6041 <= postcode <= 6044 or 6083 <= postcode <= 6084 or 6121 <= postcode <= 6126:
        return True
    if 6200 <= postcode <= 6799:
        return True
    if 5220 <= postcode <= 5223 or 5234 <= postcode <= 5235 or 5242 <= postcode <= 5250:
        return True
    if 5252 <= postcode <= 5355 or 5381 <= postcode <= 5734:
        return True
    return False


def _regional_industry_postcode(postcode: int) -> bool:
    # For plant/animal cultivation, construction and mining, exclude only obvious
    # metropolitan cores. Exact worksite and duties remain recorded for review.
    if 800 <= postcode <= 999 or 7000 <= postcode <= 7999:
        return True
    if 4000 <= postcode <= 4999 and not 4000 <= postcode <= 4306:
        return True
    if 5000 <= postcode <= 5999 and not 5000 <= postcode <= 5199:
        return True
    if 6000 <= postcode <= 6999 and not 6000 <= postcode <= 6199:
        return True
    if 2000 <= postcode <= 2999 and not 2000 <= postcode <= 2310:
        return True
    if 3000 <= postcode <= 3999 and not 3000 <= postcode <= 3999:
        return True
    return False


def _industry(title: str, description: str) -> str:
    text = f"{title} {description}".lower()
    if any(term in text for term in PLANT_ANIMAL_TERMS):
        return "Plant/Animal or Food Processing"
    if any(term in text for term in CONSTRUCTION_TERMS):
        return "Construction"
    if any(term in text for term in MINING_TERMS):
        return "Mining"
    if any(term in text for term in TOURISM_TERMS):
        return "Tourism/Hospitality"
    return "Other/Unverified"


def _role_family(title: str, description: str) -> str:
    text = f"{title} {description[:1200]}".lower()
    best = ("other", 0)
    for family, terms in ROLE_TERMS.items():
        score = sum(1 for term in terms if term in text)
        if score > best[1]:
            best = (family, score)
    return best[0]


def _second_visa(industry: str, postcode: str) -> tuple[str, str]:
    if not postcode:
        return "Unknown", "exact postcode unavailable"
    value = int(postcode)
    if industry == "Tourism/Hospitality":
        return (
            ("Likely", "remote/northern tourism-hospitality postcode")
            if _remote_tourism_postcode(value)
            else ("No", "tourism/hospitality postcode outside conservative eligible ranges")
        )
    if industry in {"Plant/Animal or Food Processing", "Construction", "Mining"}:
        return (
            ("Likely", "regional specified-industry worksite")
            if _regional_industry_postcode(value)
            else ("Unknown", "industry may qualify but regional worksite is unresolved")
        )
    return "Unknown", "direct eligible specified-work industry not established"


def _car_licence(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in LICENCE_REQUIRED_TERMS):
        return "Required"
    if any(term in lowered for term in EXPLICIT_NO_LICENCE_TERMS):
        return "Not required"
    return "Not stated"


def _accommodation(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ACCOM_PROVIDED_TERMS):
        return "Provided"
    if "no accommodation provided" in lowered or "accommodation is not provided" in lowered:
        return "No"
    return "Unknown"


def _role_fit(family: str, text: str) -> tuple[int, list[str]]:
    base = {
        "front_office": 91,
        "operations_admin": 84,
        "housekeeping": 75,
        "food_beverage": 72,
        "food_processing": 66,
        "construction_mining": 55,
        "other": 42,
    }.get(family, 42)
    reasons: list[str] = []
    lowered = text.lower()
    if family == "front_office":
        reasons.append("direct Agoda reservations, escalation and guest-operations transfer")
    elif family == "operations_admin":
        reasons.append("case management, KPI, records and cross-team coordination transfer")
    elif family == "housekeeping":
        reasons.append("guesthouse/resort support and reliability transfer")
    elif family == "food_beverage":
        reasons.append("eight months KFC and guest-service experience transfer")
    elif family == "food_processing":
        reasons.append("warehouse/manual-handling experience provides entry-level evidence")
    elif family == "construction_mining":
        reasons.append("general labour experience is relevant but tickets/site evidence are limited")

    if any(term in lowered for term in ("manager", "head chef", "executive chef", "supervisor")):
        base -= 22
        reasons.append("seniority requirement exceeds direct Australian evidence")
    if "opera" in lowered or "property management system" in lowered or "pms experience" in lowered:
        base -= 5
        reasons.append("no verified Australian hotel PMS experience")
    if any(term in lowered for term in CREDENTIAL_HOLD_TERMS):
        base -= 10
        reasons.append("role-specific credential requires confirmation or completion")
    return max(0, min(100, base)), reasons


def _canonical(company: str, title: str, location: str, source_id: str) -> str:
    raw = "|".join(
        re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
        for value in (company, title, location, source_id)
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _classify(
    *, title: str, company: str, location: str, description: str, url: str,
    source_id: str, date_posted: str, status_code: int,
) -> JobRecord:
    text = f"{title} {company} {location} {description}"
    lowered = text.lower()
    postcode = _extract_postcode(location, description)
    freshness_days, today_evidence = _freshness(date_posted)
    industry = _industry(title, description)
    family = _role_family(title, description)
    second_visa, visa_reason = _second_visa(industry, postcode)
    car = _car_licence(text)
    accommodation = _accommodation(text)
    closed = status_code not in {200, 201} or any(
        term in lowered for term in ("this job is no longer available", "job has expired", "position has been filled")
    )
    vacancy = "CLOSED" if closed else "LIVE"
    hard_reasons: list[str] = []
    if closed:
        hard_reasons.append("vacancy URL is not live")
    if second_visa == "No":
        hard_reasons.append(visa_reason)
    if car == "Required":
        hard_reasons.append("driver licence or own vehicle required")
    for term in HARD_MISMATCH_TERMS:
        if term in lowered:
            hard_reasons.append(f"hard mismatch: {term}")
    if freshness_days is not None and freshness_days > 1:
        hard_reasons.append("not posted within the strict today/24h window")

    fit, fit_reasons = _role_fit(family, text)
    exact_today = freshness_days == 0
    evidence = "A" if date_posted and title and company and location and len(description) >= 180 else "B"
    if not title or not company or not location:
        evidence = "C"

    mobility_clear = car == "Not required" or accommodation == "Provided"
    if hard_reasons:
        decision = "REJECT"
        audit = "FAILED"
    elif second_visa != "Likely":
        decision = "HOLD"
        audit = "RECHECK"
    elif not exact_today:
        decision = "HOLD"
        audit = "RECHECK"
    elif fit < 55:
        decision = "HOLD"
        audit = "RECHECK"
    elif mobility_clear and evidence in {"A", "B"} and fit >= 70:
        decision = "APPLY NOW"
        audit = "VERIFIED"
    else:
        decision = "VERIFY THEN APPLY"
        audit = "RECHECK"

    ccstm = fit
    if second_visa == "Likely":
        ccstm += 5
    if mobility_clear:
        ccstm += 4
    if freshness_days == 0:
        ccstm += 3
    ccstm = min(100, ccstm)

    hr = max(0, min(100, fit - (10 if car == "Not stated" else 0) - (8 if evidence == "C" else 0)))
    reality = 35
    reality += 20 if vacancy == "LIVE" else 0
    reality += 15 if freshness_days == 0 else 5 if freshness_days == 1 else 0
    reality += 15 if second_visa == "Likely" else 0
    reality += 10 if mobility_clear else 0
    reality += 10 if evidence == "A" else 5 if evidence == "B" else 0
    reality = min(100, reality)
    strategy = round(0.45 * ccstm + 0.35 * hr + 0.20 * reality)

    recommendation_parts = [visa_reason, *fit_reasons]
    if car == "Not stated" and accommodation == "Unknown":
        recommendation_parts.append("confirm staff housing or reliable car-free transport before relocation")
    if any(term in lowered for term in CREDENTIAL_HOLD_TERMS):
        recommendation_parts.append("confirm required ticket before applying")
    recommendation_parts.append("confirm paid hours, payslips and exact worksite for WHV evidence")

    cv_cluster = {
        "front_office": "CV_FRONT_OFFICE",
        "operations_admin": "CV_OPERATIONS_ADMIN",
        "housekeeping": "CV_HOUSEKEEPING",
        "food_beverage": "CV_HOSPITALITY_ALLROUNDER",
        "food_processing": "CV_FOOD_PROCESSING",
        "construction_mining": "CV_GENERAL_LABOUR",
    }.get(family, "CV_GENERAL")

    return JobRecord(
        source="SEEK",
        source_job_id=f"SEEK:{source_id}",
        opportunity=title or f"SEEK job {source_id}",
        company=company or "Unknown employer",
        location=location,
        postcode=postcode,
        apply_url=url,
        date_posted=date_posted,
        freshness_days=freshness_days,
        today_evidence=today_evidence,
        description=description[:6000],
        role_family=family,
        industry=industry,
        second_visa=second_visa,
        car_licence=car,
        accommodation=accommodation,
        vacancy_status=vacancy,
        evidence_grade=evidence,
        audit_status=audit,
        decision=decision,
        ccstm=ccstm,
        hr_score=hr,
        reality_score=reality,
        strategy_score=strategy,
        canonical_key=_canonical(company, title, location, source_id),
        hard_gate_reason="; ".join(dict.fromkeys(hard_reasons)),
        final_recommendation="; ".join(dict.fromkeys(recommendation_parts)),
        cv_cluster=cv_cluster,
    )


def _seek_ids(page_html: str) -> list[str]:
    values: list[str] = []
    patterns = (
        r'href=["\']/job/(\d+)',
        r'https?://(?:www\.|au\.)?seek\.com\.au/job/(\d+)',
        r'"jobId"\s*:\s*"?(\d+)"?',
    )
    for pattern in patterns:
        values.extend(re.findall(pattern, page_html, flags=re.I))
    return list(dict.fromkeys(values))


def _fetch(session: requests.Session, url: str) -> requests.Response:
    response = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    time.sleep(REQUEST_DELAY)
    return response


def _detail_record(session: requests.Session, job_id: str) -> JobRecord | None:
    url = f"https://www.seek.com.au/job/{job_id}"
    try:
        response = _fetch(session, url)
    except requests.RequestException:
        return None
    page_html = response.text
    posting = _find_job_posting(page_html)

    organization = posting.get("hiringOrganization") if isinstance(posting, dict) else None
    company = organization.get("name") if isinstance(organization, dict) else ""
    title = _first_nonempty(
        posting.get("title") if isinstance(posting, dict) else "",
        re.search(r"<title>(.*?)</title>", page_html, re.I | re.S).group(1)
        if re.search(r"<title>(.*?)</title>", page_html, re.I | re.S)
        else "",
    )
    title = re.sub(r"\s*[-|]\s*SEEK.*$", "", title, flags=re.I).strip()
    description = _first_nonempty(
        posting.get("description") if isinstance(posting, dict) else "",
        re.search(r'"description"\s*:\s*"(.*?)"\s*,\s*"', page_html, re.I | re.S).group(1)
        if re.search(r'"description"\s*:\s*"(.*?)"\s*,\s*"', page_html, re.I | re.S)
        else "",
    )
    location = _extract_location(posting, page_html)
    date_posted = _first_nonempty(
        posting.get("datePosted") if isinstance(posting, dict) else "",
        re.search(r'"listingDate"\s*:\s*"([^"]+)"', page_html, re.I).group(1)
        if re.search(r'"listingDate"\s*:\s*"([^"]+)"', page_html, re.I)
        else "",
    )

    # Reject obvious anti-bot/error bodies without inventing a vacancy.
    if response.status_code >= 400 or len(page_html) < 800:
        return None
    if not title and not description:
        return None
    return _classify(
        title=title,
        company=_clean_text(company),
        location=location,
        description=description,
        url=url,
        source_id=job_id,
        date_posted=date_posted,
        status_code=response.status_code,
    )


def _search_candidates(session: requests.Session) -> tuple[list[str], list[dict[str, Any]]]:
    ids: list[str] = []
    diagnostics: list[dict[str, Any]] = []
    for base_url in SEARCH_URLS:
        for page in (1, 2, 3):
            separator = "&" if "?" in base_url else "?"
            url = f"{base_url}{separator}page={page}"
            try:
                response = _fetch(session, url)
                found = _seek_ids(response.text)
                diagnostics.append(
                    {"url": url, "status": response.status_code, "job_ids": len(found)}
                )
                ids.extend(found)
            except requests.RequestException as exc:
                diagnostics.append({"url": url, "status": "error", "error": str(exc)})
            if len(dict.fromkeys(ids)) >= max(TARGET_COUNT * 4, 240):
                return list(dict.fromkeys(ids)), diagnostics
    return list(dict.fromkeys(ids)), diagnostics


def _rank_key(record: JobRecord) -> tuple[Any, ...]:
    decision_order = {"APPLY NOW": 0, "VERIFY THEN APPLY": 1, "HOLD": 2, "REJECT": 3}
    freshness = record.freshness_days if record.freshness_days is not None else 999
    return (
        decision_order.get(record.decision, 9),
        freshness,
        -record.strategy_score,
        -record.reality_score,
        record.company.lower(),
        record.opportunity.lower(),
    )


def _write(records: list[JobRecord], diagnostics: list[dict[str, Any]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = [asdict(record) for record in records]
    (OUTPUT_DIR / "today100.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if rows:
        with (OUTPUT_DIR / "today100.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    (OUTPUT_DIR / "search_diagnostics.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = {
        "run_date": RUN_DATE,
        "target": TARGET_COUNT,
        "collected": len(records),
        "exact_today": sum(record.freshness_days == 0 for record in records),
        "within_24h_or_one_day": sum(
            record.freshness_days is not None and record.freshness_days <= 1 for record in records
        ),
        "apply_now": sum(record.decision == "APPLY NOW" for record in records),
        "verify_then_apply": sum(record.decision == "VERIFY THEN APPLY" for record in records),
        "hold": sum(record.decision == "HOLD" for record in records),
        "reject": sum(record.decision == "REJECT" for record in records),
        "second_likely": sum(record.second_visa == "Likely" for record in records),
        "accommodation_provided": sum(record.accommodation == "Provided" for record in records),
        "car_required": sum(record.car_licence == "Required" for record in records),
        "cv_clusters": sorted({record.cv_cluster for record in records if record.decision != "REJECT"}),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


def main() -> int:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-AU,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        }
    )
    candidate_ids, diagnostics = _search_candidates(session)
    print(f"discovered_candidate_ids={len(candidate_ids)}")

    records: list[JobRecord] = []
    for index, job_id in enumerate(candidate_ids, 1):
        record = _detail_record(session, job_id)
        if record is None:
            continue
        records.append(record)
        print(
            f"[{index}/{len(candidate_ids)}] {record.decision:18} "
            f"visa={record.second_visa:7} fresh={record.freshness_days} "
            f"{record.opportunity[:55]}"
        )
        if len(records) >= max(TARGET_COUNT * 2, TARGET_COUNT + 40):
            break

    records.sort(key=_rank_key)
    selected = records[:TARGET_COUNT]
    _write(selected, diagnostics)
    if len(selected) < TARGET_COUNT:
        print(
            f"Only {len(selected)} auditable individual vacancies were collected; "
            "the collector will not fabricate rows to reach 100."
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
