"""Source-bound sentence interpretation, including parser-split continuations."""

from dataclasses import replace
from uuid import UUID

import pytest
from proofops.application.ingest.k5_context import POLICY, sentence_context
from proofops.domain.values import SourceRef

from tests.acceptance.test_binding import span
from tests.unit.test_k4_contracts import prose_case


def case(texts, selected, *, kinds=None, quality="verified", x_positions=None):
    graph, claim = prose_case()
    template = graph.blocks[0]
    blocks = []
    for index, text in enumerate(texts):
        x = x_positions[index] if x_positions else 10
        bbox = (x, 778 - index * 16, x + 150, 790 - index * 16)
        candidate = replace(
            template.candidates[0],
            kind=kinds[index] if kinds else "paragraph",
            source=replace(
                template.candidates[0].source,
                source_native_id=str(index),
                raw_text=text,
                char_end=len(text),
                native_bbox=bbox,
            ),
        )
        block = replace(
            template,
            source_id=str(UUID(int=100 + index)),
            kind=candidate.kind,
            candidates=(candidate,),
            quality=quality,
            winner=0,
        )
        blocks.append(block)
    graph = replace(
        graph,
        blocks=tuple(blocks),
        edges=(),
        candidates=tuple(
            replace(batch, blocks=tuple(b.candidates[0] for b in blocks))
            for batch in graph.candidates
        ),
    )
    index, quote = selected
    ref = span(blocks[index].source_ref(), quote)
    return graph, replace(claim, quote=quote, source_refs=(ref,), source_quality=quality)


@pytest.mark.parametrize(
    "quote", ["효율을 설계에 반영하고", "에너지 절감 기술 개발에 선제적으로 투자"]
)
def test_both_connective_atoms_keep_one_complete_sentence(quote):
    text = "효율을 설계에 반영하고 에너지 절감 기술 개발에 선제적으로 투자"
    graph, claim = case([text + "\n• 2030년까지 전환할 목표입니다."], (0, quote))
    context = sentence_context(claim, graph)
    assert context["text"] == text
    assert context["rule_credit"] is False
    assert context["policy"] == POLICY
    assert claim.quote == quote
    assert "2030" not in context["text"]


@pytest.mark.parametrize(
    "texts, selected, expected",
    [
        (
            [
                "SK하이닉스는 2022년부터 위원회를 운영하며 주요 성과에 대해서는 ESG",
                "경영위원회에 정기적으로 보고하고 있습니다.",
            ],
            0,
            "ESG\n경영위원회",
        ),
        (
            [
                "2024년, 반도체 업계 최초로 네온가스를 분리·정제하는 기술을 협력사와 함께",
                "개발해 자원 순환을 통한 온실가스 배출 저감 효과를 얻었습니다.",
            ],
            1,
            "업계 최초",
        ),
        (
            [
                "앞 문장입니다. 각 사업회사는 국가 온실가스 감축목표(NDC)",
                "달성 경로를 반영하여 단계적 감축 목표를 설정하고 있습니다.",
            ],
            1,
            "각 사업회사는",
        ),
        (
            [
                "또한 포항 양극재 공장에 2.5MW 규모의 태양광",
                "설비를 추가 구축 중이며, 2026년 11월 준공 시 연간 2.8GWh 공급이 예상됩니다.",
            ],
            1,
            "포항",
        ),
    ],
)
def test_literal_continuations_keep_subject_scope_year_and_superlative(texts, selected, expected):
    graph, claim = case(texts, (selected, texts[selected]))
    context = sentence_context(claim, graph)
    assert expected in context["text"]
    assert len(context["source_refs"]) == 2
    assert context["verification_state"] == "verified"
    assert "앞 문장" not in context["text"]
    for value in context["source_refs"]:
        ref = SourceRef(**value)
        block = next(b for b in graph.blocks if b.source_id == ref.source_id)
        assert ref.quote == block.raw_text[ref.char_start : ref.char_end]


