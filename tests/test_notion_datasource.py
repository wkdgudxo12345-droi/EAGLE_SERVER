from typing import Any

import pytest

from eagle.notion import DEFAULT_NOTION_VERSION, NotionClient
from eagle.record import schema_health


DB_ID = "11111111111111111111111111111111"
DS_ID = "22222222222222222222222222222222"
OTHER_DS_ID = "33333333333333333333333333333333"


def test_current_notion_version_is_used() -> None:
    client = NotionClient("secret")
    assert DEFAULT_NOTION_VERSION == "2026-03-11"
    assert client.session.headers["Notion-Version"] == "2026-03-11"


def test_database_with_one_source_resolves_data_source(monkeypatch) -> None:
    client = NotionClient("secret")

    def fake_request(method: str, path: str, **_kwargs: Any) -> dict[str, Any]:
        assert method == "GET"
        assert path == f"/databases/{DB_ID}"
        return {"data_sources": [{"id": DS_ID, "name": "Jobs"}]}

    monkeypatch.setattr(client, "_request", fake_request)
    assert client.resolve_data_source_id(database_id=DB_ID) == DS_ID


def test_multiple_sources_require_explicit_selection(monkeypatch) -> None:
    client = NotionClient("secret")

    def fake_request(method: str, path: str, **_kwargs: Any) -> dict[str, Any]:
        assert method == "GET"
        assert path == f"/databases/{DB_ID}"
        return {
            "data_sources": [
                {"id": DS_ID, "name": "Jobs"},
                {"id": OTHER_DS_ID, "name": "Archive"},
            ]
        }

    monkeypatch.setattr(client, "_request", fake_request)
    with pytest.raises(RuntimeError, match="multiple data sources"):
        client.resolve_data_source_id(database_id=DB_ID)


def test_explicit_data_source_is_validated(monkeypatch) -> None:
    client = NotionClient("secret")
    calls: list[tuple[str, str]] = []

    def fake_request(method: str, path: str, **_kwargs: Any) -> dict[str, Any]:
        calls.append((method, path))
        return {"object": "data_source", "id": DS_ID, "properties": {}}

    monkeypatch.setattr(client, "_request", fake_request)
    assert client.resolve_data_source_id(data_source_id=DS_ID) == DS_ID
    assert calls == [("GET", f"/data_sources/{DS_ID}")]


def test_query_uses_data_source_endpoint_and_page_filter(monkeypatch) -> None:
    client = NotionClient("secret")
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def fake_request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        calls.append((method, path, kwargs))
        return {
            "results": [
                {"object": "page", "id": "page-1", "properties": {}},
                {"object": "data_source", "id": "nested"},
            ],
            "has_more": False,
            "next_cursor": None,
        }

    monkeypatch.setattr(client, "_request", fake_request)
    pages = list(
        client.iter_data_source(
            DS_ID,
            max_rows=10,
            filter_properties=["Opportunity", "Second Visa"],
        )
    )
    assert [page["id"] for page in pages] == ["page-1"]
    method, path, kwargs = calls[0]
    assert method == "POST"
    assert path == f"/data_sources/{DS_ID}/query"
    assert kwargs["json"]["result_type"] == "page"
    assert kwargs["params"] == [
        ("filter_properties[]", "Opportunity"),
        ("filter_properties[]", "Second Visa"),
    ]


def test_schema_health_fails_before_silent_all_hold() -> None:
    schema = {
        "Opportunity": {"type": "title"},
        "Job URL": {"type": "url"},
        "Location": {"type": "rich_text"},
        "Second Visa": {"type": "select"},
    }
    report = schema_health(schema)
    assert report["missing_fatal"] == []
    assert "Car/Licence" in report["missing_promotion"]
    assert "Audit Status" in report["missing_promotion"]
    assert report["ready"] is False
