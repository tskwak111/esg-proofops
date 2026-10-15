"""OPS2 opt-in recovery, immutable money and bounded previews (offline)."""

import json
import sqlite3
from dataclasses import replace
from decimal import Decimal

import pytest
from proofops.application.analysis_profile import FINALS_I25_POLICY, OPS2_POLICY, policy_for
from proofops.domain.documents import PageGeometry
from proofops.domain.provenance import canonical_hash
from proofops_api.hosted_ops2 import FallbackState, OPS2Probe
from proofops_api.hosted_page_render import render
from proofops_api.hosted_store import HostedError, HostedStore
from pypdf import PdfWriter

from tests.test_hosted_analysis import job_setup
from tests.test_hosted_public import settings as _settings


@pytest.fixture
def settings(tmp_path):
    return _settings.__wrapped__(tmp_path)


def response(body):
    return dict(
        id="ops2-" + body["model"],
        model=body["model"],
        usage=dict(prompt_tokens=20, completion_tokens=8, cost=0.00001),
        choices=[dict(finish_reason="stop", message=dict(content='{"ok":true}'))],
    )


def probe_for(settings, tmp_path, failure, state=None):
    store, auth, job = job_setup(settings)
    seen = []

    def primary(body):
        seen.append(("openai", body))
        if failure:
            raise failure
        return response(body)

    def secondary(body):
        seen.append(("openrouter", body))
        return response(body)

    probe = OPS2Probe(
        "fake",
        tmp_path / "luna.db",
        store=store,
        job=job,
        post=primary,
        fallback_key=lambda: "fake-router",
        fallback_post=secondary,
        fallback_state=state or FallbackState(),
    )
    return probe, store, auth, job, seen


def test_pin_default_and_historical_replay_unchanged():
    assert policy_for("finals-unattended-v2") != OPS2_POLICY
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_I25_POLICY))
        == FINALS_I25_POLICY
    )
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(OPS2_POLICY)) == OPS2_POLICY
    )
    assert canonical_hash(OPS2_POLICY) != canonical_hash(FINALS_I25_POLICY)
    assert (
        OPS2_POLICY["grade_required_agreement_policy"]
        == FINALS_I25_POLICY["grade_required_agreement_policy"]
    )


@pytest.mark.parametrize("code", ["OPENAI_HTTP_429", "OPENAI_HTTP_403"])
def test_k3_then_fallback_no_primary_redelivery(settings, tmp_path, code):
    probe, store, auth, job, seen = probe_for(settings, tmp_path, ValueError(code))
    for i in range(2):
        with pytest.raises(ValueError):
            probe.complete("system", "{}", request_id=f"r{i}", json_mode=True)
    result = probe.complete("system", "{}", request_id="r2", json_mode=True)
    assert result["provider"] == "openrouter"
    assert [x[0] for x in seen] == ["openai"] * 3 + ["openrouter"]
    assert seen[-1][1]["messages"] == seen[0][1]["messages"]
    assert store.get_run(auth.tenant_id, job["run_id"])["status"] == "running"
    with store.transaction(readonly=True) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM deletion.costs WHERE status='accounting_pending'"
            ).fetchone()[0]
            == 3
        )
    assert store.budget_totals()["event_reserved_usd"] == "0.500000"
    assert probe.ops2_state.summary()["triggered_by"] == "http_429_403_k3"


@pytest.mark.parametrize("kind", ["billing", "network"])
def test_immediate_fallback_and_three_independent_receipts(settings, tmp_path, kind):
    error = (
        OSError("private network detail") if kind == "network" else ValueError("OPENAI_HTTP_403")
    )
    if kind == "billing":
        error.provider_error_code = "billing_not_active"
    probe, store, _, _, seen = probe_for(settings, tmp_path, error)
    schema = json.dumps(
        {"type": "object", "required": ["ok"], "properties": {"ok": {"const": True}}}
    )
    for i in range(1, 4):
        result = probe.complete(
            "Return JSON.", "{}", request_id=f"replica-{i}", schema_json=schema, json_mode=True
        )
        assert result["schema_valid"] and result["provider"] == "openrouter"
    assert [x[0] for x in seen] == ["openai"] + ["openrouter"] * 3
    with sqlite3.connect(str(probe.ledger) + ".ops2-openrouter") as db:
        assert db.execute("SELECT count(*),sum(receipt IS NULL) FROM probe_calls").fetchone() == (
            3,
            0,
        )
    with store.transaction(readonly=True) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM deletion.costs "
                "WHERE provider='openrouter' AND status='settled'"
            ).fetchone()[0]
            == 3
        )
    assert len(probe.ops2_state.summary()["calls"]) == 3


