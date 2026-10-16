"""S5 physical limits, role fairness, retry accounting and frozen runtime controls."""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from proofops.domain.provenance import canonical_hash


def test_runtime_controls_are_consumed_only_by_new_policy():
    from proofops.application.analysis_profile import FINALS_I7_POLICY, FINALS_S5_POLICY, policy_for
    from proofops_api.hosted_analysis import operator_profiles

    config = dict(analysis_policy_sha256=canonical_hash(FINALS_S5_POLICY))
    default = operator_profiles(config)
    assert (default["llm_max_workers"], default["llm_requests_per_second"]) == (8, 4)
    configured = operator_profiles(config | dict(llm_max_workers=12, llm_requests_per_second=6))
    assert (configured["llm_max_workers"], configured["llm_requests_per_second"]) == (12, 6)
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_I7_POLICY))
        == FINALS_I7_POLICY
    )
    assert (
        canonical_hash(FINALS_I7_POLICY)
        == "0d10ccb21b953f5c29846438fb72538baf50ebd280c45d89b5adbf727c6c9efb"
    )
    with pytest.raises(ValueError, match="SCHEDULER_POLICY_REQUIRED"):
        operator_profiles(
            dict(analysis_policy_sha256=canonical_hash(FINALS_I7_POLICY), llm_requests_per_second=6)
        )
    for invalid in (True, 0, 9, 1.5, "6"):
        with pytest.raises(ValueError, match="RPS_INVALID"):
            operator_profiles(config | dict(llm_requests_per_second=invalid))


def test_all_roles_share_physical_limit_and_pacing(tmp_path):
    from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency

    gate = RoleProviderConcurrency(2, requests_per_second=8, resilience_directory=tmp_path)
    starts = []
    lock = threading.Lock()

    def call(role):
        with gate.attempt(role):
            gate.pace_transport()
            with lock:
                starts.append(time.monotonic())
            time.sleep(0.18)

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(call, ["extract", "preliminary", "relation", "elements"] * 2))
    assert gate.snapshot()["peak"] <= 2
    assert all(b - a >= 0.12 for a, b in zip(sorted(starts), sorted(starts)[1:]))
    assert gate.snapshot()["physical_attempts"] == 8
    assert all(v == 0 for v in gate.snapshot()["queued_by_role"].values())


def test_tagging_priority_and_bounded_starvation():
    from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency

    gate = RoleProviderConcurrency(1, requests_per_second=8)
    order = []
    with ThreadPoolExecutor(3) as pool:
        with gate.attempt("extract"):
            low = pool.submit(lambda: record(gate, "extract", order))
            high = pool.submit(lambda: record(gate, "elements", order))
            deadline = time.monotonic() + 2
            while sum(gate.snapshot()["queued_by_role"].values()) != 2:
                assert time.monotonic() < deadline
                time.sleep(0.01)
        low.result(timeout=3)
        high.result(timeout=3)
    assert order == ["elements", "extract"]
    # Exercise the same selection rule under sustained high-priority backlog.
    with gate.condition:
        low = gate.enqueue("extract")
        for _ in range(9):
            gate.enqueue("elements")
        selected = []
        for _ in range(9):
            item = gate.next_ticket()
            selected.append(item)
            gate.dequeue(item)
    assert selected.index(low) <= 8


def record(gate, role, order):
    with gate.attempt(role):
        order.append(role)


