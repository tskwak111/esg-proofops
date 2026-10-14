"""Keep launcher, composed worker and direct tag runner on the safe local default."""

import pytest

from tests.integration.test_local_tag_runner import TENANT, tag_setup


@pytest.mark.parametrize("configured,expected", [(None, 8), ("4", 4), ("16", 16)])
def test_worker_composition_preserves_operator_cap(tmp_path, monkeypatch, configured, expected):
    import json
    from uuid import uuid4

    from proofops.application.ingest.graph_fusion import ParserProfile
    from proofops_worker.composition import build_composition

    config = tmp_path / "parser.json"
    config.write_text(json.dumps(ParserProfile(str(uuid4())).config_snapshot()))
    monkeypatch.setenv("LOCAL_PARSER_PROFILE_PATH", str(config))
    monkeypatch.setenv("LOCAL_DATABASE_PATH", str(tmp_path / "state.sqlite3"))
    monkeypatch.setenv("LOCAL_TAGGING_MODE", "local_synthetic")
    monkeypatch.delenv("LOCAL_LLM_MAX_WORKERS", raising=False)
    if configured is not None:
        monkeypatch.setenv("LOCAL_LLM_MAX_WORKERS", configured)
    runner = build_composition(stage="tag")
    try:
        assert runner.max_workers == expected
    finally:
        runner.uploads.close()
        runner.uploads.registry.close()


def test_direct_tag_runner_default_can_process_gated_pdf(tmp_path, monkeypatch):
    _, run_id, runner, _, _ = tag_setup(tmp_path, monkeypatch)
    assert runner.max_workers == 8
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "blocked"
