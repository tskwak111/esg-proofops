"""HX4 keeps malformed candidates local and source/checkpoint guards intact."""

from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from proofops.adapters.parsing.opendataloader import ParseFailure, _batch, _with_quality_issues
from proofops.application.ingest.graph_fusion import ParserProfile, fuse_candidates
from proofops.domain.provenance import canonical_hash

from tests.acceptance.test_parsing import MANIFEST, TENANT, source


def profile():
    return ParserProfile(
        MANIFEST, local_resource_policy="selected-pdf-h6-v1", failure_policy="partial-v4"
    )


def geometry():
    return {
        str(p): {"crop": dict(width_pt=600, height_pt=800, rotation=0, crop_box=[0, 0, 600, 800])}
        for p in (1, 2)
    }


def node(page=1, box=None):
    return dict(
        id=1,
        type="paragraph",
        content="Environmental policy 10%",
        **{"page number": page, "bounding box": box or [10, 10, 300, 50]},
    )


def test_duplicate_ids_on_different_pages_keep_both_candidates_and_old_guard():
    raw = dict(kids=[node(), node(2)])
    saved = deepcopy(raw)
    with pytest.raises(ValueError, match="duplicate native"):
        _batch(raw, geometry(), source(b"fixture"), ParserProfile(MANIFEST), "b" * 64)
    batch = _batch(raw, geometry(), source(b"fixture"), profile(), "b" * 64)
    assert len({b.source.source_native_id for b in batch.blocks}) == 2
    assert {b.source.physical_page for b in batch.blocks} == {1, 2}
    assert raw == saved
    assert all(b.source.raw_text == "Environmental policy 10%" for b in batch.blocks)


@pytest.mark.parametrize("box", [[10, 10, 10, 20], [20, 10, 10, 20], [10, 10, 20, 10]])
def test_bad_geometry_holds_only_that_block_and_preserves_good_sibling(box):
    bad, good = node(box=box), node(2)
    raw = dict(kids=[bad, good])
    batch = _batch(raw, geometry(), source(b"fixture"), profile(), "b" * 64)
    graph = _with_quality_issues(fuse_candidates((batch,), tenant_id=TENANT), (1, 2), profile())
    held = next(b for b in graph.blocks if b.page_num == 1)
    kept = next(b for b in graph.blocks if b.page_num == 2)
    assert held.bbox is None and held.kind == "unknown" and held.quality != "verified"
    assert held.raw_text == bad["content"]
    assert kept.kind == "paragraph" and kept.bbox is not None
    assert any(i.state == "unreadable" and i.page_num == 1 for i in graph.issues)
    assert not any(i.state == "unreadable" and i.page_num == 2 for i in graph.issues)
    assert raw["kids"][0]["bounding box"] == box


def test_duplicate_same_page_parent_edges_use_occurrence_identity():
    a, b = node(), node()
    a["kids"] = [node()]
    batch = _batch(dict(kids=[a, b]), geometry(), source(b"fixture"), profile(), "b" * 64)
    assert len({c.source.source_native_id for c in batch.blocks}) == 3
    assert batch.edges[0].target_native_id == batch.blocks[0].source.source_native_id
    assert batch.edges[0].source_native_id == batch.blocks[1].source.source_native_id


def test_auxiliary_subpixel_height_collapse_is_local_and_children_stay_held():
    geo = geometry()
    geo["1"]["media"] = geo["1"]["crop"]
    bad = node(box=[0.03525, 0.00036333333324970835, 500, 0.0003633333332497084])
    bad["page origin"] = [0, 0]
    child = node()
    child["page origin"] = [0, 0]
    bad["kids"] = [child]
    batch = _batch(dict(kids=[bad]), geo, source(b"fixture"), profile(), "b" * 64, auxiliary=True)
    assert len(batch.blocks) == 2
    assert all(b.kind == "unknown" and b.source.native_bbox is None for b in batch.blocks)
    assert all("hx4_geometry_invalid=true" in b.context for b in batch.blocks)


