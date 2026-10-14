import json
from dataclasses import asdict, replace

import pytest
from proofops.application.claims import ExtractionOutputError
from proofops_agent.upstage_extraction import UpstageClaimExtractor, _profile_with_options

from tests.integration.test_upstage_extraction import FakeProbe, packet


class SelectAll(FakeProbe):
    def complete(self, system, user_json, **kwargs):
        data = json.loads(user_json)["untrusted_document_data"]
        self.content = json.dumps(
            {"sentence_ids": [s["sentence_id"] for s in data["source_sentences"]]}
        )
        return super().complete(system, user_json, **kwargs)


def test_opt_in_atomic_wire_exact_spans_and_replay(tmp_path):
    probe = SelectAll()
    extractor = UpstageClaimExtractor(
        probe, tmp_path, extraction_source_ids=True, extraction_atomic=True
    )
    text = "당사는 2024년 온실가스 배출량을 8% 감축했으며, 2030년까지 40% 감축할 계획입니다."
    data = packet(text)
    data["extraction_profile"] = asdict(extractor.profile)
    first = extractor.extract(data)
    assert len(first["spans"]) == 2
    assert all(s["quote"] == text[s["char_start"] : s["char_end"]] for s in first["spans"])
    wire = json.loads(probe.calls[0]["user_json"])["untrusted_document_data"]
    assert all(s["parent_quote"] == text for s in wire["source_sentences"])
    assert "extraction-atomic-v2" in probe.calls[0]["system"]
    assert extractor.extract(data) == first
    assert len(probe.calls) == 1


def test_atomic_profile_distinct_and_requires_id_selection(tmp_path):
    base = _profile_with_options(source_ids=True)
    atomic = _profile_with_options(source_ids=True, extraction_atomic=True)
    atomic_v3 = _profile_with_options(
        source_ids=True,
        extraction_atomic=True,
        extraction_atomic_v3=True,
        extraction_failure_diagnostics=True,
    )
    assert base.model_sha256 == atomic.model_sha256
    assert base.prompt_sha256 != atomic.prompt_sha256
    assert base.rule_sha256 != atomic.rule_sha256
    assert atomic_v3.prompt_sha256 != atomic.prompt_sha256
    assert atomic_v3.rule_sha256 != atomic.rule_sha256
    with pytest.raises(ValueError):
        UpstageClaimExtractor(FakeProbe(), tmp_path, extraction_atomic=True)


def test_atomic_nonclaims_make_no_transport_call(tmp_path):
    probe = FakeProbe()
    extractor = UpstageClaimExtractor(
        probe, tmp_path, extraction_source_ids=True, extraction_atomic=True
    )
    data = packet("목표 및 이행 성과")
    data["extraction_profile"] = asdict(extractor.profile)
    assert extractor.extract(data) == {"spans": []}
    assert not probe.calls


def test_atomic_rejects_legacy_or_foreign_ids(tmp_path):
    probe = FakeProbe(
        json.dumps({"sentence_ids": [packet()["untrusted_document_data"]["source_id"] + ":0"]})
    )
    extractor = UpstageClaimExtractor(
        probe, tmp_path, extraction_source_ids=True, extraction_atomic=True
    )
    data = packet("2030년 탄소중립 달성 목표")
    data["extraction_profile"] = asdict(extractor.profile)
    with pytest.raises(ExtractionOutputError, match="MODEL_SPAN_OR_SCHEMA_INVALID"):
        extractor.extract(data)


def test_atomic_cell_resolves_only_its_literal_value_and_own_axes(tmp_path):
    from tests.acceptance.test_preliminary_table_sources import table_corpus
    from tests.integration.test_extraction_table_context import _packet

    graph, _, block = table_corpus()
    probe = SelectAll()
    extractor = UpstageClaimExtractor(
        probe,
        tmp_path,
        extraction_source_ids=True,
        extraction_atomic=True,
        extraction_context=True,
        extraction_table_context=True,
    )
    data = _packet(graph, block("r1_2025-atom"))
    result = extractor.extract(data, context_graph=graph)
    assert [s["quote"] for s in result["spans"]] == ["900"]
    wire = json.loads(probe.calls[0]["user_json"])["untrusted_document_data"]
    assert "2025" in [b["text"] for b in wire["context_blocks"]]
    assert "2024" not in [b["text"] for b in wire["context_blocks"]]
    assert "5,000" not in [b["text"] for b in wire["context_blocks"]]
    assert extractor.extract(data, context_graph=graph) == result