def test_new_schema_and_transport_retries_are_separate_physical_admissions(tmp_path, monkeypatch):
    from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency
    from proofops.application.analysis_profile import FINALS_S5_POLICY

    from tests.test_t1_403_retry import costs, denial, setup, success, wire

    store, auth, _, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    probe.configure_response_policy(
        dict(
            tenant_id=auth.tenant_id,
            document=dict(sha256="a" * 64),
            analysis_profile_policy=FINALS_S5_POLICY,
            analysis_profile_policy_sha256=canonical_hash(FINALS_S5_POLICY),
        ),
        role="extract",
    )
    gate = RoleProviderConcurrency(
        2, requests_per_second=8, resilience_directory=tmp_path / "events"
    )
    gate.bind(probe)
    calls = wire(monkeypatch, iter([denial(), success("invalid JSON"), success()]))
    result = probe.complete("JSON", "{}", request_id="s5-retry", json_mode=True)
    assert result["schema_valid"] and len(calls) == gate.snapshot()["physical_attempts"] == 3
    assert [r[1] for r in costs(store)] == ["accounting_pending", "settled", "settled"]
    assert len(result["provider_scheduler"]["attempts"]) == 3
    assert gate.snapshot()["active"] == 0
    assert gate.snapshot()["consecutive_denials"] == 0


def test_unknown_denials_remain_unretried_and_durable_k3(tmp_path, monkeypatch):
    from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency
    from proofops.application.analysis_profile import FINALS_S5_POLICY

    from tests.test_t1_403_retry import costs, setup, wire

    store, auth, _, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    probe.configure_response_policy(
        dict(
            tenant_id=auth.tenant_id,
            document=dict(sha256="a" * 64),
            analysis_profile_policy=FINALS_S5_POLICY,
            analysis_profile_policy_sha256=canonical_hash(FINALS_S5_POLICY),
        ),
        role="extract",
    )
    gate = RoleProviderConcurrency(2, resilience_directory=tmp_path / "events")
    gate.bind(probe)
    calls = wire(monkeypatch, iter([(403, b"", {})] * 3))
    for i in range(3):
        with pytest.raises(ValueError, match="PROVIDER_PROCESSING_FAILED"):
            probe.complete("JSON", json.dumps(dict(i=i)), request_id=f"denial-{i}", json_mode=True)
    with pytest.raises(ValueError, match="PROVIDER_CIRCUIT_OPEN"):
        probe.complete("JSON", "{}", request_id="unsent", json_mode=True)
    assert len(calls) == len(costs(store)) == 3
    assert all(row[1] == "accounting_pending" for row in costs(store))
    assert RoleProviderConcurrency(2, resilience_directory=tmp_path / "events").snapshot()[
        "circuit_open"
    ]


def test_429_retry_after_and_long_delay_defer_without_second_dispatch():
    from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency

    gate = RoleProviderConcurrency(12, requests_per_second=6, clock=lambda: 10)
    error = ValueError("OPENAI_HTTP_429")
    error.retry_after_seconds = 7
    with pytest.raises(ValueError, match="429"), gate.attempt("relation"):
        raise error
    assert gate.snapshot()["limit"] == 6 and gate.not_before == 17
    gate = RoleProviderConcurrency(12, requests_per_second=6, clock=lambda: 10)
    error.retry_after_seconds = 60
    with pytest.raises(ValueError, match="429"), gate.attempt("preliminary"):
        raise error
    with pytest.raises(ValueError, match="429"), gate.attempt("extract"):
        pytest.fail("long Retry-After was shortened")
    assert gate.snapshot()["attempt_admissions"] == 1
    assert sum(gate.snapshot()["queued_by_role"].values()) == 0


def test_live_settings_are_frozen_when_run_is_accepted(tmp_path, monkeypatch):
    from dataclasses import replace

    from proofops.application.analysis_profile import FINALS_S5_POLICY
    from proofops_api.hosted_store import HostedStore

    from tests.test_hosted_public import actor, settings, uploaded

    config = tmp_path / "candidate-config.json"
    config.write_text(
        json.dumps(
            dict(
                analysis_policy_sha256=canonical_hash(FINALS_S5_POLICY),
                llm_max_workers=12,
                llm_requests_per_second=6,
            )
        )
    )
    store = HostedStore(replace(settings.__wrapped__(tmp_path), live_config=config))
    auth = actor(store)
    doc = uploaded(store, auth)
    store.create_run(
        auth,
        doc["document_id"],
        [1],
        "s5-freeze-runtime-001",
        now=time.time(),
        pipeline_profile="finals-unattended-v2",
    )
    config.write_text(json.dumps(dict(llm_max_workers=1, llm_requests_per_second=1)))
    frozen = store.run_options(store.claim(now=time.time()))
    assert frozen["provider_execution"] == dict(llm_max_workers=12, llm_requests_per_second=6)
    assert frozen["provider_execution_sha256"] == canonical_hash(frozen["provider_execution"])


