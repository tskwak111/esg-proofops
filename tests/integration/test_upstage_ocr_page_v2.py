"""O1b: bounded geometry recovery without weakening source or replay gates."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from tests.acceptance.test_parsing import FOREIGN, TENANT
from tests.integration.test_claim_source_verification import inputs
from tests.integration.test_upstage_ocr_page import response, store


def reading(words, box, peers=()):
    from proofops.adapters.local.upstage_ocr_mapping_v2 import map_words

    return map_words(
        {"width": 600, "height": 800, "words": words},
        {"width_pt": 600, "height_pt": 800},
        box,
        competing_boxes=peers,
    )


def word(wid, text, box):
    x0, y0, x1, y1 = box
    return dict(
        id=wid,
        text=text,
        confidence=0.99,
        order=wid,
        polygon=[[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
    )


def test_tight_box_crossing_and_provider_order_recover_geometrically():
    words = [word(0, "left", [10, 20, 30, 32]), word(1, "right", [35, 20, 60, 32])]
    result = reading(list(reversed(words)), [11, 21, 59, 31])
    assert result["status"] == "read"
    assert result["text"] == "left right"
    assert result["word_ids"] == [0, 1]


def test_small_polygon_tilt_recovers_but_rotated_word_holds():
    words = [word(0, "visible", [10, 20, 40, 32])]
    words[0]["polygon"][1][1] += 0.1
    assert reading(words, [11, 21, 39, 31])["status"] == "read"
    words[0]["polygon"][1][1] += 6
    assert reading(words, [5, 15, 50, 40])["reason"] == "ocr_word_rotation_ambiguous"


def test_neighbor_assignment_is_exclusive_and_foreign_word_not_borrowed():
    words = [word(0, "own", [10, 20, 30, 32]), word(1, "neighbor", [35, 20, 60, 32])]
    assert reading(words, [9, 19, 31, 33], [[34, 19, 61, 33]])["text"] == "own"
    assert reading(words, [9, 19, 61, 33], [[28, 19, 61, 33]])["reason"] == (
        "ocr_block_overlap_ambiguous"
    )


def test_cross_column_synthetic_read_is_held():
    words = [
        word(0, "left1", [10, 20, 30, 32]),
        word(1, "left2", [10, 40, 30, 52]),
        word(2, "right1", [150, 20, 180, 32]),
        word(3, "right2", [150, 40, 180, 52]),
    ]
    assert reading(words, [9, 19, 181, 53])["reason"] == "ocr_column_order_ambiguous"


def test_boundary_large_crossing_empty_word_and_duplicate_detection_hold():
    assert reading([word(0, "outside", [0, 20, 30, 32])], [20, 20, 40, 32])["status"] == (
        "unresolved"
    )
    assert reading([word(0, "", [10, 20, 30, 32])], [10, 20, 30, 32])["reason"] == (
        "ocr_unrecognized_word"
    )
    assert (
        reading([word(0, "a", [10, 20, 30, 32]), word(1, "b", [10, 20, 30, 32])], [10, 20, 30, 32])[
            "reason"
        ]
        == "ocr_word_overlap_ambiguous"
    )


def test_v2_profile_dispatch_and_v1_policies_stay_distinct():
    from proofops.adapters.local import upstage_ocr_profile as v1
    from proofops.adapters.local import upstage_ocr_profile_v2 as v2
    from proofops.adapters.local.claim_source_policies import publication_reader
    from proofops.adapters.parsing.opendataloader import _locates_auxiliary_cells, _table_verifier

    from evaluation.local_upstage_pilot import claim_source_policy_for

    policy = claim_source_policy_for(SimpleNamespace(claim_source_profile=v2.PROFILE))
    assert policy == v2.claim_source_policy()
    assert publication_reader(policy) is v2
    assert publication_reader(v1.claim_source_policy()) is v1
    assert policy != v1.claim_source_policy()
    assert v2.reader_policy()["mapping_sha256"] != v1.reader_policy()["mapping_sha256"]
    assert _table_verifier(v2.table_policy_sha256()) is v2
    assert _locates_auxiliary_cells({"table_source_policy_sha256": v2.table_policy_sha256()})
    policy["reader"]["mapping_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        publication_reader(policy)


@pytest.mark.parametrize("text", ["Page 1 emissions 1234 tCO2e", "Page 1 emissions 1235 tCO2e"])
def test_v2_reuses_v1_collection_and_replays_offline_with_numeric_guard(
    tmp_path, monkeypatch, text
):
    from proofops.adapters.local import upstage_ocr_profile as v1
    from proofops.adapters.local import upstage_ocr_profile_v2 as v2
    from proofops.adapters.local.upstage_ocr_page import render_page

    source, graph, ref = inputs()
    db = store(tmp_path, lambda png: (response(text), "provider"))
    collected = db.fetch(render_page(source, 1), tenant_id=TENANT, run_id="v1-run")
    old_policy = v1.claim_source_policy()
    before = db.usage()
    db.transport = lambda png: pytest.fail("v2 must reuse persistent OCR cache")
    monkeypatch.setattr("subprocess.run", lambda *a, **k: pytest.fail("Swift must never run"))
    reader = v2.Reader(db, run_id="v2-run")
    receipt = reader.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    assert receipt["records"][0]["status"] == ("verified" if "1234" in text else "unresolved")
    assert receipt["page_collections"] == [collected]
    assert receipt["policy"] == v2.claim_source_policy()
    assert (
        reader.recompute_claim_receipt(receipt, graph, source, (ref,), tenant_id=TENANT) == receipt
    )
    assert db.usage() == before and v1.claim_source_policy() == old_policy
    forged = deepcopy(receipt)
    forged["page_collections"][0]["response_hex"] = response().hex()
    forged["page_collections"][0]["policy"] = v2.reader_policy()
    with pytest.raises(ValueError, match="OCR_COLLECTION_UNTRUSTED"):
        reader.recompute_claim_receipt(forged, graph, source, (ref,), tenant_id=TENANT)
    with pytest.raises(ValueError):
        reader.recompute_claim_receipt(receipt, graph, source, (ref,), tenant_id=FOREIGN)


def test_v2_context_receipt_replay_and_run_binding(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from dataclasses import asdict

    from proofops.adapters.local import upstage_ocr_profile_v2 as profile
    from proofops.adapters.local.tag_store import LocalTagStore

    source, graph, ref = inputs()
    reader = profile.Reader(store(tmp_path), run_id="run-1")
    monkeypatch.setattr(profile, "for_run", lambda run_id: reader)
    jobs = SimpleNamespace(_transaction=lambda: nullcontext(object()))
    backend = SimpleNamespace(
        snapshot=lambda *a: {"claim_source_policy": profile.claim_source_policy()}, jobs=jobs
    )
    tags = LocalTagStore(backend, SimpleNamespace(read_original=lambda *a: source), None)
    claim = SimpleNamespace(
        tenant_id=TENANT, document_version_id=graph.document_version_id, claim_id="claim-1"
    )
    case = SimpleNamespace(run_id="run-1", original=graph, context=SimpleNamespace(claim=claim))
    _, receipt = tags.verify_context_sources(case, (ref,))
    reader.store.transport = lambda png: pytest.fail("context replay must be offline")
    published = dict(
        confirmed_tags=dict(claim_id="claim-1"),
        report_level_review=[dict(refs=[asdict(ref)], source_receipt=receipt)],
    )
    _, replay = tags.verify_context_sources(
        case, (ref,), replay_receipt=receipt, published_tag=published
    )
    assert replay == receipt
    case.run_id = "other-run"
    monkeypatch.setattr(
        profile, "for_run", lambda run_id: profile.Reader(reader.store, run_id=run_id)
    )
    with pytest.raises(ValueError):
        tags.verify_context_sources(case, (ref,), replay_receipt=receipt, published_tag=published)


def test_v2_native_dispatch_replays_and_rejects_policy_mutation(tmp_path, monkeypatch):
    from proofops.adapters.local import upstage_ocr_profile_v2 as profile
    from proofops.adapters.local.frozen_native_replay import replay_native_with_policy
    from proofops.adapters.local.run_artifacts import accepted_native_policy_digests
    from proofops.domain.provenance import canonical_hash

    source, graph, _ = inputs()
    reader = profile.Reader(store(tmp_path), run_id="run-1")
    receipt = reader.attest_native_sources(graph, source, tenant_id=TENANT)
    monkeypatch.setattr(profile, "for_run", lambda run_id: reader)
    reader.store.transport = lambda png: pytest.fail("native replay must be offline")
    assert canonical_hash(profile.native_policy()) in accepted_native_policy_digests()
    assert replay_native_with_policy(
        profile.native_policy(), receipt, graph, source, tenant_id=TENANT
    )
    bad = deepcopy(profile.native_policy())
    bad["reader"]["mapping_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        replay_native_with_policy(bad, receipt, graph, source, tenant_id=TENANT)