def test_empty_evidence_graph_returns_bound_empty_receipt_and_replays():
    from proofops.adapters.local import evidence_source_hx4 as reader

    from tests.integration.test_claim_source_v3 import synthetic

    pdf, graph, _ = synthetic("Environmental policy 10%")
    graph = replace(
        graph,
        blocks=(),
        edges=(),
        candidates=tuple(replace(b, blocks=(), edges=()) for b in graph.candidates),
    )
    receipt = reader.attest_evidence_sources(graph, pdf, tenant_id=graph.tenant_id)
    assert receipt["records"] == [] and receipt["physical_pages"] == ()
    assert reader.replay_evidence_sources(receipt, graph, pdf, tenant_id=graph.tenant_id) == graph
    altered = deepcopy(receipt)
    altered["records"] = [dict(status="verified")]
    with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
        reader.replay_evidence_sources(altered, graph, pdf, tenant_id=graph.tenant_id)
    with pytest.raises(ValueError, match="SOURCE_MISMATCH"):
        reader.attest_evidence_sources(graph, pdf + b"x", tenant_id=graph.tenant_id)
    with pytest.raises(ValueError):
        reader.attest_evidence_sources(graph, pdf, tenant_id="22222222-2222-4222-8222-222222222222")
    with pytest.raises(ValueError, match="PAGE_SELECTION_INVALID"):
        reader.attest_evidence_sources(graph, pdf, tenant_id=graph.tenant_id, physical_pages=(0,))


def test_unreadable_native_receipt_has_full_checkpoint_provenance(monkeypatch):
    from proofops.adapters.local import upstage_ocr_profile_hx4_v16 as reader
    from proofops.adapters.local.run_artifacts import checkpoint_native_attestation

    from tests.integration.test_claim_source_v3 import synthetic

    pdf, graph, _ = synthetic("Environmental policy 10%")
    run = "55555555-5555-4555-8555-555555555555"

    # Reproduce the legitimate H6 fallback shape returned through H7.
    def fallback(self, *a, **k):
        return self._finish(
            dict(
                schema="source_h6_unreadable_v1",
                geometry_mode="glyph",
                records=[
                    dict(
                        source_id=graph.blocks[0].source_id,
                        status="unresolved",
                        reason="native_text_unreadable",
                    )
                ],
            ),
            {},
            native=True,
        )

    monkeypatch.setattr(reader._wrapper.Reader, "_native_receipt", fallback)
    instance = reader.for_run(run)
    receipt = instance.attest_native_sources(graph, pdf, tenant_id=graph.tenant_id)
    envelope = dict(
        schema="local_parser_checkpoint_v4",
        native_paragraph_attestation=receipt,
        native_paragraph_policy_sha256=canonical_hash(reader.native_policy()),
    )
    assert checkpoint_native_attestation(envelope) == receipt
    assert receipt["input_graph_sha256"] == canonical_hash(asdict(graph))
    assert receipt["records"][0]["status"] == "unresolved"
    assert instance.replay_native_sources(receipt, graph, pdf, tenant_id=graph.tenant_id) == graph
    altered = deepcopy(receipt)
    altered["records"][0]["status"] = "verified"
    with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
        instance.replay_native_sources(altered, graph, pdf, tenant_id=graph.tenant_id)
    bad = deepcopy(envelope)
    bad["native_paragraph_attestation"]["schema"] = "source_h6_unreadable_v1"
    with pytest.raises(ParseFailure, match="CHECKPOINT_INVALID"):
        checkpoint_native_attestation(bad)


def test_hx4_pin_keeps_v15_and_source_reader_hashes():
    from proofops.adapters.local.claim_source_policies import page_ocr_profile
    from proofops.application import analysis_profile as p

    pin = canonical_hash(p.FINALS_HX4_POLICY)
    assert p.policy_for(p.V2_PROFILE, pinned_hash=pin) == p.FINALS_HX4_POLICY
    assert p.publication_policy_for(p.V2_PROFILE, pinned_hash=pin) == p.FINALS_HX4_POLICY
    assert (
        p.policy_for(p.V2_PROFILE, pinned_hash=canonical_hash(p.FINALS_I15_POLICY))
        == p.FINALS_I15_POLICY
    )
    assert (
        canonical_hash(p.FINALS_I13_POLICY)
        == "05770a9a6e8a4a42270666b28234bd0f0103634397a717a42934a96f2f89a11c"
    )
    assert page_ocr_profile("upstage-ocr-page-v16").PROFILE == "upstage-ocr-page-v16"
    args = SimpleNamespace(analysis_profile=p.V2_PROFILE, analysis_policy_sha256=pin)
    p.apply_pilot_profile(args)
    assert args.parser_failure_policy == "partial-v4"
    assert args.claim_source_profile == "upstage-ocr-page-v16-hx4"


