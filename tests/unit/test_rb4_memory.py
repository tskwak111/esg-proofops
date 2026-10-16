"""RB4 releases completed proof buffers without changing receipt or domain contracts."""

import json
import weakref

import pytest
from proofops.application import analysis_profile as profiles
from proofops.application.rb1_input_isolation import InputIsolation
from proofops.application.rb3_deadline import configured
from proofops.application.rb4_memory import POLICY, enabled
from proofops.domain.provenance import canonical_hash


@pytest.mark.parametrize("selected", [profiles.RB4_POLICY, profiles.RB4_STREAM_POLICY])
def test_rb4_is_a_new_explicit_pin_composing_both_guards(selected):
    pin = canonical_hash(selected)
    assert pin not in {canonical_hash(profiles.RB1_POLICY), canonical_hash(profiles.RB3_POLICY)}
    assert profiles.policy_for(profiles.V2_PROFILE) == profiles.FINALS_I29_POLICY
    assert (
        profiles.policy_for(
            profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I28_POLICY)
        )
        == profiles.FINALS_I28_POLICY
    )
    assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=pin) == selected
    assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=pin) == selected
    assert InputIsolation(selected).active
    assert configured(selected)
    assert selected["source"] == profiles.RB3_POLICY["source"]
    assert enabled({"analysis_profile_policy": selected})
    for old in (
        profiles.FINALS_I25_POLICY,
        profiles.FXH_POLICY,
        profiles.RB1_POLICY,
        profiles.RB3_POLICY,
    ):
        assert not enabled({"analysis_profile_policy": old})
    with pytest.raises(ValueError, match="RB4_MEMORY_POLICY_MISMATCH"):
        enabled({"analysis_profile_policy": {"rb4_memory": POLICY | {"receipt_bytes": "changed"}}})


@pytest.mark.parametrize("selected", [profiles.RB4_POLICY, profiles.RB4_STREAM_POLICY])
def test_hosted_child_accepts_rb4_and_rejects_changed_pin(tmp_path, selected):
    from evaluation.hosted_r108 import prepare_argv
    from tests.test_hosted_analysis import source_pdf

    pdf = tmp_path / "original.pdf"
    pdf.write_bytes(source_pdf())
    pin = canonical_hash(selected)
    config = dict(
        analysis_profile=profiles.V2_PROFILE,
        analysis_policy_sha256=pin,
        llm_provider="openai",
        report_year=2025,
        period_start="2025-01-01",
        period_end="2025-12-31",
    )
    args = prepare_argv(
        pdf, tmp_path / "state", "tenant", config, dict(analysis_profile_sha256=pin)
    )
    assert args[args.index("--analysis-policy-sha256") + 1] == pin
    with pytest.raises(ValueError, match="PIN_MISMATCH"):
        prepare_argv(
            pdf, tmp_path / "state", "tenant", config, dict(analysis_profile_sha256="0" * 64)
        )


def test_publication_key_stream_preserves_every_authoritative_row(tmp_path):
    import sqlite3

    from proofops.application.rb4_memory import PUBLICATION_POLICY, publication_enabled
    from proofops_api.hosted_publication import _authoritative_state

    with sqlite3.connect(tmp_path / "state.sqlite3") as db:
        db.execute("CREATE TABLE run_snapshots(run_id TEXT, payload TEXT)")
        db.execute("INSERT INTO run_snapshots VALUES ('run','{}')")
        db.execute(
            "CREATE TABLE job_records(tenant_id TEXT, run_id TEXT, kind TEXT, "
            "record_id TEXT, value BLOB, PRIMARY KEY(tenant_id,run_id,kind,record_id))"
        )
        # Include duplicate sort keys across tenants, mixed SQLite types,
        # Unicode, and the existing nonauthoritative cache exclusions.
        db.executemany(
            "INSERT INTO job_records VALUES (?,?,?,?,?)",
            [
                ("z", "r", "checkpoint", "same", b"first" * 1000),
                ("a", "r", "checkpoint", "same", b"second" * 1000),
                ("a", "r", "review", "1", '{"text":"근거"}'),
                ("a", "r", "document_evidence_search", "1", b"cache"),
                ("a", "r", "element_evidence_search", "1", b"cache"),
            ],
        )
    before = _authoritative_state(tmp_path)
    assert _authoritative_state(tmp_path, stream_records=True) == before
    with sqlite3.connect(tmp_path / "state.sqlite3") as db:
        db.execute(
            "UPDATE job_records SET value=? WHERE kind='checkpoint' AND tenant_id='z'",
            (b"changed",),
        )
    assert _authoritative_state(tmp_path, stream_records=True) == _authoritative_state(tmp_path)
    assert _authoritative_state(tmp_path, stream_records=True) != before
    assert publication_enabled(profiles.RB4_STREAM_POLICY)
    assert not publication_enabled(profiles.RB4_POLICY)
    with pytest.raises(ValueError, match="RB4_PUBLICATION_POLICY_MISMATCH"):
        publication_enabled({"rb4_publication_digest": PUBLICATION_POLICY | {"records": "omit"}})