def test_atomic_discovery_keeps_refs_and_uncovered_source_unknown(tmp_path):
    from proofops.application.claims import ClaimScope, discover_atomic_claims

    from tests.acceptance.test_claims import MANIFEST, TENANT, VERSION, graph_of

    text = "당사는 2024년 온실가스 배출량을 8% 감축했으며, 2030년까지 40% 감축할 계획입니다."
    graph = graph_of(text)
    extractor = UpstageClaimExtractor(
        SelectAll(), tmp_path, extraction_source_ids=True, extraction_atomic=True
    )
    result = discover_atomic_claims(
        graph, ClaimScope(TENANT, VERSION, MANIFEST), extractor=extractor
    )
    assert len(result.claims) == 2
    for claim in result.claims:
        ref = claim.source_refs[0]
        assert ref.document_version_id == VERSION and ref.parse_manifest_id == MANIFEST
        assert ref.quote == text[ref.char_start : ref.char_end] == claim.quote
        assert ref.verification_state == "candidate"
    assert all(e.state == "unknown" for e in result.exclusions)


def test_atomic_display_preserves_raw_offsets_and_parent_context(tmp_path):
    from proofops.application.ingest.display_text import PROFILE

    from tests.integration.test_glyph_display_text import fixture_catalog
    from tests.integration.test_upstage_extraction import _extraction_context_graph

    raw = "당사는 온실가스 배출량을 8% 감축했으며, 2030년까지 탄 소중립을 달성할 계획입니다."
    graph, sid = _extraction_context_graph(text=raw, with_neighbors=False)
    catalog = fixture_catalog(graph, {sid: [raw.index("탄 소") + 1]})
    probe = SelectAll()
    extractor = UpstageClaimExtractor(
        probe,
        tmp_path,
        extraction_source_ids=True,
        extraction_atomic=True,
        display_text_profile=PROFILE,
    )
    data = packet(raw)
    data.update(source_sha256=graph.source_sha256, extraction_profile=asdict(extractor.profile))
    data["untrusted_document_data"]["source_id"] = sid
    result = extractor.extract(data, context_graph=graph, display_catalog=catalog)
    assert len(result["spans"]) == 2
    assert "탄 소" in result["spans"][1]["quote"]
    sent = json.loads(probe.calls[0]["user_json"])["untrusted_document_data"]["source_sentences"]
    assert "탄소" in sent[1]["text"] and sent[1]["parent_quote"] == raw
    assert extractor.extract(data, context_graph=graph, display_catalog=catalog) == result


def test_atomic_catalog_limit_refuses_before_transport_or_receipt(tmp_path):
    probe = SelectAll()
    extractor = UpstageClaimExtractor(
        probe, tmp_path, extraction_source_ids=True, extraction_atomic=True
    )
    data = packet(" ".join("당사는 2030년 탄소중립을 달성할 계획입니다." for _ in range(65)))
    data["extraction_profile"] = asdict(extractor.profile)
    with pytest.raises(ExtractionOutputError, match="EXTRACTION_SOURCE_SENTENCES_UNBOUNDED"):
        extractor.extract(data)
    assert not probe.calls


