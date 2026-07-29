from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping

import requests

from .notion import DEFAULT_NOTION_VERSION, NotionClient, normalize_notion_id
from .properties import plain_text
from .scoring import normalize_url


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "ready", "__yes__"}


def candidate_identity(candidate: Mapping[str, Any]) -> str:
    canonical = str(candidate.get("duplicate_key") or "").strip()
    if canonical:
        return f"canonical:{canonical.lower()}"
    source_job_id = str(candidate.get("source_job_id") or "").strip()
    if source_job_id:
        return f"source:{source_job_id.lower()}"
    normalized = normalize_url(str(candidate.get("canonical_url") or ""))
    if normalized:
        return f"url:{normalized}"
    return ""


def _option_names(definition: Mapping[str, Any], prop_type: str) -> set[str]:
    config = definition.get(prop_type) or {}
    return {
        str(item.get("name"))
        for item in config.get("options", [])
        if item.get("name")
    }


def _encode(definition: Mapping[str, Any], value: Any) -> dict[str, Any] | None:
    prop_type = str(definition.get("type") or "")
    if prop_type in {"title", "rich_text"}:
        text = str(value or "")[:2000]
        return {prop_type: [] if not text else [{"type": "text", "text": {"content": text}}]}
    if prop_type == "url":
        return {"url": str(value) if value else None}
    if prop_type == "number":
        if value in (None, ""):
            return {"number": None}
        return {"number": round(float(value), 1)}
    if prop_type == "checkbox":
        return {"checkbox": _truthy(value)}
    if prop_type == "date":
        return {"date": None if not value else {"start": str(value)}}
    if prop_type in {"select", "status"}:
        name = str(value or "")
        if not name:
            return {prop_type: None}
        options = _option_names(definition, prop_type)
        if options and name not in options:
            return None
        return {prop_type: {"name": name}}
    return None


def _put(
    payload: dict[str, Any],
    schema: Mapping[str, Mapping[str, Any]],
    aliases: tuple[str, ...],
    value: Any,
) -> bool:
    for name in aliases:
        definition = schema.get(name)
        if not definition:
            continue
        encoded = _encode(definition, value)
        if encoded is None:
            return False
        payload[name] = encoded
        return True
    return False