def test_streamed_handoff_retains_pins_and_rejects_authoritative_mutation(tmp_path, monkeypatch):
    import sqlite3

    from proofops.adapters.local.rb3_claim_source import claim_source_policy
    from proofops_api import hosted_publication as handoff

    from tests.unit.test_s4_publication_handoff import state

    path, job, calls, content = state.__wrapped__(tmp_path, monkeypatch)
    with sqlite3.connect(path / "state.sqlite3") as db:
        db.execute(
            "UPDATE run_snapshots SET payload=?",
            (
                json.dumps(
                    dict(
                        analysis_profile_policy=profiles.RB4_STREAM_POLICY,
                        claim_source_policy=claim_source_policy(),
                    )
                ),
            ),
        )
        db.execute("CREATE TABLE job_records(kind TEXT,record_id TEXT,value BLOB)")
        db.execute("INSERT INTO job_records VALUES ('checkpoint','1',?)", (b"frozen",))
    packet = handoff.make_handoff(path, job, [13])
    assert packet is not None
    assert "rb4_publication_digest" in json.loads(packet)["context"]
    assert handoff.reuse_handoff(packet, path, job, [13]) == content
    assert calls == [1]

    def mutate_during_read(*args):
        with sqlite3.connect(path / "state.sqlite3") as db:
            db.execute("UPDATE job_records SET value=?", (b"changed",))
        return content

    monkeypatch.setattr("proofops_api.hosted_results.result_snapshot", mutate_during_read)
    assert handoff.make_handoff(path, job, [13]) is None


@pytest.mark.parametrize("opt_in", [False, True])
def test_tagging_releases_only_completed_source_proof_before_calls(tmp_path, monkeypatch, opt_in):
    from tests.integration.test_local_tag_runner import tag_message
    from tests.integration.test_unattended_pipeline import TENANT, setup

    class ProofBuffer(dict):
        pass

    service, run_id, runner, _, _ = setup(tmp_path, monkeypatch)
    extraction, discovery, graph = runner.claims.load_evidence(TENANT, run_id)
    references = []

    def verified_evidence(*args):
        proof = ProofBuffer(already_replayed=True)
        references.append(weakref.ref(proof))
        return extraction | {"claim_source_attestation": proof}, discovery, graph

    monkeypatch.setattr(runner.claims, "load_evidence", verified_evidence)
    original = runner.preliminary
    observed = []

    def preliminary(claim, graph):
        observed.append(references[-1]() is None)
        return original(claim, graph)

    runner.preliminary = preliminary
    snapshot = service.store.snapshot(TENANT, run_id)
    if opt_in:
        snapshot["analysis_profile_policy"] = {"rb4_memory": POLICY}
    message = tag_message(service, run_id, runner.clock())
    lease = service.store.jobs.claim_job(
        message, owner="RB4-test", now=runner.clock(), lease_seconds=300
    )
    result = json.loads(runner._execute(lease, snapshot, {"synthetic_calls": 0}))
    assert observed and all(released is opt_in for released in observed)
    assert result["stage_status"] == "completed"
    assert len(result["claims"]) == len(discovery.claims)
    assert all(len(claim["tag_runs"]) == 3 for claim in result["claims"])
    assert all(ref() is None for ref in references)


def test_tagging_memory_branch_preserves_complete_checkpoint_bytes(tmp_path, monkeypatch):
    from proofops_worker import tag_runner

    from tests.integration.test_local_tag_runner import tag_message
    from tests.integration.test_unattended_pipeline import TENANT, setup

    service, run_id, runner, _, _ = setup(tmp_path, monkeypatch)
    snapshot = service.store.snapshot(TENANT, run_id)
    message = tag_message(service, run_id, runner.clock())
    lease = service.store.jobs.claim_job(
        message, owner="RB4-byte-equivalence", now=runner.clock(), lease_seconds=300
    )
    monkeypatch.setattr(tag_runner, "rb4_memory_enabled", lambda snapshot: False)
    # Warm the immutable response cache first so both compared executions have
    # the same cache-hit receipt fields as well as identical inputs and pins.
    runner._execute(lease, snapshot, {"synthetic_calls": 0})
    before = runner._execute(lease, snapshot, {"synthetic_calls": 0})
    monkeypatch.setattr(tag_runner, "rb4_memory_enabled", lambda snapshot: True)
    after = runner._execute(lease, snapshot, {"synthetic_calls": 0})
    assert after == before


