"""HF1: new pinned behavior, literal-source negatives and legacy isolation."""

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace

import pdfplumber
import pytest

from tests.acceptance.test_parsing import TENANT, candidate
from tests.integration.test_claim_source_verification import geometry_pdf


def test_unique_first_row_region_preserves_refs_and_requires_pixels(monkeypatch):
    import io

    import pypdfium2 as pdfium
    from proofops.adapters.local import claim_source_glyph_region as region
    from proofops.adapters.local import claim_source_verification_v3 as legacy
    from proofops.application.ingest.graph_fusion import fuse_candidates

    quote = "ESG policy 10% achieved"
    source = geometry_pdf([(72, 720, quote), (72, 680, "OTHER ROW 999 tonnes")])
    with pdfium.PdfDocument(source) as native:
        entries = legacy._native_page(native, 1)
    selected = entries[: len(quote.replace(" ", ""))]
    top = min(g["bbox"][1] for g in selected)
    batch = replace(
        candidate("hf1", [("P", "paragraph", quote, (70, 705, 400, 792 - top - 0.5), ())]),
        source_sha256=sha256(source).hexdigest(),
    )
    graph = fuse_candidates((batch,), tenant_id=TENANT)
    block = graph.blocks[0]
    ref = block.source_ref()
    monkeypatch.setattr(legacy, "_rendered_text", lambda *a, **k: dict(status="read", text=quote))
    with pdfplumber.open(io.BytesIO(source)) as doc, pdfium.PdfDocument(source) as native:
        assert (
            legacy._recover(doc, native, block, ref, {}, {}, graph.source_sha256)["status"]
            == "unresolved"
        )
        result = region.recover(
            doc, native, block, ref, {}, {}, graph.source_sha256, literal=legacy
        )
        assert result["status"] == "verified"
        assert result["normalization"]["original_bbox"] == list(ref.bbox)
        assert result["normalization"]["bbox"][1] < ref.bbox[1]
        assert result["normalization"]["parser_quote"] == ref.quote
        monkeypatch.setattr(
            legacy,
            "_rendered_text",
            lambda *a, **k: dict(status="read", text="ESG policy 99% achieved"),
        )
        assert (
            region.recover(doc, native, block, ref, {}, {}, graph.source_sha256, literal=legacy)[
                "status"
            ]
            == "unresolved"
        )
    assert ref == block.source_ref()


@pytest.mark.parametrize(
    "entries",
    [
        [
            dict(index=0, char="A", bbox=[1, 9, 4, 11]),
            dict(index=1, char="B", bbox=[30, 9, 33, 11]),
        ],
        [dict(index=0, char="A", bbox=[1, 9, 4, 11]), dict(index=1, char="B", bbox=[1, 25, 4, 27])],
        [dict(index=0, char="A", bbox=[1, 0, 4, 2]), dict(index=1, char="B", bbox=[4, 0, 7, 2])],
    ],
)
def test_region_never_borrows_other_column_row_or_nonoverlapping_glyph(entries):
    from proofops.adapters.local.claim_source_glyph_region import glyph_region

    assert glyph_region(entries, "AB", [0, 10, 20, 20], []) is None


def test_whitespace_restore_is_unique_and_returns_original_offsets():
    from proofops.application.tagging.citation_restore import restore_whitespace

    ref = dict(
        quote="2025년에는 총 8건의 에너지 효율화\n과제를 통해 약 3만 톤을 저감",
        char_start=77,
        char_end=119,
    )
    restored = restore_whitespace("총 8건의 에너지 효율화 과제를 통해", ref)
    assert restored["quote"] == "총 8건의 에너지 효율화\n과제를 통해"
    assert restored["char_start"] == 85
    assert restored["char_end"] == 85 + len(restored["quote"])
    for quote in ("ESG위원회", "총 9건", "총8건의"):
        with pytest.raises(ValueError):
            restore_whitespace(quote, ref)
    with pytest.raises(ValueError):
        restore_whitespace("기술 개발", dict(quote="기술\n개발 / 기술 개발", char_start=0))