def test_slow_reservation_cannot_bunch_physical_http_starts():
    from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency

    gate = RoleProviderConcurrency(8, requests_per_second=8)
    starts = []

    def call(index):
        with gate.attempt("extract"):
            if index == 0:
                time.sleep(0.4)  # reservation delays first admitted request
            gate.pace_transport()
            starts.append(time.monotonic())

    with ThreadPoolExecutor(4) as pool:
        list(pool.map(call, range(4)))
    assert all(b - a >= 0.12 for a, b in zip(sorted(starts), sorted(starts)[1:]))


def test_retained_parser_cache_is_found_only_by_exact_response_hash(tmp_path):
    from evaluation.pa3_replay import retained_parse_batches

    root = tmp_path / "parser-prepared/upstage-cache"
    root.mkdir(parents=True)
    raw = [dict(content="retained PDF response")]
    (root / "raw.json").write_text(json.dumps(dict(raw_batches=raw)))
    assert retained_parse_batches(tmp_path, dict(response_sha256=canonical_hash(raw))) == raw
    with pytest.raises(StopIteration):
        retained_parse_batches(tmp_path, dict(response_sha256="0" * 64))


def test_s5_pin_reaches_preparation_and_old_queued_pin_ignores_new_rps(tmp_path, monkeypatch):
    import sys

    from proofops.adapters.local.run_store import LocalSQLiteRunStore
    from proofops.application.analysis_profile import FINALS_I7_POLICY, FINALS_S5_POLICY

    from evaluation import local_upstage_pilot as pilot
    from evaluation.hosted_r108 import prepare_argv
    from tests.test_hosted_analysis import source_pdf

    pdf = tmp_path / "selected.pdf"
    pdf.write_bytes(source_pdf())
    state = tmp_path / "pilot"
    config = dict(
        analysis_profile="finals-unattended-v2",
        report_year=2024,
        period_start="2024-01-01",
        period_end="2024-12-31",
        analysis_policy_sha256=canonical_hash(FINALS_S5_POLICY),
        llm_max_workers=12,
        llm_requests_per_second=6,
    )
    pin = canonical_hash(FINALS_S5_POLICY)
    argv = prepare_argv(
        pdf,
        state,
        "11111111-1111-4111-8111-111111111111",
        config,
        dict(pages=[10, 20], claim_pages=[10], analysis_profile_sha256=pin),
    )
    monkeypatch.setattr(sys, "argv", argv)
    assert pilot.main() == 0
    manifest = json.loads((state / "pilot.json").read_text())
    snapshot = LocalSQLiteRunStore(state / "state.sqlite3").snapshot(
        manifest["tenant_id"], manifest["run_id"]
    )
    assert snapshot["analysis_profile_policy"] == FINALS_S5_POLICY
    old = prepare_argv(
        pdf,
        tmp_path / "old",
        manifest["tenant_id"],
        config,
        dict(
            pages=[10, 20],
            claim_pages=[10],
            analysis_profile_sha256=canonical_hash(FINALS_I7_POLICY),
        ),
    )
    assert old[old.index("--analysis-policy-sha256") + 1] == canonical_hash(FINALS_I7_POLICY)


def test_long_429_also_stops_already_admitted_transport():
    from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency

    clock = [10.0]
    gate = RoleProviderConcurrency(2, requests_per_second=6, clock=lambda: clock[0])
    with gate.attempt("elements"):
        clock[0] = 11.0
        error = ValueError("OPENAI_HTTP_429")
        error.retry_after_seconds = 60
        with pytest.raises(ValueError, match="429"), gate.attempt("relation"):
            raise error
        assert gate.snapshot()["deferred"]
        with pytest.raises(ValueError, match="429"):
            gate.pace_transport()
        assert gate.snapshot()["physical_attempts"] == 0


