from __future__ import annotations

import re
import time
from collections.abc import Iterator, Mapping
from typing import Any

import requests

API_BASE = "https://api.notion.com/v1"
DEFAULT_NOTION_VERSION = "2022-06-28"


def normalize_notion_id(value: str) -> str:
    """Return a 32-character Notion UUID from a raw ID or Notion URL."""
    compact = re.sub(r"[^0-9a-fA-F]", "", value or "")
    if len(compact) < 32:
        raise ValueError("NOTION_DATABASE_ID does not contain a valid Notion UUID")
    return compact[-32:].lower()


class NotionClient:
    def __init__(
        self,
        token: str,
        *,
        notion_version: str = DEFAULT_NOTION_VERSION,
        timeout_seconds: int = 30,
        max_retries: int = 5,
    ) -> None:
        if not token:
            raise ValueError("A Notion token is required")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": notion_version,
                "Content-Type": "application/json",
                "User-Agent": "EagleServer/1.1",
            }
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.request(
                    method,
                    f"{API_BASE}{path}",
                    timeout=self.timeout_seconds,
                    **kwargs,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise RuntimeError(f"Notion request failed: {method} {path}") from exc
                time.sleep(min(2**attempt, 20))
                continue

            if response.status_code == 429:
                if attempt >= self.max_retries:
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After", "2")
                try:
                    delay = max(float(retry_after), 0.5)
                except ValueError:
                    delay = 2.0
                time.sleep(delay)
                continue

            if response.status_code >= 500:
                if attempt >= self.max_retries:
                    response.raise_for_status()
                time.sleep(min(2**attempt, 20))
                continue

            if response.status_code >= 400:
                detail = response.text[:1000]
                raise RuntimeError(
                    f"Notion API returned {response.status_code} for {method} {path}: {detail}"
                )
            return response.json() if response.content else {}

        raise RuntimeError(f"Notion request failed: {method} {path}") from last_error

    def get_database(self, database_id: str) -> dict[str, Any]:
        return self._request("GET", f"/databases/{normalize_notion_id(database_id)}")

    def database_properties(self, database_id: str) -> Mapping[str, dict[str, Any]]:
        database = self.get_database(database_id)
        properties = database.get("properties", {})
        return properties if isinstance(properties, dict) else {}

    def iter_database(
        self,
        database_id: str,
        *,
        page_size: int = 100,
        max_rows: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        database_id = normalize_notion_id(database_id)
        cursor: str | None = None
        yielded = 0
        while True:
            payload: dict[str, Any] = {"page_size": min(max(page_size, 1), 100)}
            if cursor:
                payload["start_cursor"] = cursor
            data = self._request("POST", f"/databases/{database_id}/query", json=payload)
            for page in data.get("results", []):
                yield page
                yielded += 1
                if max_rows is not None and yielded >= max_rows:
                    return
            if not data.get("has_more"):
                return
            cursor = data.get("next_cursor")
            if not cursor:
                return

    def update_page(self, page_id: str, properties: Mapping[str, Any]) -> None:
        if not properties:
            return
        self._request("PATCH", f"/pages/{page_id}", json={"properties": dict(properties)})

    def archive_page(self, page_id: str) -> None:
        self._request("PATCH", f"/pages/{page_id}", json={"archived": True})