def test_partial_restore_keeps_failed_element_unknown_and_legacy_fails():
    from proofops.application.tagging.citation_restore import POLICY
    from proofops_agent.upstage_tagging import UpstageTaggingTransport

    transport = object.__new__(UpstageTaggingTransport)
    transport._settings = SimpleNamespace(model_profile="upstage-compact-source-quotes-v5")
    transport._display_catalog = None
    refs = {"e0": dict(quote="에너지 효율화\n과제를 추진", char_start=0, char_end=14)}
    payload = dict(
        elements=[
            dict(
                element_id="M1",
                state="present",
                evidence_refs=[dict(id="e0", quote="에너지 효율화 과제를")],
                normalized_value=None,
                credited_from=None,
                reason_code=None,
            ),
            dict(
                element_id="M5",
                state="present",
                evidence_refs=[dict(id="e0", quote="ESG위원회")],
                normalized_value=None,
                credited_from=None,
                reason_code=None,
            ),
        ],
        warnings=[],
    )
    before = deepcopy(payload)
    with pytest.raises(ValueError):
        transport.restore_payload(deepcopy(payload), refs)
    result = transport.restore_payload(deepcopy(payload), refs, policy=POLICY)
    assert result["elements"][0]["state"] == "present"
    assert result["elements"][0]["evidence_refs"][0]["quote"] == "에너지 효율화\n과제를"
    assert result["elements"][1]["state"] == "unknown"
    assert result["elements"][1]["evidence_refs"] == []
    assert result["warnings"] == ["CITATION_RESTORE_UNRESOLVED:M5"]
    assert payload == before


def test_real_gaps_only_hold_display_and_legacy_unchanged():
    from proofops.application.tagging.quality import hold_projection

    grade = dict(
        evidence_grade=None,
        reason="blocked_evidence",
        grade_range=dict(floor="E0", ceiling="E3", rule_gap=True),
        elements=[],
        gap_ids=[],
    )
    item = dict(
        provisional_grade=grade,
        source_status=dict(status="unverified"),
        frozen_packet=dict(track="management"),
    )
    assert "규칙 미정" in hold_projection(item)["hold_reasons"]
    assert hold_projection(item, profile="hf1-v1")["hold_reasons"] == ["원문 미검증", "근거 없음"]
    item["provisional_grade"] = grade | dict(gap_ids=["GAP-001"], reason="blocked_rule_gap")
    assert "규칙 미정" in hold_projection(item, profile="hf1-v1")["hold_reasons"]


def test_new_default_has_new_hash_and_old_v2_pins_still_resolve():
    from proofops.application.analysis_profile import (
        FINALS_I2_POLICY,
        V2_POLICY,
        V2_PRE_HF1_POLICY,
        apply_pilot_profile,
        policy_for,
    )
    from proofops.domain.provenance import canonical_hash

    assert canonical_hash(V2_POLICY) != canonical_hash(V2_PRE_HF1_POLICY)
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(V2_PRE_HF1_POLICY))
        == V2_PRE_HF1_POLICY
    )
    args = SimpleNamespace(
        analysis_profile="finals-unattended-v2",
        resume=False,
        claim_source_profile="upstage-ocr-page-v5",
    )
    apply_pilot_profile(args)
    assert args.claim_source_profile == "i31_claim_source_v1"
    assert args.extraction_pb1 and args.extraction_table_rows
    args.analysis_policy_sha256 = canonical_hash(FINALS_I2_POLICY)
    apply_pilot_profile(args)
    assert args.claim_source_profile == "upstage-ocr-page-v10"


def test_v6_composition_keeps_v5_policy_and_replays_without_transport(tmp_path, monkeypatch):
    from proofops.adapters.local import upstage_ocr_profile_v5 as v5
    from proofops.adapters.local import upstage_ocr_profile_v6 as v6
    from proofops.adapters.local.claim_source_policies import publication_reader

    from tests.integration.test_claim_source_verification import inputs
    from tests.integration.test_upstage_ocr_page import response, store

    before = deepcopy(v5.claim_source_policy())
    calls = []
    db = store(
        tmp_path, lambda png: (calls.append(1) or response("Page 1 emissions 1234 tCO2e"), "fake")
    )
    monkeypatch.setattr(
        v6._wrapper,
        "LocalRasterReader",
        lambda source: SimpleNamespace(
            policy=dict(status="ready"),
            read=lambda *a, **k: dict(status="read", text="Page 1 emissions 1234 tCO2e"),
        ),
    )
    reader = v6.Reader(db, run_id="hf1")
    source, graph, ref = inputs()
    receipt = reader.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    assert receipt["records"][0]["status"] == "verified"
    db.transport = lambda *a: pytest.fail("offline replay must not dispatch")
    assert (
        reader.recompute_claim_receipt(receipt, graph, source, (ref,), tenant_id=TENANT) == receipt
    )
    assert publication_reader(v6.claim_source_policy()) is v6
    assert v5.claim_source_policy() == before
    assert receipt["policy"] != before


