"""HX3: outcome uses extraction bytes even after source admission changes quality."""

import logging
from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from proofops.adapters.local import evidence_source_hx3, source_hx3
from proofops.adapters.local import upstage_ocr_profile_v16 as hx3
from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash

from tests.acceptance.test_upload import TENANT
from tests.integration.test_claim_source_v3 import synthetic
from tests.integration.test_extract_batch_continuation import setup_run


def test_source_promoted_discovery_uses_exact_admitted_extraction_checkpoint(tmp_path, monkeypatch):
    from tests.integration.test_real_extract_runner import FakeProbe

    service, run, runner, _, _, _ = setup_run(
        tmp_path, monkeypatch, paragraphs=2, probe=FakeProbe('{"claims":["carbon emission"]}')
    )
    assert runner.run_once(tenant_id=TENANT, run_id=run) == "committed"
    checkpoint, discovery, _ = runner.claims.load_evidence(TENANT, run)
    verified = replace(
        discovery,
        claims=tuple(
            replace(
                c,
                source_quality="verified",
                source_refs=tuple(replace(r, verification_state="verified") for r in c.source_refs),
            )
            for c in discovery.claims
        ),
    )
    assert canonical_hash(asdict(verified)) != canonical_hash(checkpoint["discovery"])
    before = deepcopy(checkpoint)
    assert runner.claims.outcome_projection(TENANT, run, admitted_checkpoint=checkpoint) == (
        {"extraction_outcome": checkpoint["extraction_outcome"]}
        if "extraction_outcome" in checkpoint
        else {}
    )
    assert checkpoint == before
    forged = deepcopy(checkpoint)
    forged["discovery"]["claims"][0]["claim_text"] = "altered"
    with pytest.raises(ValueError, match="CLAIM_SNAPSHOT_REPLAY_MISMATCH"):
        runner.claims.outcome_projection(TENANT, run, admitted_checkpoint=forged)


def test_hx3_pin_preserves_v14_and_routes_new_readers():
    from proofops.adapters.local.claim_source_policies import claim_source_reader
    from proofops.adapters.local.evidence_source_policies import evidence_source_reader
    from proofops.adapters.local.run_artifacts import accepted_native_policy_digests

    pin = canonical_hash(profiles.FINALS_I16_POLICY)
    args = SimpleNamespace(
        analysis_profile=profiles.V2_PROFILE, resume=False, analysis_policy_sha256=pin
    )
    profiles.apply_pilot_profile(args)
    assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=pin) == profiles.FINALS_I16_POLICY
    assert args.claim_source_profile == hx3.PROFILE
    assert args.analysis_policy_sha256 != canonical_hash(profiles.FINALS_I13_POLICY)
    assert canonical_hash(profiles.FINALS_I13_POLICY) == (
        "05770a9a6e8a4a42270666b28234bd0f0103634397a717a42934a96f2f89a11c"
    )
    assert (
        profiles.publication_policy_for(
            profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I13_POLICY)
        )
        == profiles.FINALS_I13_POLICY
    )
    assert claim_source_reader(hx3.claim_source_policy()) is hx3
    assert evidence_source_reader(evidence_source_hx3.policy()) is evidence_source_hx3
    assert canonical_hash(hx3.native_policy()) in accepted_native_policy_digests()


