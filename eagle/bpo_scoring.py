from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass
class BpoScoreResult:
    career_transfer: float
    hiring_reality: float
    strategic_value: float
    final_priority: float
    fit: str
    verdict: str
    hard_gate: bool
    canonical_key: str
    reasons: list[str] = field(default_factory=list)


def _normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _match_text(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#]+", " ", _normalized(value))).strip()


def _all_text(record: dict[str, Any]) -> str:
    return _match_text(" ".join(str(value or "") for value in record.values()))


def _contains_any(text: str, terms: list[str]) -> bool:
    normalized_terms = [_match_text(term) for term in terms if str(term).strip()]
    return any(term and term in text for term in normalized_terms)


def _coverage(text: str, terms: list[str], *, floor: float = 0.0) -> float:
    normalized_terms = {_match_text(term) for term in terms if str(term).strip()}
    if not normalized_terms:
        return floor
    matches = sum(1 for term in normalized_terms if term in text)
    if matches == 0:
        return floor
    return min(100.0, max(floor, 34.0 + matches * 13.0))


def _weighted(components: dict[str, float], weights: dict[str, Any]) -> float:
    parsed = {key: float(value) for key, value in weights.items()}
    total = sum(parsed.values())
    if total <= 0:
        return 0.0
    value = sum(parsed.get(key, 0.0) * components.get(key, 0.0) for key in parsed)
    return round(value / total, 1)


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
        "tracking",
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


def canonical_key(record: dict[str, Any]) -> str:
    url = normalize_url(str(record.get("Source URL") or record.get("Apply URL") or ""))
    if url:
        return f"url:{url}"
    identity = "|".join(
        _normalized(record.get(field))
        for field in ("Company", "Opportunity", "Country", "City")
    )
    if not identity.replace("|", ""):
        return ""
    return "identity:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def _is_individual_url(url: str, patterns: list[str]) -> bool:
    normalized = normalize_url(url)
    return bool(normalized) and not _contains_any(_match_text(normalized), patterns)


def _freshness_score(value: Any) -> float:
    if value is None or value == "":
        return 45.0
    if isinstance(value, (int, float)):
        days = float(value)
    else:
        raw = str(value).strip()
        match = re.search(r"\d+(?:\.\d+)?", raw)
        if match and len(raw) < 20:
            days = float(match.group())
        else:
            try:
                posted = datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
                days = float((date.today() - posted).days)
            except ValueError:
                return 45.0
    if days <= 3:
        return 100.0
    if days <= 7:
        return 90.0
    if days <= 14:
        return 76.0
    if days <= 30:
        return 58.0
    if days <= 60:
        return 32.0
    return 10.0


def _authorization_score(record: dict[str, Any], profile: dict[str, Any]) -> tuple[float, bool, str | None]:
    authorization = _match_text(record.get("Work Authorization"))
    sponsorship = _match_text(record.get("Visa Sponsorship"))
    unknown_values = {"", "unknown", "not stated", "n a", "na", "not applicable"}
    if authorization in unknown_values:
        authorization = ""
    if sponsorship in unknown_values:
        sponsorship = ""

    candidate_eligible = _normalized(record.get("Candidate Eligible")) in {
        "yes",
        "true",
        "eligible",
        "1",
    }
    sponsorship_terms = profile.get("hard_gates", {}).get("work_authorization", {}).get(
        "sponsorship_positive_values", []
    )
    sponsorship_positive = _contains_any(sponsorship, [str(term) for term in sponsorship_terms])

    local_only = _contains_any(
        authorization,
        [
            "local only",
            "citizen only",
            "permanent resident only",
            "existing work rights required",
            "no sponsorship",
        ],
    )
    if candidate_eligible:
        return 100.0, False, None
    if sponsorship_positive:
        return 90.0, False, None
    if local_only:
        return 0.0, True, "candidate lacks required local work authorization and sponsorship is unavailable"
    if not authorization and not sponsorship:
        return 45.0, False, "work authorization and sponsorship are unverified"
    return 55.0, False, "work authorization requires manual verification"


def score_bpo(record: dict[str, Any], profile: dict[str, Any], live: bool | None) -> BpoScoreResult:
    text = _all_text(record)
    hard_config = profile.get("hard_gates", {})
    thresholds = profile.get("thresholds", {})
    weights = profile.get("weights", {})
    candidate = profile.get("candidate", {})
    reasons: list[str] = []
    hard_gate = False

    reject_terms = [str(term) for term in hard_config.get("reject_terms", [])]
    matched_rejects = [term for term in reject_terms if _match_text(term) in text]
    if matched_rejects:
        hard_gate = True
        reasons.append(f"hard gate terms: {', '.join(matched_rejects[:3])}")

    vacancy_status = _normalized(record.get("Vacancy Status") or record.get("Application Status"))
    reject_statuses = {_normalized(value) for value in hard_config.get("reject_statuses", [])}
    if vacancy_status in reject_statuses:
        hard_gate = True
        reasons.append(f"vacancy status is {vacancy_status}")
    if live is False:
        hard_gate = True
        reasons.append("vacancy URL appears closed")

    source_url = str(record.get("Source URL") or record.get("Apply URL") or "")
    search_patterns = [str(term) for term in hard_config.get("non_individual_url_patterns", [])]
    individual_url = _is_individual_url(source_url, search_patterns)
    if not individual_url:
        reasons.append("individual vacancy URL is not verified")

    authorization, authorization_gate, authorization_reason = _authorization_score(record, profile)
    if authorization_gate:
        hard_gate = True
    if authorization_reason:
        reasons.append(authorization_reason)

    korean_requirement = _match_text(record.get("Korean Requirement"))
    korean_value = 100.0 if _contains_any(korean_requirement, ["required", "native", "fluent"]) else 72.0
    if _contains_any(korean_requirement, ["preferred", "advantage", "plus"]):
        korean_value = 86.0
    if _contains_any(korean_requirement, ["not required", "none"]):
        korean_value = 35.0

    candidate_domains = [str(value) for value in candidate.get("domains", [])]
    agoda_domain_match = _coverage(
        text,
        candidate_domains
        + [
            "travel",
            "hotel",
            "flight",
            "booking",
            "reservation",
            "refund",
            "reissue",
            "OTA",
            "GDS",
        ],
        floor=22.0,
    )
    operations_match = _coverage(
        text,
        [
            "customer operations",
            "service operations",
            "case management",
            "queue management",
            "SLA",
            "KPI",
            "customer support",
            "partner support",
            "vendor operations",
            "real time",
            "workforce management",
        ],
        floor=28.0,
    )
    escalation_qa_training = _coverage(
        text,
        [
            "escalation",
            "quality assurance",
            "QA",
            "SME",
            "floor support",
            "training",
            "coaching",
            "mentor",
            "audit",
        ],
        floor=25.0,
    )

    seniority = _match_text(record.get("Seniority"))
    title_text = _match_text(record.get("Opportunity"))
    if _contains_any(seniority + " " + title_text, ["senior", "specialist", "analyst", "SME", "lead"]):
        seniority_match = 88.0
    elif _contains_any(seniority + " " + title_text, ["manager", "head", "director"]):
        seniority_match = 48.0
        reasons.append("role may be above current verified management level")
    else:
        seniority_match = 68.0

    tool_process_match = _coverage(
        text,
        ["CRM", "ticketing", "Salesforce", "Zendesk", "Excel", "GDS", "SOP", "knowledge base"],
        floor=45.0,
    )

    career_transfer = _weighted(
        {
            "agoda_domain_match": agoda_domain_match,
            "operations_match": operations_match,
            "escalation_qa_training": escalation_qa_training,
            "korean_language_value": korean_value,
            "seniority_match": seniority_match,
            "tool_process_match": tool_process_match,
        },
        weights.get("career_transfer", {}),
    )

    experience_requirement = _match_text(record.get("Experience Requirement"))
    required_years_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:\+\s*)?years?", experience_requirement)
    candidate_years = float(candidate.get("total_bpo_years", 0) or 0)
    if required_years_match:
        required_years = float(required_years_match.group(1))
        if candidate_years + 0.25 >= required_years:
            experience_score = 95.0
        elif required_years - candidate_years <= 1.0:
            experience_score = 60.0
            reasons.append("experience requirement is slightly above verified tenure")
        else:
            experience_score = 20.0
            reasons.append("experience requirement materially exceeds verified tenure")
    else:
        experience_score = 62.0

    work_mode = _match_text(record.get("Work Mode"))
    location_score = 75.0 if work_mode or record.get("Country") or record.get("City") else 45.0
    if _contains_any(work_mode, ["remote", "hybrid"]):
        location_score = 88.0

    salary_text = _match_text(record.get("Salary"))
    contract_text = _match_text(record.get("Employment Type"))
    salary_contract = 75.0 if salary_text and contract_text else (58.0 if salary_text or contract_text else 35.0)

    evidence_text = str(record.get("Evidence Text") or record.get("Research Notes") or "")
    evidence_quality = min(100.0, 25.0 + min(len(evidence_text), 900) / 12.0)
    freshness = _freshness_score(record.get("Freshness Days") or record.get("Posted Date"))

    hiring_reality = _weighted(
        {
            "vacancy_live": 100.0 if live is True else (45.0 if live is None else 0.0),
            "individual_url": 100.0 if individual_url else 0.0,
            "work_authorization": authorization,
            "experience_requirement": experience_score,
            "location_and_work_mode": location_score,
            "salary_and_contract": salary_contract,
            "evidence_quality": evidence_quality,
        },
        weights.get("hiring_reality", {}),
    )

    progression = _coverage(
        text,
        ["senior", "specialist", "analyst", "QA", "trainer", "SME", "workforce", "operations"],
        floor=48.0,
    )
    compensation = 72.0 if salary_text else 45.0
    brand_value = 78.0 if record.get("Company") else 40.0
    transferable_scope = _coverage(
        text,
        ["operations", "travel", "customer", "partner", "quality", "training", "analytics"],
        floor=45.0,
    )
    stability_text = _match_text(record.get("Employment Type"))
    stability = 82.0 if _contains_any(stability_text, ["permanent", "full time"]) else 58.0
    if _contains_any(stability_text, ["temporary", "contract", "casual"]):
        stability = 48.0

    strategic_value = _weighted(
        {
            "career_progression": progression,
            "compensation": compensation,
            "brand_value": brand_value,
            "transferable_scope": transferable_scope,
            "stability": stability,
        },
        weights.get("strategic_value", {}),
    )

    final_priority = round(0.45 * career_transfer + 0.35 * hiring_reality + 0.20 * strategic_value, 1)
    apply_now = float(thresholds.get("apply_now", 78))
    priority_recheck = float(thresholds.get("priority_recheck", 64))
    min_reality = float(thresholds.get("minimum_hiring_reality", 55))
    min_evidence = float(thresholds.get("minimum_evidence", 45))

    if hard_gate:
        fit = "Reject"
        verdict = "DO NOT APPLY"
    elif live is not True or not individual_url or evidence_quality < min_evidence:
        fit = "C"
        verdict = "RESEARCH"
    elif final_priority >= apply_now and hiring_reality >= min_reality:
        fit = "A"
        verdict = "APPLY NOW"
    elif final_priority >= priority_recheck:
        fit = "B"
        verdict = "VERIFY THEN APPLY"
    else:
        fit = "C"
        verdict = "HOLD"

    if not reasons:
        reasons.append("passed deterministic BPO checks")

    return BpoScoreResult(
        career_transfer=career_transfer,
        hiring_reality=hiring_reality,
        strategic_value=strategic_value,
        final_priority=final_priority,
        fit=fit,
        verdict=verdict,
        hard_gate=hard_gate,
        canonical_key=canonical_key(record),
        reasons=reasons,
    )
