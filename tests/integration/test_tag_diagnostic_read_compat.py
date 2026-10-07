"""Historical tag inputs replay without changing the immutable stored snapshot."""

from copy import deepcopy

from tests.integration.test_local_extract_runner import TENANT
from tests.integration.test_local_tag_runner import verified_setup


def test_load_inputs_accepts_historical_missing_diagnostic_detail(tmp_path, monkeypatch):
    _, run_id, runner, _, _ = verified_setup(tmp_path, monkeypatch)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "needs_review"
    envelope, evidence = runner.tags._load_snapshot_with_evidence(TENANT, run_id)
    envelope = deepcopy(envelope)
    record = envelope["claims"][0]
    raw = record["review_inputs"]
    for entry in raw["tag_runs"]:
        assert entry.pop("diagnostic_detail") is None
    before = deepcopy(raw)
    monkeypatch.setattr(
        runner.tags, "_load_snapshot_with_evidence", lambda *_args: (envelope, evidence)
    )
    inputs = runner.tags.load_inputs(TENANT, run_id, record["claim_id"])
    assert all(run.diagnostic_detail is None for run in inputs.tag_runs)
    assert raw == before
