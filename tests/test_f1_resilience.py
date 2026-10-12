"""F1 partial publication, bounded denial and retained uncertain costs."""

import json
import time
from decimal import Decimal

import pytest
from proofops.adapters.local.provider_concurrency import ProviderConcurrency
from proofops.application.analysis_profile import FINALS_F1_POLICY, FINALS_I5_POLICY, policy_for
from proofops.domain.provenance import canonical_hash

from tests.test_t1_403_retry import costs, setup, success, wire


def configure(probe, auth):
    probe.configure_response_policy(
        dict(
            tenant_id=auth.tenant_id,
            document=dict(sha256="a" * 64),
            analysis_profile_policy=FINALS_F1_POLICY,
            analysis_profile_policy_sha256=canonical_hash(FINALS_F1_POLICY),
        ),
        role="extract",
    )


@pytest.mark.parametrize("status", [403, 500, 502, 503, 504])
def test_http_failure_keeps_run_fence_and_next_result(tmp_path, monkeypatch, status):
    store, auth, job, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    configure(probe, auth)
    calls = wire(monkeypatch, iter([(status, b"", {}), success()]))
    with pytest.raises(ValueError, match="^PROVIDER_PROCESSING_FAILED$"):
        probe.complete("Return JSON", "{}", request_id="failed", json_mode=True)
    assert store.get_run(auth.tenant_id, job["run_id"])["status"] == "running"
    assert probe.complete("Return JSON", '{"different":true}', request_id="next", json_mode=True)[
        "schema_valid"
    ]
    assert len(calls) == 2
    assert [r[1] for r in costs(store)] == ["accounting_pending", "settled"]
    with store.transaction() as db:
        assert (
            db.execute("SELECT fence FROM runs WHERE run_id=?", (job["run_id"],)).fetchone()[0]
            == job["fence"]
        )
        assert db.execute("SELECT status FROM deletion.spend").fetchone()[0] == "accounting_pending"


def test_denial_circuit_stops_before_reservation_and_survives_restart(tmp_path, monkeypatch):
    store, auth, job, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    configure(probe, auth)
    gate = ProviderConcurrency(2, resilience_directory=tmp_path / "events")
    calls = wire(monkeypatch, iter([(403, b"", {})] * 3))
    gate.bind(probe)
    for i in range(3):
        with pytest.raises(ValueError, match="^PROVIDER_PROCESSING_FAILED$"):
            probe.complete("JSON", json.dumps(dict(i=i)), request_id=f"denied-{i}", json_mode=True)
    with pytest.raises(ValueError, match="^PROVIDER_CIRCUIT_OPEN$"):
        probe.complete("JSON", "{}", request_id="unsent", json_mode=True)
    assert len(calls) == len(costs(store)) == 3
    assert ProviderConcurrency(2, resilience_directory=tmp_path / "events").snapshot()[
        "circuit_open"
    ]


def test_new_policy_is_explicit_only():
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_I5_POLICY))
        == FINALS_I5_POLICY
    )
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_F1_POLICY))
        == FINALS_F1_POLICY
    )


def test_broker_receipt_mismatch_remains_terminal(tmp_path, monkeypatch):
    store, auth, job, _, _ = setup(tmp_path, monkeypatch)
    with pytest.raises(Exception):
        store.dispatch(
            job,
            "openai",
            "mismatch",
            "a" * 64,
            Decimal(".011"),
            lambda request: request | dict(request_id="wrong", actual_usd=".001"),
            now=time.time(),
            allow_model_partial=True,
        )
    assert store.get_run(auth.tenant_id, job["run_id"])["status"] == "accounting_pending"


def test_extraction_failed_source_is_immutable_hold_and_sibling_continues(tmp_path):
    from proofops.application.claims import ExtractionOutputError
    from proofops.application.provider_resilience import POLICY

    from tests.integration.test_upstage_extraction import FakeProbe, make_extractor

    probe = FakeProbe(error=ValueError("PROVIDER_PROCESSING_FAILED"))
    probe.provider_resilience = POLICY
    extractor, packet = make_extractor(probe, tmp_path)
    with pytest.raises(ExtractionOutputError, match="PROVIDER_PROCESSING_FAILED"):
        extractor.extract(packet)
    failures = list((tmp_path / "receipts").glob("*/failure.json"))
    original = failures[0].read_bytes()
    with pytest.raises(ExtractionOutputError, match="PROVIDER_PROCESSING_FAILED"):
        extractor.extract(packet)
    assert failures[0].read_bytes() == original and len(probe.calls) == 1
    probe.error, probe.content = None, '{"claims":[]}'
    packet["untrusted_document_data"]["source_id"] = "22222222-2222-4333-8444-555555555555"
    assert extractor.extract(packet)
    assert len(probe.calls) == 2


