"""FXG eliminates transient local pixel retries while retaining full receipt gates."""

from copy import deepcopy
from dataclasses import asdict

import pytest
from proofops.adapters.local import claim_source_verification_v4 as v4
from proofops.adapters.local import fxg_claim_source as fxg
from proofops.adapters.local import upstage_ocr_profile_v21 as old
from proofops.adapters.local.claim_source_policies import page_ocr_profile, publication_reader
from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash

from tests.integration.test_claim_source_verification import inputs
from tests.integration.test_upstage_ocr_page import store


def test_opt_in_policy_preserves_defaults_and_historical_readers():
    assert (
        profiles.policy_for(
            profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I23_POLICY)
        )
        == profiles.FINALS_I23_POLICY
    )
    assert (
        profiles.policy_for(profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FXG_POLICY))
        == profiles.FXG_POLICY
    )
    assert profiles.FXG_POLICY["source"] == fxg.PROFILE
    assert publication_reader(fxg.claim_source_policy()) is fxg
    assert page_ocr_profile(old.PROFILE, policy=old.claim_source_policy()) is old
    assert fxg.native_policy() == old.native_policy()
    assert fxg.table_policy_sha256() == old.table_policy_sha256()


def test_pilot_pins_fxg_and_resumes_without_changing_saved_identity(tmp_path, monkeypatch):
    import json
    import os
    import sys

    from evaluation import local_upstage_pilot as pilot
    from tests.integration.test_finals_candidate_profile import create_argv

    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(
        sys,
        "argv",
        create_argv(tmp_path)
        + [
            "--analysis-profile",
            profiles.V2_PROFILE,
            "--analysis-policy-sha256",
            canonical_hash(profiles.FXG_POLICY),
            "--pages",
            "1",
            "--claim-pages",
            "1",
            "--mixed-ocr-max-pages",
            "1",
        ],
    )
    assert pilot.main() == 0
    state = tmp_path / "state"
    saved = {name: (state / name).read_bytes() for name in ("settings.json", "pilot.json")}
    for raw in saved.values():
        value = json.loads(raw)
        assert value["extraction_fxg_split"] is True
    assert json.loads(saved["settings.json"])["claim_source_policy"] == fxg.claim_source_policy()
    assert json.loads(saved["pilot.json"])["claim_source_profile"] == fxg.PROFILE
    monkeypatch.setattr(sys, "argv", ["pilot", "--resume", "--state", str(state)])
    assert pilot.main() == 0
    assert all((state / name).read_bytes() == raw for name, raw in saved.items())


def test_native_proof_and_source_offsets_are_unchanged(monkeypatch, tmp_path):
    source, graph, ref = inputs()
    db = store(tmp_path)
    monkeypatch.setattr(fxg.PageOCRStore, "from_env", lambda: db)
    monkeypatch.setattr(old.previous, "_post_png", db.transport)
    expected = v4.attest_claim_spans(graph, source, (ref,), tenant_id=graph.tenant_id)
    proof = fxg.for_run("fxg-native").attest_claim_spans(
        graph, source, (ref,), tenant_id=graph.tenant_id
    )
    assert proof["prose_receipt"]["records"] == expected["records"]
    assert proof["records"][0]["status"] == "verified"
    assert proof["records"][0]["ref"] == asdict(ref)
    assert (
        fxg.for_run("fxg-native").recompute_claim_receipt(
            proof, graph, source, (ref,), tenant_id=graph.tenant_id
        )
        == proof
    )


def test_transient_pixel_hash_breaks_old_replay_but_fxg_uses_retained_ocr(tmp_path, monkeypatch):
    source, graph, ref = inputs()
    db = store(tmp_path)
    monkeypatch.setattr(fxg.PageOCRStore, "from_env", lambda: db)
    monkeypatch.setattr(old.previous, "_post_png", db.transport)
    monkeypatch.setattr(
        v4, "_render_type_proof", lambda *_: dict(status="pixel_required", reason="inventory")
    )
    attempts = iter(("timeout", "read"))

    def volatile_pixel(*args, **kwargs):
        return dict(
            records=[dict(ref=asdict(ref), status="verified", reason=None)],
            artifact_sha256=canonical_hash(next(attempts)),
        )

    monkeypatch.setattr(v4.v3, "attest_claim_spans", volatile_pixel)
    legacy = old.for_run("fxg-pixel")
    receipt = legacy.attest_claim_spans(graph, source, (ref,), tenant_id=graph.tenant_id)
    with pytest.raises(ValueError, match="I20_CLAIM_RECEIPT_MISMATCH"):
        legacy.recompute_claim_receipt(receipt, graph, source, (ref,), tenant_id=graph.tenant_id)
    # No live local pixel result is consulted in the new profile.
    monkeypatch.setattr(
        v4.v3, "attest_claim_spans", lambda *a, **k: pytest.fail("unretained pixel retry")
    )
    receipt = fxg.for_run("fxg-pixel").attest_claim_spans(
        graph, source, (ref,), tenant_id=graph.tenant_id
    )
    assert receipt["prose_receipt"]["records"][0]["status"] == "pixel_required"
    assert receipt["records"][0]["status"] == "verified"
    db.transport = lambda *_: pytest.fail("cold replay must use authenticated saved collection")
    assert (
        fxg.for_run("fxg-pixel").recompute_claim_receipt(
            receipt, graph, source, (ref,), tenant_id=graph.tenant_id
        )
        == receipt
    )
    for field, value in (("status", "unresolved"), ("ref", asdict(ref) | dict(char_start=1))):
        forged = deepcopy(receipt)
        forged["records"][0][field] = value
        forged["artifact_sha256"] = canonical_hash(
            {k: v for k, v in forged.items() if k != "artifact_sha256"}
        )
        with pytest.raises(ValueError):
            fxg.for_run("fxg-pixel").recompute_claim_receipt(
                forged, graph, source, (ref,), tenant_id=graph.tenant_id
            )
    with pytest.raises(ValueError, match="CLAIM_SOURCE_MISMATCH"):
        fxg.for_run("fxg-pixel").recompute_claim_receipt(
            receipt, graph, source + b"modified", (ref,), tenant_id=graph.tenant_id
        )
