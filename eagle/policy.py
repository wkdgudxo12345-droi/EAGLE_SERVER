from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PolicyDecision:
    second_visa_state: str
    proof_gate: str
    red_team_status: str
    final_decision: str
    promotion_allowed: bool
    reasons: list[str] = field(default_factory=list)


def _lower(value: Any) -> str:
    return str(value or "").strip().lower()


def _contains(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)


def _words(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def second_visa_state(record: dict[str, Any]) -> str:
    value = _lower(record.get("Second Visa"))
    words = _words(value)
    if value in {"likely", "eligible", "verified yes", "yes"}:
        return "LIKELY"
    if "likely" in words or ("verified" in words and "yes" in words):
        return "LIKELY"
    if value in {"no", "unlikely", "ineligible"}:
        return "NO"
    if "unlikely" in words or "ineligible" in words:
        return "NO"
    return "UNKNOWN"


def _freshness_days(record: dict[str, Any]) -> float | None:
    value = _lower(record.get("Freshness"))
    if not value:
        return None
    number = ""
    decimal_seen = False
    for char in value:
        if char.isdigit():
            number += char
        elif char == "." and number and not decimal_seen:
            number += char
            decimal_seen = True
        elif number:
            break
    try:
        return float(number) if number else None
    except ValueError:
        return None


def _accommodation_provided(value: str) -> bool:
    if not value or value in {"no", "unknown", "not stated"}:
        return False
    if "not provided" in value or "no accommodation" in value:
        return False
    return _contains(value, ("provided", "included", "live on site", "staff housing"))


def evaluate_policy(
    record: dict[str, Any],
    *,
    live: bool | None,
    individual_url: bool,
    duplicate: bool,
    scoring_hard_gate: bool,
    rag_verdict: str,
) -> PolicyDecision:
    """Apply Eagle's non-negotiable promotion order.

    Scores are advisory. They can never override second/third-year visa evidence,
    mobility, vacancy proof, audit state, evidence quality, or Red Team/RAG HOLD.
    """

    reasons: list[str] = []
    visa = second_visa_state(record)
    car = _lower(record.get("Car/Licence"))
    accommodation = _lower(record.get("Accommodation"))
    audit = _lower(record.get("Audit Status"))
    grade = _lower(record.get("Evidence Grade"))
    verification = _lower(record.get("Verification Level"))
    freshness = _freshness_days(record)

    hard_reject = scoring_hard_gate
    if duplicate:
        hard_reject = True
        reasons.append("duplicate job")
    if visa == "NO":
        hard_reject = True
        reasons.append("second/third visa evidence says no")
    if "required" in car and "not required" not in car:
        hard_reject = True
        reasons.append("car or driver licence required")
    if live is False:
        hard_reject = True
        reasons.append("vacancy appears closed")

    if hard_reject:
        return PolicyDecision(
            second_visa_state=visa,
            proof_gate="REJECT",
            red_team_status="REJECT",
            final_decision="HOLD",
            promotion_allowed=False,
            reasons=reasons or ["deterministic hard gate"],
        )

    holds: list[str] = []
    if visa != "LIKELY":
        holds.append("second/third visa evidence is unknown")
    if live is not True:
        holds.append("live vacancy not confirmed")
    if not individual_url:
        holds.append("individual vacancy URL not confirmed")
    if audit != "verified":
        holds.append("audit status VERIFIED is required")
    if grade not in {"a", "b"}:
        holds.append("evidence grade A/B is required")

    # `Verification Level` exists in some Stage databases but not in the current
    # Final DB. A live URL that passed the individual-URL classifier is the actual
    # runtime proof. When the optional column is present, an explicitly conflicting
    # value still blocks promotion.
    if verification and "individual" not in verification:
        holds.append("verification level conflicts with individual vacancy proof")

    if freshness is None:
        holds.append("freshness is unknown")
    elif freshness > 14:
        holds.append("vacancy is older than 14 days")

    car_explicitly_clear = _contains(car, ("not required", "no licence required"))
    mobility_clear = car_explicitly_clear or _accommodation_provided(accommodation)
    if not mobility_clear:
        holds.append("no-car transport or staff accommodation is unverified")

    if rag_verdict != "PASS":
        holds.append(f"evidence RAG verdict is {rag_verdict}")

    if holds:
        return PolicyDecision(
            second_visa_state=visa,
            proof_gate="HOLD",
            red_team_status="HOLD",
            final_decision="VERIFY THEN APPLY",
            promotion_allowed=False,
            reasons=holds,
        )

    return PolicyDecision(
        second_visa_state=visa,
        proof_gate="PASS",
        red_team_status="PASS",
        final_decision="APPLY NOW",
        promotion_allowed=True,
        reasons=["all visa-first evidence gates passed"],
    )