def test_tagging_failure_does_not_stop_other_claims(tmp_path, monkeypatch):
    from uuid import uuid4

    from proofops.application.provider_resilience import POLICY

    from tests.integration.test_upstage_tagging import configured

    transport, probe, calls, request = configured(tmp_path, monkeypatch)
    probe.provider_resilience = POLICY
    original = probe.complete
    probe.complete = lambda *a, **k: (_ for _ in ()).throw(ValueError("PROVIDER_PROCESSING_FAILED"))
    response = transport.invoke(request)
    assert response.usage.error_code == "PROVIDER_PROCESSING_FAILED"
    assert not list((tmp_path / "receipts").glob("transport-stop*.json"))
    probe.complete = original
    response = transport.invoke(request | dict(request_id=str(uuid4())))
    assert response.usage.status == "succeeded" and len(calls) == 1


def test_partial_result_publication_retains_accounting_pending(tmp_path, monkeypatch):
    store, auth, job, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    configure(probe, auth)
    wire(monkeypatch, iter([(403, b"", {})]))
    with pytest.raises(ValueError, match="PROVIDER_PROCESSING_FAILED"):
        probe.complete("JSON", "{}", request_id="failed", json_mode=True)
    state = tmp_path / "publication"
    state.mkdir()
    (state / "outcome.json").write_text(
        json.dumps(
            dict(
                status="partial_blocked",
                reason="PROVIDER_PROCESSING_FAILED",
                provider_failures=dict(failed_calls=1, deferred_calls=0, total=1),
            )
        )
    )
    store.publish_analysis(job, state, "partial_blocked", "PROVIDER_PROCESSING_FAILED")
    assert store.get_run(auth.tenant_id, job["run_id"])["result_url"]
    result = store.get_result(auth.tenant_id, job["run_id"])
    assert result["pipeline"]["provider_failures"]["total"] == 1
    assert costs(store)[0][1] == "accounting_pending"

    assert store.get_run(auth.tenant_id, probe.job["run_id"])["status"] == "partial_blocked"


def test_physical_circuit_guard_is_proven_unsent_and_does_not_change_other_costs(
    tmp_path, monkeypatch
):
    import sqlite3

    store, auth, job, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    configure(probe, auth)
    gate = ProviderConcurrency(2, resilience_directory=tmp_path / "events")
    gate.bind(probe)
    original = probe._post

    def circuit_between_reservation_and_send(*a, **k):
        gate.circuit_open = True
        return original(*a, **k)

    probe._post = circuit_between_reservation_and_send
    with pytest.raises(ValueError, match="PROVIDER_CIRCUIT_OPEN"):
        probe.complete("JSON", "{}", request_id="never-sent", json_mode=True)
    assert not costs(store)
    with sqlite3.connect(probe.ledger) as db:
        row = db.execute("SELECT committed,receipt FROM probe_calls").fetchone()
    assert row[0] == "0" and json.loads(row[1])["dispatch_state"] == "never_sent"


def test_retry_circuit_rejection_keeps_first_uncertain_cost(tmp_path, monkeypatch):
    from proofops.adapters.local.provider_concurrency import ProviderCircuitOpen

    from tests.test_t1_403_retry import denial

    store, auth, _, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    configure(probe, auth)
    gate = ProviderConcurrency(2, resilience_directory=tmp_path / "events")
    gate.bind(probe)
    calls = wire(monkeypatch, iter([denial()]))
    admitted = []

    def only_first_admitted():
        if admitted:
            raise ProviderCircuitOpen()
        admitted.append(True)

    probe.http_dispatch_admission = only_first_admitted
    with pytest.raises(ValueError, match="PROVIDER_CIRCUIT_OPEN"):
        probe.complete("JSON", "{}", request_id="retry-blocked", json_mode=True)
    assert len(calls) == 1 and costs(store)[0][1] == "accounting_pending"
    assert probe.summary()["unsettled_calls"] == 1


def test_timeout_is_a_hold_and_next_call_succeeds(tmp_path, monkeypatch):
    store, auth, _, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    configure(probe, auth)
    probe.post = lambda body: (_ for _ in ()).throw(TimeoutError())
    with pytest.raises(ValueError, match="PROVIDER_PROCESSING_FAILED"):
        probe.complete("JSON", "{}", request_id="timed-out", json_mode=True)
    assert store.get_run(auth.tenant_id, probe.job["run_id"])["status"] == "running"
    assert costs(store)[0][1] == "accounting_pending"
    probe.post = None
    wire(monkeypatch, iter([success()]))
    assert probe.complete("JSON", '{"next":true}', request_id="after-timeout", json_mode=True)[
        "schema_valid"
    ]


def test_pacing_applies_to_each_schema_attempt(tmp_path, monkeypatch):
    _, auth, _, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    configure(probe, auth)
    gate = ProviderConcurrency(2, resilience_directory=tmp_path / "events")
    gate.bind(probe)
    calls = wire(monkeypatch, iter([success("not JSON"), success()]))
    times = []
    admit = probe.http_dispatch_admission

    def observed_admission():
        admit()
        times.append(time.monotonic())

    probe.http_dispatch_admission = observed_admission
    assert probe.complete("JSON", "{}", request_id="schema-retry", json_mode=True)["schema_valid"]
    assert len(calls) == len(times) == 2 and times[1] - times[0] >= 0.24


