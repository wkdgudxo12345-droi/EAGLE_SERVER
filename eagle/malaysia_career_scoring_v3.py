from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass
class MalaysiaCareerResult:
    hiring_reality_score: float
    career_transfer_score: float
    salary_score: float
    career_upside_score: float
    authorization_stability_score: float
    final_score: float
    queue: str
    hard_gate: bool
    canonical_key: str
    individual_url: bool
    industry_track: str
    role_track: str
    cv_variant: str
    reasons: list[str] = field(default_factory=list)


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _match_text(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#]+", " ", _text(value))).strip()


def _all_text(record: dict[str, Any]) -> str:
    return _match_text(" ".join(str(value or "") for value in record.values()))


def _contains(text: str, terms: list[str]) -> bool:
    return any(_match_text(term) in text for term in terms if _match_text(term))


def _coverage(text: str, terms: list[str], floor: float = 0.0) -> float:
    normalized = {_match_text(term) for term in terms if _match_text(term)}
    if not normalized:
        return floor
    hits = sum(term in text for term in normalized)
    if hits == 0:
        return floor
    return min(100.0, max(floor, 35.0 + 12.0 * hits))


def _weighted(values: dict[str, float], weights: dict[str, Any]) -> float:
    parsed = {key: float(value) for key, value in weights.items()}
    total = sum(parsed.values()) or 100.0
    return round(sum(values.get(key, 0.0) * weight for key, weight in parsed.items()) / total, 1)


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
    normalized = normalize_url(raw)
    if not normalized:
        return False
    parts = urlsplit(normalized)
    host, path, query = parts.netloc.lower(), parts.path.lower(), parts.query.lower()
    if "linkedin.com" in host:
        return "/jobs/view/" in path
    if "jobstreet.com" in host:
        return bool(re.search(r"/job/\d+", path))
    if "indeed.com" in host:
        return path.endswith("/viewjob") and "jk=" in query
    if "careers.trip.com" in host:
        return "job-detail" in path
    search_markers = (
        "/jobs/search", "/job-search", "/search", "/jobs?", "/careers?",
        "keywords=", "query=", "/jobs/in-", "/korean-speaker-jobs",
    )
    full = f"{path}?{query}"
    if any(marker in full for marker in search_markers):
        return False
    return bool(re.search(r"/(?:job|jobs|position|positions|vacancy|vacancies|role|opening)/[^/]+", path))


def canonical_key(record: dict[str, Any]) -> str:
    url = normalize_url(str(record.get("url") or record.get("source_url") or record.get("Source URL") or ""))
    if url:
        return f"url:{url}"
    identity = "|".join(_text(record.get(key)) for key in ("company", "title", "location"))
    if not identity.replace("|", ""):
        return ""
    return "identity:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _freshness(days: Any) -> float:
    value = _float(days, 999)
    if value <= 1:
        return 100.0
    if value <= 3:
        return 94.0
    if value <= 7:
        return 84.0
    if value <= 14:
        return 68.0
    if value <= 30:
        return 45.0
    return 15.0


def _salary(record: dict[str, Any], profile: dict[str, Any]) -> tuple[float, float | None]:
    lo_raw, hi_raw = record.get("salary_min"), record.get("salary_max")
    lo = _float(lo_raw, -1)
    hi = _float(hi_raw, -1)
    lo = None if lo < 0 else lo
    hi = None if hi < 0 else hi
    config = profile.get("salary_bands_myr_monthly", {})
    if lo is None and hi is None:
        return float(config.get("undisclosed_score", 48)), None
    lo = hi if lo is None else lo
    hi = lo if hi is None else hi
    midpoint = (lo + hi) / 2.0
    for band in config.get("bands", []):
        if midpoint >= float(band.get("minimum", 0)):
            return float(band.get("score", 0)), lo
    return 20.0, lo


def _authorization(record: dict[str, Any], profile: dict[str, Any]) -> float:
    status = _text(record.get("visa") or record.get("visa_status") or record.get("work_authorization") or "unknown")
    status = status.replace(" ", "_")
    aliases = {
        "employment_pass_will_be_provided": "employment_pass_provided",
        "employment_pass_supported": "employment_pass_provided",
        "visa_supported": "supported",
        "sponsorship_available": "available",
        "local_nationals_only": "local_only",
        "local_only": "local_only",
    }
    status = aliases.get(status, status)
    scores = profile.get("authorization_scores", {})
    return float(scores.get(status, scores.get("unknown", 48)))


def infer_industry(record: dict[str, Any]) -> str:
    text = _all_text(record)
    if _contains(text, ["crypto", "blockchain", "exchange", "web3", "wallet", "digital asset", "okx", "bitget", "bybit", "binance"]):
        return "Crypto / Blockchain"
    if _contains(text, ["fintech", "payment", "transaction", "banking", "financial services", "merchant"]):
        return "Fintech / Payments"
    if _contains(text, ["travel", "hotel", "flight", "booking", "reservation", "ota", "agoda", "trip.com", "klook"]):
        return "Travel / OTA"
    if _contains(text, ["platform", "tiktok", "bytedance", "tencent", "shopee", "technology"]):
        return "Technology Platform"
    if _contains(text, ["bpo", "contact centre", "customer service", "shared services"]):
        return "Premium BPO / Shared Services"
    return "Other Operations"


def infer_role(record: dict[str, Any]) -> str:
    text = _all_text(record)
    if _contains(text, ["aml", "kyc", "transaction monitoring", "compliance operations", "fraud", "investigation", "risk operations"]):
        return "Risk / Compliance Operations"
    if _contains(text, ["trust and safety", "content moderation", "content operations"]):
        return "Trust & Safety / Content Operations"
    if _contains(text, ["qa", "quality analyst", "trainer", "sme", "floor support", "team lead", "workforce", "real time analyst"]):
        return "QA / SME / Leadership Support"
    if _contains(text, ["partner support", "merchant", "client operations", "onboarding", "vendor operations"]):
        return "Partner / Client Operations"
    if _contains(text, ["crypto", "exchange", "wallet", "user operations"]):
        return "Crypto Exchange User Operations"
    if _contains(text, ["travel", "reservation", "hotel", "flight", "booking"]):
        return "Travel Platform Operations"
    return "Korean Senior Customer Operations"


def infer_cv(industry: str, role: str) -> str:
    if role in {"Risk / Compliance Operations", "Trust & Safety / Content Operations"}:
        return "Risk · Trust & Safety · Compliance Operations"
    if industry in {"Crypto / Blockchain", "Fintech / Payments", "Technology Platform"}:
        return "Tech · Fintech · Crypto Operations"
    return "Korean Operations / Senior CX"


def score_record(record: dict[str, Any], profile: dict[str, Any]) -> MalaysiaCareerResult:
    reasons: list[str] = []
    hard_gate = False
    text = _all_text(record)
    gates = profile.get("hard_gates", {})
    status = _text(record.get("vacancy_status") or "live")

    if status in {_text(value) for value in gates.get("reject_statuses", [])}:
        hard_gate = True
        reasons.append(f"vacancy status is {status}")
    for group_name in ("reject_terms", "local_only_terms", "mandatory_language_terms", "mandatory_credential_terms"):
        matches = [term for term in gates.get(group_name, []) if _match_text(term) in text]
        if matches:
            hard_gate = True
            reasons.append(f"{group_name}: {', '.join(matches[:2])}")
    if _contains(text, list(gates.get("overlevel_terms", []))):
        hard_gate = True
        reasons.append("role is above the verified management level")

    individual = is_individual_url(str(record.get("url") or record.get("source_url") or ""))
    if not individual:
        reasons.append("individual vacancy URL is not verified")

    korean_signal = _contains(text, ["korean", "한국어", "korea market", "korean speaker", "native korean"])
    if gates.get("require_korean_advantage", True) and not korean_signal:
        hard_gate = True
        reasons.append("Korean-language hiring advantage is not verified")

    salary_score, salary_floor = _salary(record, profile)
    salary_cfg = profile.get("salary_bands_myr_monthly", {})
    if gates.get("reject_below_salary_floor", True) and salary_floor is not None and salary_floor < float(salary_cfg.get("minimum_actionable", 8000)):
        hard_gate = True
        reasons.append("disclosed salary is below the project floor")

    company = _text(record.get("company"))
    excluded = {_text(value) for value in profile.get("scope", {}).get("target_companies", {}).get("excluded_by_default", [])}
    if company in excluded:
        exception = gates.get("excluded_company_exception", {})
        promotion = _contains(text, list(exception.get("promotion_terms", [])))
        high_salary = salary_floor is not None and salary_floor >= float(exception.get("salary_minimum", 12000))
        if not (promotion and high_salary):
            hard_gate = True
            reasons.append("previous employer is excluded unless the role is a clear high-pay promotion")

    role_match = _float(record.get("role_match"), 50)
    seniority_fit = _float(record.get("seniority_fit"), 55)
    english_fit = _float(record.get("english_fit"), 60)
    source_conf = _float(record.get("source_conf", record.get("source_confidence")), 50)
    fresh = _freshness(record.get("posted_age_days"))

    direct_ops = max(role_match, _coverage(text, [
        "customer operations", "customer service", "case management", "ticket", "chat", "email", "voice",
        "escalation", "complaint", "sla", "kpi", "24x7", "shift", "support operations",
    ], 25.0))
    korean_advantage = 100.0 if korean_signal else 0.0
    hiring = _weighted({
        "korean_advantage": korean_advantage,
        "direct_operations_match": direct_ops,
        "seniority_fit": seniority_fit,
        "english_feasibility": english_fit,
        "freshness": fresh,
        "source_confidence": source_conf,
        "individual_url": 100.0 if individual else 0.0,
    }, profile.get("weights", {}).get("hiring_reality", {}))

    customer_ops = _coverage(text, ["customer service", "customer operations", "support", "case management", "complaint", "resolution"], 35.0)
    escalation = _coverage(text, ["escalation", "quality assurance", "qa", "sme", "floor support", "training", "coaching", "audit"], 30.0)
    platform = _coverage(text, ["travel", "hotel", "flight", "reservation", "payment", "transaction", "platform", "exchange", "wallet", "fintech"], 28.0)
    tools = _coverage(text, ["crm", "zendesk", "salesforce", "ticketing", "excel", "microsoft office", "g suite", "knowledge base", "sop"], 38.0)
    transfer = _weighted({
        "customer_operations": customer_ops,
        "escalation_qa_training": escalation,
        "travel_payment_platform": platform,
        "korean_market": korean_advantage,
        "tools_process": tools,
    }, profile.get("weights", {}).get("career_transfer", {}))

    industry = infer_industry(record)
    role = infer_role(record)
    cv = infer_cv(industry, role)
    tier1 = {_text(value) for value in profile.get("scope", {}).get("target_companies", {}).get("tier_1", [])}
    brand = 94.0 if company in tier1 else (72.0 if company else 45.0)
    inhouse = 92.0 if industry in {"Crypto / Blockchain", "Fintech / Payments", "Travel / OTA", "Technology Platform"} and company in tier1 else 65.0
    scope = _coverage(text, ["senior", "specialist", "analyst", "operations", "risk", "quality", "trainer", "partner", "client", "onboarding"], 45.0)
    industry_value = {
        "Crypto / Blockchain": 92.0,
        "Fintech / Payments": 90.0,
        "Technology Platform": 84.0,
        "Travel / OTA": 80.0,
        "Premium BPO / Shared Services": 58.0,
    }.get(industry, 50.0)
    upside = round(0.35 * inhouse + 0.30 * scope + 0.20 * brand + 0.15 * industry_value, 1)

    authorization = _authorization(record, profile)
    employment = _text(record.get("employment_type") or "full time")
    stability = 88.0 if "permanent" in employment or "full time" in employment else 60.0
    if "contract" in employment or "temporary" in employment:
        stability = 48.0
    auth_stability = round(0.7 * authorization + 0.3 * stability, 1)

    final_weights = profile.get("weights", {}).get("final", {})
    final = _weighted({
        "hiring_reality": hiring,
        "career_transfer": transfer,
        "salary": salary_score,
        "career_upside": upside,
        "authorization_stability": auth_stability,
    }, final_weights)

    thresholds = profile.get("thresholds", {})
    if hard_gate:
        queue = "Reject"
    elif not individual or status != "live":
        queue = "C - Verify/Hold"
    elif final >= float(thresholds.get("apply_first", 80)) and hiring >= float(thresholds.get("minimum_hiring_reality_a", 74)):
        queue = "A - Apply First"
    elif final >= float(thresholds.get("apply", 72)) and hiring >= float(thresholds.get("minimum_hiring_reality_b", 64)):
        queue = "B - Apply"
    else:
        queue = "C - Verify/Hold"

    if salary_floor is None:
        reasons.append("salary is undisclosed; no automatic salary-floor rejection")
    if authorization <= 48:
        reasons.append("Employment Pass or work authorization remains unverified")
    if english_fit < 60:
        reasons.append("English B1-B2 may reduce interview or execution fit")
    if queue in {"A - Apply First", "B - Apply"} and not reasons:
        reasons.append("passed Malaysia Career Eagle V3 gates")

    return MalaysiaCareerResult(
        hiring_reality_score=hiring,
        career_transfer_score=transfer,
        salary_score=salary_score,
        career_upside_score=upside,
        authorization_stability_score=auth_stability,
        final_score=final,
        queue=queue,
        hard_gate=hard_gate,
        canonical_key=canonical_key(record),
        individual_url=individual,
        industry_track=industry,
        role_track=role,
        cv_variant=cv,
        reasons=reasons,
    )
