from argparse import Namespace

import pytest
from proofops.adapters.local.claim_source_policies import publication_reader
from proofops.application.analysis_profile import FINALS_I3_POLICY, V2_PROFILE, apply_pilot_profile
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import UpstageClaimExtractor

from evaluation.w7_sentence_replay import NoTransport


def extractor(tmp_path, h1):
    return UpstageClaimExtractor(
        NoTransport(),
        tmp_path / str(h1),
        extraction_source_ids=True,
        extraction_linewrap_join=True,
        extraction_h1=h1,
    )


def test_selected_heading_linewraps_are_restored_without_changing_the_original_ids(tmp_path):
    text = "당사는 기후변화가 사업에 미치는\n잠재적 영향력을 분석하고 있습니다."
    packet = dict(untrusted_document_data=dict(kind="heading", source_id="source", text=text))
    old, new = extractor(tmp_path, False), extractor(tmp_path, True)
    payload = {"sentence_ids": [sid for sid, _ in old._sentence_index(text, "source")]}
    before, _ = old._resolve_payload(payload, text, "source", packet=packet)
    after, _ = new._resolve_payload(payload, text, "source", packet=packet)
    assert len(before) == 2 and len(after) == 1
    assert after[0].quote == text
    assert old.profile.prompt_sha256 == new.profile.prompt_sha256
    assert old.profile.rule_sha256 != new.profile.rule_sha256


@pytest.mark.parametrize(
    "quote,excluded",
    [
        ("*2030년 목표에는 다렌(Dalian), 용인 사업장의 예상 배출량 포함", True),
        ("*2030년까지 사업장 배출량을 40% 감축할 목표입니다.", False),
        ("2030년 목표에는 사업장 예상 배출량 포함", False),
    ],
)
def test_marked_scope_notes_stay_context_and_targets_stay_claims(tmp_path, quote, excluded):
    old, new = extractor(tmp_path, False), extractor(tmp_path, True)
    packet = dict(untrusted_document_data=dict(kind="paragraph", source_id="source", text=quote))
    payload = {"sentence_ids": [sid for sid, _ in old._sentence_index(quote, "source")]}
    assert old._resolve_payload(payload, quote, "source", packet=packet)[0]
    spans, diagnostics = new._resolve_payload(payload, quote, "source", packet=packet)
    assert bool(spans) is not excluded
    assert bool(diagnostics["h1_scope_notes"]) is excluded


def test_new_source_reader_is_distinct_and_v11_remains_publishable():
    from proofops.adapters.local import upstage_ocr_profile_v11 as v11
    from proofops.adapters.local import upstage_ocr_profile_v12 as v12

    assert canonical_hash(v12.claim_source_policy()) != canonical_hash(v11.claim_source_policy())
    assert publication_reader(v12.claim_source_policy()) is v12
    assert publication_reader(v11.claim_source_policy()) is v11
    args = Namespace(
        analysis_profile=V2_PROFILE, analysis_policy_sha256=canonical_hash(FINALS_I3_POLICY)
    )
    apply_pilot_profile(args)
    assert not args.extraction_h1 and args.claim_source_profile == "upstage-ocr-page-v11"


def test_h1_cannot_be_enabled_without_linewrap(tmp_path):
    with pytest.raises(ValueError, match="EXTRACTION_H1_INVALID"):
        UpstageClaimExtractor(NoTransport(), tmp_path, extraction_h1=True)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("• 환경 전담 부서 내 내부탄소가격제 조직 운영", 1),
        ("• 재생에너지 전환, 환경친화적 서비스 발굴 지원,\n파트너십 협력 등 과제 수립 이행", 1),
        ("• 30.0\n• 755\n• 환경 전담 부서\n• 2040 Carbon Negative\n• LEED", 0),
        ("• 2030년 감축 목표\n단, 해당 계획은 취소", 1),
        ("• 재생에너지 전환 및", 0),
        ("Environment Department", 0),
    ],
)
def test_qc_figure_candidates_require_whole_literal_bullets(text, expected):
    from proofops.application.ingest.k6_coverage import native_figure_bullets

    spans = native_figure_bullets(text)
    assert len(spans) == expected
    assert all(text[a:b] == quote for a, b, quote in spans)
    if "취소" in text:
        assert spans[0][2] == text


def test_qc_figure_profile_requires_source_id_table_context_and_native_source(tmp_path):
    from proofops_agent.upstage_extraction import GraphBoundExtractor

    with pytest.raises(ValueError, match="QC_NATIVE_FIGURE_PROFILE_INVALID"):
        UpstageClaimExtractor(NoTransport(), tmp_path, extraction_qc_native_figures=True)
    new = UpstageClaimExtractor(
        NoTransport(),
        tmp_path,
        extraction_qc_native_figures=True,
        extraction_source_ids=True,
        extraction_context=True,
        extraction_table_rows=True,
        extraction_w9=True,
        extraction_pb1=True,
    )
    with pytest.raises(ValueError, match="QC_NATIVE_FIGURE_SOURCE_REQUIRED"):
        GraphBoundExtractor(new, object())


