from eagle.properties import build_update_payload, plain_text


def test_plain_text_reads_common_notion_types() -> None:
    assert plain_text({"type": "title", "title": [{"plain_text": "Job"}]}) == "Job"
    assert plain_text({"type": "select", "select": {"name": "A"}}) == "A"
    assert plain_text({"type": "checkbox", "checkbox": True}) == "true"


def test_update_payload_skips_missing_or_incompatible_fields() -> None:
    schema = {
        "CCSTM": {"type": "number", "number": {}},
        "Fit": {
            "type": "select",
            "select": {"options": [{"name": "A"}, {"name": "B"}]},
        },
    }
    payload, skipped = build_update_payload(
        schema,
        {"CCSTM": 82.33, "Fit": "A", "Unknown": "x"},
    )
    assert payload["CCSTM"] == {"number": 82.3}
    assert payload["Fit"] == {"select": {"name": "A"}}
    assert skipped == ["Unknown"]
