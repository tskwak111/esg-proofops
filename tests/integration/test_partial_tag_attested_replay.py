"""Partial publication must pin the verified replay graph, not pre-attestation extraction."""

import pytest

from tests.acceptance.test_upload import TENANT
from tests.integration.test_local_tag_runner import verified_setup


@pytest.mark.parametrize("tamper", [None, "graph", "claim", "decision_policy"])
def test_partial_tag_replays_attested_graph(tmp_path, monkeypatch, tamper):
    service, run_id, runner, _, _ = verified_setup(tmp_path, monkeypatch)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "needs_review"
    cid = runner.tags.load_snapshot(TENANT, run_id)["claims"][0]["claim_id"]
    expected = runner.tags.load_inputs(TENANT, run_id, cid)
    evidence = runner.tags.claims.load_evidence(TENANT, run_id)
    # Source attestation changes the interpretation graph after extraction pins.
    monkeypatch.setattr(
        runner.tags.claims,
        "load_evidence",
        lambda *args: (evidence[0] | {"graph_sha256": "0" * 64}, *evidence[1:]),
    )
    original_run = service.store.jobs.get_run

    def partial_run(*args):
        run = dict(original_run(*args))
        run.pop("tag_job", None)
        run.pop("tag_snapshot_sha256", None)
        return run

    monkeypatch.setattr(service.store.jobs, "get_run", partial_run)
    if tamper == "decision_policy":
        original_snapshot = service.store.snapshot
        monkeypatch.setattr(
            service.store,
            "snapshot",
            lambda *args: original_snapshot(*args) | {"decision_settings": {}},
        )
        with pytest.raises(ValueError, match="DECISION"):
            runner.tags.load_inputs(TENANT, run_id, cid)
    elif tamper:
        original_get = service.store.jobs._get

        def poisoned(db, tenant, run_id, kind, key):
            value = original_get(db, tenant, run_id, kind, key)
            if kind == "tag_revision":
                raw = value["inputs"]
                if tamper == "graph":
                    raw["original"]["graph_sha256"] = "1" * 64
                else:
                    raw["claim"]["quote"] = "invented claim"
            return value

        monkeypatch.setattr(service.store.jobs, "_get", poisoned)
        with pytest.raises(ValueError, match="TAG_REPLAY_MISMATCH"):
            runner.tags.load_inputs(TENANT, run_id, cid)
    else:
        assert runner.tags.load_inputs(TENANT, run_id, cid) == expected