def test_noneligible_failure_never_falls_back(settings, tmp_path):
    probe, _, _, _, seen = probe_for(settings, tmp_path, ValueError("OPENAI_HTTP_401"))
    with pytest.raises(ValueError):
        probe.complete("x", "{}", request_id="unauthorized")
    assert [p for p, _ in seen] == ["openai"]


def test_recovery_resets_consecutive_and_admission_not_counted():
    from proofops.adapters.local.provider_scheduler import ProviderAdmissionDeferred
    from proofops_api.hosted_ops2 import fallback_trigger

    state = FallbackState()
    state.observe("http_429_403_k3")
    state.observe("http_429_403_k3")
    state.observe(None)
    state.observe("http_429_403_k3")
    assert state.reason is None and state.consecutive == 1
    assert fallback_trigger(ProviderAdmissionDeferred()) is None


def test_fallback_retains_broker_budget_fence(settings, tmp_path):
    settings = replace(settings, run_usd=Decimal(".02"))
    error = ValueError("OPENAI_HTTP_403")
    error.provider_error_code = "billing_not_active"
    probe, store, _, _, seen = probe_for(settings, tmp_path, error)
    with pytest.raises(ValueError, match="BUDGET_EXHAUSTED"):
        probe.complete("x", "{}", request_id="money")
    assert [p for p, _ in seen] == ["openai"]
    assert store.budget_totals()["event_reserved_usd"] == "0.020000"


def test_observed_success_clears_only_same_provider_warning(settings, tmp_path):
    probe, store, _, job, _ = probe_for(settings, tmp_path, None)
    with store.transaction() as db:
        db.execute(
            "INSERT INTO ops2_provider_observations VALUES (?,?,?)",
            ("openai", 1, "OPENAI_HTTP_429"),
        )
        db.execute(
            "INSERT INTO ops2_provider_observations VALUES (?,?,?)",
            ("openrouter", 1, "OPENROUTER_HTTP_402"),
        )
    probe.complete("x", "{}", request_id="recovery")
    limits = HostedStore(settings).provider_limits()
    assert limits["openai"]["status"] == "available" and limits["openai"]["error_code"] is None
    assert limits["openrouter"]["status"] == "blocked"
    # A later real failure replaces the success, without erasing historical money.
    probe.post = lambda body: (_ for _ in ()).throw(ValueError("OPENAI_HTTP_429"))
    with pytest.raises(ValueError):
        probe.complete("x", "{}", request_id="relapse")
    assert store.provider_limits()["openai"]["error_code"] == "OPENAI_HTTP_429"


@pytest.mark.parametrize(
    "width,height", [(1001, 600), (841.92, 1191.12), (5000, 5000), (100, 5000)]
)
def test_adaptive_render_preserves_geometry_and_limits(tmp_path, width, height):
    source = tmp_path / "large.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width, height)
    writer.write(source)
    geometry = PageGeometry(width, height, 0, (0, 0, width, height))
    png, meta = render(source, 1, geometry, tmp_path, fit_page=True)
    assert png.startswith(b"\x89PNG") and max(meta["width_px"], meta["height_px"]) <= 2000
    assert meta["width_px"] * meta["height_px"] <= 4_000_000
    assert (
        meta["dpi"] < 144
        and meta["width_pt"] == pytest.approx(width, abs=0.0001)
        and meta["height_pt"] == pytest.approx(height, abs=0.0001)
    )


def test_adaptive_render_sanitized_timeout(tmp_path, monkeypatch):
    from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser, ParseFailure

    source = tmp_path / "source.pdf"
    source.write_bytes(b"private document")
    monkeypatch.setattr(
        OpenDataLoaderParser,
        "_execute",
        lambda *a: (_ for _ in ()).throw(ParseFailure("PARSER_TIMEOUT")),
    )
    with pytest.raises(HostedError, match="SOURCE_RENDER_UNAVAILABLE_TIMEOUT"):
        render(source, 1, PageGeometry(600, 400, 0, (0, 0, 600, 400)), tmp_path, fit_page=True)


def test_operator_can_select_ops2_pin_without_changing_default():
    from proofops_api.hosted_analysis import operator_profiles

    configured = operator_profiles(
        dict(
            analysis_profile="finals-unattended-v2",
            analysis_policy_sha256=canonical_hash(OPS2_POLICY),
        )
    )
    assert configured["llm_provider"] == "openai"
    assert "ops2" not in configured["analysis_profile_options"]


