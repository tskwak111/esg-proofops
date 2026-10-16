"""DEC-24 changes guidance/display/extraction, never rule-engine votes."""

from copy import deepcopy
from types import SimpleNamespace

import pytest


def test_old_policy_and_guidance_replay():
    from proofops.application.analysis_profile import (
        FINALS_I2_POLICY,
        V2_D24_POLICY,
        V2_POLICY,
        V2_PRE_D24_POLICY,
        policy_for,
    )
    from proofops.application.tagging.dec24 import (
        DEFINITIONS,
        DEFINITIONS_HASH,
        INTEGRATED_DEFINITIONS,
        INTEGRATED_DEFINITIONS_HASH,
        INTEGRATED_V2_DEFINITIONS,
        INTEGRATED_V2_DEFINITIONS_HASH,
    )
    from proofops.application.tagging.quality import ELEMENT_DEFINITIONS
    from proofops.domain.provenance import canonical_hash

    assert canonical_hash(V2_PRE_D24_POLICY) == (
        "3acefc784aeff5e2c922ceb4cc9d8aed06e089f28eff1980524458e9baf7f1b8"
    )
    assert canonical_hash(V2_PRE_D24_POLICY) != canonical_hash(V2_POLICY)
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(V2_PRE_D24_POLICY))
        == V2_PRE_D24_POLICY
    )
    assert V2_D24_POLICY["element_definitions_sha256"] == DEFINITIONS_HASH
    assert policy_for("finals-unattended-v2", pinned_hash=canonical_hash(V2_D24_POLICY)) == (
        V2_D24_POLICY
    )
    assert DEFINITIONS in INTEGRATED_DEFINITIONS
    assert INTEGRATED_DEFINITIONS_HASH == canonical_hash(INTEGRATED_DEFINITIONS)
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_I2_POLICY))[
            "element_definitions_sha256"
        ]
        == INTEGRATED_V2_DEFINITIONS_HASH
    )
    from proofops.application.tagging.k1_semantics import DEFINITIONS as K1_DEFINITIONS

    assert V2_POLICY["element_definitions_sha256"] == canonical_hash(K1_DEFINITIONS)
    for constraint in (
        "M1",
        "G6",
        "M2",
        "G2",
        "G3/G4",
        "M1/M2/P2",
        "SAME sentence",
        "Scope3",
        "no company/year from another paragraph/page",
        "Preserve G2 conflict",
        "PC1",
    ):
        assert constraint in INTEGRATED_V2_DEFINITIONS
    from evaluation.local_upstage_pilot import live_tagging_settings

    old = live_tagging_settings(10, model_id="gpt-6-luna", element_definition_profile="qi1-v1")
    new = live_tagging_settings(10, model_id="gpt-6-luna", element_definition_profile="dec24-v1")
    assert DEFINITIONS not in old["tagging_settings"]["system_prompt"]
    assert ELEMENT_DEFINITIONS in old["tagging_settings"]["system_prompt"]
    assert DEFINITIONS in new["tagging_settings"]["system_prompt"]
    assert "same sentence" in DEFINITIONS and "G2" in DEFINITIONS
    assert (
        new["preliminary_settings"]["system_prompt"] == old["preliminary_settings"]["system_prompt"]
    )


@pytest.mark.parametrize("category", ["forward_looking", "emissions_estimate"])
def test_estimate_hold_is_display_only_and_versioned(category):
    from proofops.application.tagging.quality import hold_projection

    result = dict(
        evidence_grade=None,
        label=None,
        gap_ids=["GAP-001"],
        grade_range=dict(floor="E0", ceiling="E3", rule_gap=True),
        elements=[],
        semantic_hash="a" * 64,
        rule_pack_sha256="b" * 64,
    )
    item = dict(
        provisional_grade=result,
        source_status=dict(status="verified"),
        frozen_packet=dict(track="performance", safe_harbor_category=category),
    )
    before = deepcopy(item)
    new = hold_projection(item, profile="dec24-v1")
    assert "추정치 · 산정 근거 확인 필요" in new["hold_reasons"]
    old = hold_projection(item, profile="hf1-v1")
    assert "추정치 · 산정 근거 확인 필요" not in old["hold_reasons"]
    for key in result:
        assert new[key] == old[key]
    assert item == before