def _candidate_payload(
    schema: Mapping[str, Mapping[str, Any]], candidate: Mapping[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    payload: dict[str, Any] = {}
    skipped: list[str] = []
    title_name = next(
        (name for name, definition in schema.items() if definition.get("type") == "title"),
        None,
    )
    if not title_name:
        return {}, ["missing title property"]
    encoded_title = _encode(schema[title_name], candidate.get("opportunity"))
    if encoded_title is None:
        return {}, ["title encoding failed"]
    payload[title_name] = encoded_title

    mappings: list[tuple[tuple[str, ...], str]] = [
        (("Company",), "company"),
        (("Location", "Region"), "location"),
        (("Department", "Role Family"), "role_family"),
        (("Apply URL", "Job URL", "Official URL", "Canonical URL"), "canonical_url"),
        (("Audit Status",), "audit_status"),
        (("Evidence Grade",), "evidence_grade"),
        (("CCSTM",), "ccstm"),
        (("HR Score",), "hr"),
        (("Reality Score",), "reality"),
        (("Fit",), "fit"),
        (("Second Visa", "WHV/88 Days"), "second_visa"),
        (("Car/Licence",), "car_licence"),
        (("Accommodation",), "accommodation"),
        (("Freshness Days", "Freshness"), "freshness_days"),
        (("Source Job ID",), "source_job_id"),
        (("Canonical Key", "Duplicate Key"), "duplicate_key"),
        (("Operational Decision",), "decision"),
        (("Apply Status", "Application Status"), "apply_status"),
        (("CV Ready",), "cv_ready"),
        (("CV Filename",), "cv_filename"),
        (("Final Recommendation", "Reality Note"), "reasons"),
        (("RAG Evidence", "Evidence Text"), "evidence_text"),
        (("V4 Run ID", "Batch ID"), "run_id"),
        (("Last Verified", "Last Checked"), "last_verified"),
    ]
    for aliases, key in mappings:
        value = candidate.get(key)
        if value in (None, ""):
            continue
        if not _put(payload, schema, aliases, value):
            if any(alias in schema for alias in aliases):
                skipped.append(f"unsupported option/type for {aliases[0]}={value}")
    return payload, skipped


def _existing_identities(
    client: NotionClient,
    data_source_id: str,
    schema: Mapping[str, Mapping[str, Any]],
) -> set[str]:
    identities: set[str] = set()
    for page in client.iter_data_source(data_source_id):
        props = page.get("properties") or {}
        for name in ("Canonical Key", "Duplicate Key"):
            canonical = plain_text(props.get(name))
            if canonical:
                identities.add(f"canonical:{canonical.lower()}")
        source_id = plain_text(props.get("Source Job ID"))
        if source_id:
            identities.add(f"source:{source_id.lower()}")
        for name in ("Apply URL", "Job URL", "Official URL", "Canonical URL"):
            url = plain_text(props.get(name))
            normalized = normalize_url(url)
            if normalized:
                identities.add(f"url:{normalized}")
    return identities


def main() -> int:
    token = os.getenv("NOTION_TOKEN", "").strip()
    final_data_source_id = os.getenv("FINAL_NOTION_DATA_SOURCE_ID", "").strip()
    notion_version = os.getenv("NOTION_VERSION", DEFAULT_NOTION_VERSION).strip()
    candidates_path = Path(
        os.getenv("PROMOTION_CANDIDATES_FILE", "output/promotion_candidates.json")
    )
    manifest_path = Path(os.getenv("PROMOTION_MANIFEST", "output/promotion_manifest.json"))
    apply = _truthy(os.getenv("PROMOTE_APPLY", "false"))
    require_cv = _truthy(os.getenv("PROMOTION_REQUIRE_CV_READY", "true"))
    limit_raw = os.getenv("PROMOTE_MAX_ROWS", "").strip()
    limit = int(limit_raw) if limit_raw else None

    if not token or not final_data_source_id:
        print("Missing NOTION_TOKEN or FINAL_NOTION_DATA_SOURCE_ID", file=sys.stderr)
        return 2
    if not candidates_path.exists():
        _atomic_json(manifest_path, {"status": "completed", "created": 0, "rows": []})
        print("No promotion candidate file; nothing to promote")
        return 0
    try:
        loaded = json.loads(candidates_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Invalid candidate file: {exc}", file=sys.stderr)
        return 2
    candidates = [row for row in loaded if isinstance(row, dict)] if isinstance(loaded, list) else []
    if limit is not None:
        candidates = candidates[: max(limit, 0)]

    try:
        client = NotionClient(token, notion_version=notion_version)
        final_id = normalize_notion_id(final_data_source_id)
        schema = client.data_source_properties(final_id)
        existing = _existing_identities(client, final_id, schema)
    except (ValueError, RuntimeError, requests.RequestException) as exc:
        print(f"Final DB preflight failed: {exc}", file=sys.stderr)
        return 2

    manifest: list[dict[str, Any]] = []
    failures = 0
    created = 0
    for candidate in candidates:
        identity = candidate_identity(candidate)
        title = str(candidate.get("opportunity") or "")
        if not identity:
            manifest.append({"opportunity": title, "status": "SKIPPED_NO_IDENTITY"})
            continue
        if identity in existing:
            manifest.append({"opportunity": title, "identity": identity, "status": "SKIPPED_DUPLICATE"})
            continue
        if require_cv and not _truthy(candidate.get("cv_ready")):
            manifest.append({"opportunity": title, "identity": identity, "status": "SKIPPED_CV_NOT_READY"})
            continue
        if not _truthy(candidate.get("promotion_allowed")):
            manifest.append({"opportunity": title, "identity": identity, "status": "SKIPPED_GATE"})
            continue
        payload, skipped = _candidate_payload(schema, candidate)
        if not payload:
            manifest.append(
                {"opportunity": title, "identity": identity, "status": "SKIPPED_SCHEMA", "details": skipped}
            )
            continue
        if not apply:
            manifest.append(
                {"opportunity": title, "identity": identity, "status": "DRY_RUN", "skipped": skipped}
            )
            existing.add(identity)
            continue
        try:
            page = client._request(
                "POST",
                "/pages",
                json={
                    "parent": {"type": "data_source_id", "data_source_id": final_id},
                    "properties": payload,
                },
            )
            created += 1
            existing.add(identity)
            manifest.append(
                {
                    "opportunity": title,
                    "identity": identity,
                    "status": "CREATED",
                    "page_id": page.get("id"),
                    "url": page.get("url"),
                    "skipped": skipped,
                }
            )
            time.sleep(0.35)
        except (RuntimeError, requests.RequestException) as exc:
            failures += 1
            manifest.append(
                {"opportunity": title, "identity": identity, "status": "FAILED", "error": str(exc)}
            )

    result = {
        "status": "failed" if failures else "completed",
        "apply": apply,
        "candidates": len(candidates),
        "created": created,
        "failures": failures,
        "rows": manifest,
    }
    _atomic_json(manifest_path, result)
    print(json.dumps({key: result[key] for key in ("status", "apply", "candidates", "created", "failures")}, ensure_ascii=False))
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