def test_one_literal_read_failure_holds_only_that_item_and_replays(monkeypatch, caplog):
    from proofops.adapters.local import evidence_source_verification_v1 as base

    source, graph, _ = synthetic("ESG policy 10% achieved")
    block = graph.blocks[0]
    bad = replace(block, source_id="hx3-bad-item")
    graph = replace(graph, blocks=(block, bad))
    original = evidence_source_hx3._exec_private

    def private(*args, **kwargs):
        module = original(*args, **kwargs)
        literal = module._literal

        def read(document, native, graph, item, cache, **kw):
            if item.source_id == bad.source_id:
                raise ValueError("secret-key-and-private-source-must-not-appear")
            return literal(document, native, graph, item, cache, **kw)

        module._literal = read
        return module

    monkeypatch.setattr(evidence_source_hx3, "_exec_private", private)
    monkeypatch.setattr(
        __import__("proofops.adapters.local.source_h7", fromlist=["_ocr"]),
        "_ocr",
        lambda png: dict(text="ESG policy 10% achieved"),
    )
    with caplog.at_level(logging.WARNING):
        receipt = evidence_source_hx3.attest_evidence_sources(
            graph, source, tenant_id=graph.tenant_id
        )
        evidence_source_hx3.replay_evidence_sources(
            receipt, graph, source, tenant_id=graph.tenant_id
        )
    assert receipt["records"][0]["status"] == "verified"
    assert receipt["records"][1]["status"] == "unresolved"
    assert receipt["records"][1]["reason"] == "source_item_read_unresolved"
    assert "secret-key-and-private-source" not in caplog.text
    assert "stage=source_verification location=" in caplog.text
    assert ".read:" in caplog.text
    assert base.policy() != evidence_source_hx3.policy()


@pytest.mark.parametrize(
    "code", ["OCR_CLAIM_RECEIPT_MISMATCH", "EVIDENCE_SOURCE_MISMATCH", "TENANT_MISMATCH"]
)
def test_item_boundary_cannot_hide_integrity_failure(code):
    def broken(*args):
        raise ValueError(code)

    with pytest.raises(ValueError, match=code):
        source_hx3.hold_read(broken)()


def test_hx3_normal_claim_and_native_replay_remain_strict(monkeypatch, tmp_path):
    from proofops.adapters.local import source_verification

    from tests.integration.test_upstage_ocr_page import store

    source, graph, ref = synthetic("ESG policy 10% achieved")
    monkeypatch.setattr(
        source_verification,
        "_rendered_text",
        lambda *a, **kw: dict(
            status="read", text="ESG policy 10% achieved", pixel_bbox=[210, 195, 1200, 285], scale=3
        ),
    )
    reader = hx3.Reader(
        store(tmp_path, lambda *a: pytest.fail("paid OCR")), run_id="hx3-regression"
    )
    native = reader.attest_native_sources(graph, source, tenant_id=graph.tenant_id)
    assert (
        reader.replay_native_sources(native, graph, source, tenant_id=graph.tenant_id)
        .blocks[0]
        .quality
        == "verified"
    )
    receipt = reader.attest_claim_spans(graph, source, (ref,), tenant_id=graph.tenant_id)
    assert receipt["records"][0]["status"] == "verified"
    reader.recompute_claim_receipt(receipt, graph, source, (ref,), tenant_id=graph.tenant_id)
    forged = deepcopy(receipt)
    forged["records"][0]["status"] = "unresolved"
    with pytest.raises(ValueError, match="OCR_CLAIM_RECEIPT_MISMATCH"):
        reader.recompute_claim_receipt(forged, graph, source, (ref,), tenant_id=graph.tenant_id)


def test_hosted_failure_logs_stage_and_location_without_exception_text(
    settings, monkeypatch, caplog
):
    from proofops_api.hosted_store import HostedStore

    store = HostedStore(settings)
    # Use normal intake; leave the claimed job available to tick.
    from tests.test_hosted_public import actor, uploaded

    auth = actor(store)
    document = uploaded(store, auth)
    store.create_run(
        auth, document["document_id"], [1], "hx3-log-run00001", now=__import__("time").time()
    )

    def broken(store, job, prepared):
        store.update_progress(job, "result", 95)
        raise ValueError("private-source-and-key")

    with caplog.at_level(logging.WARNING):
        done = store.tick(now=__import__("time").time(), analysis=broken)
    assert done["status"] == "failed"
    assert "stage=result location=" in caplog.text
    assert ".broken:" in caplog.text
    assert "private-source-and-key" not in caplog.text


@pytest.fixture
def settings(tmp_path):
    from tests.test_hosted_public import settings as fixture

    return fixture.__wrapped__(tmp_path)