def test_outcome_reuses_canonical_admission_and_preserves_fallback_guards(tmp_path, monkeypatch):
    from copy import deepcopy
    from hashlib import sha256
    from types import SimpleNamespace

    from proofops.adapters.local import claim_store

    from tests.integration.test_extract_batch_continuation import TENANT, setup_run
    from tests.integration.test_real_extract_runner import FakeProbe

    service, run_id, runner, _, _, _ = setup_run(
        tmp_path, monkeypatch, paragraphs=2, probe=FakeProbe('{"claims":["carbon emission"]}')
    )
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    admitted, _, _ = runner.claims.load_evidence(TENANT, run_id)
    expected = runner.claims.outcome_projection(TENANT, run_id, admitted_checkpoint=admitted)
    monkeypatch.setattr(claim_store, "rb4_memory_enabled", lambda snapshot: True)
    decoded = []

    def loads(payload):
        decoded.append(1)
        return json.loads(payload)

    monkeypatch.setattr(claim_store, "json", SimpleNamespace(loads=loads))
    assert (
        runner.claims.outcome_projection(TENANT, run_id, admitted_checkpoint=admitted) == expected
    )
    assert not decoded
    # Formatting differences keep the original semantic-equality fallback.
    encoded = json.dumps(admitted, indent=2).encode()
    run = service.store.jobs.get_run(TENANT, run_id)
    monkeypatch.setattr(service.store.jobs, "read_checkpoint", lambda message: encoded)
    monkeypatch.setattr(
        service.store.jobs,
        "get_run",
        lambda *args: run | {"claim_snapshot_sha256": sha256(encoded).hexdigest()},
    )
    assert (
        runner.claims.outcome_projection(TENANT, run_id, admitted_checkpoint=admitted) == expected
    )
    assert decoded == [1]
    forged = deepcopy(admitted)
    forged["discovery"]["claims"][0]["claim_text"] = "altered"
    with pytest.raises(ValueError, match="CLAIM_SNAPSHOT_REPLAY_MISMATCH"):
        runner.claims.outcome_projection(TENANT, run_id, admitted_checkpoint=forged)
    monkeypatch.setattr(service.store.jobs, "read_checkpoint", lambda message: b"changed")
    with pytest.raises(ValueError, match="CLAIM_SNAPSHOT_HASH_MISMATCH"):
        runner.claims.outcome_projection(TENANT, run_id, admitted_checkpoint=admitted)


def test_publication_memory_branch_preserves_complete_result_bytes(tmp_path, monkeypatch):
    import time

    from proofops.adapters.local import claim_store
    from proofops.application import rb4_memory
    from proofops_api import hosted_results
    from proofops_api.hosted_store import HostedStore

    from tests.test_hosted_analysis import fake_analysis, source_pdf
    from tests.test_hosted_public import actor, settings

    store = HostedStore(settings.__wrapped__(tmp_path))
    auth = actor(store)
    doc = store.upload(auth, source_pdf(), "rb4-byte-upload001", now=time.time())
    store.create_run(
        auth,
        doc["document_id"],
        [1, 2],
        "rb4-byte-run000001",
        now=time.time(),
        pipeline_profile="strict-v1",
    )
    done = store.tick(now=time.time(), analysis=fake_analysis)
    path = store.document_dir(auth.tenant_id, doc["document_id"]) / "analysis" / done["run_id"]
    before = hosted_results.result_snapshot(path, auth.tenant_id, [1, 2])
    monkeypatch.setattr(claim_store, "rb4_memory_enabled", lambda snapshot: True)
    monkeypatch.setattr(rb4_memory, "enabled", lambda snapshot: True)
    after = hosted_results.result_snapshot(path, auth.tenant_id, [1, 2])
    assert after == before


@pytest.mark.parametrize("opt_in", [False, True])
def test_continuation_releases_prior_proof_without_repeating_or_rewriting(
    tmp_path, monkeypatch, opt_in
):
    from proofops.application.ports.jobs import JobMessage
    from proofops_worker import extract_runner

    from tests.integration.test_extract_batch_continuation import TENANT, setup_run

    class ProofBuffer(dict):
        pass

    service, run_id, runner, _, probe, _ = setup_run(tmp_path, monkeypatch, paragraphs=4)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    head = JobMessage(**service.store.jobs.get_run(TENANT, run_id)["extract_job"])
    checkpoint = service.store.jobs.read_checkpoint(head)
    load = runner.claims.load_evidence
    references = []

    def verified_evidence(*args, **kwargs):
        envelope, discovery, graph = load(*args, **kwargs)
        proof = ProofBuffer(already_replayed=True)
        references.append(weakref.ref(proof))
        return envelope | {"claim_source_attestation": proof}, discovery, graph

    monkeypatch.setattr(runner.claims, "load_evidence", verified_evidence)
    # Exercise the lifetime branch on the existing fake-provider fixture. Exact
    # policy selection is covered separately; no stored pin or hash is changed.
    monkeypatch.setattr(extract_runner, "rb4_memory_enabled", lambda snapshot: opt_in)
    post = probe._client._post
    observed = []

    def next_response(body):
        observed.append(references[0]() is None)
        return post(body)

    probe._client._post = next_response
    result = runner.run_batch(tenant_id=TENANT, run_id=run_id)
    assert result["status"] == "committed"
    assert len(result["processed"]) == len(result["replayed"]) == 2
    assert len(probe.calls) == 4
    assert observed and all(released is opt_in for released in observed)
    assert service.store.jobs.read_checkpoint(head) == checkpoint
    assert all(ref() is None for ref in references)
