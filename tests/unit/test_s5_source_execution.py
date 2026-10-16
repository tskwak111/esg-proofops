"""S5 changes computation cost, never source proof, policy pins or replay guards."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from proofops.adapters.local import fxh_claim_source, s5_claim_source
from proofops.adapters.local.s5_policy_evaluation import evaluate
from proofops.domain.provenance import canonical_hash

from tests.integration.test_claim_source_v3 import synthetic


def test_policy_dag_evaluation_is_exact_and_does_not_retain_stale_values(monkeypatch):
    from proofops.adapters.local import source_fxe

    before = fxh_claim_source.claim_source_policy()
    assert evaluate(fxh_claim_source.claim_source_policy) == before
    original = source_fxe.policy
    monkeypatch.setattr(source_fxe, "policy", lambda: original() | dict(changed=True))
    assert evaluate(fxh_claim_source.claim_source_policy) == fxh_claim_source.claim_source_policy()
    assert evaluate(fxh_claim_source.claim_source_policy) != before


def test_s5_is_opt_in_and_previous_analysis_pins_are_unchanged():
    from proofops.application import analysis_profile as profiles

    assert (
        profiles.policy_for(
            profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I26_POLICY)
        )
        == profiles.FINALS_I26_POLICY
    )
    for policy in (profiles.FXH_POLICY, profiles.S5_LIVE_POLICY):
        pin = canonical_hash(policy)
        assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=pin) == policy
        assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=pin) == policy
    assert profiles.S5_LIVE_POLICY["source"] == "s5_claim_source_v1"
    assert profiles.S5_LIVE_POLICY["extract_batch_calls"] == 256


def test_s5_uses_existing_bounded_batch_limit_without_changing_old_defaults():
    from proofops.application.analysis_profile import FXH_POLICY, S5_LIVE_POLICY
    from proofops.application.claim_scope import MAX_EXTRACTION_BATCH_CALLS
    from proofops_api.hosted_analysis import operator_profiles

    for policy, expected in ((FXH_POLICY, 100), (S5_LIVE_POLICY, 256)):
        config = dict(
            analysis_profile="finals-unattended-v2",
            analysis_policy_sha256=canonical_hash(policy),
            llm_provider="openai",
        )
        assert operator_profiles(config)["extract_batch_calls"] == expected
        assert expected <= MAX_EXTRACTION_BATCH_CALLS
        with pytest.raises(ValueError, match="EXTRACT_BATCH_INVALID"):
            operator_profiles(config | dict(extract_batch_calls=MAX_EXTRACTION_BATCH_CALLS + 1))


@pytest.fixture
def source(monkeypatch):
    monkeypatch.setattr(
        fxh_claim_source.PageOCRStore,
        "from_env",
        lambda: SimpleNamespace(fetch=lambda *a, **k: pytest.fail("unexpected OCR acquisition")),
    )
    return synthetic("ESG policy 10% achieved")


def test_all_nested_proof_bytes_match_fxh_and_forgery_is_rejected(source):
    content, graph, ref = source
    arguments = dict(tenant_id=graph.tenant_id, run_id="s5-test")
    old = fxh_claim_source.attest_claim_spans(graph, content, (ref,), **arguments)
    new = s5_claim_source.attest_claim_spans(graph, content, (ref,), **arguments)
    # Only the deliberately new outer execution policy and its artifact hash differ.
    assert {k: v for k, v in old.items() if k not in {"policy", "artifact_sha256"}} == {
        k: v for k, v in new.items() if k not in {"policy", "artifact_sha256"}
    }
    reader = s5_claim_source.for_run("s5-test")
    assert (
        reader.recompute_claim_receipt(new, graph, content, (ref,), tenant_id=graph.tenant_id)
        == new
    )
    forged = deepcopy(new)
    forged["previous_receipt"]["records"][0]["status"] = "forged"
    forged["artifact_sha256"] = canonical_hash(
        {k: v for k, v in forged.items() if k != "artifact_sha256"}
    )
    with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
        reader.recompute_claim_receipt(forged, graph, content, (ref,), tenant_id=graph.tenant_id)
    with pytest.raises(ValueError):
        reader.attest_claim_spans(graph, content + b"changed", (ref,), tenant_id=graph.tenant_id)
    with pytest.raises(ValueError):
        reader.attest_claim_spans(graph, content, (ref,), tenant_id="other-tenant")


def test_policy_change_after_reader_creation_fails_closed(source, monkeypatch):
    content, graph, ref = source
    reader = s5_claim_source.for_run("s5-test")
    original = s5_claim_source.claim_source_policy
    monkeypatch.setattr(
        s5_claim_source, "claim_source_policy", lambda: original() | dict(changed=1)
    )
    with pytest.raises(ValueError, match="S5_READER_POLICY_CHANGED"):
        reader.attest_claim_spans(graph, content, (ref,), tenant_id=graph.tenant_id)


def test_policy_change_during_read_discards_completed_proof(source, monkeypatch):
    content, graph, ref = source
    reader = s5_claim_source.for_run("s5-test")
    attest = reader.reader.attest_claim_spans
    policy = s5_claim_source.claim_source_policy
    completed = []

    def change_after_proof(*args, **kwargs):
        result = attest(*args, **kwargs)
        completed.append(result)
        monkeypatch.setattr(
            s5_claim_source, "claim_source_policy", lambda: policy() | dict(changed=1)
        )
        return result

    monkeypatch.setattr(reader.reader, "attest_claim_spans", change_after_proof)
    with pytest.raises(ValueError, match="S5_READER_POLICY_CHANGED"):
        reader.attest_claim_spans(graph, content, (ref,), tenant_id=graph.tenant_id)
    assert completed


def test_s5_hosted_child_accepts_only_registered_pin(tmp_path):
    from proofops.application.analysis_profile import S5_LIVE_POLICY

    from evaluation.hosted_r108 import prepare_argv
    from tests.test_hosted_analysis import source_pdf

    pdf = tmp_path / "original.pdf"
    pdf.write_bytes(source_pdf())
    pin = canonical_hash(S5_LIVE_POLICY)
    config = dict(
        analysis_profile="finals-unattended-v2",
        analysis_policy_sha256=pin,
        llm_provider="openai",
        report_year=2025,
        period_start="2025-01-01",
        period_end="2025-12-31",
    )
    argv = prepare_argv(
        pdf, tmp_path / "state", "tenant", config, dict(analysis_profile_sha256=pin)
    )
    assert argv[argv.index("--analysis-policy-sha256") + 1] == pin
    with pytest.raises(ValueError, match="PIN_MISMATCH"):
        prepare_argv(
            pdf, tmp_path / "state", "tenant", config, dict(analysis_profile_sha256="0" * 64)
        )


def test_raw_roi_cache_retains_large_working_set_and_keeps_identity_guards(monkeypatch):
    from collections import OrderedDict

    old_cache = fxh_claim_source.raster._reads.copy()
    monkeypatch.setattr(s5_claim_source._raw_raster, "_reads", OrderedDict())
    monkeypatch.setattr(fxh_claim_source.source_fxe, "policy", lambda: dict(version=1))
    calls = []
    response = dict(status="read", text="exact raw OCR")

    def submit(*args):
        calls.append(args)
        value = response.copy()
        return SimpleNamespace(result=lambda: value)

    def read(*, tenant="tenant", run="run", source=b"pdf", index=0):
        reader = object.__new__(s5_claim_source._ScopedFXERaster)
        reader.source, reader.visibility_hold = source, None
        page = SimpleNamespace(page_number=1, width=2000, height=2000)
        with fxh_claim_source.raster.scope(tenant, run, dict(profile="test")):
            return reader.read(page, (index, 0, index + 1, 1))

    token = fxh_claim_source.raster._pool.set(SimpleNamespace(submit=submit))
    try:
        for index in range(328):
            assert read(index=index) == response
        before = len(calls)
        for index in range(328):
            assert read(index=index) == response
        assert len(calls) == before
        for change in (dict(tenant="other"), dict(run="other"), dict(source=b"other")):
            read(**change)
        assert len(calls) == before + 6
        monkeypatch.setattr(fxh_claim_source.source_fxe, "policy", lambda: dict(version=2))
        read()
        assert len(calls) == before + 8
        response["status"] = "unavailable"
        read(index=999)
        read(index=999)
        assert len(calls) == before + 12  # failed raw reads are never retained
        response["status"] = "read"
        for index in range(1100):
            read(index=index)
        cache = s5_claim_source._raw_raster._reads
        assert len(cache) <= 1024
        assert sum(len(v) + 1024 for v in cache.values()) <= 8 * 1024 * 1024
        assert fxh_claim_source.raster._reads == old_cache
    finally:
        fxh_claim_source.raster._pool.reset(token)
