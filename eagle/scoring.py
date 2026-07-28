from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass
class ScoreResult:
    ccstm: float
    hr: float
    reality: float
    rag: float
    fit: str
    verdict: str
    duplicate_key: str
    hard_gate: bool
    reasons: list[str] = field(default_factory=list)


def _text(record: dict[str, Any]) -> str:
    return " ".join(str(value or "") for value in record.values()).lower()


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term.lower() in text for term in terms)


def _normalized_match_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def _coverage(text: str, terms: list[str], *, floor: float = 0.0) -> float:
    if not terms:
        return floor
    matches = sum(1 for term in terms if term.lower() in text)
    return min(100.0, max(floor, 35.0 + matches * 18.0 if matches else floor))


def _weighted(components: dict[str, float], weights: dict[str, float]) -> float:
    total_weight = sum(float(value) for value in weights.values())
    if total_weight <= 0:
        return 0.0
    score_value = sum(
        float(weights.get(name, 0)) * components.get(name, 0.0) for name in weights
    )
    return round(score_value / total_weight, 1)


def _freshness_score(value: str) -> float:
    match = re.search(r"\d+(?:\.\d+)?", value or "")
    if not match:
        return 45.0
    days = float(match.group())
    if days <= 7:
        return 100.0
    if days <= 14:
        return 82.0
    if days <= 30:
        return 62.0
    if days <= 60:
        return 35.0
    return 10.0


def normalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    if not parts.netloc:
        return url.strip().lower()
    ignored = {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "ref",
        "source",
    }
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in ignored
        )
    )
    path = re.sub(r"/+", "/", parts.path).rstrip("/") or "/"
    return urlunsplit(
        (parts.scheme.lower() or "https", parts.netloc.lower(), path, query, "")
    )


def duplicate_key(record: dict[str, Any]) -> str:
    url = normalize_url(
        str(record.get("Canonical URL") or record.get("Source") or "")
    )
    if url:
        return f"url:{url}"
    identity = "|".join(
        re.sub(r"\s+", " ", str(record.get(name) or "").strip().lower())
        for name in ("Company", "Opportunity", "Region")
    )
    if identity.replace("|", ""):
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        return f"identity:{digest}"
    return ""


def _is_individual_url(url: str, patterns: list[str]) -> bool:
    normalized = normalize_url(url)
    return bool(normalized) and not _contains_any(normalized.lower(), patterns)


