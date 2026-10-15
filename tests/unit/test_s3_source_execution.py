"""The v23 server's actual native mode is v21, not I21's v20 benchmark."""

from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from proofops.adapters.local import verified_read_cache as cache
from proofops.adapters.local.claim_source_policies import page_ocr_profile
from proofops.domain.provenance import canonical_hash

from tests.integration.test_claim_source_v3 import synthetic


@pytest.mark.parametrize("kind", ["native", "table"])
def test_native_v21_cold_recomputes_once_and_checks_entire_receipt(monkeypatch, kind):
    reader = page_ocr_profile("upstage-ocr-page-v21", native=True)
    source, graph, _ = synthetic("ESG policy 10% achieved")
    monkeypatch.setattr(
        reader.PageOCRStore,
        "from_env",
        lambda: SimpleNamespace(
            fetch=lambda *a, **k: (_ for _ in ()).throw(ValueError("OCR_COLLECTION_UNTRUSTED"))
        ),
    )
    instance = reader.for_run("s3")
    method = "attest_native_sources" if kind == "native" else "attest_tables"
    replay = instance.replay_native_sources if kind == "native" else instance.replay_tables
    receipt = getattr(instance, method)(graph, source, tenant_id=graph.tenant_id)
    expected = replay(receipt, graph, source, tenant_id=graph.tenant_id)
    # v12 falls through for the very same registered v21 native policy.
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v12")
    assert (
        cache._single_parse_replay(
            "native:" + reader.PROFILE,
            reader.native_policy(),
            receipt,
            graph,
            source,
            graph.tenant_id,
        )
        is None
    )
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "s3_exact-verified-read-v13")
    cache._results.clear()
    args = dict(
        reader_name="native:" + reader.PROFILE,
        policy=reader.native_policy(),
        receipt=receipt,
        graph=graph,
        source=source,
        tenant_id=graph.tenant_id,
        recompute=lambda *a, **k: pytest.fail("v21 fell through to nested legacy replay"),
    )
    actual = cache.replay_cached(**args)
    assert asdict(actual) == asdict(expected)
    forged = deepcopy(receipt)
    forged["s3_forged"] = True
    forged["artifact_sha256"] = canonical_hash(
        {k: v for k, v in forged.items() if k != "artifact_sha256"}
    )
    with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
        cache.replay_cached(**dict(args, receipt=forged))


def test_d2_acquisition_holds_keep_original_replay(monkeypatch):
    reader = page_ocr_profile("upstage-ocr-page-v21", native=True)
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "s3_exact-verified-read-v13")
    assert (
        cache._single_parse_replay(
            "native:" + reader.PROFILE,
            reader.native_policy(),
            {"table_acquisition_holds": [{"page": 1}]},
            None,
            b"",
            "tenant",
        )
        is None
    )


def test_s3_table_adapter_seeds_only_a_fresh_v21_attestation(monkeypatch):
    from proofops.adapters.local import s3_table_replay as adapter

    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "s3_exact-verified-read-v13")
    receipt = {"reader_policy": {"mode": "upstage-ocr-page-v21"}}
    monkeypatch.setattr(adapter.historical, "attest", lambda *a, **k: receipt)
    seeded = []
    monkeypatch.setattr(adapter, "remember_parse_attestation", lambda **k: seeded.append(k))
    assert adapter.attest(None, None, b"source", tenant_id="tenant") is receipt
    assert len(seeded) == 1 and seeded[0]["receipt"] is receipt
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v12")
    adapter.attest(None, None, b"source", tenant_id="tenant")
    assert len(seeded) == 1  # Prior profile is still delegated to the frozen adapter.


def test_d2_table_acquisition_failure_is_rechecked_on_every_read(monkeypatch):
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "s3_exact-verified-read-v13")
    receipt = {"table_acquisition_holds": [{"page": 1}]}
    assert (
        cache._parse_key(
            reader_name="native:upstage-ocr-page-v21",
            policy={},
            receipt=receipt,
            graph=None,
            source=b"",
            tenant_id="tenant",
        )
        is None
    )
    calls = []
    args = dict(
        reader_name="native:upstage-ocr-page-v21",
        policy={},
        receipt=receipt,
        graph=None,
        source=b"",
        tenant_id="tenant",
        recompute=lambda *a, **k: calls.append(1),
    )
    cache.replay_cached(**args)
    cache.replay_cached(**args)
    assert calls == [1, 1]


@pytest.mark.parametrize(
    "profile",
    [
        "fxe_upstage-ocr-page-v21",
        "fxf_upstage-ocr-page-v21",
        "fxg_claim_source_v1",
        "i24_claim_source_v1",
    ],
)
def test_prefixed_claim_reader_uses_full_replay_and_invalidates_warm_cache(monkeypatch, profile):
    from tests.unit.test_pa1_replay_cache import Graph

    reader = page_ocr_profile(profile)
    policy = reader.claim_source_policy()
    current = dict(policy)
    calls = []
    monkeypatch.setattr(reader, "claim_source_policy", lambda: dict(current))
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "s3_exact-verified-read-v13")
    cache._results.clear()

    def recompute(*a, **k):
        calls.append(1)
        if current != policy:
            raise ValueError("OCR_POLICY_OR_RUN_MISMATCH")
        return Graph("verified")

    args = dict(
        reader_name=reader.__name__,
        policy=policy,
        receipt={},
        graph=Graph("source"),
        discovery=Graph("claims"),
        source=b"pdf",
        tenant_id="tenant",
        recompute=recompute,
    )
    assert cache.replay_cached(**args) == Graph("verified")
    assert cache.replay_cached(**args) == Graph("verified")
    assert len(calls) == 1
    current["verifier_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="OCR_POLICY_OR_RUN_MISMATCH"):
        cache.replay_cached(**args)
    assert len(calls) == 2
