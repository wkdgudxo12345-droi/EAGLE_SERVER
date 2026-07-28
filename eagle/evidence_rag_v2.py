from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

from . import evidence_rag as base
from .policy import second_visa_state

Evidence = base.Evidence
RagResult = base.RagResult


def _lower(value: Any) -> str:
    return str(value or "").strip().lower()


def _domain(url: str) -> str:
    try:
        return urlsplit(url).netloc.lower() or "unknown"
    except ValueError:
        return "unknown"


def _accommodation_provided(value: str) -> bool:
    value = _lower(value)
    if not value or value in {"no", "unknown", "not stated"}:
        return False
    if "not provided" in value or "no accommodation" in value:
        return False
    return any(
        term in value
        for term in ("provided", "included", "live on site", "staff housing")
    )


def row_evidence(
    record: dict[str, Any], *, live: bool | None, individual_url: bool
) -> list[Evidence]:
    url = str(record.get("Canonical URL") or "")
    audit = _lower(record.get("Audit Status"))
    grade = _lower(record.get("Evidence Grade"))
    car = _lower(record.get("Car/Licence"))
    accommodation = _lower(record.get("Accommodation"))
    today = datetime.now(UTC).date().isoformat()
    audit_verified = audit == "verified" and grade in {"a", "b"}
    audit_strength = 0.82 if audit_verified else 0.35

    visa_state = second_visa_state(record)
    visa_value = {
        "LIKELY": "yes",
        "NO": "no",
        "UNKNOWN": "unknown",
    }[visa_state]

    if "required" in car and "not required" not in car:
        mobility_value = "no"
    elif "not required" in car or "no licence required" in car:
        mobility_value = "yes"
    elif _accommodation_provided(accommodation):
        mobility_value = "yes"
    else:
        mobility_value = "unknown"

    return [
        Evidence(
            id="row:vacancy-live",
            claim_key="vacancy_live",
            value="yes" if live is True else ("no" if live is False else "unknown"),
            text=f"Vacancy URL check for {url}",
            source_type="employer_or_board",
            source_domain=_domain(url),
            source_url=url or None,
            checked_at=today,
            authority=0.9 if live is True and individual_url else 0.35,
            reality_checked=live is not None and individual_url,
            critical=True,
        ),
        Evidence(
            id="row:visa-audit",
            claim_key="specified_work_eligibility",
            value=visa_value,
            text=(
                f"Notion audit: Second Visa={record.get('Second Visa', '')}; "
                f"location={record.get('Location', '')}; "
                f"role={record.get('Role Family', '')}; "
                f"evidence={record.get('Evidence Text', '')}"
            ),
            source_type="notion_audit",
            source_domain="eagle-notion-audit",
            checked_at=today,
            authority=audit_strength,
            reality_checked=audit_verified,
            critical=True,
        ),
        Evidence(
            id="row:mobility",
            claim_key="no_car_execution",
            value=mobility_value,
            text=(
                f"Car/Licence={record.get('Car/Licence', '')}; "
                f"Accommodation={record.get('Accommodation', '')}"
            ),
            source_type="notion_audit",
            source_domain="eagle-notion-audit",
            checked_at=today,
            authority=audit_strength,
            reality_checked=audit_verified,
            critical=True,
        ),
        Evidence(
            id="row:audit-quality",
            claim_key="audit_quality",
            value="yes" if audit_verified else "unknown",
            text=f"Audit Status={audit}; Evidence Grade={grade}",
            source_type="notion_audit",
            source_domain="eagle-notion-audit",
            checked_at=today,
            authority=audit_strength,
            reality_checked=True,
            critical=True,
        ),
    ]


def run_evidence_rag(
    record: dict[str, Any],
    *,
    live: bool | None,
    individual_url: bool,
    evidence_path: Path | None,
    use_llm: bool = False,
    require_llm: bool = False,
) -> RagResult:
    query = (
        "Verify current paid specified work, no-car execution and vacancy proof "
        f"for {record.get('Opportunity', '')} at {record.get('Company', '')} "
        f"in {record.get('Location', '')}."
    )
    corpus = base.load_evidence(evidence_path) + row_evidence(
        record, live=live, individual_url=individual_url
    )
    retrieved = base.retrieve(query, corpus)
    verdict, score, reasons = base.deterministic_proof(retrieved)
    model_output: dict[str, Any] | None = None
    provider = "deterministic-hybrid-rag-v2"

    if use_llm or require_llm:
        try:
            model_output = base._call_openai(query, retrieved)
            provider = str(model_output.get("model") or "openai-responses")
            model_verdict = str(
                model_output.get("recommended_verdict") or "HOLD"
            )
            if model_verdict != verdict:
                reasons.append(
                    f"LLM proposed {model_verdict}; deterministic proof retained {verdict}"
                )
            reasons.extend(
                str(flag) for flag in model_output.get("risk_flags", [])
            )
        except RuntimeError as exc:
            if require_llm:
                raise
            reasons.append(
                f"LLM RAG unavailable; deterministic fallback used: {exc}"
            )

    return RagResult(
        verdict=verdict,
        proof_score=score,
        provider=provider,
        retrieved_ids=[item.id for item in retrieved],
        reasons=reasons,
        model_output=model_output,
    )