def score(
    record: dict[str, Any], config: dict[str, Any], live: bool | None
) -> ScoreResult:
    text = _text(record)
    normalized_text = _normalized_match_text(text)
    thresholds = config.get("thresholds", {})
    weights = config.get("weights", {})
    hard_terms = [str(term).lower() for term in config.get("hard_reject_terms", [])]
    preferred_terms = [str(term).lower() for term in config.get("preferred_terms", [])]
    experience_terms = [
        str(term).lower()
        for term in config.get("experience_terms", preferred_terms)
    ]
    search_patterns = [
        str(term).lower() for term in config.get("search_url_patterns", [])
    ]

    reasons: list[str] = []
    matched_hard_terms = [
        term
        for term in hard_terms
        if _normalized_match_text(term) in normalized_text
    ]
    hard_gate = bool(matched_hard_terms)
    if matched_hard_terms:
        reasons.append(f"hard gate: {', '.join(matched_hard_terms[:3])}")

    car_value = str(record.get("Car/Licence") or "").lower()
    if "required" in car_value and "not required" not in car_value:
        hard_gate = True
        reasons.append("car or licence required")

    status_value = str(record.get("Application Status") or "").strip().lower()
    if status_value in {"closed", "rejected", "do not apply", "delete candidate"}:
        hard_gate = True
        reasons.append(f"application status is {status_value}")

    accommodation_value = str(record.get("Accommodation") or "").lower()
    visa_value = str(record.get("WHV/88 Days") or "").strip().lower()
    negative_visa_values = {"no", "unlikely", "ineligible"}
    if config.get("require_visa_eligibility", False) and visa_value in negative_visa_values:
        hard_gate = True
        reasons.append("specified-work visa eligibility is negative")

    freshness = _freshness_score(str(record.get("Freshness") or ""))
    url = str(record.get("Canonical URL") or record.get("Source") or "")
    individual_url = _is_individual_url(url, search_patterns)

    role_match = _coverage(
        text,
        preferred_terms,
        floor=35.0 if record.get("Role Family") else 20.0,
    )
    experience = _coverage(
        text,
        experience_terms,
        floor=45.0 if record.get("Evidence Text") else 25.0,
    )
    no_car = (
        100.0
        if any(term in car_value for term in ("not required", "no licence"))
        else 55.0
    )
    if hard_gate and "licence" in " ".join(matched_hard_terms + [car_value]):
        no_car = 0.0
    accommodation = (
        100.0
        if any(term in accommodation_value for term in ("provided", "included", "yes"))
        else 45.0
    )
    if any(term in accommodation_value for term in ("no", "not provided")):
        accommodation = 0.0
    visa = (
        100.0
        if any(term in visa_value for term in ("likely", "yes", "eligible"))
        else 55.0
    )
    if visa_value in negative_visa_values:
        visa = 0.0

    ccstm = _weighted(
        {
            "role_match": role_match,
            "experience": experience,
            "no_car": no_car,
            "accommodation": accommodation,
            "visa": visa,
            "freshness": freshness,
        },
        weights.get("ccstm", {}),
    )

    direct_experience = experience
    transferable_ops = _coverage(
        text,
        [
            "operations",
            "customer",
            "guest",
            "reservation",
            "escalation",
            "qa",
            "training",
        ],
        floor=35.0,
    )
    shift_reliability = _coverage(
        text, ["shift", "night", "roster", "weekend", "24/7"], floor=55.0
    )
    language = _coverage(
        text, ["english", "korean", "customer communication"], floor=55.0
    )
    location_commitment = 75.0 if record.get("Region") else 40.0
    requirements = 0.0 if hard_gate else 85.0
    hr = _weighted(
        {
            "direct_experience": direct_experience,
            "transferable_ops": transferable_ops,
            "shift_reliability": shift_reliability,
            "language": language,
            "location_commitment": location_commitment,
            "requirements": requirements,
        },
        weights.get("hr", {}),
    )

    evidence_quality = min(
        100.0,
        30.0 + min(len(str(record.get("Evidence Text") or "")), 700) / 10.0,
    )
    reality = _weighted(
        {
            "live_link": 100.0 if live is True else (45.0 if live is None else 0.0),
            "individual_job_url": 100.0 if individual_url else 0.0,
            "no_hard_gate": 0.0 if hard_gate else 100.0,
            "accommodation": accommodation,
            "evidence_quality": evidence_quality,
            "freshness": freshness,
        },
        weights.get("reality", {}),
    )
    rag = round(0.40 * ccstm + 0.30 * hr + 0.30 * reality, 1)

    fit_a = float(thresholds.get("fit_a", 82))
    fit_b = float(thresholds.get("fit_b", 68))
    min_reality = float(thresholds.get("min_reality", 55))
    min_hr = float(thresholds.get("min_hr", 60))
    min_ccstm = float(thresholds.get("min_ccstm", 68))

    if live is False:
        hard_gate = True
        reasons.append("vacancy URL appears closed")
    if not individual_url:
        reasons.append("individual job URL not verified")

    if hard_gate:
        fit = "Reject"
        verdict = "DELETE CANDIDATE"
    elif live is not True or not individual_url:
        fit = "C"
        verdict = "RECHECK"
    elif ccstm >= fit_a and hr >= min_hr and reality >= min_reality:
        fit = "A"
        verdict = "APPLY NOW"
    elif (
        ccstm >= max(fit_b, min_ccstm)
        and hr >= min_hr
        and reality >= min_reality
    ):
        fit = "B"
        verdict = "APPLY NOW"
    else:
        fit = "C"
        verdict = "RECHECK"

    if not reasons:
        reasons.append("passed deterministic checks")
    return ScoreResult(
        ccstm=ccstm,
        hr=hr,
        reality=reality,
        rag=rag,
        fit=fit,
        verdict=verdict,
        duplicate_key=duplicate_key(record),
        hard_gate=hard_gate,
        reasons=reasons,
    )
