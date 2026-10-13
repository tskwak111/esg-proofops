"""E05 safe diagnostics and real broker/publication fault injection; no paid calls."""

import json
import stat

import pytest
from proofops.domain.provenance import canonical_hash

from tests.test_t1_403_retry import costs, setup, success, wire


def configure(probe, auth):
    from proofops.application.analysis_profile import FINALS_E05_POLICY

    probe.configure_response_policy(
        dict(
            tenant_id=auth.tenant_id,
            document=dict(sha256="a" * 64),
            analysis_profile_policy=FINALS_E05_POLICY,
            analysis_profile_policy_sha256=canonical_hash(FINALS_E05_POLICY),
        ),
        role="extract",
    )
    from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency

    gate = RoleProviderConcurrency(
        16, requests_per_second=8, resilience_directory=probe.ledger.parent / "events"
    )
    gate.bind(probe)
    return gate


def diagnostic(probe):
    path = next(probe.http_error_directory.glob("*.http-error.json"))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    return json.loads(path.read_text()), path.read_text()


def test_empty_403_preserves_wire_context_and_redacts_headers(tmp_path, monkeypatch):
    from proofops.application.provider_resilience import HTTP_DIAGNOSTIC_POLICY

    store, auth, _, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    configure(probe, auth)
    wire(
        monkeypatch,
        iter(
            [
                (
                    403,
                    b"",
                    {
                        "cf-ray": "a491e93ded4130fe-ICN",
                        "server": "cloudflare",
                        "content-length": "0",
                        "content-type": "application/json",
                        "set-cookie": "private-cookie",
                        "x-request-id": "req_safe123",
                    },
                )
            ]
        ),
    )
    with probe.response_context(role="extract", replica=2):
        with pytest.raises(ValueError, match="^PROVIDER_PROCESSING_FAILED$"):
            probe.complete("PRIVATE-PROMPT", "PRIVATE-BODY", request_id="failed")
    d, raw = diagnostic(probe)
    assert d["diagnostic_policy_sha256"] == canonical_hash(HTTP_DIAGNOSTIC_POLICY)
    assert d["headers"]["cf-ray"].endswith("-ICN")
    assert d["headers"]["content-length"] == "0"
    assert d["headers"]["x-request-id"] == "req_safe123"
    assert d["connection_new"] and d["connection_reused"] is False
    assert d["http_version"] is None  # fake did not negotiate a version
    assert d["role"] == "extract" and d["replica"] == 2
    assert d["reservation_id"] == costs(store)[0][0]
    assert d["response_body_bytes_read"] == 0 and d["response_received"]
    assert d["wire_sha256"] and d["connection_id"]
    assert d["recent_requests_1s"] == d["recent_requests_60s"] == 1
    assert d["ttfb_ms"] >= 0 and d["total_ms"] >= d["ttfb_ms"]
    assert d["dns_ms"] is None and d["tls_ms"] is None
    for secret in ("PRIVATE-PROMPT", "PRIVATE-BODY", "private-cookie", "Bearer", "fake"):
        assert secret not in raw
    assert costs(store)[0][1] == "accounting_pending"


@pytest.mark.parametrize("failure", [403, 503, "timeout"])
def test_partial_publication_with_sibling_and_uncertain_spend(tmp_path, monkeypatch, failure):
    store, auth, job, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    configure(probe, auth)
    replies = [(failure, b"", {})] if isinstance(failure, int) else []
    calls = wire(monkeypatch, iter(replies + [success()])) if failure != "timeout" else []
    if failure == "timeout":
        probe.post = lambda _: (_ for _ in ()).throw(TimeoutError("private"))
    with pytest.raises(ValueError, match="PROVIDER_PROCESSING_FAILED"):
        probe.complete("JSON", "{}", request_id="failed", json_mode=True)
    if failure == "timeout":
        probe.post = None
        calls = wire(monkeypatch, iter([success()]))
    result = probe.complete("JSON", '{"next":true}', request_id="sibling", json_mode=True)
    assert result["schema_valid"]
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
    public = store.get_result(auth.tenant_id, job["run_id"])
    assert public["pipeline"]["provider_failures"]["total"] == 1
    assert store.get_run(auth.tenant_id, job["run_id"])["result_url"]
    assert [r[1] for r in costs(store)] == ["accounting_pending", "settled"]
    assert len(calls) == (1 if failure == "timeout" else 2)


def test_invalid_usage_receipt_remains_terminal_with_uncertain_cost(tmp_path, monkeypatch):
    store, auth, job, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    configure(probe, auth)
    data = json.loads(success()[1])
    data["usage"]["prompt_tokens"] = -1
    calls = wire(monkeypatch, iter([(200, json.dumps(data).encode(), {}), success()]))
    with pytest.raises(ValueError, match="OPENAI_REQUEST_FAILED"):
        probe.complete("JSON", "{}", request_id="invalid-usage")
    assert store.get_run(auth.tenant_id, job["run_id"])["status"] == "accounting_pending"
    assert costs(store)[0][1] == "accounting_pending"
    with pytest.raises(Exception):
        probe.complete("JSON", '{"next":true}', request_id="unsent")
    assert len(calls) == len(costs(store)) == 1


