"""P3: failed acquisition and absent replay collections must select the same proof."""

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from proofops.adapters.local import authorized_ocr_execution as execution
from proofops.adapters.local import source_h7
from proofops.adapters.local import upstage_ocr_profile_v20 as reader
from proofops.adapters.local.claim_source_policies import page_ocr_profile
from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash

from tests.integration.test_selected_cell_table_verification import (
    LAYOUT_A_CELLS,
    LAYOUT_A_WORDS,
    grid_pdf,
    table_graph,
)


@pytest.mark.parametrize(
    "failure",
    ["OCR_PENDING_OR_FAILED", "OCR_COLLECTION_FAILED_RESERVATION_RETAINED:OCR_SNAPSHOT_DRIFT"],
)
def test_failed_table_acquisition_replays_the_same_local_proof(monkeypatch, failure):
    source = grid_pdf(LAYOUT_A_WORDS)
    graph = table_graph(source, LAYOUT_A_CELLS)
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(1)
        raise ValueError(failure)

    monkeypatch.setattr(
        source_h7.RasterReader,
        "read",
        lambda self, page, box, **kwargs: dict(
            status="read", text=page.crop(box).extract_text() or "", reader="unit-fixture"
        ),
    )
    monkeypatch.setattr(reader.PageOCRStore, "from_env", lambda: SimpleNamespace(fetch=unavailable))
    fresh = reader.for_run("p3")
    receipt = fresh.attest_tables(graph, source, tenant_id=graph.tenant_id)
    assert calls
    calls.clear()
    projected = reader.for_run("p3").replay_tables(
        receipt, graph, source, tenant_id=graph.tenant_id
    )
    assert calls == []
    with execution.retained_collections(fresh, receipt):
        assert fresh.attest_tables(graph, source, tenant_id=graph.tenant_id) == receipt
    expected = {
        selection["value_source_id"]
        for record in receipt["records"]
        for selection in record["selections"]
    }
    assert expected
    # Preserve v19's projection contract; P3 changes acquisition/replay only.
    assert projected == graph


def test_unreadable_fallback_keeps_table_unverified(monkeypatch):
    source = grid_pdf(LAYOUT_A_WORDS)
    graph = table_graph(source, LAYOUT_A_CELLS)
    monkeypatch.setattr(
        source_h7.RasterReader,
        "read",
        lambda *a, **k: dict(status="unresolved", reason="h7_raster_unresolved"),
    )
    monkeypatch.setattr(
        reader.PageOCRStore,
        "from_env",
        lambda: SimpleNamespace(
            fetch=lambda *a, **k: (_ for _ in ()).throw(ValueError("OCR_PENDING_OR_FAILED"))
        ),
    )
    receipt = reader.for_run("p3").attest_tables(graph, source, tenant_id=graph.tenant_id)
    assert not any(record["selections"] for record in receipt["records"])
    projected = reader.for_run("p3").replay_tables(
        receipt, graph, source, tenant_id=graph.tenant_id
    )
    assert projected == graph


@pytest.mark.parametrize(
    "failure",
    ["OCR_SOURCE_MISMATCH", "OCR_PAGE_COORDINATE_MISMATCH", "OCR_COLLECTION_UNTRUSTED"],
)
def test_availability_adapter_preserves_integrity_errors(failure):
    def reject(*args, **kwargs):
        raise ValueError(failure)

    wrapped = reader._AvailableStore(SimpleNamespace(fetch=reject, validate=reject))
    for call in (wrapped.fetch, wrapped.validate):
        with pytest.raises(ValueError, match=f"^{failure}$"):
            call()


def test_table_replay_rejects_identity_and_rehashed_forgery(monkeypatch):
    source = grid_pdf(LAYOUT_A_WORDS)
    graph = table_graph(source, LAYOUT_A_CELLS)
    monkeypatch.setattr(
        source_h7.RasterReader,
        "read",
        lambda self, page, box, **kwargs: dict(
            status="read", text=page.crop(box).extract_text() or "", reader="unit-fixture"
        ),
    )
    monkeypatch.setattr(
        reader.PageOCRStore,
        "from_env",
        lambda: SimpleNamespace(
            fetch=lambda *a, **k: (_ for _ in ()).throw(ValueError("OCR_PENDING_OR_FAILED"))
        ),
    )
    instance = reader.for_run("p3")
    receipt = instance.attest_tables(graph, source, tenant_id=graph.tenant_id)
    for changes in (
        dict(tenant_id="22222222-2222-4222-8222-222222222222"),
        dict(source=source + b"changed"),
        dict(graph=replace(graph, parse_manifest_id="11111111-1111-4111-8111-111111111111")),
    ):
        with pytest.raises(ValueError):
            instance.replay_tables(
                receipt, **(dict(graph=graph, source=source, tenant_id=graph.tenant_id) | changes)
            )
    for change in (
        lambda r: r.update(run_id="other"),
        lambda r: r["reader_policy"].update(mode="forged-policy"),
        lambda r: r["records"][0]["selections"][0].update(value_text="9999"),
        lambda r: r["base_receipt"]["records"][0].update(reason="forged-record"),
    ):
        forged = deepcopy(receipt)
        change(forged)
        forged["artifact_sha256"] = canonical_hash(
            {k: v for k, v in forged.items() if k != "artifact_sha256"}
        )
        with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
            instance.replay_tables(forged, graph, source, tenant_id=graph.tenant_id)


def test_new_policy_and_historical_v19_dispatch_remain_distinct():
    from proofops.adapters.local import upstage_ocr_profile_v19 as old

    assert sha256(Path(old.__file__).read_bytes()).hexdigest() == (
        "d672ac56acae21d12d57654e45ac7ca49b6ab48afa51395e679d363e154c5260"
    )
    for module in (old, reader):
        assert page_ocr_profile(module.PROFILE, policy=module.claim_source_policy()) is module
        assert (
            page_ocr_profile(module.PROFILE, policy=module.native_policy(), native=True) is module
        )
    for policy in (
        profiles.FINALS_I18_POLICY,
        profiles.FINALS_P2_POLICY,
        profiles.FINALS_P3_POLICY,
        profiles.FINALS_D2_POLICY,
        profiles.FINALS_I19_POLICY,
        profiles.FINALS_I20_POLICY,
    ):
        pin = canonical_hash(policy)
        assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=pin) == policy
        assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=pin) == policy
    assert (
        profiles.policy_for(
            profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I23_POLICY)
        )
        == profiles.FINALS_I23_POLICY
    )
    assert canonical_hash(profiles.FINALS_I19_POLICY) == (
        "6fe453450016e3cf363a08e8c092941834c5052bb0cf324a3399d8c0b17bd61a"
    )
    assert canonical_hash(reader.claim_source_policy()) != canonical_hash(old.claim_source_policy())
