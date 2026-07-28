from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def plain_text(prop: Mapping[str, Any] | None) -> str:
    if not prop:
        return ""
    prop_type = prop.get("type")
    if prop_type == "title":
        values = prop.get("title", [])
    elif prop_type == "rich_text":
        values = prop.get("rich_text", [])
    elif prop_type == "url":
        return str(prop.get("url") or "")
    elif prop_type == "select":
        return str((prop.get("select") or {}).get("name", ""))
    elif prop_type == "status":
        return str((prop.get("status") or {}).get("name", ""))
    elif prop_type == "multi_select":
        return ", ".join(str(item.get("name", "")) for item in prop.get("multi_select", []))
    elif prop_type == "number":
        value = prop.get("number")
        return "" if value is None else str(value)
    elif prop_type == "checkbox":
        return "true" if prop.get("checkbox") else "false"
    elif prop_type == "date":
        date = prop.get("date") or {}
        return str(date.get("start") or "")
    elif prop_type == "formula":
        formula = prop.get("formula") or {}
        value_type = formula.get("type")
        value = formula.get(value_type) if value_type else None
        return "" if value is None else str(value)
    else:
        return ""
    return "".join(str(value.get("plain_text", "")) for value in values)


def _option_names(definition: Mapping[str, Any], prop_type: str) -> set[str]:
    config = definition.get(prop_type) or {}
    return {str(item.get("name")) for item in config.get("options", []) if item.get("name")}


def encode_property(definition: Mapping[str, Any], value: Any) -> dict[str, Any] | None:
    prop_type = definition.get("type")
    if prop_type == "number":
        return {"number": None if value is None else round(float(value), 1)}
    if prop_type in {"rich_text", "title"}:
        key = str(prop_type)
        text = str(value or "")[:2000]
        return {key: [] if not text else [{"type": "text", "text": {"content": text}}]}
    if prop_type == "checkbox":
        return {"checkbox": bool(value)}
    if prop_type == "url":
        return {"url": str(value) if value else None}
    if prop_type in {"select", "status"}:
        name = str(value or "")
        if not name:
            return {str(prop_type): None}
        options = _option_names(definition, str(prop_type))
        if options and name not in options:
            return None
        return {str(prop_type): {"name": name}}
    return None


def build_update_payload(
    schema: Mapping[str, Mapping[str, Any]], values: Mapping[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    payload: dict[str, Any] = {}
    skipped: list[str] = []
    for name, value in values.items():
        definition = schema.get(name)
        if not definition:
            skipped.append(name)
            continue
        encoded = encode_property(definition, value)
        if encoded is None:
            skipped.append(name)
            continue
        payload[name] = encoded
    return payload, skipped
