"""I21 composes v20 semantics and S2 execution without changing stored pins."""

from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from proofops.adapters.local import verified_read_cache as cache
from proofops.adapters.local.claim_source_policies import page_ocr_profile
from proofops.adapters.local.i21_reader_execution import reader_scope
from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash

from tests.integration.test_claim_source_v3 import synthetic


def test_v21_default_changes_only_execution_and_preserves_v20_and_s2_pins():
    old = profiles.FINALS_I20_POLICY
    policy = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I21_POLICY)
    )
    assert canonical_hash(old) == "56bbc5fa8c2f1fd9e9c709c82ba473dec20b907e44195256caaf86e8a926ca32"
    assert policy == profiles.FINALS_I21_POLICY
    assert policy["integration_profile"] == "finals-20261015-v21"
    assert policy["verified_read_cache"] == profiles.VERIFIED_READ_V12_POLICY
    exclude = {"integration_profile", "verified_read_cache"}
    assert {k: v for k, v in old.items() if k not in exclude} == {
        k: v for k, v in policy.items() if k not in exclude
    }
    for previous in (
        old,
        profiles.FINALS_I20_INITIAL_POLICY,
        profiles.FINALS_I19_POLICY,
        profiles.FINALS_P2_POLICY,
        profiles.FINALS_S2_SPEED_POLICY,
    ):
        pin = canonical_hash(previous)
        assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=pin) == previous
        assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=pin) == previous
    assert (
        canonical_hash(profiles.FINALS_S2_SPEED_POLICY)
        == "207d2c86400e8e81786c97a7ca6bf10e6258224889711a15b400942ff1aea1ca"
    )


@pytest.mark.parametrize("version", [19, 20, 21])
def test_private_execution_keeps_whole_claim_receipt_and_policy_guards(monkeypatch, version):
    reader = page_ocr_profile(f"upstage-ocr-page-v{version}")
    source, graph, ref = synthetic("ESG policy 10% achieved")
    monkeypatch.setattr(
        reader.PageOCRStore,
        "from_env",
        lambda: SimpleNamespace(
            fetch=lambda *a, **k: (_ for _ in ()).throw(ValueError("OCR_COLLECTION_UNTRUSTED"))
        ),
    )
    expected = reader.for_run("i21").attest_claim_spans(
        graph, source, (ref,), tenant_id=graph.tenant_id
    )
    with reader_scope(reader, run_id="i21", tenant_id=graph.tenant_id) as instance:
        actual = instance.attest_claim_spans(graph, source, (ref,), tenant_id=graph.tenant_id)
        assert actual == expected
        assert (
            instance.recompute_claim_receipt(
                actual, graph, source, (ref,), tenant_id=graph.tenant_id
            )
            == actual
        )
        forged = deepcopy(actual)
        forged["records"][0]["reason"] = "forged"
        forged["artifact_sha256"] = canonical_hash(
            {k: v for k, v in forged.items() if k != "artifact_sha256"}
        )
        with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
            instance.recompute_claim_receipt(
                forged, graph, source, (ref,), tenant_id=graph.tenant_id
            )
    original = reader.claim_source_policy
    with pytest.raises(ValueError, match="S2_READER_POLICY_CHANGED"):
        with reader_scope(reader, run_id="i21", tenant_id=graph.tenant_id):
            monkeypatch.setattr(
                reader, "claim_source_policy", lambda: original() | dict(changed=True)
            )


def test_native_v20_recomputes_once_and_rejects_forged_receipt(monkeypatch):
    reader = page_ocr_profile("upstage-ocr-page-v20")
    source, graph, _ = synthetic("ESG policy 10% achieved")
    monkeypatch.setattr(
        reader.PageOCRStore,
        "from_env",
        lambda: SimpleNamespace(
            fetch=lambda *a, **k: (_ for _ in ()).throw(ValueError("OCR_COLLECTION_UNTRUSTED"))
        ),
    )
    instance = reader.for_run("i21")
    receipt = instance.attest_native_sources(graph, source, tenant_id=graph.tenant_id)
    expected = instance.replay_native_sources(receipt, graph, source, tenant_id=graph.tenant_id)
    calls = []
    attest = instance.attest_native_sources

    def counted(*args, **kwargs):
        calls.append(1)
        return attest(*args, **kwargs)

    monkeypatch.setattr(instance, "attest_native_sources", counted)
    monkeypatch.setattr(reader, "for_run", lambda run: instance)
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v12")
    cache._results.clear()
    args = dict(
        reader_name="native:" + reader.PROFILE,
        policy=reader.native_policy(),
        receipt=receipt,
        graph=graph,
        source=source,
        tenant_id=graph.tenant_id,
        recompute=lambda *a, **k: pytest.fail("nested whole proof repeated"),
    )
    actual = cache.replay_cached(**args)
    assert asdict(actual) == asdict(expected)
    assert calls == [1]
    assert cache.replay_cached(**args) == actual
    assert calls == [1]
    forged = deepcopy(receipt)
    forged["records"][0]["reason"] = "forged"
    forged["artifact_sha256"] = canonical_hash(
        {k: v for k, v in forged.items() if k != "artifact_sha256"}
    )
    with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
        cache.replay_cached(**(args | dict(receipt=forged)))
