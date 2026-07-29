from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
DEFAULT_QUERY = (
    'newer_than:21d -in:spam -in:trash '
    '{unfortunately unsuccessful "not progressing" "other candidates" '
    '"application outcome" "minimum age" "legally eligible to work"}'
)


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _decode(data: str | None) -> str:
    if not data:
        return ""
    padding = "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(data + padding).decode("utf-8", errors="ignore")
    except (ValueError, UnicodeDecodeError):
        return ""


def _walk_text(part: dict[str, Any]) -> str:
    chunks: list[str] = []
    mime_type = str(part.get("mimeType") or "")
    body = part.get("body") or {}
    if mime_type in {"text/plain", "text/html"}:
        chunks.append(_decode(body.get("data")))
    for child in part.get("parts") or []:
        if isinstance(child, dict):
            chunks.append(_walk_text(child))
    return "\n".join(chunk for chunk in chunks if chunk)


def _header(payload: dict[str, Any], name: str) -> str:
    wanted = name.lower()
    for item in payload.get("headers") or []:
        if str(item.get("name", "")).lower() == wanted:
            return str(item.get("value") or "")
    return ""


def _clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"&(?:nbsp|amp|lt|gt|quot);", " ", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip()


def classify_outcome(subject: str, body: str) -> tuple[str, str, str]:
    text = _clean_text(f"{subject} {body}").lower()
    if any(
        phrase in text
        for phrase in (
            "not currently legally eligible to work",
            "legally eligible to work in this country",
            "due to immigration restrictions",
            "work rights",
        )
    ):
        return "R01", "AUTO_FILTER", "work-rights screening"
    if any(
        phrase in text
        for phrase in (
            "minimum age requirement",
            "do not meet the minimum age",
            "don't meet the minimum age",
        )
    ):
        return "R03", "AUTO_FILTER", "age or date-of-birth screening"
    if "interview" in text and any(
        phrase in text
        for phrase in (
            "other candidates",
            "another candidate",
            "not be progressing",
            "not progressing",
        )
    ):
        return "R07", "INTERVIEW", "interview-stage rejection"
    if any(
        phrase in text
        for phrase in (
            "position has been filled",
            "role has been filled",
            "vacancy has closed",
            "job has closed",
        )
    ):
        return "R09", "CLOSED", "vacancy closed"
    if any(
        phrase in text
        for phrase in (
            "not be progressing",
            "not progressing",
            "unsuccessful",
            "unfortunately",
            "other candidates",
            "another candidate",
            "application outcome",
            "thank you for your interest",
        )
    ):
        return "R05", "ATS_OR_HUMAN_REVIEW", "generic rejection"
    return "R10", "UNKNOWN", "unclassified outcome"


def _refresh_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    response = requests.post(
        TOKEN_URL,
        timeout=20,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    response.raise_for_status()
    token = str(response.json().get("access_token") or "")
    if not token:
        raise RuntimeError("Google OAuth response did not include an access token")
    return token


def _request(token: str, path: str, **kwargs: Any) -> dict[str, Any]:
    response = requests.get(
        f"{GMAIL_API}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=25,
        **kwargs,
    )
    response.raise_for_status()
    return response.json()


def collect_outcomes(
    *, token: str, query: str, max_messages: int, seen: set[str]
) -> tuple[list[dict[str, Any]], set[str]]:
    listing = _request(
        token,
        "/messages",
        params={"q": query, "maxResults": max(1, min(max_messages, 100))},
    )
    outcomes: list[dict[str, Any]] = []
    updated_seen = set(seen)
    for item in listing.get("messages") or []:
        message_id = str(item.get("id") or "")
        if not message_id:
            continue
        digest = hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:20]
        if digest in updated_seen:
            continue
        message = _request(token, f"/messages/{message_id}", params={"format": "full"})
        payload = message.get("payload") or {}
        subject = _header(payload, "Subject")
        body = _walk_text(payload) or str(message.get("snippet") or "")
        code, stage, reason = classify_outcome(subject, body)
        outcomes.append(
            {
                "message_hash": digest,
                "received_epoch_ms": int(message.get("internalDate") or 0),
                "subject": _clean_text(subject)[:240],
                "outcome_code": code,
                "stage": stage,
                "reason": reason,
            }
        )
        updated_seen.add(digest)
    outcomes.sort(key=lambda row: row["received_epoch_ms"], reverse=True)
    return outcomes, updated_seen


def main() -> int:
    output_path = Path(os.getenv("GMAIL_FEEDBACK_OUTPUT", "output/gmail_outcomes.json"))
    state_path = Path(os.getenv("GMAIL_FEEDBACK_STATE", "state/gmail_feedback_state.json"))
    client_id = os.getenv("GMAIL_CLIENT_ID", "").strip()
    client_secret = os.getenv("GMAIL_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("GMAIL_REFRESH_TOKEN", "").strip()
    query = os.getenv("GMAIL_QUERY", DEFAULT_QUERY).strip() or DEFAULT_QUERY
    max_messages = int(os.getenv("GMAIL_MAX_MESSAGES", "50"))

    previous: dict[str, Any] = {}
    if state_path.exists():
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                previous = loaded
        except (OSError, json.JSONDecodeError):
            previous = {}
    seen = {str(value) for value in previous.get("seen", [])}

    if not all((client_id, client_secret, refresh_token)):
        result = {
            "status": "skipped",
            "reason": "Gmail OAuth secrets are not configured",
            "query": query,
            "outcomes": [],
            "counts": {},
        }
        _atomic_json(output_path, result)
        print(json.dumps(result, ensure_ascii=False))
        return 0

    try:
        token = _refresh_token(client_id, client_secret, refresh_token)
        outcomes, updated_seen = collect_outcomes(
            token=token,
            query=query,
            max_messages=max_messages,
            seen=seen,
        )
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        result = {
            "status": "failed",
            "error": str(exc),
            "query": query,
            "outcomes": [],
            "counts": {},
        }
        _atomic_json(output_path, result)
        print(f"Gmail feedback failed: {exc}", file=sys.stderr)
        return 2

    counts = Counter(row["outcome_code"] for row in outcomes)
    result = {
        "status": "completed",
        "query": query,
        "outcomes": outcomes,
        "counts": dict(sorted(counts.items())),
    }
    _atomic_json(output_path, result)
    _atomic_json(state_path, {"seen": sorted(updated_seen)[-2000:]})
    print(json.dumps({"status": "completed", "new": len(outcomes), "counts": dict(counts)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
