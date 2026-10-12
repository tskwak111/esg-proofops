"""Offline worker and hosted admission checks for C24's execution contract."""

import json
import time
from dataclasses import replace

import pytest
from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash


@pytest.mark.parametrize("stage", ["extract", "tag"])
def test_worker_composition_accepts_24_rejects_25(tmp_path, monkeypatch, stage):
    from proofops.application.ingest.graph_fusion import ParserProfile
    from proofops_worker.composition import build_composition

    config = tmp_path / "parser.json"
    config.write_text(
        json.dumps(ParserProfile("00000000-0000-4000-8000-000000000000").config_snapshot())
    )
    monkeypatch.setenv("LOCAL_PARSER_PROFILE_PATH", str(config))
    monkeypatch.setenv("LOCAL_DATABASE_PATH", str(tmp_path / "state.sqlite3"))
    monkeypatch.setenv("LOCAL_EXTRACTION_MODE", "local_synthetic")
    monkeypatch.setenv("LOCAL_TAGGING_MODE", "local_synthetic")
    monkeypatch.setenv("LOCAL_LLM_MAX_WORKERS", "24")
    runner = build_composition(stage=stage)
    try:
        assert runner.max_workers == 24
        with pytest.raises(ValueError, match="CONCURRENCY_INVALID"):
            type(runner)(
                None,
                runner.uploads,
                None,
                telemetry=None,
                max_workers=25,
                **(dict(extractor=runner.extractor) if stage == "extract" else {}),
            )
    finally:
        runner.uploads.close()
        runner.uploads.registry.close()
    monkeypatch.setenv("LOCAL_LLM_MAX_WORKERS", "25")
    with pytest.raises(ValueError, match="LOCAL_LLM_CONFIGURATION_INVALID"):
        build_composition(stage=stage)


def test_v10_hosted_run_freezes_24_12_and_preserves_one_active_run(tmp_path):
    from proofops_api.hosted_store import HostedStore

    from tests.test_hosted_public import actor, settings, uploaded

    config = tmp_path / "c24-config.json"
    config.write_text(json.dumps(dict(llm_max_workers=24, llm_requests_per_second=12)))
    store = HostedStore(replace(settings.__wrapped__(tmp_path), live_config=config))
    assert store.settings.max_active_runs == 1
    auth = actor(store)
    for i in range(2):
        doc = uploaded(store, auth)
        store.create_run(
            auth,
            doc["document_id"],
            [1],
            f"c24-freeze-runtime-{i:03}",
            now=time.time(),
            pipeline_profile=profiles.V2_PROFILE,
        )
    config.write_text(json.dumps(dict(llm_max_workers=8, llm_requests_per_second=4)))
    job = store.claim(now=time.time())
    frozen = store.run_options(job)
    assert frozen["analysis_profile_sha256"] == canonical_hash(profiles.V2_POLICY)
    assert frozen["provider_execution"] == dict(llm_max_workers=24, llm_requests_per_second=12)
    assert frozen["provider_execution_sha256"] == canonical_hash(frozen["provider_execution"])
    assert store.claim(now=time.time()) is None


def test_tagging_service_accepts_24_rejects_25_without_changing_replicas(tmp_path):
    from tests.acceptance.test_tagging import execute, setup

    inputs = setup(tmp_path)
    runs = execute(inputs | dict(max_workers=24))
    assert [run.replicate_id for run in runs] == [1, 2, 3]
    assert all(run.usage and run.usage.status == "succeeded" for run in runs)
    with pytest.raises(ValueError, match="TAGGING_CONCURRENCY_INVALID"):
        execute(inputs | dict(max_workers=25))


def test_v10_fake_transport_uses_selected_scheduler_and_preserves_accounting(tmp_path, monkeypatch):
    from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency

    from tests.test_t1_403_retry import costs, setup, success, wire

    store, auth, _, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    selected = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_C24_POLICY)
    )
    probe.configure_response_policy(
        dict(
            tenant_id=auth.tenant_id,
            document=dict(sha256="a" * 64),
            analysis_profile_policy=selected,
            analysis_profile_policy_sha256=canonical_hash(selected),
        ),
        role="extract",
    )
    gate = RoleProviderConcurrency(
        24, requests_per_second=12, scheduler_policy=selected["provider_scheduler"]
    )
    gate.bind(probe)
    calls = wire(monkeypatch, iter([success()]))
    result = probe.complete("JSON", "{}", request_id="c24-fake", json_mode=True)
    assert result["schema_valid"]
    assert len(calls) == gate.snapshot()["physical_attempts"] == 1
    assert gate.snapshot()["scheduler"] == selected["provider_scheduler"]["profile"]
    assert gate.snapshot()["active"] == 0
    assert [row[1] for row in costs(store)] == ["settled"]