def test_pre_broker_429_queue_rejection_settles_only_proven_unsent_cost(tmp_path, monkeypatch):
    from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency
    from proofops.application.analysis_profile import FINALS_S5_POLICY

    from tests.test_t1_403_retry import costs, setup, success, wire

    store, auth, _, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    probe.configure_response_policy(
        dict(
            tenant_id=auth.tenant_id,
            document=dict(sha256="a" * 64),
            analysis_profile_policy=FINALS_S5_POLICY,
            analysis_profile_policy_sha256=canonical_hash(FINALS_S5_POLICY),
        ),
        role="extract",
    )
    gate = RoleProviderConcurrency(2, resilience_directory=tmp_path / "events")
    gate.bind(probe)
    gate.deferred = True
    calls = wire(monkeypatch, iter([success()]))
    with pytest.raises(ValueError, match="429"):
        probe.complete("JSON", "{}", request_id="unsent-429", json_mode=True)
    assert not calls and not costs(store)
    assert probe.summary()["unsettled_calls"] == 0
    assert probe.summary()["committed_usd"] == "0"


def test_429_queue_rejection_after_paid_schema_attempt_retains_reservation(tmp_path, monkeypatch):
    from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency
    from proofops.application.analysis_profile import FINALS_S5_POLICY

    from tests.test_t1_403_retry import costs, setup, success, wire

    store, auth, _, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    probe.configure_response_policy(
        dict(
            tenant_id=auth.tenant_id,
            document=dict(sha256="a" * 64),
            analysis_profile_policy=FINALS_S5_POLICY,
            analysis_profile_policy_sha256=canonical_hash(FINALS_S5_POLICY),
        ),
        role="extract",
    )
    gate = RoleProviderConcurrency(2, resilience_directory=tmp_path / "events")
    gate.bind(probe)
    calls = wire(monkeypatch, iter([success("invalid JSON")]))
    original = probe._post

    def stop_next(*a, **kw):
        result = original(*a, **kw)
        gate.deferred = True
        return result

    probe._post = stop_next
    with pytest.raises(ValueError, match="429"):
        probe.complete("JSON", "{}", request_id="paid-then-429", json_mode=True)
    assert len(calls) == len(costs(store)) == 1
    assert probe.summary()["unsettled_calls"] == 1
    assert probe.summary()["committed_usd"] == "0.02"


def test_wire_body_is_prepared_before_physical_pacing(tmp_path, monkeypatch):
    from proofops.adapters.local import openai
    from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency
    from proofops.application.analysis_profile import FINALS_S5_POLICY

    from tests.test_t1_403_retry import success, wire

    probe = openai.OpenAIProbe("fake", tmp_path / "wire.sqlite3")
    probe.configure_response_policy(
        dict(
            tenant_id="tenant",
            document=dict(sha256="a" * 64),
            analysis_profile_policy=FINALS_S5_POLICY,
            analysis_profile_policy_sha256=canonical_hash(FINALS_S5_POLICY),
        ),
        role="extract",
    )
    gate = RoleProviderConcurrency(
        2, requests_per_second=8, resilience_directory=tmp_path / "events"
    )
    gate.bind(probe)
    wire(monkeypatch, iter([success()]))
    events = []
    dump = openai.json.dumps
    request = openai.http.client.HTTPSConnection.request
    pace = probe.http_transport_pacing
    monkeypatch.setattr(
        openai.json, "dumps", lambda *a, **kw: events.append("encoded") or dump(*a, **kw)
    )
    monkeypatch.setattr(
        openai.http.client.HTTPSConnection,
        "request",
        lambda *a, **kw: events.append("wire") or request(*a, **kw),
    )
    probe.http_transport_pacing = lambda: events.append("pace") or pace()
    probe._post(dict(model="gpt-6-luna"))
    assert events == ["encoded", "pace", "wire"]
