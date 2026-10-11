"""PA4 response reuse retains PB4 evidence, PA7 execution and historical pins."""

import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest
from proofops.application.analysis_profile import (
    MODEL_RESPONSE_POLICY,
    V2_PA4_POLICY,
    V2_PRE_PA8_POLICY,
    policy_for,
)
from proofops.application.analysis_profile import (
    V2_PRE_PA9_POLICY as V2_POLICY,
)
from proofops.domain.provenance import canonical_hash

from tests.unit import test_pa7_extract_cache as pa7
from tests.unit.test_pa4_model_reuse import probe, snapshot

fresh = pa7.fresh


def test_every_historical_policy_remains_readable():
    for digest in (
        "75307d385ca8e4147ecb4dcebe9762f8d0abcbe1f92224c00bc31f2da9366729",
        "6327fc11289cb57f52b8bdcf32b72945a15310e74abf613cd4bb6f10d244d777",
        "73ab80d29edc6281e39514e8b910282d7383c3b4525ac80645876f9abe3e3c78",
        "626d4f0075d7c66dd938aa9a04242943cfb7db0a5cc2ee073a53e90f7ead9ec1",
        "3f1ea21f49dd2b9bf6b58c5b2c84abaadfba203b2dda3415d00ae93b29e8e3d8",
        "54a118c81f4a0c32fd83f07a32fea51b734d6de2de4884e31bd4fb675b29c67d",
        "4209c3881df2cf392d54a9ed5fcdef5e125bd43ffb6866d67134bc99235f1e22",
        "2c4fbd7ba2bc27c26207cd7fb19f41c9829d2eee2ddbe0ab51cbc68baea5ecb2",
        "a54e4d8ee846212aa69ed83430bc157837975c9507b1750093b0af9409cab2c1",
        "de8e156a804c27f5ec9197332273e1245f14cd92e2a6e113c923dfb563b9aef7",
        "d2bb24cc356e25029b384a5fe926866594e002b67a128c8a442f8ff498336f15",
        "ff1cafde4a89d770fc12fe523248b9acca104ec3fca98e19d0fb465cf72111d1",
        "491cc71fc038a563fe8f7f3c17aa2445181da1f8d92ef98f90ee8eaf93d3135a",
        "58755cb54e60ee3e6176df3a57957a55de25b3953afbe00df46b3e0390731884",
        "196d611664f355efa58278f58ea24f87f6b2b8fee45269a56158fb96b4d18aee",
        "ec63057b3bd775240bf10bcd90afefd7881bb112e47e772799d50ff33b7cc11a",
    ):
        assert canonical_hash(policy_for("finals-unattended-v2", pinned_hash=digest)) == digest
    assert canonical_hash(V2_PRE_PA8_POLICY) == (
        "ec63057b3bd775240bf10bcd90afefd7881bb112e47e772799d50ff33b7cc11a"
    )
    assert canonical_hash(V2_PA4_POLICY) == (
        "a6bc7a720704e3538f8dd5bf0cd837bb3e598481b38c5ab52bab4f8896ba4aa1"
    )
    assert V2_POLICY == V2_PRE_PA8_POLICY | dict(model_response_policy=MODEL_RESPONSE_POLICY)
    assert V2_POLICY["source"] == "upstage-ocr-page-v9"
    assert V2_POLICY["verified_read_cache"]["profile"] == "exact-verified-read-v4"


@pytest.mark.parametrize("change", ["tenant", "replica", "receipt", "graph", "policy"])
def test_pb4_v9_pa7_response_reuse_keeps_complete_evidence_boundaries(tmp_path, fresh, change):
    from proofops.adapters.local.native_replay_cache import replay_claims_cached

    from tests.unit.test_openai_luna import response

    args, calls, expected = fresh
    assert replay_claims_cached(**args) == expected
    assert calls == []  # PA7 fresh proof reused with all v9 ownership checks.
    wire = dict(
        graph_sha256=canonical_hash(asdict(args["graph"])),
        source_receipt_sha256=canonical_hash(args["receipt"]),
        table_source_ref=asdict(args["discovery"].claims[0].source_refs[0]),
    )
    scope = snapshot(args["tenant_id"])
    scope["document"]["sha256"] = args["receipt"]["source_sha256"]
    first = probe(tmp_path, "first", scope)
    first._post = lambda _: response()
    user = json.dumps(wire, sort_keys=True)
    with first.response_context(role="elements", replica=1):
        original = first.complete("Table JSON", user, request_id="first", json_mode=True)
    second = probe(tmp_path, "second", scope)
    second._post = lambda _: pytest.fail("duplicate dispatch")
    with second.response_context(role="elements", replica=1):
        reused = second.complete("Table JSON", user, request_id="second", json_mode=True)
    assert reused["content"] == original["content"]
    assert reused["response_sha256"] == original["response_sha256"]
    assert reused["response_reuse"]["source_receipt_sha256"] == canonical_hash(
        {k: v for k, v in original.items() if k != "content"}
    )
    assert reused["cost_with_vat_reserve_usd"] == "0"
    altered = deepcopy(wire)
    if change == "tenant":
        scope["tenant_id"] = "foreign-tenant"
    elif change == "receipt":
        receipt = deepcopy(args["receipt"])
        receipt["pb1_cell_proofs"][0]["status"] = "unresolved"
        altered["source_receipt_sha256"] = canonical_hash(receipt)
    elif change == "graph":
        graph = asdict(args["graph"])
        graph["blocks"][0]["source_id"] += "changed"
        altered["graph_sha256"] = canonical_hash(graph)
    elif change == "policy":
        scope["analysis_profile_policy"] = deepcopy(V2_PA4_POLICY)
        scope["analysis_profile_policy_sha256"] = canonical_hash(V2_PA4_POLICY)
    third = probe(tmp_path, "third", scope)
    sent = []
    third._post = lambda body: sent.append(body) or response()
    with third.response_context(role="elements", replica=2 if change == "replica" else 1):
        result = third.complete(
            "Table JSON", json.dumps(altered, sort_keys=True), request_id="third", json_mode=True
        )
    assert len(sent) == 1 and "response_reuse" not in result
    assert replay_claims_cached(**args) == expected  # Response cache mutates no source proof.