def test_empty_atomic_receipt_records_gate_rejections_and_replays_without_call(tmp_path):
    probe = FakeProbe()
    extractor = UpstageClaimExtractor(
        probe, tmp_path, extraction_source_ids=True, extraction_atomic=True
    )
    data = packet("범례: 재생에너지. 온실가스 배출량 (tCO2-eq)")
    data["extraction_profile"] = asdict(extractor.profile)
    assert extractor.extract(data) == {"spans": []}
    receipt = next(tmp_path.glob("*/candidate_diagnostics.json"))
    diagnostic = json.loads(receipt.read_text())
    assert diagnostic["gate_rejected_count"] == diagnostic["parent_count"] == 2
    assert diagnostic["candidate_count"] == 0
    assert diagnostic["model_call_skipped"] is True
    assert extractor.usage_checkpoint() == 0
    assert extractor.extract(data) == {"spans": []}
    assert not probe.calls


def test_dependent_parent_never_expands_selected_source_ref_or_approves_evidence(tmp_path):
    from proofops.application.claims import ClaimScope, discover_atomic_claims

    from tests.acceptance.test_claims import MANIFEST, TENANT, VERSION, graph_of

    first = "당사는 재생에너지 전환을 추진합니다."
    footnote = "1) 2024년까지 누적 64대 전환"
    text = first + " " + footnote
    graph = graph_of(text)
    probe = SelectAll()
    extractor = UpstageClaimExtractor(
        probe, tmp_path, extraction_source_ids=True, extraction_atomic=True
    )
    result = discover_atomic_claims(
        graph, ClaimScope(TENANT, VERSION, MANIFEST), extractor=extractor
    )
    claim = next(c for c in result.claims if c.quote == footnote)
    ref = claim.source_refs[0]
    assert ref.quote == text[ref.char_start : ref.char_end] == footnote
    assert ref.verification_state == "candidate"
    wire = json.loads(probe.calls[0]["user_json"])["untrusted_document_data"]
    atom = next(s for s in wire["source_sentences"] if s["text"] == footnote)
    assert atom["context_dependent"] is True
    assert atom["parent_quote"] == text
    receipt = next(tmp_path.glob("*/candidate_diagnostics.json"))
    diagnostic = json.loads(receipt.read_text())
    assert diagnostic["context_dependent_count"] == 1
    assert diagnostic["model_call_skipped"] is False


KAKAO_P50 = (
    "카카오 데이터센터 안산은 시공 계획 단계부터 운영까지 에너지 절감 기술과 "
    "친환경 설계를 적용했습니다. "
    "그 결과 친환경 건축인증인 LEED Certified 등급을 획득하여 부지 선정, 대지 환경, "
    "수자원 효율성, 에너지 및 대기환경 등 항목에서 친환경 성과 효율성을 입증했습니다. "
    "또한 소비자시민모임에서 주최하는 에너지위너상을 수상하여 친환경 및 에너지 절감 운영을 "
    "인정받았으며, ISO 14001 인증을 통해 체계적인 환경 관리 역량을 유지하고 있습니다."
)
KAKAO_ISO = "ISO 14001 인증을 통해 체계적인 환경 관리 역량을 유지하고 있습니다."


