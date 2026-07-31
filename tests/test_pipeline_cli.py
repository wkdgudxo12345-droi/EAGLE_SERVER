import sys

from eagle import pipeline_cli, pipeline_loop


def test_pipeline_cli_injects_stderr_dependency(monkeypatch) -> None:
    observed = {}

    def fake_run() -> int:
        observed["sys"] = pipeline_loop.sys
        return 7

    monkeypatch.delattr(pipeline_loop, "sys", raising=False)
    monkeypatch.setattr(pipeline_loop, "run", fake_run)

    assert pipeline_cli.main() == 7
    assert observed["sys"] is sys
