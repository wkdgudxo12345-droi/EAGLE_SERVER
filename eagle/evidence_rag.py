from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests


@dataclass(frozen=True)
class Evidence:
    id: str
    claim_key: str
    value: str
    text: str
    source_type: str
    source_domain: str
    source_url: str | None = None
    checked_at: str = "1970-01-01"
    authority: float = 0.0
    reality_checked: bool = False
    critical: bool = False


@dataclass
class RagResult:
    verdict: str
    proof_score: int
    provider: str
    retrieved_ids: list[str]
    reasons: list[str] = field(default_factory=list)
    model_output: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _lower(value: Any) -> str:
    return str(value or "").strip().lower()


def _domain(url: str) -> str:
    try:
        return urlsplit(url).netloc.lower() or "unknown"
    except ValueError:
        return "unknown"


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w]+", str(text).lower(), flags=re.UNICODE)


def _embedding(text: str, dimensions: int = 64) -> list[float]:
    vector = [0.0] * dimensions
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % dimensions
        vector[index] += 1.0 if digest[2] & 1 else -1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _cosine(first: list[float], second: list[float]) -> float:
    return sum(left * right for left, right in zip(first, second, strict=True))


def _freshness(checked_at: str) -> float:
    try:
        checked = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=UTC)
        days = max(0.0, (datetime.now(UTC) - checked).total_seconds() / 86_400)
    except ValueError:
        return 0.0
    return max(0.0, 1.0 - days / 365.0)


def load_evidence(path: Path | None) -> list[Evidence]:
    if path is None or not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Evidence file must contain a JSON array")
    return [Evidence(**item) for item in raw]


def row_evidence(
    record: dict[str, Any], *, live: bool | None, individual_url: bool
) -> list[Evidence]:
    url = str(record.get("Canonical URL") or "")
    audit = _lower(record.get("Audit Status"))
    grade = _lower(record.get("Evidence Grade"))
    visa = _lower(record.get("Second Visa"))
    car = _lower(record.get("Car/Licence"))
    accommodation = _lower(record.get("Accommodation"))
    today = datetime.now(UTC).date().isoformat()
    audit_strength = 0.82 if audit == "verified" and grade in {"a", "b"} else 0.35

    if any(term in visa for term in ("likely", "eligible", "verified yes", "yes")):
        visa_value = "yes"
    elif any(term in visa for term in ("no", "unlikely", "ineligible")):
        visa_value = "no"
    else:
        visa_value = "unknown"

    if "required" in car and "not required" not in car:
        mobility_value = "no"
    elif any(term in car for term in ("not required", "no licence", "not stated")):
        mobility_value = "yes"
    elif any(term in accommodation for term in ("provided", "included", "live on site", "yes")):
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
                f"location={record.get('Location', '')}; role={record.get('Role Family', '')}; "
                f"evidence={record.get('Evidence Text', '')}"
            ),
            source_type="notion_audit",
            source_domain="eagle-notion-audit",
            checked_at=today,
            authority=audit_strength,
            reality_checked=audit == "verified" and grade in {"a", "b"},
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
            reality_checked=audit == "verified" and grade in {"a", "b"},
            critical=True,
        ),
        Evidence(
            id="row:audit-quality",
            claim_key="audit_quality",
            value="yes" if audit == "verified" and grade in {"a", "b"} else "unknown",
            text=f"Audit Status={audit}; Evidence Grade={grade}",
            source_type="notion_audit",
            source_domain="eagle-notion-audit",
            checked_at=today,
            authority=audit_strength,
            reality_checked=True,
            critical=True,
        ),
    ]


def retrieve(query: str, evidence: list[Evidence], top_k: int = 12) -> list[Evidence]:
    query_tokens = set(_tokens(query))
    query_vector = _embedding(query)
    scored: list[tuple[float, Evidence]] = []
    for item in evidence:
        item_text = f"{item.claim_key} {item.value} {item.text}"
        tokens = set(_tokens(item_text))
        lexical = len(query_tokens & tokens) / max(1, len(query_tokens))
        semantic = _cosine(query_vector, _embedding(item_text))
        score = (
            0.35 * lexical
            + 0.25 * max(semantic, 0.0)
            + 0.25 * item.authority
            + 0.15 * _freshness(item.checked_at)
        )
        scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    selected = [item for _, item in scored[:top_k]]

    # Critical evidence may not contain the role title, but it must always enter the
    # proof loop.  Retrieval ranking cannot hide a visa or mobility contradiction.
    by_id = {item.id: item for item in selected}
    for item in evidence:
        if item.critical:
            by_id.setdefault(item.id, item)
    return list(by_id.values())