def test_long_misclassified_heading_continuation_is_interpretation_only():
    text = (
        "앞 문장입니다. " + "각 사업회사는 업종 특성 및 국가 온실가스 감축목표"
        "(Nationally Determined Contribution, NDC)"
    )
    graph, claim = case(
        [text, "달성 경로를 반영하여 단계적 감축 목표를 설정합니다."],
        (1, "달성 경로를 반영하여 단계적 감축 목표를 설정합니다."),
        kinds=["heading", "paragraph"],
    )
    assert "각 사업회사는" in sentence_context(claim, graph)["text"]


def test_unverified_context_never_inherits_focal_verification():
    graph, claim = case(
        ["업계 최초로 네온 기술을 협력사와 함께", "개발해 온실가스를 절감했습니다."],
        (1, "개발해 온실가스를 절감했습니다."),
        quality="unverified",
    )
    context = sentence_context(claim, graph)
    assert context["verification_state"] == "candidate"
    assert all(r["verification_state"] != "verified" for r in context["source_refs"])


@pytest.mark.parametrize(
    "texts,x",
    [
        (["다른 독립 문장입니다.", "개발해 온실가스를 절감했습니다."], [10, 10]),
        (["협력사와 함께", "개발해 온실가스를 절감했습니다."], [10, 400]),
    ],
)
def test_terminal_and_other_column_are_not_joined(texts, x):
    graph, claim = case(texts, (1, texts[1]), x_positions=x)
    assert sentence_context(claim, graph)["text"] == texts[1]


def test_forged_focal_reference_and_foreign_tenant_have_no_context():
    graph, claim = prose_case()
    assert sentence_context(replace(claim, tenant_id=str(UUID(int=999))), graph) is None
    forged = replace(claim.source_refs[0], quote="원문 없는 주어")
    assert sentence_context(replace(claim, source_refs=(forged,)), graph) is None


def test_table_compound_keeps_both_quantities_joint_scope_and_column_header():
    from tests.unit.test_pb4_source import naver_case

    graph, _, table = naver_case()
    _, claim = prose_case()
    quote = (
        "• 약 2,944 tCO₂를 저장, 연간 약 156 tCO₂ 흡수 (커넥트원 포함, 국립공주대학교 연구 결과)"
    )
    ref = span(table.source_ref(), quote)
    claim = replace(claim, tenant_id=graph.tenant_id, source_refs=(ref,), quote=quote)
    context = sentence_context(claim, graph)
    assert "데이터센터 각 춘천" in context["text"]
    assert "2,944" in context["text"] and "연간 약 156" in context["text"]
    assert "커넥트원 포함" in context["text"] and "국립공주대학교 연구 결과" in context["text"]
    assert "건축물 단열" not in context["text"]
    assert context["verification_state"] == "candidate"
    assert context["source_refs"][-1]["bbox"] is not None


def test_short_title_and_ambiguous_neighbours_are_not_joined():
    text = "2024년 업계 최초로 네온 기술을 협력사와 함께"
    graph, claim = case(
        ["네온가스 재활용 기술 개발", text, "개발해 온실가스를 절감했습니다."],
        (2, "개발해 온실가스를 절감했습니다."),
    )
    assert sentence_context(claim, graph)["text"] == text + "\n" + claim.quote
    other = replace(
        graph.blocks[0], source_id=str(UUID(int=987)), candidates=graph.blocks[1].candidates
    )
    graph = replace(graph, blocks=(*graph.blocks, other))
    assert sentence_context(claim, graph)["text"] == claim.quote


def test_raw_unicode_offsets_survive_normalization():
    text = "Cafe\u0301 기술을 개발하고 에너지 절감 설비에 투자합니다."
    quote = "에너지 절감 설비에 투자합니다."
    graph, claim = case([text], (0, quote))
    context = sentence_context(claim, graph)
    assert context["text"] == text
    ref = context["source_refs"][0]
    assert ref["char_end"] == len(text)
    assert ref["verification_state"] == "verified"