@pytest.mark.parametrize(
    "gap,category",
    [([], "emissions_estimate"), (["GAP-001"], None), (["GAP-001"], "third_party_information")],
)
def test_other_holds_keep_existing_reason(gap, category):
    from proofops.application.tagging.quality import hold_projection

    item = dict(
        provisional_grade=dict(
            evidence_grade=None,
            gap_ids=gap,
            grade_range=dict(floor="E0", ceiling="E3"),
            elements=[],
        ),
        frozen_packet=dict(track="management", safe_harbor_category=category),
    )
    assert (
        "추정치 · 산정 근거 확인 필요"
        not in hold_projection(item, profile="dec24-v1")["hold_reasons"]
    )


@pytest.mark.parametrize(
    "quote,kind,context,expected",
    [
        ("¹ 산정 시 해외 사업장을 제외하였습니다.", "table_cell", False, True),
        ("² 폐기물은 전량 위탁 처리하여 공시하였습니다.", "paragraph", True, True),
        ("1) 유기물질 측정 지표의 COD에서 TOC로 전환을 반영하였습니다.", "paragraph", True, True),
        ("1.2024년부터 임차자산 배출량을 Scope 1 & 2로 포함하여 산정", "paragraph", True, True),
        ("1) 당사는 환경정책을 수립하고 이행한다.", "paragraph", True, False),
        ("1) 배출량 산정방법을 개선한다.", "paragraph", False, False),
        ("¹ 산정 시 해외 사업장을 제외하였습니다.", "paragraph", False, False),
        ("2024년 배출량 10톤", "table_cell", True, False),
        ("• PUE(전력사용효율지수)2) 1.1x 유지", "table_cell", True, False),
        ("※ 2025년 국내 공장 인증을 유지하고 있습니다.", "paragraph", True, False),
    ],
)
def test_only_numbered_table_notes_are_excluded(quote, kind, context, expected):
    from proofops.application.tagging.dec24 import table_footnote

    assert table_footnote(quote, kind=kind, table_context=context) is expected


def test_extractor_option_has_new_hash_and_preserves_legacy(tmp_path):
    from proofops_agent.upstage_extraction import UpstageClaimExtractor, _profile_with_options

    old = _profile_with_options(source_ids=True)
    new = _profile_with_options(source_ids=True, extraction_table_footnotes=True)
    assert new.rule_sha256 != old.rule_sha256 and new.prompt_sha256 == old.prompt_sha256
    with pytest.raises(ValueError):
        _profile_with_options(extraction_table_footnotes=True)
    text = "¹ 산정 시 해외 사업장을 제외하였습니다."
    packet = dict(untrusted_document_data=dict(kind="table_cell"))
    probe = SimpleNamespace(complete=lambda *a, **kw: None)
    baseline = UpstageClaimExtractor(probe, tmp_path / "old", extraction_source_ids=True)
    candidate = UpstageClaimExtractor(
        probe, tmp_path / "new", extraction_source_ids=True, extraction_table_footnotes=True
    )
    ids = [entry[0] for entry in baseline._sentence_index(text, "source")]
    payload = dict(sentence_ids=ids)
    spans, _ = baseline._resolve_payload(payload, text, "source", packet=packet)
    filtered, diagnostics = candidate._resolve_payload(payload, text, "source", packet=packet)
    assert spans and not filtered
    assert diagnostics["table_footnote_excluded"]
    assert baseline._profile == old


def test_numbered_policy_with_accounting_terms_stays_candidate():
    from proofops.application.tagging.dec24 import table_footnote

    assert not table_footnote(
        "1) 당사는 배출량 산정방법을 개선하고 환경정책을 이행한다.",
        kind="paragraph",
        table_context=True,
    )


