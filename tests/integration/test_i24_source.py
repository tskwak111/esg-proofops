"""Composed FXG/FXE/FXF source replay, with historical readers kept isolated."""

from copy import deepcopy

import pytest
from proofops.adapters.local import fxg_claim_source as fxg
from proofops.adapters.local import i24_claim_source as current
from proofops.adapters.local import upstage_ocr_profile_fxe as fxe
from proofops.adapters.local import upstage_ocr_profile_fxf as fxf
from proofops.adapters.local.claim_source_policies import page_ocr_profile
from proofops.domain.provenance import canonical_hash


def test_composition_pins_all_three_readers_without_mutating_historical_modules():
    assert page_ocr_profile(current.PROFILE, policy=current.claim_source_policy()) is current
    assert current._fxe.previous is fxg
    assert current._fxf.previous is current._fxe
    assert fxe.previous.PROFILE == "upstage-ocr-page-v21"
    assert fxf.previous is fxe
    assert current.claim_source_policy()["previous_policy_sha256"] == canonical_hash(
        current._fxe.claim_source_policy()
    )
    assert current._fxe.claim_source_policy()["previous_policy_sha256"] == canonical_hash(
        fxg.claim_source_policy()
    )
    assert current.native_policy() == fxf.native_policy()
    assert current.table_policy_sha256() == fxf.table_policy_sha256()


def test_composed_replay_uses_retained_pixels_and_rejects_rewritten_receipt(tmp_path, monkeypatch):
    from proofops.adapters.local import claim_source_verification_v4 as v4
    from proofops.adapters.local import upstage_ocr_profile_v21 as old

    from tests.integration.test_claim_source_verification import inputs
    from tests.integration.test_upstage_ocr_page import store

    source, graph, ref = inputs()
    db = store(tmp_path)
    monkeypatch.setattr(current.PageOCRStore, "from_env", lambda: db)
    monkeypatch.setattr(old.previous, "_post_png", db.transport)
    monkeypatch.setattr(
        v4, "_render_type_proof", lambda *_: dict(status="pixel_required", reason="inventory")
    )
    monkeypatch.setattr(
        v4.v3, "attest_claim_spans", lambda *a, **k: pytest.fail("unretained pixel retry")
    )
    reader = current.for_run("i24-pixel")
    receipt = reader.attest_claim_spans(graph, source, (ref,), tenant_id=graph.tenant_id)
    assert receipt["records"][0]["status"] == "verified"
    baseline = receipt["previous_receipt"]["previous_receipt"]
    assert baseline["policy"] == fxg.claim_source_policy()
    assert baseline["prose_receipt"]["records"][0]["status"] == "pixel_required"
    db.transport = lambda *_: pytest.fail("cold replay must not acquire OCR")
    assert (
        reader.recompute_claim_receipt(receipt, graph, source, (ref,), tenant_id=graph.tenant_id)
        == receipt
    )
    for level in ((), ("previous_receipt",), ("previous_receipt", "previous_receipt")):
        forged = deepcopy(receipt)
        target = forged
        for name in level:
            target = target[name]
        target["records"][0]["status"] = "unresolved"
        forged["artifact_sha256"] = canonical_hash(
            {k: v for k, v in forged.items() if k != "artifact_sha256"}
        )
        with pytest.raises(ValueError):
            reader.recompute_claim_receipt(forged, graph, source, (ref,), tenant_id=graph.tenant_id)