def test_durable_k3_at_current_workers_and_rps(tmp_path, monkeypatch):
    from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency

    store, auth, _, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    gate = configure(probe, auth)
    calls = wire(monkeypatch, iter([(403, b"", {})] * 3))
    for i in range(3):
        with pytest.raises(ValueError, match="PROVIDER_PROCESSING_FAILED"):
            probe.complete("JSON", str(i), request_id=f"denial-{i}")
    with pytest.raises(ValueError, match="PROVIDER_CIRCUIT_OPEN"):
        probe.complete("JSON", "{}", request_id="unsent")
    assert len(calls) == len(costs(store)) == 3
    assert all(row[1] == "accounting_pending" for row in costs(store))
    assert gate.snapshot()["circuit_open"]
    assert RoleProviderConcurrency(
        16, requests_per_second=8, resilience_directory=tmp_path / "events"
    ).snapshot()["circuit_open"]


def test_new_policy_is_opt_in_and_old_pins_do_not_change():
    from proofops.application.analysis_profile import (
        FINALS_E05_POLICY,
        FINALS_I9_POLICY,
        V2_POLICY,
        policy_for,
        publication_policy_for,
    )

    assert policy_for("finals-unattended-v2") == V2_POLICY
    assert (
        publication_policy_for(
            "finals-unattended-v2", pinned_hash=canonical_hash(FINALS_E05_POLICY)
        )
        == FINALS_E05_POLICY
    )
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_I9_POLICY))
        == FINALS_I9_POLICY
    )
    assert FINALS_E05_POLICY != FINALS_I9_POLICY


def test_real_tls_empty_403_records_negotiation_and_handshake(tmp_path, monkeypatch):
    import http.client
    from types import SimpleNamespace
    from urllib.parse import urlsplit

    from proofops.adapters.local import openai

    from evaluation.e05_transport_matrix import local_echo

    _, auth, _, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    configure(probe, auth)
    original = http.client.HTTPSConnection
    with local_echo(response_status=403) as (url, context):
        target = urlsplit(url)
        monkeypatch.setattr(
            openai,
            "http",
            SimpleNamespace(
                client=SimpleNamespace(
                    HTTPSConnection=lambda host, timeout: original(
                        target.hostname, target.port, timeout=timeout, context=context
                    ),
                    HTTPException=http.client.HTTPException,
                )
            ),
        )
        with pytest.raises(ValueError, match="PROVIDER_PROCESSING_FAILED"):
            probe.complete("PRIVATE-PROMPT", "{}", request_id="real-tls")
    d, raw = diagnostic(probe)
    assert d["http_version"] == "HTTP/1.1" and d["connect_tls_ms"] > 0
    assert d["response_body_bytes_read"] == 0
    assert d["headers"]["cf-ray"] == "local-echo-test"
    assert "PRIVATE-PROMPT" not in raw


@pytest.mark.parametrize(
    "policy_name",
    [
        "FINALS_E05_POLICY",
        "FINALS_C24_POLICY",
        "FINALS_Q1_POLICY",
        "FINALS_I10_POLICY",
        "FINALS_H6_POLICY",
    ],
)
def test_e05_public_projection_keeps_sibling_and_holds_failed_claim(
    tmp_path, monkeypatch, policy_name
):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from proofops.application import analysis_profile
    from proofops_api import hosted_results

    from tests.unit.test_pb1_source import fixture

    graph, source, ref = fixture()
    claims = [
        SimpleNamespace(
            claim_id=f"claim-{i}",
            tenant_id=source.tenant_id,
            quote=ref.quote,
            source_refs=(ref,),
            source_quality="unverified",
        )
        for i in (1, 2)
    ]
    failure = dict(usage=dict(status="failed", error_code="PROVIDER_PROCESSING_FAILED"))
    projections = [
        dict(
            claim_id=c.claim_id,
            source_status="unverified",
            provisional_grade={},
            stage="elements",
            status="completed",
            tag_runs=[failure] if c.claim_id == "claim-1" else [],
        )
        for c in claims
    ]
    claim_store = SimpleNamespace(
        store=SimpleNamespace(
            jobs=SimpleNamespace(get_run=lambda *a: dict(extract_job={}, tag_job={}))
        ),
        current_tag=lambda *a: dict(tag=dict(elements=[dict(state="unknown")])),
        # Synthetic saved decision: exercise projection only, not model/source accuracy.
        summary=lambda c, _: dict(
            claim_id=c.claim_id,
            page_num=1,
            track="performance",
            quote=c.quote,
            decision=dict(evidence_grade="E1"),
        ),
        missing_evidence=lambda *a, **k: [],
    )
    tags = SimpleNamespace(
        _load_snapshot_with_evidence=lambda *a: (
            dict(
                analysis_profile_policy_sha256=canonical_hash(
                    getattr(analysis_profile, policy_name)
                ),
                claims=projections,
            ),
            (None, SimpleNamespace(claims=claims), graph),
        )
    )
    reviews = SimpleNamespace(store=SimpleNamespace(page=lambda *a, **k: dict(items=[])))

    @contextmanager
    def services(*a):
        yield "run", claim_store, tags, reviews

    monkeypatch.setattr(hosted_results, "services", services)
    (tmp_path / "pilot.json").write_text("{}")
    (tmp_path / "outcome.json").write_text(
        json.dumps(dict(status="partial_blocked", reason="PROVIDER_PROCESSING_FAILED"))
    )
    result = hosted_results.read_result(tmp_path, source.tenant_id, [1])
    failed, sibling = result["claims"]
    assert failed["confirmed_grade"] is None and failed["pipeline_status"] == "needs_review"
    assert failed["hold_reason"] == "PROVIDER_PROCESSING_FAILED"
    assert sibling["confirmed_grade"] == "E1" and sibling["hold_reason"] is None
    assert all(c["elements"] == [dict(state="unknown")] for c in result["claims"])
    assert all(c["duplicate_occurrences"] == ["claim-1", "claim-2"] for c in result["claims"])
    assert all(c["source_refs"] for c in result["claims"])
