from __future__ import annotations

import re
import time
from collections.abc import Iterator, Mapping
from typing import Any

import requests

API_BASE = "https://api.notion.com/v1"
DEFAULT_NOTION_VERSION = "2026-03-11"


def normalize_notion_id(value: str) -> str:
    """Return a 32-character Notion UUID from a raw ID or Notion URL."""
    compact = re.sub(r"[^0-9a-fA-F]", "", value or "")
    if len(compact) < 32:
        raise ValueError("Notion ID does not contain a valid 32-character UUID")
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
        self.notion_version = notion_version
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": notion_version,
                "Content-Type": "application/json",
                "User-Agent": "EagleServer/4.0",
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
                    raise RuntimeError(
                        f"Notion request failed: {method} {path}"
                    ) from exc
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
                detail = response.text[:1500]
                raise RuntimeError(
                    f"Notion API returned {response.status_code} for "
                    f"{method} {path}: {detail}"
                )
            return response.json() if response.content else {}

        raise RuntimeError(f"Notion request failed: {method} {path}") from last_error

    def get_database(self, database_id: str) -> dict[str, Any]:
        return self._request(
            "GET", f"/databases/{normalize_notion_id(database_id)}"
        )

    def get_data_source(self, data_source_id: str) -> dict[str, Any]:
        return self._request(
            "GET", f"/data_sources/{normalize_notion_id(data_source_id)}"
        )

    def resolve_data_source_id(
        self,
        *,
        database_id: str | None = None,
        data_source_id: str | None = None,
    ) -> str:
        """Resolve the exact data source used for schema and row operations.

        Since Notion API 2025-09-03, a database is a container and data source IDs
        are required for schema/query operations. An explicit data source ID is
        preferred. If only a database ID is supplied, Eagle discovers its single
        data source and refuses to guess when multiple sources exist.
        """

        if data_source_id and data_source_id.strip():
            resolved = normalize_notion_id(data_source_id)
            self.get_data_source(resolved)
            return resolved

        if not database_id or not database_id.strip():
            raise ValueError(
                "Provide NOTION_DATA_SOURCE_ID or NOTION_DATABASE_ID"
            )

        normalized = normalize_notion_id(database_id)
        try:
            database = self.get_database(normalized)
        except RuntimeError as database_error:
            # Backward-compatible convenience: if an operator accidentally placed
            # a data source ID in NOTION_DATABASE_ID, validate and use it rather
            # than silently falling back to the removed database query endpoint.
            try:
                self.get_data_source(normalized)
            except RuntimeError:
                raise database_error
            return normalized

        raw_sources = database.get("data_sources", [])
        sources = [
            item
            for item in raw_sources
            if isinstance(item, dict) and item.get("id")
        ]
        if len(sources) == 1:
            return normalize_notion_id(str(sources[0]["id"]))
        if not sources:
            raise RuntimeError(
                "Notion database returned no data_sources. Share the source with "
                "the integration or set NOTION_DATA_SOURCE_ID explicitly."
            )
        source_list = ", ".join(
            f"{item.get('name', 'unnamed')}={item['id']}" for item in sources
        )
        raise RuntimeError(
            "Notion database contains multiple data sources; Eagle will not "
            f"guess. Set NOTION_DATA_SOURCE_ID to one of: {source_list}"
        )

    def data_source_properties(
        self, data_source_id: str
    ) -> Mapping[str, dict[str, Any]]:
        data_source = self.get_data_source(data_source_id)
        properties = data_source.get("properties", {})
        return properties if isinstance(properties, dict) else {}

    def iter_data_source(
        self,
        data_source_id: str,
        *,
        page_size: int = 100,
        max_rows: int | None = None,
        filter_properties: list[str] | None = None,
    ) -> Iterator[dict[str, Any]]:
        data_source_id = normalize_notion_id(data_source_id)
        cursor: str | None = None
        yielded = 0
        params: list[tuple[str, str]] = []
        for name in filter_properties or []:
            params.append(("filter_properties[]", name))

        while True:
            payload: dict[str, Any] = {
                "page_size": min(max(page_size, 1), 100),
                "result_type": "page",
            }
            if cursor:
                payload["start_cursor"] = cursor
            data = self._request(
                "POST",
                f"/data_sources/{data_source_id}/query",
                params=params or None,
                json=payload,
            )
            for page in data.get("results", []):
                if not isinstance(page, dict) or page.get("object") != "page":
                    continue
                yield page
                yielded += 1
                if max_rows is not None and yielded >= max_rows:
                    return
            if not data.get("has_more"):
                return
            cursor = data.get("next_cursor")
            if not cursor:
                return

    # Compatibility wrappers for the original recovery branch. New code should
    # resolve the data source once and use data_source_properties/iter_data_source.
    def database_properties(
        self, database_id: str
    ) -> Mapping[str, dict[str, Any]]:
        data_source_id = self.resolve_data_source_id(database_id=database_id)
        return self.data_source_properties(data_source_id)

    def iter_database(
        self,
        database_id: str,
        *,
        page_size: int = 100,
        max_rows: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        data_source_id = self.resolve_data_source_id(database_id=database_id)
        return self.iter_data_source(
            data_source_id, page_size=page_size, max_rows=max_rows
        )

    def update_page(self, page_id: str, properties: Mapping[str, Any]) -> None:
        if not properties:
            return
        self._request(
            "PATCH", f"/pages/{page_id}", json={"properties": dict(properties)}
        )

    def archive_page(self, page_id: str) -> None:
        self._request("PATCH", f"/pages/{page_id}", json={"in_trash": True})