def test_qc_real_naver_native_bullets_preserve_provenance_and_do_not_approve_caption():
    from dataclasses import asdict, replace

    from proofops.adapters.local.h1_native_title import native_figure_candidates
    from proofops.application.ingest.graph_fusion import candidates_from_snapshot, fuse_candidates
    from proofops.application.ingest.k6_coverage import FIGURE_MARKER

    from tests.unit.test_pa9_source import fixture

    original, source = fixture("naver")
    batch = original.candidates[0]
    caption = replace(
        batch.blocks[0],
        kind="figure",
        source=replace(
            batch.blocks[0].source,
            source_native_id="diagram",
            raw_text="Invented 755 tCO2eq and monthly reporting",
            char_start=0,
            char_end=len("Invented 755 tCO2eq and monthly reporting"),
            native_bbox=None,
        ),
        parser_bbox=None,
        parser_to_canonical=None,
        context=("provider_bbox=604.067,376.813,1013.626,539.367", "vision_only"),
    )
    graph = fuse_candidates(
        (replace(batch, blocks=(*batch.blocks, caption)), *original.candidates[1:]),
        tenant_id=source.tenant_id,
    )
    new, receipt = native_figure_candidates(graph, source.content)
    candidates = [
        b
        for b in new.blocks
        if b.winner is not None and FIGURE_MARKER in b.candidates[b.winner].context
    ]
    assert len(candidates) == 2
    assert any("과제 수립 이행" in b.raw_text for b in candidates)
    assert any("Env. Operation" in b.raw_text and b.raw_text.endswith("운영") for b in candidates)
    assert all(b.quality == "unverified" and b.bbox for b in candidates)
    assert all("755" not in b.raw_text and "monthly" not in b.raw_text for b in candidates)
    assert all(b in new.blocks for b in graph.blocks)
    assert native_figure_candidates(new, source.content)[0] == new
    replay = fuse_candidates(
        candidates_from_snapshot([asdict(b) for b in new.candidates]), tenant_id=source.tenant_id
    )
    assert replay.blocks == new.blocks and replay.edges == new.edges
    assert len(receipt["candidates"]) == 2
    with pytest.raises(ValueError, match="SOURCE_MISMATCH"):
        native_figure_candidates(graph, b"different PDF")


@pytest.mark.parametrize("lines", [[], [(230, 50, "- We operate a renewable energy task force.")]])
def test_qc_figure_caption_cannot_supply_missing_or_other_column_native_text(lines):
    from proofops.adapters.local.h1_native_title import native_figure_candidates
    from proofops.application.ingest.graph_fusion import fuse_candidates

    from tests.integration.test_parser_source_recovery import batch, block, fixture

    source, manifest, run = fixture(lines)
    caption = block(
        source,
        manifest,
        run,
        "diagram",
        "- We operate a renewable energy task force.",
        None,
        kind="figure",
        context=("provider_bbox=25,35,210,80", "vision_only"),
    )
    graph = fuse_candidates((batch(source, manifest, run, [caption]),), tenant_id=source.tenant_id)
    new, receipt = native_figure_candidates(graph, source.content)
    assert new == graph and not receipt["candidates"]
    assert new.blocks[0].quality == "unlocated"
    assert receipt["unresolved"]


def test_native_title_requires_a_source_bound_proof_and_keeps_year_targets(tmp_path):
    from proofops.application.claims import ExtractionOutputError
    from proofops.application.ingest.h1_boundaries import POLICY, strategy_title

    text = "그룹 탈탄소 전략 및 로드맵 수립"
    new = extractor(tmp_path, True)
    packet = dict(
        source_sha256="a" * 64,
        untrusted_document_data=dict(kind="paragraph", source_id="source", text=text),
    )
    payload = {"sentence_ids": [sid for sid, _ in new._sentence_index(text, "source")]}
    assert new._resolve_payload(payload, text, "source", packet=packet)[0]
    pin = dict(
        is_title=True,
        source_id="source",
        source_sha256="a" * 64,
        quote_sha256=canonical_hash(text),
        policy_sha256=canonical_hash(POLICY),
    )
    assert not new._resolve_payload(
        payload, text, "source", packet=packet | dict(h1_native_title=pin)
    )[0]
    with pytest.raises(ExtractionOutputError, match="H1_TITLE_PROOF_INVALID"):
        new._resolve_payload(
            payload,
            text,
            "source",
            packet=packet | dict(h1_native_title=pin | dict(source_id="other")),
        )
    assert not strategy_title("2025년 그룹 탈탄소 전략 및 로드맵 수립")


def test_source_v12_recomputes_every_proof_and_rejects_tampering(monkeypatch):
    from copy import deepcopy
    from dataclasses import asdict
    from uuid import uuid4

    from proofops.adapters.local import upstage_ocr_profile_v6 as v6
    from proofops.adapters.local import upstage_ocr_profile_v12 as source

    from tests.unit.test_pb4_source import naver_case

    graph, original, table = naver_case()
    quote = "• 2025년 16,673 tCO2eq의 온실가스 절감"
    start = table.normalized_text.index(quote)
    ref = table.source_ref(normalized_char_start=start, normalized_char_end=start + len(quote))
    run = str(uuid4())
    baseline = dict(
        tenant_id=graph.tenant_id,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        run_id=run,
        source_sha256=graph.source_sha256,
        graph_sha256=canonical_hash(asdict(graph)),
        records=[dict(ref=asdict(ref), status="unresolved", reason="unsupported_block_kind")],
    )
    # Only the unchanged v6 prose layer is mocked; the table proof reads the real PDF.
    monkeypatch.setattr(v6.Reader, "attest_claim_spans", lambda *a, **k: deepcopy(baseline))
    reader = source.Reader(object(), run_id=run)
    receipt = reader.attest_claim_spans(graph, original.content, [ref], tenant_id=graph.tenant_id)
    assert receipt["records"][0]["status"] == "verified"
    assert (
        reader.recompute_claim_receipt(
            receipt, graph, original.content, [ref], tenant_id=graph.tenant_id
        )
        == receipt
    )
    edited = deepcopy(receipt)
    edited["records"][0]["ref"]["quote"] = quote.replace("16,673", "16,674")
    with pytest.raises(ValueError, match="OCR_CLAIM_RECEIPT_MISMATCH"):
        reader.recompute_claim_receipt(
            edited, graph, original.content, [ref], tenant_id=graph.tenant_id
        )
