"""Registry-based execution retains whole receipts, source guards and old pins."""

import json
import sqlite3
from argparse import Namespace
from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from proofops.adapters.local import upstage_ocr_profile_v19 as reader
from proofops.adapters.local import verified_read_cache as cache
from proofops.adapters.local.claim_source_policies import page_ocr_profile
from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash
from proofops_api import hosted_publication as handoff

from tests.integration.test_batch_attestation_cache import discovery_for
from tests.integration.test_claim_source_v3 import synthetic
from tests.unit.test_s4_publication_handoff import state as handoff_state


@pytest.fixture
def state(tmp_path, monkeypatch):
    return handoff_state.__wrapped__(tmp_path, monkeypatch)


def test_default_and_later_policy_use_registered_reader(monkeypatch):
    for selected in (
        profiles.FINALS_I18_POLICY,
        profiles.FINALS_I18_POLICY | dict(integration_profile="future-policy-regression"),
    ):
        monkeypatch.setattr(profiles, "V2_POLICY", selected)
        args = Namespace(analysis_profile=profiles.V2_PROFILE, resume=False)
        profiles.apply_pilot_profile(args)
        assert args.claim_source_profile == reader.PROFILE
        assert args.analysis_policy_sha256 == canonical_hash(selected)
        for key, value in profiles.FINALS_I17_POLICY.items():
            if key not in {
                "integration_profile",
                "source",
                "local_resource_policy",
                "verified_read_cache",
                "publication_handoff",
            }:
                assert selected[key] == value


def test_normal_store_and_collection_only_cold_replay(monkeypatch):
    source, graph, ref = synthetic("ESG policy 10% achieved")
    calls = []

    def missing(*args, **kwargs):
        calls.append(1)
        raise ValueError("OCR_COLLECTION_UNTRUSTED")

    store = SimpleNamespace(fetch=missing)
    monkeypatch.setattr(reader.PageOCRStore, "from_env", lambda: store)
    instance = reader.for_run("i18")
    assert instance.previous.store is store
    receipt = instance.attest_claim_spans(graph, source, (ref,), tenant_id=graph.tenant_id)
    assert calls
    calls.clear()
    assert (
        instance.recompute_claim_receipt(receipt, graph, source, (ref,), tenant_id=graph.tenant_id)
        == receipt
    )
    assert calls == []
    forged = deepcopy(receipt)
    forged["records"][0]["reason"] = "forged-receipt"
    forged["artifact_sha256"] = canonical_hash(
        {k: v for k, v in forged.items() if k != "artifact_sha256"}
    )
    with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
        instance.recompute_claim_receipt(forged, graph, source, (ref,), tenant_id=graph.tenant_id)


def test_registered_fresh_claim_reuse_and_scope_guards(monkeypatch):
    source, graph, ref = synthetic("ESG policy 10% achieved")
    monkeypatch.setattr(
        reader.PageOCRStore,
        "from_env",
        lambda: SimpleNamespace(
            fetch=lambda *a, **k: (_ for _ in ()).throw(ValueError("OCR_COLLECTION_UNTRUSTED"))
        ),
    )
    receipt = reader.for_run("i18").attest_claim_spans(
        graph, source, (ref,), tenant_id=graph.tenant_id
    )
    policy = reader.claim_source_policy()
    discovery = discovery_for(graph, (ref,))
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", profiles.VERIFIED_READ_V10_POLICY["profile"])
    cache._results.clear()
    cache.remember_fresh_attestation(
        reader=reader,
        policy=policy,
        receipt=receipt,
        graph=graph,
        source=source,
        refs=(ref,),
        tenant_id=graph.tenant_id,
    )
    args = dict(
        reader=reader,
        policy=policy,
        receipt=receipt,
        graph=graph,
        source=source,
        discovery=discovery,
        tenant_id=graph.tenant_id,
    )
    assert cache.reuse_fresh_attestation(**args) is not None
    for change in (
        dict(source=source + b"x"),
        dict(tenant_id="other"),
        dict(graph=replace(graph, parse_manifest_id="11111111-1111-4111-8111-111111111111")),
        dict(receipt=receipt | dict(run_id="other")),
        dict(policy=policy | dict(verifier_sha256="0" * 64)),
    ):
        assert cache.reuse_fresh_attestation(**(args | change)) is None


