import json
from dataclasses import asdict

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
    assert base.model_sha256 == atomic.model_sha256
    assert base.prompt_sha256 != atomic.prompt_sha256
    assert base.rule_sha256 != atomic.rule_sha256
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