def test_active_fallback_never_reissues_a_previously_successful_id(settings, tmp_path):
    probe, _, _, _, seen = probe_for(settings, tmp_path, None)
    probe.complete("x", "{}", request_id="already-successful")
    probe.ops2_state.observe("network_failure")
    with pytest.raises(ValueError, match="DUPLICATE_PROBE_REQUEST"):
        probe.complete("x", "{}", request_id="already-successful")
    assert len(seen) == 1


def test_configured_scheduler_keeps_k3_and_independent_context(settings, tmp_path):
    from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency

    probe, store, auth, job, seen = probe_for(settings, tmp_path, ValueError("OPENAI_HTTP_403"))
    probe.configure_response_policy(
        dict(
            tenant_id=auth.tenant_id,
            document=dict(sha256="a" * 64),
            analysis_profile_policy=OPS2_POLICY,
            analysis_profile_policy_sha256=canonical_hash(OPS2_POLICY),
        ),
        role="elements",
    )
    gate = RoleProviderConcurrency(1, cooldown_seconds=0)
    gate.bind(probe)
    for i in (1, 2):
        with probe.response_context(role="elements", replica=i), pytest.raises(ValueError):
            probe.complete("x", "{}", request_id=f"configured-{i}", json_mode=True)
    with probe.response_context(role="elements", replica=3):
        result = probe.complete("x", "{}", request_id="configured-3", json_mode=True)
    assert gate.circuit_open and result["provider"] == "openrouter"
    assert gate.failed_calls == 3
    assert probe.ops2_state.summary()["recovered_primary_failures"] == 1
    assert store.get_run(auth.tenant_id, job["run_id"])["status"] == "running"
    with pytest.raises(ValueError, match="MODEL_RESPONSE_REPLICA_REQUIRED"):
        probe.complete("x", "{}", request_id="missing-replica", json_mode=True)
    assert len(seen) == 4


@pytest.mark.parametrize("invalid_reply", [False, True])
def test_failed_or_invalid_fallback_does_not_recover_primary_failure(
    settings, tmp_path, invalid_reply
):
    from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency

    probe, _, auth, _, _ = probe_for(settings, tmp_path, OSError("offline"))
    probe.configure_response_policy(
        dict(
            tenant_id=auth.tenant_id,
            document=dict(sha256="a" * 64),
            analysis_profile_policy=OPS2_POLICY,
            analysis_profile_policy_sha256=canonical_hash(OPS2_POLICY),
        ),
        role="extract",
    )
    gate = RoleProviderConcurrency(1, cooldown_seconds=0)
    gate.bind(probe)
    schema = json.dumps({"type": "object", "required": ["missing"]})
    if invalid_reply:
        result = probe.complete("x", "{}", request_id="invalid", schema_json=schema)
        assert result["schema_valid"] is False
    else:

        def unavailable(body):
            raise ValueError("OPENROUTER_HTTP_402")

        probe.ops2_post = unavailable
        with pytest.raises(ValueError):
            probe.complete("x", "{}", request_id="unavailable", schema_json=schema)
    assert gate.failed_calls == 1
    assert probe.ops2_state.summary()["recovered_primary_failures"] == 0


def test_billing_error_decoded_from_real_transport_shape(settings, tmp_path, monkeypatch):
    from tests.test_t1_403_retry import denial, wire

    probe, store, _, _, seen = probe_for(settings, tmp_path, None)
    probe.post = None
    calls = wire(monkeypatch, iter([denial(code="billing_not_active")]))
    result = probe.complete("x", "{}", request_id="billing-wire")
    assert len(calls) == 1 and result["provider"] == "openrouter"
    assert store.provider_limits()["openai"]["error_code"] == "OPENAI_INSUFFICIENT_QUOTA"


def test_cancelled_owner_cannot_dispatch_fallback(settings, tmp_path):
    probe, store, auth, job, seen = probe_for(settings, tmp_path, None)
    probe.ops2_state.observe("network_failure")
    store.cancel(auth, job["run_id"], now=__import__("time").time())
    with pytest.raises(HostedError):
        probe.complete("x", "{}", request_id="cancelled")
    assert seen == []


def test_wrong_fallback_model_is_rejected(settings, tmp_path):
    probe, store, _, _, seen = probe_for(settings, tmp_path, OSError("offline"))
    probe.ops2_post = lambda body: response(body) | {"model": "unapproved/model"}
    with pytest.raises(ValueError):
        probe.complete("x", "{}", request_id="model-mismatch")
    assert probe.ops2_state.summary()["calls"] == []
    with store.transaction(readonly=True) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM deletion.costs "
                "WHERE provider='openrouter' AND status='settled'"
            ).fetchone()[0]
            == 0
        )