def test_table_context_never_crosses_page_or_unlocated_source():
    from proofops.application.tagging.dec24 import adjacent_table

    def block(sid, page, kind, bbox):
        return SimpleNamespace(
            source_id=sid,
            page_num=page,
            kind=kind,
            winner=0,
            source_ref=lambda: SimpleNamespace(bbox=bbox),
        )

    focal = block("note", 1, "paragraph", (10, 100, 200, 120))
    same = block("table", 1, "table", (10, 10, 200, 95))
    packet = dict(untrusted_document_data=dict(source_id="note", kind="paragraph"))
    assert adjacent_table(packet, SimpleNamespace(blocks=[focal, same]))
    same.page_num = 2
    assert not adjacent_table(packet, SimpleNamespace(blocks=[focal, same]))
    same.page_num = 1
    same.source_ref = lambda: SimpleNamespace(bbox=None)
    assert not adjacent_table(packet, SimpleNamespace(blocks=[focal, same]))


def test_new_profile_wires_extraction_and_old_resume_does_not_opt_in():
    from proofops.application.analysis_profile import apply_pilot_profile

    args = SimpleNamespace(analysis_profile="finals-unattended-v2", resume=False)
    apply_pilot_profile(args)
    assert args.extraction_table_footnotes
    legacy = SimpleNamespace(analysis_profile="finals-unattended-v2", resume=True)
    apply_pilot_profile(legacy)
    assert not hasattr(legacy, "extraction_table_footnotes")


def test_estimate_reason_preserves_other_rule_gap_reason():
    from proofops.application.tagging.quality import hold_projection

    item = dict(
        provisional_grade=dict(
            evidence_grade=None,
            gap_ids=["GAP-001", "GAP-006"],
            grade_range=dict(floor="E0", ceiling="E3"),
            elements=[],
        ),
        frozen_packet=dict(track="goal", safe_harbor_category="forward_looking"),
    )
    reasons = hold_projection(item, profile="dec24-v1")["hold_reasons"]
    assert "규칙 미정" in reasons
    assert "추정치 · 산정 근거 확인 필요" in reasons


def test_pb1_table_fast_path_also_excludes_superscript_note(tmp_path):
    import json
    from dataclasses import replace

    from proofops.application.ingest.graph_fusion import fuse_candidates
    from proofops_agent.upstage_extraction import UpstageClaimExtractor

    from tests.acceptance.test_claims import graph_of

    text = "지표명\t단위\t2024\n온실가스 배출량\ttCO2e\t15\n¹ 온실가스 산정 참고\ttCO2e\t20"
    batch = graph_of(text).candidates[0]
    batch = replace(batch, blocks=tuple(replace(b, kind="table") for b in batch.blocks))
    graph = fuse_candidates((batch,), tenant_id=batch.tenant_id)
    block = graph.blocks[0]
    packet = dict(
        tenant_id=graph.tenant_id,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        source_sha256=graph.source_sha256,
        untrusted_document_data=dict(
            source_id=block.source_id, kind="table", page_num=1, text=text
        ),
    )
    probe = SimpleNamespace(complete=lambda *a, **kw: pytest.fail("No paid calls allowed"))
    options = dict(extraction_source_ids=True, extraction_context=True, extraction_pb1=True)
    old = UpstageClaimExtractor(probe, tmp_path / "old", **options)
    new = UpstageClaimExtractor(probe, tmp_path / "new", extraction_table_footnotes=True, **options)
    assert len(old.extract(packet, context_graph=graph)["spans"]) == 2
    result = new.extract(packet, context_graph=graph)
    assert len(result["spans"]) == 1
    assert result["spans"][0]["quote"] == "온실가스 배출량\ttCO2e\t15"
    observations = next((tmp_path / "new").rglob("observations.json"))
    assert len(json.loads(observations.read_text())) == 2
    assert graph.blocks[0].raw_text == text