def _deduplicate(evidence: list[Evidence]) -> list[Evidence]:
    best: dict[tuple[str, str, str], Evidence] = {}
    for item in evidence:
        key = (item.source_domain, item.claim_key, item.value)
        if key not in best or best[key].authority < item.authority:
            best[key] = item
    return list(best.values())


def _claim_values(evidence: list[Evidence], claim_key: str) -> set[str]:
    return {
        item.value
        for item in evidence
        if item.claim_key == claim_key and item.reality_checked
    }


def deterministic_proof(evidence: list[Evidence]) -> tuple[str, int, list[str]]:
    evidence = _deduplicate(evidence)
    reasons: list[str] = []
    official_policy = any(
        item.source_type == "official" and item.reality_checked
        for item in evidence
    )
    if not official_policy:
        reasons.append("official specified-work policy evidence is missing")

    required = {
        "vacancy_live": "live vacancy",
        "specified_work_eligibility": "second/third visa eligibility",
        "no_car_execution": "no-car execution",
        "audit_quality": "verified audit quality",
    }
    passed = 0
    contradictions = 0
    for claim_key, label in required.items():
        values = _claim_values(evidence, claim_key)
        if "yes" in values and "no" in values:
            contradictions += 1
            reasons.append(f"contradiction in {label}")
        elif values == {"yes"}:
            passed += 1
        elif "no" in values:
            reasons.append(f"{label} failed")
        else:
            reasons.append(f"{label} is unknown")

    independent_domains = len(
        {item.source_domain for item in evidence if item.reality_checked}
    )
    score = min(100, passed * 18 + min(20, independent_domains * 7) + (12 if official_policy else 0))
    score = max(0, score - contradictions * 30)

    if contradictions:
        return "HOLD", score, reasons
    if official_policy and passed == len(required) and independent_domains >= 2:
        return "PASS", score, reasons or ["critical evidence claims passed"]
    if any("failed" in reason for reason in reasons):
        return "REJECT", score, reasons
    return "HOLD", score, reasons


def _call_openai(query: str, evidence: list[Evidence]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for LLM RAG")
    model = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "input": (
                "You are the Eagle Red Team. Identify contradictions, missing proof, "
                "and unsupported assumptions. Never override deterministic policy.\n"
                f"Query: {query}\nEvidence: {json.dumps([asdict(item) for item in evidence], ensure_ascii=False)}"
            ),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "eagle_red_team",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "recommended_verdict": {
                                "type": "string",
                                "enum": ["PASS", "HOLD", "REJECT"],
                            },
                            "risk_flags": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "summary": {"type": "string"},
                        },
                        "required": ["recommended_verdict", "risk_flags", "summary"],
                        "additionalProperties": False,
                    },
                }
            },
        },
        timeout=60,
    )
    if not response.ok:
        raise RuntimeError(f"OpenAI request failed: {response.status_code} {response.text[:500]}")
    body = response.json()
    return {"model": model, **json.loads(body["output_text"])}


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
        f"Verify current paid specified work, no-car execution and vacancy proof for "
        f"{record.get('Opportunity', '')} at {record.get('Company', '')} "
        f"in {record.get('Location', '')}."
    )
    corpus = load_evidence(evidence_path) + row_evidence(
        record, live=live, individual_url=individual_url
    )
    retrieved = retrieve(query, corpus)
    verdict, score, reasons = deterministic_proof(retrieved)
    model_output: dict[str, Any] | None = None
    provider = "deterministic-hybrid-rag"

    if use_llm or require_llm:
        try:
            model_output = _call_openai(query, retrieved)
            provider = str(model_output.get("model") or "openai-responses")
            model_verdict = str(model_output.get("recommended_verdict") or "HOLD")
            if model_verdict != verdict:
                reasons.append(
                    f"LLM proposed {model_verdict}; deterministic proof retained {verdict}"
                )
            reasons.extend(str(flag) for flag in model_output.get("risk_flags", []))
        except RuntimeError as exc:
            if require_llm:
                raise
            reasons.append(f"LLM RAG unavailable; deterministic fallback used: {exc}")

    return RagResult(
        verdict=verdict,
        proof_score=score,
        provider=provider,
        retrieved_ids=[item.id for item in retrieved],
        reasons=reasons,
        model_output=model_output,
    )