def test_parse_fresh_projection_matches_cold_native_and_evidence(monkeypatch):
    from proofops.adapters.local import evidence_source_i17 as evidence

    source, graph, _ = synthetic("ESG policy 10% achieved")
    monkeypatch.setattr(
        reader.PageOCRStore,
        "from_env",
        lambda: SimpleNamespace(
            fetch=lambda *a, **k: (_ for _ in ()).throw(ValueError("OCR_COLLECTION_UNTRUSTED"))
        ),
    )
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", profiles.VERIFIED_READ_V10_POLICY["profile"])
    instance = reader.for_run("i18")
    native = instance.attest_native_sources(graph, source, tenant_id=graph.tenant_id)
    proof = evidence.attest_evidence_sources(graph, source, tenant_id=graph.tenant_id)
    for name, policy, receipt, recompute in (
        (
            "native:" + reader.PROFILE,
            reader.native_policy(),
            native,
            instance.replay_native_sources,
        ),
        (evidence.__name__, evidence.policy(), proof, evidence.replay_evidence_sources),
    ):
        cold = recompute(receipt, graph, source, tenant_id=graph.tenant_id)
        args = dict(
            reader_name=name,
            policy=policy,
            receipt=receipt,
            graph=graph,
            source=source,
            tenant_id=graph.tenant_id,
        )
        cache.remember_parse_attestation(**args)
        warm = cache._fresh_parse_replay(**args)
        assert warm is not None
        assert asdict(warm) == asdict(cold)


@pytest.mark.parametrize("future", [False, True])
def test_registered_publication_handoff_and_forged_policy_rejection(state, monkeypatch, future):
    path, job, calls, content = state
    policy = profiles.FINALS_I18_POLICY | (
        dict(integration_profile="future-regression") if future else {}
    )
    if future:
        monkeypatch.setattr(profiles, "V2_POLICY", policy)
    snapshot = dict(
        analysis_profile_policy=policy, claim_source_policy=reader.claim_source_policy()
    )
    with sqlite3.connect(path / "state.sqlite3") as db:
        db.execute("UPDATE run_snapshots SET payload=?", (json.dumps(snapshot),))
    packet = handoff.make_handoff(path, job, [13])
    assert packet is not None
    assert handoff.reuse_handoff(packet, path, job, [13]) == content
    assert calls == [1]
    snapshot["claim_source_policy"]["verifier_sha256"] = "0" * 64
    with sqlite3.connect(path / "state.sqlite3") as db:
        db.execute("UPDATE run_snapshots SET payload=?", (json.dumps(snapshot),))
    assert handoff.make_handoff(path, job, [13]) is None


def test_colliding_rg1_reader_pin_is_preserved():
    from proofops.adapters.local import upstage_ocr_profile_rg1_v17 as rg1
    from proofops.adapters.local import upstage_ocr_profile_v17 as hx4

    for module in (rg1, hx4):
        assert page_ocr_profile(module.PROFILE, policy=module.claim_source_policy()) is module
        assert (
            page_ocr_profile(module.PROFILE, policy=module.native_policy(), native=True) is module
        )
    for policy in (profiles.FINALS_I17_POLICY, profiles.FINALS_RG1_POLICY):
        pin = canonical_hash(policy)
        assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=pin) == policy
        assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=pin) == policy


def test_explicit_historical_rg1_run_selects_its_colliding_reader():
    from proofops.adapters.local import upstage_ocr_profile_rg1_v17 as rg1

    args = Namespace(
        analysis_profile=profiles.V2_PROFILE,
        analysis_policy_sha256=canonical_hash(profiles.FINALS_RG1_POLICY),
        resume=False,
    )
    profiles.apply_pilot_profile(args)
    assert args.claim_source_profile == "upstage-ocr-page-v17-rg1"
    assert page_ocr_profile(args.claim_source_profile) is rg1
    assert args.analysis_policy_sha256 == canonical_hash(profiles.FINALS_RG1_POLICY)