def test_kakao_p50_v3_binds_only_iso_atomic_claim_for_m1_and_m4(tmp_path):
    from proofops.application.claims import ClaimScope, discover_atomic_claims
    from proofops.application.evidence.binding import ClaimContext, accept_binding
    from proofops_worker.tag_runner import _atomic_v3_binding_enabled

    from tests.acceptance.test_claims import MANIFEST, TENANT, VERSION, graph_of
    from tests.acceptance.test_rules import pack

    graph = graph_of(KAKAO_P50)
    graph = replace(
        graph, blocks=tuple(replace(block, quality="verified") for block in graph.blocks)
    )
    extractor = UpstageClaimExtractor(
        SelectAll(),
        tmp_path,
        extraction_source_ids=True,
        extraction_atomic=True,
        extraction_atomic_v3=True,
    )
    discovery = discover_atomic_claims(
        graph, ClaimScope(TENANT, VERSION, MANIFEST), extractor=extractor
    )
    iso_claim = next(claim for claim in discovery.claims if claim.quote == KAKAO_ISO)
    assert len(discovery.claims) == 4
    assert iso_claim.claim_id and iso_claim.source_quality == "verified"
    assert all(
        claim.claim_id != iso_claim.claim_id for claim in discovery.claims if claim is not iso_claim
    )
    assert _atomic_v3_binding_enabled({"extraction_profile": asdict(extractor.profile)}, iso_claim)
    legacy_profile = _profile_with_options(source_ids=True, extraction_atomic=True)
    assert not _atomic_v3_binding_enabled({"extraction_profile": asdict(legacy_profile)}, iso_claim)

    original = pack()
    claim_source = iso_claim.source_refs[0]

    def subspan(quote):
        offset = claim_source.quote.index(quote)
        return replace(
            claim_source,
            char_start=claim_source.char_start + offset,
            char_end=claim_source.char_start + offset + len(quote),
            quote=quote,
        )

    def bind(ref, element, *, edge_whitespace=False):
        return accept_binding(
            ClaimContext(iso_claim, {}),
            ref,
            {},
            original=graph,
            tenant_id=TENANT,
            rulepack=original,
            element_id=element,
            allow_edge_whitespace=edge_whitespace,
        )

    # The two short replica quotes share the same literal ISO claim. M1 is an
    # ISO method assertion; M4 remains claim-local and cannot be satisfied by
    # the unrelated LEED or award atoms.
    for _replica in range(2, 4):
        assert bind(subspan("ISO 14001 인증"), "M1") == "accepted"
        spaced_quote = replace(
            claim_source,
            char_start=claim_source.char_start - 1,
            quote=" " + KAKAO_ISO,
        )
        assert bind(spaced_quote, "M4") != "accepted"
        assert bind(spaced_quote, "M4", edge_whitespace=True) == "accepted"
    full_paragraph = next(block for block in graph.blocks if block.page_num == 1).source_ref()
    assert bind(full_paragraph, "M4") != "accepted"
    unrelated_claims = (
        next(claim for claim in discovery.claims if "LEED Certified" in claim.quote),
        next(claim for claim in discovery.claims if "에너지위너상" in claim.quote),
    )
    for unrelated_claim in unrelated_claims:
        unrelated_ref = unrelated_claim.source_refs[0]
        assert bind(unrelated_ref, "M1") != "accepted"
        assert bind(unrelated_ref, "M4") != "accepted"
    assert all(
        ref.verification_state == "candidate"
        for claim in discovery.claims
        for ref in claim.source_refs
    )


def test_model_schema_refusal_keeps_source_unknown_and_replays_its_failure_code(tmp_path):
    from proofops.adapters.local.claim_store import extraction_outcome
    from proofops.application.claims import ClaimScope, discover_atomic_claims

    from tests.acceptance.test_claims import MANIFEST, TENANT, VERSION, graph_of

    text = "당사는 2024년 온실가스 배출량을 8% 감축했습니다."
    graph = graph_of(text)
    probe = FakeProbe("{malformed-json")
    extractor = UpstageClaimExtractor(
        probe,
        tmp_path,
        extraction_source_ids=True,
        extraction_failure_diagnostics=True,
    )
    result = discover_atomic_claims(
        graph, ClaimScope(TENANT, VERSION, MANIFEST), extractor=extractor
    )
    assert result.claims == ()
    assert result.processed_source_ids == ()
    assert len(result.receipts) == 1 and result.receipts[0].status == "failed"
    failure = result.exclusions[0]
    assert failure.reason == "MODEL_JSON_INVALID" and failure.state == "unknown"
    assert failure.source_ref.quote == text

    outcome = extraction_outcome(graph, result, claim_pages=(1,), include_source_failures=True)
    assert outcome["status"] == "blocked"
    assert outcome["code"] == "CLAIM_SOURCE_EXTRACTION_FAILURE"
    assert outcome["page_failures"] == []
    assert outcome["failed_sources"] == [
        dict(source_id=failure.source_id, physical_page=1, failure_code="MODEL_JSON_INVALID")
    ]
    replay = discover_atomic_claims(
        graph, ClaimScope(TENANT, VERSION, MANIFEST), extractor=extractor
    )
    assert replay == result
    assert len(probe.calls) == 1