def test_claim_unreadable_receipt_keeps_provenance_and_rejects_tampered_records(monkeypatch):
    from proofops.adapters.local import upstage_ocr_profile_v17 as reader

    from tests.integration.test_claim_source_v3 import synthetic

    pdf, graph, ref = synthetic("Environmental policy 10%")

    def fallback(self, graph, source, refs, *, tenant_id):
        return self._finish(
            dict(
                schema="claim_source_h6_unreadable_v1",
                records=[
                    dict(ref=asdict(ref), status="unresolved", reason="native_text_unreadable")
                ],
                pb1_cell_proofs=[],
            ),
            {},
        )

    monkeypatch.setattr(reader._wrapper.Reader, "attest_claim_spans", fallback)
    instance = reader.for_run("55555555-5555-4555-8555-555555555555")
    receipt = instance.attest_claim_spans(graph, pdf, (ref,), tenant_id=graph.tenant_id)
    assert receipt["tenant_id"] == graph.tenant_id
    assert receipt["document_version_id"] == graph.document_version_id
    assert receipt["parse_manifest_id"] == graph.parse_manifest_id
    assert receipt["source_sha256"] == graph.source_sha256
    assert receipt["graph_sha256"] == canonical_hash(asdict(graph))
    assert receipt["records"][0]["status"] == "unresolved"
    assert (
        instance.recompute_claim_receipt(receipt, graph, pdf, (ref,), tenant_id=graph.tenant_id)
        == receipt
    )
    altered = deepcopy(receipt)
    altered["records"][0]["status"] = "verified"
    with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
        instance.recompute_claim_receipt(altered, graph, pdf, (ref,), tenant_id=graph.tenant_id)


def test_complete_hx4_pin_preserves_initial_hx4_reader_and_resolves_v17():
    from proofops.adapters.local.claim_source_policies import page_ocr_profile
    from proofops.application import analysis_profile as p

    selected = p.FINALS_HX4_COMPLETE_POLICY
    pin = canonical_hash(selected)
    assert p.policy_for(p.V2_PROFILE, pinned_hash=pin) == selected
    assert p.publication_policy_for(p.V2_PROFILE, pinned_hash=pin) == selected
    assert (
        p.policy_for(p.V2_PROFILE, pinned_hash=canonical_hash(p.FINALS_HX4_POLICY))
        == p.FINALS_HX4_POLICY
    )
    assert page_ocr_profile(selected["source"]).PROFILE == "upstage-ocr-page-v17"
    args = SimpleNamespace(analysis_profile=p.V2_PROFILE, analysis_policy_sha256=pin)
    p.apply_pilot_profile(args)
    assert args.claim_source_profile == "upstage-ocr-page-v17"


def test_empty_facility_scope_does_not_parse_damaged_pdf_but_keeps_identity_guard(monkeypatch):
    from pdfplumber.utils.exceptions import PdfminerException
    from proofops.adapters.local import k4_facilities

    from tests.integration.test_claim_source_v3 import synthetic

    pdf, graph, _ = synthetic("Environmental policy 10%")

    def damaged(*a, **k):
        raise PdfminerException("Unexpected EOF")

    monkeypatch.setattr(k4_facilities.pdfplumber, "open", damaged)
    assert k4_facilities.restore_facilities(graph, pdf, (), tenant_id=graph.tenant_id) == {}
    with pytest.raises(ValueError, match="SOURCE_MISMATCH"):
        k4_facilities.restore_facilities(graph, pdf + b"x", (), tenant_id=graph.tenant_id)
    with pytest.raises(ValueError, match="SOURCE_MISMATCH"):
        k4_facilities.restore_facilities(graph, pdf, (), tenant_id="foreign")