def test_reconfiguring_probe_to_historical_snapshot_restores_original_wire(tmp_path):
    p = probe(tmp_path, "switch")
    assert "top_p" in p.request_body("JSON", "{}", request_id="new")
    p.configure_response_policy(dict(analysis_profile_policy=V2_PRE_PA8_POLICY), role="extract")
    assert p.response_policy is None
    assert "top_p" not in p.request_body("JSON", "{}", request_id="old")
    from proofops.adapters.local.openai import WIRE_POLICY

    assert p.wire_policy == WIRE_POLICY


def test_pb4_frozen_reader_is_unchanged():
    from hashlib import sha256

    from proofops.adapters.local import upstage_ocr_profile_v9

    assert (
        sha256(Path(upstage_ocr_profile_v9.__file__).read_bytes()).hexdigest()
        == (V2_POLICY["verified_read_cache"]["v9_replay_sha256"])
    )


@pytest.mark.parametrize("change", ["active", "cancel", "expired", "delete", "wait-cancel"])
def test_hosted_reuse_rechecks_live_fence_and_source_before_cache_access(
    tmp_path, monkeypatch, change
):
    import time

    from proofops_api.hosted_analysis import HostedOpenAILunaProbe
    from proofops_api.hosted_store import HostedError

    from tests.test_hosted_analysis import job_setup
    from tests.test_hosted_public import settings
    from tests.unit.test_openai_luna import response

    store, auth, job = job_setup(settings.__wrapped__(tmp_path))
    cache = store.document_dir(auth.tenant_id, job["document_id"]) / "model-responses.sqlite3"
    scope = snapshot(auth.tenant_id)
    first = HostedOpenAILunaProbe(
        "fake", tmp_path / "first.sqlite3", store=store, job=job, post=lambda _: response()
    )
    first.response_cache_path = cache
    first.configure_response_policy(scope, role="extract")
    first.complete("JSON", "{}", request_id="first", json_mode=True)
    second = HostedOpenAILunaProbe(
        "fake",
        tmp_path / "second.sqlite3",
        store=store,
        job=job,
        post=lambda _: pytest.fail("dispatch after authorization ended"),
    )
    second.response_cache_path = cache
    second.configure_response_policy(scope, role="extract")
    if change == "cancel":
        store.cancel(auth, job["run_id"], now=time.time())
    elif change == "expired":
        with store.transaction() as db:
            db.execute("UPDATE documents SET expires=0 WHERE document_id=?", (job["document_id"],))
    elif change == "delete":
        store.delete_document(auth, job["document_id"], "delete-pa8-document", now=time.time())
    elif change == "wait-cancel":
        from proofops.adapters.local.model_response_cache import ModelResponseCache

        claim = ModelResponseCache.claim

        def cancel_during_wait(*args):
            hit = claim(*args)
            store.cancel(auth, job["run_id"], now=time.time())
            return hit

        monkeypatch.setattr(ModelResponseCache, "claim", cancel_during_wait)
    if change == "active":
        reused = second.complete("JSON", "{}", request_id="second", json_mode=True)
        assert reused["response_reuse"] and reused["cost_with_vat_reserve_usd"] == "0"
    else:
        with pytest.raises(HostedError):
            second.complete("JSON", "{}", request_id="second", json_mode=True)
    if change == "delete":
        assert not cache.parent.exists()
    assert second.summary()["committed_usd"] == "0"
