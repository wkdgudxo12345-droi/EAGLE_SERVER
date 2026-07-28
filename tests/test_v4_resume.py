from pathlib import Path

from eagle.v4_main import (
    _append_jsonl,
    _checkpoint,
    _load_json,
    _load_jsonl,
    _run_fingerprint,
    _summary,
)


def test_jsonl_resume_ignores_partial_last_line(tmp_path: Path) -> None:
    path = tmp_path / "report.jsonl"
    _append_jsonl(path, {"id": "one", "decision": "HOLD", "rag_provider": "det"})
    _append_jsonl(path, {"id": "two", "decision": "APPLY NOW", "rag_provider": "det"})
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"id":"partial"')

    rows = _load_jsonl(path)
    assert [row["id"] for row in rows] == ["one", "two"]


def test_checkpoint_is_atomic_and_loadable(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    _checkpoint(
        path,
        fingerprint="abc",
        run_key="run-1",
        completed=7,
        total_hint=10,
        last_page_id="page-7",
        status="paused",
    )
    value = _load_json(path)
    assert value["fingerprint"] == "abc"
    assert value["completed"] == 7
    assert value["status"] == "paused"
    assert not path.with_suffix(".json.tmp").exists()


def test_fingerprint_changes_when_code_or_run_changes(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.json"
    evidence.write_text("[]", encoding="utf-8")
    common = {
        "database_id": "db",
        "config": {"weights": {"x": 1}},
        "evidence_path": evidence,
        "url_checks": True,
        "use_llm": False,
        "require_llm": False,
        "max_rows": 10,
    }
    first = _run_fingerprint(run_key="run-1", code_sha="sha-1", **common)
    second = _run_fingerprint(run_key="run-1", code_sha="sha-2", **common)
    third = _run_fingerprint(run_key="run-2", code_sha="sha-1", **common)
    assert first != second
    assert first != third


def test_summary_reports_operational_counts() -> None:
    report = [
        {"decision": "APPLY NOW", "rag_provider": "det"},
        {"decision": "VERIFY THEN APPLY", "rag_provider": "det"},
        {"decision": "HOLD", "rag_provider": "openai"},
    ]
    value = _summary(report, "paused")
    assert value["status"] == "paused"
    assert value["processed"] == 3
    assert value["apply_now"] == 1
    assert value["verify"] == 1
    assert value["hold"] == 1
    assert value["rag_providers"] == ["det", "openai"]