def test_claim_hold_comes_only_from_trusted_failure_fields():
    from proofops.application.provider_resilience import claim_hold_reason

    assert claim_hold_reason({"tag_runs": None, "preliminary_records": None}) is None

    assert (
        claim_hold_reason(
            {
                "tag_runs": [
                    {"usage": {"status": "failed", "error_code": "PROVIDER_PROCESSING_FAILED"}}
                ]
            }
        )
        == "PROVIDER_PROCESSING_FAILED"
    )
    assert (
        claim_hold_reason(
            {
                "preliminary_records": [
                    {
                        "status": "needs_review",
                        "stable_reason": {"error_code": "PROVIDER_CIRCUIT_OPEN"},
                    }
                ]
            }
        )
        == "PROVIDER_CIRCUIT_OPEN"
    )
    assert (
        claim_hold_reason(
            {
                "tag_runs": [
                    {
                        "raw_response_json": "PROVIDER_PROCESSING_FAILED",
                        "usage": {"status": "succeeded", "error_code": None},
                    }
                ]
            }
        )
        is None
    )


def test_measurement_keeps_evidence_only_pages_out_of_claim_scope(tmp_path):
    from evaluation.f1_live import source_claim_pages

    (tmp_path / "pilot.json").write_text(json.dumps(dict(selected_pages=[19, 20, 21])))
    (tmp_path / "settings.json").write_text(
        json.dumps(
            dict(extraction_limits=dict(max_calls=20, max_output_tokens=1024, claim_pages=[1]))
        )
    )
    assert source_claim_pages(tmp_path) == [19]


def test_malformed_http200_preserves_received_status_and_headers(tmp_path, monkeypatch):
    store, auth, _, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    configure(probe, auth)
    wire(
        monkeypatch,
        iter([(200, b"", {"server": "cloudflare", "cf-ray": "edge-123", "set-cookie": "secret"})]),
    )
    with pytest.raises(ValueError, match="PROVIDER_PROCESSING_FAILED"):
        probe.complete("JSON", "{}", request_id="malformed", json_mode=True)
    diagnostic = json.loads(next(probe.http_error_directory.glob("*.http-error.json")).read_text())
    assert diagnostic["http_status"] == 200
    assert diagnostic["exception_type"] == "JSONDecodeError" and diagnostic["response_received"]
    assert diagnostic["headers"] == {"server": "cloudflare", "cf-ray": "edge-123"}
    assert store.get_run(auth.tenant_id, probe.job["run_id"])["status"] == "running"
    assert costs(store)[0][1] == "accounting_pending"


def test_no_http_response_has_null_status_and_hash_not_fake_empty_body(tmp_path, monkeypatch):
    from proofops.adapters.local import openai

    store, auth, _, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    configure(probe, auth)
    wire(monkeypatch, iter([success()]))
    monkeypatch.setattr(
        openai.http.client.HTTPSConnection,
        "getresponse",
        lambda self: (_ for _ in ()).throw(TimeoutError("must-not-be-recorded")),
    )
    with pytest.raises(ValueError, match="PROVIDER_PROCESSING_FAILED"):
        probe.complete("JSON", "{}", request_id="no-response", json_mode=True)
    file = next(probe.http_error_directory.glob("*.http-error.json"))
    d = json.loads(file.read_text())
    assert d["http_status"] is None and d["response_body_sha256"] is None
    assert d["exception_type"] == "TimeoutError" and not d["response_received"]
    assert "must-not-be-recorded" not in file.read_text()
    assert store.get_run(auth.tenant_id, probe.job["run_id"])["status"] == "running"
    assert costs(store)[0][1] == "accounting_pending"


def test_old_f1_v2_malformed_response_contract_is_preserved(tmp_path, monkeypatch):
    from proofops.application.analysis_profile import FINALS_F1_TRANSPORT_POLICY

    store, auth, _, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    probe.configure_response_policy(
        dict(
            tenant_id=auth.tenant_id,
            document=dict(sha256="a" * 64),
            analysis_profile_policy=FINALS_F1_TRANSPORT_POLICY,
            analysis_profile_policy_sha256=canonical_hash(FINALS_F1_TRANSPORT_POLICY),
        ),
        role="extract",
    )
    wire(monkeypatch, iter([(200, b"", {})]))
    with pytest.raises(ValueError, match="OPENAI_REQUEST_FAILED"):
        probe.complete("JSON", "{}", request_id="legacy-malformed", json_mode=True)
    assert store.get_run(auth.tenant_id, probe.job["run_id"])["status"] == "accounting_pending"
    assert not list(probe.http_error_directory.glob("*.http-error.json"))
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_F1_TRANSPORT_POLICY))
        == FINALS_F1_TRANSPORT_POLICY
    )