def test_display_whitespace_roundtrip_preserves_deleted_space_and_rejects_tamper():
    from proofops.adapters.local.glyph_display_text import GlyphDisplayCatalog
    from proofops.application.ingest.display_text import display_alignment, mapping_pin
    from proofops.application.tagging.citation_restore import POLICY

    raw = "에너 지 효율화\n과제를 추진한다"
    mapping = display_alignment(raw, [2])
    pin = mapping_pin(mapping, identity={}, boundaries=[])
    ref = dict(quote=raw, char_start=20)
    restored = GlyphDisplayCatalog.restore("에너지 효율화 과제를", ref, pin, policy=POLICY)
    assert restored["quote"] == "에너 지 효율화\n과제를"
    assert restored["char_start"] == 20
    assert restored["char_end"] == 20 + len(restored["quote"])
    with pytest.raises(ValueError, match="DISPLAY_MAP_MISMATCH"):
        GlyphDisplayCatalog.restore(
            "에너지 효율화 과제를", ref, pin | dict(text="forged"), policy=POLICY
        )


def test_glyph_owner_does_not_remove_competing_row_or_column(monkeypatch):
    from proofops.adapters.local import claim_source_glyph_region as region
    from proofops.adapters.local import upstage_ocr_profile_v6 as v6

    owner = (0, 10, 20, 20)
    peers = [owner, (30, 10, 50, 20), (0, 25, 20, 35)]
    observed = []
    monkeypatch.setattr(v6.v5, "map_words", lambda *a, **k: observed.append(k["competing_boxes"]))
    v6.map_words([], {}, [0, 9.5, 20, 20], competing_boxes=peers)
    assert observed[-1] == peers
    token = region.VERIFICATION_OWNER.set(owner)
    try:
        v6.map_words([], {}, [0, 9.5, 20, 20], competing_boxes=peers)
        assert observed[-1] == peers[1:]
    finally:
        region.VERIFICATION_OWNER.reset(token)
    assert region.VERIFICATION_OWNER.get() is None


def test_whitespace_recovery_allows_hangul_wrap_but_keeps_numeric_units():
    from proofops.application.tagging.citation_restore import restore_whitespace

    ref = dict(quote="에너지 효율화\n과제를 추진", char_start=20)
    assert restore_whitespace("효율화과제를", ref)["quote"] == "효율화\n과제를"
    for raw, quote in [("10 %", "10%"), ("1 0%", "10%"), ("10 톤", "10톤"), ("만 원", "만원")]:
        with pytest.raises(ValueError):
            restore_whitespace(quote, dict(quote=raw, char_start=0))


def test_hosted_v2_default_selects_approved_v10_without_changing_v1(monkeypatch):
    from proofops_api import hosted_analysis

    monkeypatch.setattr(hosted_analysis.sys, "platform", "linux")
    new = hosted_analysis.operator_profiles({"analysis_profile": "finals-unattended-v2"})
    old = hosted_analysis.operator_profiles({"analysis_profile": "finals-unattended-v1"})
    assert new["claim_source"] == new["source_reader"] == "upstage-ocr-page-v10"
    assert old["claim_source"] == old["source_reader"] == "upstage-ocr-page-v5"
    monkeypatch.setattr(hosted_analysis, "GATE_PASSED_RENDERED_READERS", frozenset())
    assert (
        hosted_analysis.operator_profiles({"analysis_profile": "finals-unattended-v2"})[
            "source_reader"
        ]
        == "unresolved"
    )


def test_recovery_refuses_glyph_region_outside_visible_page(monkeypatch):
    from proofops.adapters.local import claim_source_glyph_region as region

    # Isolate the new crop boundary: an original region is on-page, but its
    # native first glyph would extend into pixels outside the visible PDF page.
    literal = SimpleNamespace(
        _recover=lambda *a: dict(
            status="unresolved", reason="clipped_ambiguous_or_cross_row_quote"
        ),
        _canonical=lambda *a: dict(canonical_quote="A", changed_boundaries=[]),
    )
    monkeypatch.setattr(region, "glyph_region", lambda *a: ([-1, 0, 10, 10], []))

    class NativePage:
        def get_textpage(self):
            return self

        def get_text_bounded(self, *a):
            return "A"

        def close(self):
            pass

    document = SimpleNamespace(pages=[SimpleNamespace(width=100, height=100)])
    block = SimpleNamespace(winner=0, candidates=[SimpleNamespace(bbox=[0, 0, 10, 10])])
    ref = SimpleNamespace(page_num=1, quote="A")
    assert (
        region.recover(
            document, [NativePage()], block, ref, {1: []}, {}, "a" * 64, literal=literal
        )["status"]
        == "unresolved"
    )
