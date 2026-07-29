from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass
class BpoV2Result:
    hiring_probability_score: float
    estimated_hire_range: str
    salary_score: float
    career_fit_score: float
    english_fit: float
    visa_score: float
    final_score: float
    queue: str
    hard_gate: bool
    canonical_key: str
    individual_url: bool
    reasons: list[str] = field(default_factory=list)


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


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
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "ref", "source", "tracking", "origin", "type",
    }
    query = urlencode(sorted(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in ignored
    ))
    path = re.sub(r"/+", "/", parts.path).rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower() or "https", parts.netloc.lower(), path, query, ""))


def is_individual_url(url: str) -> bool:
    raw = str(url or "").strip().lower()
    if "careers.trip.com" in raw and "job-detail" in raw:
        return True
    normalized = normalize_url(url)
    if not normalized:
        return False
    parts = urlsplit(normalized)
    host = parts.netloc.lower()
    path = parts.path.lower()
    query = parts.query.lower()

    if "linkedin.com" in host:
        return "/jobs/view/" in path
    if "jobstreet.com" in host:
        return bool(re.search(r"/job/\d+", path))
    if "indeed.com" in host:
        return path.endswith("/viewjob") and ("jk=" in query)

    search_markers = (
        "/jobs/search", "/job-search", "/search", "/jobs?", "/q-", "/jobs/in-",
        "keywords=", "query=",
    )
    full = f"{path}?{query}"
    if any(marker in full for marker in search_markers):
        return False

    # A jobs subdomain is not itself evidence of a search page.
    return bool(re.search(r"/(?:job|jobs|position|positions|vacancy|vacancies|role)/[^/]+", path))


def canonical_key(record: dict[str, Any]) -> str:
    normalized = normalize_url(str(record.get("url") or record.get("source_url") or ""))
    if normalized:
        return f"url:{normalized}"
    identity = "|".join(_text(record.get(k)) for k in ("company", "title", "location"))
    if not identity.replace("|", ""):
        return ""
    return "identity:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def freshness_score(days: Any) -> float:
    try:
        value = float(days)
    except (TypeError, ValueError):
        return 45.0
    if value <= 1:
        return 100.0
    if value <= 3:
        return 92.0
    if value <= 5:
        return 84.0
    if value <= 7:
        return 75.0
    return max(20.0, 75.0 - (value - 7.0) * 3.0)


def salary_score(record: dict[str, Any], profile: dict[str, Any]) -> float:
    lo = record.get("salary_min")
    hi = record.get("salary_max")
    try:
        lo = float(lo) if lo not in (None, "") else None
        hi = float(hi) if hi not in (None, "") else None
    except (TypeError, ValueError):
        lo, hi = None, None
    salary_config = profile.get("salary_bands_myr_monthly", {})
    if lo is None and hi is None:
        return float(salary_config.get("undisclosed_score", 42))
    lo = hi if lo is None else lo
    hi = lo if hi is None else hi
    midpoint = (lo + hi) / 2.0
    for band in salary_config.get("bands", []):
        if midpoint >= float(band.get("minimum", 0)):
            return float(band.get("score", 0))
    return 20.0


def visa_score(record: dict[str, Any], profile: dict[str, Any]) -> float:
    status = _text(record.get("visa") or "unknown").replace(" ", "_")
    scores = profile.get("visa_scores", {})
    aliases = {
        "employment_pass_supported": "supported",
        "visa_supported": "supported",
        "sponsorship_available": "available",
        "local_nationals_only": "local_only",
        "local_work_rights_required": "local_only",
    }
    status = aliases.get(status, status)
    return float(scores.get(status, scores.get("unknown", 50)))


def hire_range(score: float) -> str:
    if score >= 82:
        return "18-30%"
    if score >= 75:
        return "12-22%"
    if score >= 68:
        return "8-16%"
    if score >= 60:
        return "4-10%"
    if score >= 52:
        return "2-6%"
    return "1-3%"


def score_record(record: dict[str, Any], profile: dict[str, Any]) -> BpoV2Result:
    reasons: list[str] = []
    hard_gate = False

    status = _text(record.get("vacancy_status") or "live")
    if status in {_text(x) for x in profile.get("hard_gates", {}).get("reject_statuses", [])}:
        hard_gate = True
        reasons.append(f"vacancy status is {status}")

    all_text = _text(" ".join(str(v or "") for v in record.values()))
    for term in profile.get("hard_gates", {}).get("reject_terms", []):
        if _text(term) in all_text:
            hard_gate = True
            reasons.append(f"hard gate term: {term}")

    visa_status = _text(record.get("visa") or "unknown")
    if profile.get("hard_gates", {}).get("reject_local_only", True) and visa_status in {
        "local only", "local_only", "local nationals only", "local work rights required"
    }:
        hard_gate = True
        reasons.append("role is explicitly limited to local work-right holders")

    role_match = float(record.get("role_match", 50))
    seniority_fit = float(record.get("seniority_fit", 50))
    english_fit = float(record.get("english_fit", 50))
    source_confidence = float(record.get("source_conf", record.get("source_confidence", 50)))
    fresh = freshness_score(record.get("posted_age_days"))

    hp_weights = profile.get("weights", {}).get("hiring_probability", {})
    hp_total = sum(float(v) for v in hp_weights.values()) or 100.0
    hiring = round((
        role_match * float(hp_weights.get("role_match", 42)) +
        seniority_fit * float(hp_weights.get("seniority_fit", 18)) +
        english_fit * float(hp_weights.get("english_feasibility", 18)) +
        fresh * float(hp_weights.get("freshness", 12)) +
        source_confidence * float(hp_weights.get("source_confidence", 10))
    ) / hp_total, 1)

    career = round(role_match * 0.68 + seniority_fit * 0.32, 1)
    salary = salary_score(record, profile)
    visa = visa_score(record, profile)
    individual = is_individual_url(str(record.get("url") or record.get("source_url") or ""))
    if not individual:
        reasons.append("individual vacancy URL requires verification")

    final_weights = profile.get("weights", {}).get("final", {})
    fw_total = sum(float(v) for v in final_weights.values()) or 100.0
    final = round((
        hiring * float(final_weights.get("hiring_probability", 35)) +
        salary * float(final_weights.get("salary", 30)) +
        career * float(final_weights.get("career_fit", 20)) +
        english_fit * float(final_weights.get("english_feasibility", 10)) +
        visa * float(final_weights.get("visa", 5))
    ) / fw_total, 1)

    thresholds = profile.get("thresholds", {})
    if hard_gate:
        queue = "Reject"
    elif final >= float(thresholds.get("apply_first", 75)):
        queue = "A - Apply First"
    elif final >= float(thresholds.get("apply", 65)):
        queue = "B - Apply"
    elif final >= float(thresholds.get("verify_hold", 55)):
        queue = "C - Verify/Hold"
    else:
        queue = "D - Low Priority"

    if salary == 42:
        reasons.append("salary is undisclosed and receives the model default")
    if visa == 50:
        reasons.append("visa support is unverified but has only 5% final weight")
    if english_fit < 60:
        reasons.append("English B1-B2 creates execution risk for this role")

    return BpoV2Result(
        hiring_probability_score=hiring,
        estimated_hire_range=hire_range(hiring),
        salary_score=salary,
        career_fit_score=career,
        english_fit=english_fit,
        visa_score=visa,
        final_score=final,
        queue=queue,
        hard_gate=hard_gate,
        canonical_key=canonical_key(record),
        individual_url=individual,
        reasons=reasons or ["passed BPO Eagle V2 checks"],
    )
