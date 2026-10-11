"""Sentence-prefix recovery from one literal paragraph; historical receipts stay pinned."""

import json
from dataclasses import asdict

import pytest
from proofops_agent.upstage_extraction import UpstageClaimExtractor, _profile_with_options

from tests.integration.test_upstage_extraction import FakeProbe, packet


def resolve(tmp_path, text, suffix, *, enabled=True, kind="paragraph", **options):
    extractor = UpstageClaimExtractor(
        FakeProbe(),
        tmp_path,
        extraction_context=True,
        extraction_source_ids=True,
        extraction_linewrap_join=True,
        extraction_sentence_prefix=enabled,
        **options,
    )
    data = packet(text)
    data["untrusted_document_data"]["kind"] = kind
    source = data["untrusted_document_data"]["source_id"]
    sid = next(
        sid for sid, (a, b) in extractor._sentence_index(text, source) if text[a:b] == suffix
    )
    return extractor._resolve_payload({"sentence_ids": [sid]}, text, source, packet=data)[0]


@pytest.mark.parametrize(
    "prefix,suffix",
    [
        (
            "또한 대기, 수질, 폐기물, 수자원 등 주요 환경 영향",
            "요소에 대한 실행 성과를 축적·분석하고 있습니다.",
        ),
        ("2025년에는 토양오염 관리 지침,", "잔류성오염물질 관리 지침 등을 제·개정했습니다."),
        (
            "또한 환경 개선 과제를 연간 투자 계획에 반영하여 지속적으로",
            "이행함으로써 환경 관리 수준을 강화해 나가고 있습니다.",
        ),
        ("대기오염, 악취, 수질오염,", "폐기물 등 주요 환경 요소를 점검하고 있습니다."),
        (
            "국제표준화기구의 ISO 14001(환경경영시스템)에 부합하는 체계를",
            "기반으로, 환경안전보건방침을 적용하고 있습니다.",
        ),
        ("당사는 재생에너지 조달을", "통해 환경 부담을 줄이고 있습니다."),
        (
            "생산능력 확대에 따른 배출량 증가 요인에도 불구하고,",
            "Scope 1 배출량을 관리하고 있습니다.",
        ),
    ],
)
def test_unselected_prefix_is_literal_and_restored_before_fragment_guard(tmp_path, prefix, suffix):
    text = "이전 환경 정책을 수립했습니다. " + prefix + "\n" + suffix
    spans = resolve(tmp_path, text, suffix, extraction_pb1=True)
    assert len(spans) == 1
    assert spans[0].quote == prefix + "\n" + suffix
    assert text[spans[0].char_start : spans[0].char_end] == spans[0].quote
    old = resolve(tmp_path / "old", text, suffix, enabled=False, extraction_pb1=True)
    if suffix.startswith("통해"):
        assert old == ()
    else:
        assert old[0].quote == suffix


@pytest.mark.parametrize(
    "prefix,kind",
    [
        ("이전 문단의 환경 정책\n\n", "paragraph"),
        ("환경경영\n", "paragraph"),
        ("온실가스\t2024\t20%\n", "paragraph"),
        ("환경 영향을\n", "table"),
        ("환경 영향을\n", "table_cell"),
        ("회사는 온실가스를 감축했으며,\n", "paragraph"),
        ("회사는 대기오염을 모니터링하며,\n", "paragraph"),
        ("We reduced emissions, and\n", "paragraph"),
    ],
)
def test_other_paragraph_heading_row_and_independent_claim_are_not_borrowed(tmp_path, prefix, kind):
    suffix = "폐기물을 줄이고 있습니다."
    assert resolve(tmp_path, prefix + suffix, suffix, kind=kind)[0].quote == suffix


def test_bullet_is_hard_boundary_and_next_bullet_cannot_be_borrowed(tmp_path):
    text = "첫 환경 주제\n• 국내 사업장의 환경 영향을\n줄이고 있습니다."
    assert resolve(tmp_path, text, "줄이고 있습니다.")[0].quote == (
        "• 국내 사업장의 환경 영향을\n줄이고 있습니다."
    )
    text = "국내 환경 영향을\n• 폐기물을 줄입니다."
    assert resolve(tmp_path, text, "• 폐기물을 줄입니다.")[0].quote == "• 폐기물을 줄입니다."
    text = "• 이전 환경 정책 • 국내 사업장의 환경 영향을\n줄이고 있습니다."
    assert resolve(tmp_path, text, "줄이고 있습니다.")[0].quote == (
        "• 국내 사업장의 환경 영향을\n줄이고 있습니다."
    )


def test_earlier_selected_claim_and_derived_blocks_stay_separate():
    from proofops.application.ingest.sentence_prefix import expand_sentence_prefixes

    text = "국내 사업장의 환경 영향을\n줄이고 있습니다."
    cut = text.index("\n")
    spans = [
        dict(char_start=0, char_end=cut, quote=text[:cut]),
        dict(char_start=cut + 1, char_end=len(text), quote=text[cut + 1 :]),
    ]
    assert expand_sentence_prefixes(spans, text, kind="paragraph")[0] == spans
    assert expand_sentence_prefixes(spans[1:], text, kind="derived_paragraph")[0] == spans[1:]


def test_embedded_heading_is_boundary_for_the_following_continuation(tmp_path):
    text = "환경경영\n국내 사업장의 환경 영향을\n줄이고 있습니다."
    assert resolve(tmp_path, text, "줄이고 있습니다.")[0].quote == (
        "국내 사업장의 환경 영향을\n줄이고 있습니다."
    )


def test_prefix_requires_proven_graph_origin_and_refuses_derived_paragraph(tmp_path):
    from dataclasses import replace

    from proofops.application.ingest.graph_fusion import CanonicalEdge

    from tests.acceptance.test_claims import graph_of
    from tests.integration.test_extraction_table_context import _packet

    with pytest.raises(ValueError, match="SENTENCE_PREFIX"):
        UpstageClaimExtractor(
            FakeProbe(),
            tmp_path / "no-context",
            extraction_source_ids=True,
            extraction_linewrap_join=True,
            extraction_sentence_prefix=True,
        )
    text = "국내 사업장의 환경 영향을\n줄이고 있습니다."
    graph = graph_of(text, "다른 원본 문단의 조각")
    focal = next(b for b in graph.blocks if b.normalized_text == text)
    other = next(b for b in graph.blocks if b != focal)
    graph = replace(
        graph, edges=(*graph.edges, CanonicalEdge(focal.source_id, other.source_id, "derived_from"))
    )
    extractor = UpstageClaimExtractor(
        FakeProbe(),
        tmp_path / "derived",
        extraction_context=True,
        extraction_source_ids=True,
        extraction_linewrap_join=True,
        extraction_sentence_prefix=True,
    )
    data = _packet(graph, focal)
    ids = extractor._sentence_index(text, focal.source_id)
    spans, _ = extractor._resolve_payload(
        {"sentence_ids": [ids[1][0]]}, text, focal.source_id, packet=data, context_graph=graph
    )
    assert spans[0].quote == "줄이고 있습니다."


def test_policy_is_opt_in_and_new_receipt_is_immutable(tmp_path):
    old = _profile_with_options(
        extraction_context=True, source_ids=True, extraction_linewrap_join=True
    )
    new = _profile_with_options(
        extraction_context=True,
        source_ids=True,
        extraction_linewrap_join=True,
        extraction_sentence_prefix=True,
    )
    assert old.prompt_sha256 == new.prompt_sha256
    assert old.rule_sha256 != new.rule_sha256
    with pytest.raises(ValueError, match="SENTENCE_PREFIX"):
        _profile_with_options(extraction_sentence_prefix=True)
    text = "2025년 국내 사업장의 환경 영향을\n줄이고 있습니다."
    from tests.acceptance.test_claims import graph_of
    from tests.integration.test_extraction_table_context import _packet

    graph = graph_of(text)
    data = _packet(graph, graph.blocks[0])
    source = data["untrusted_document_data"]["source_id"]
    ids = UpstageClaimExtractor._sentence_index(text, source)
    probe = FakeProbe(json.dumps({"sentence_ids": [ids[1][0]]}))
    extractor = UpstageClaimExtractor(
        probe,
        tmp_path,
        extraction_context=True,
        extraction_source_ids=True,
        extraction_linewrap_join=True,
        extraction_sentence_prefix=True,
    )
    data["extraction_profile"] = asdict(extractor.profile)
    first = extractor.extract(data, context_graph=graph)
    assert first["spans"][0]["quote"] == text
    assert extractor.extract(data, context_graph=graph) == first and len(probe.calls) == 1
    data["extraction_profile"] = asdict(old)
    with pytest.raises(ValueError, match="IDENTITY"):
        extractor.extract(data, context_graph=graph)


def test_expansion_never_approves_source_or_invalid_quote(tmp_path):
    text = "당사는 ‘환경 영향을\n줄이고 있습니다."
    with pytest.raises(ValueError):
        resolve(tmp_path, text, "줄이고 있습니다.")


def test_pilot_resume_and_worker_require_same_prefix_policy(tmp_path, monkeypatch):
    import sys

    from proofops.adapters.local import openrouter
    from proofops_worker.composition import build_composition
    from pypdf import PdfWriter

    from evaluation import local_upstage_pilot as pilot

    pdf, state = tmp_path / "report.pdf", tmp_path / "state"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(pdf)
    argv = [
        "pilot",
        "--pdf",
        str(pdf),
        "--state",
        str(state),
        "--report-year",
        "2025",
        "--period-start",
        "2024-01-01",
        "--period-end",
        "2024-12-31",
        "--parser",
        "local",
        "--extraction-context",
        "--extraction-source-ids",
        "--extraction-linewrap-join",
        "--extraction-sentence-prefix",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    assert pilot.main() == 0
    settings = json.loads((state / "settings.json").read_text())
    expected = asdict(
        _profile_with_options(
            "openai/gpt-6-luna",
            extraction_context=True,
            source_ids=True,
            extraction_linewrap_join=True,
            extraction_sentence_prefix=True,
            wire_policy_version=2,
        )
    )
    assert settings["extraction_profile"] == expected
    assert settings["extraction_sentence_prefix"] is True
    before = (state / "pilot.json").read_bytes()
    monkeypatch.setattr(sys, "argv", ["pilot", "--resume", "--state", str(state)])
    assert pilot.main() == 0 and (state / "pilot.json").read_bytes() == before
    monkeypatch.setattr(sys, "argv", argv[:-1])
    with pytest.raises(ValueError, match="sentence_prefix policy changed"):
        pilot.main()

    class Probe(FakeProbe):
        model = "openai/gpt-6-luna"
        wire_policy_version = 2

        def __init__(self, *args, **kwargs):
            super().__init__()

    monkeypatch.setattr(openrouter, "OpenRouterProbe", Probe)
    for k, v in dict(
        LOCAL_DATABASE_PATH=str(state / "state.sqlite3"),
        LOCAL_PARSER_PROFILE_PATH=str(state / "parser.json"),
        LOCAL_RUN_SETTINGS_PATH=str(state / "settings.json"),
        LOCAL_EXTRACTION_MODE="upstage_probe",
    ).items():
        monkeypatch.setenv(k, v)
    runner = build_composition(stage="extract")
    try:
        assert runner.extractor._sentence_prefix is True
        assert asdict(runner.extractor.profile) == expected
        settings.pop("extraction_sentence_prefix")
        (state / "settings.json").write_text(json.dumps(settings))
        with pytest.raises(ValueError, match="EXTRACTION_PROFILE_MISMATCH"):
            build_composition(stage="extract")
    finally:
        runner.uploads.close()
        runner.uploads.registry.close()


@pytest.mark.parametrize("value,linewrap", [("yes", True), (True, False), (False, True)])
def test_runtime_rejects_unpinned_or_invalid_prefix_opt_in(tmp_path, value, linewrap):
    from proofops_api.local_runtime import load_local_runtime

    from tests.integration.test_local_runtime_config import _budget_limits, _parser_snapshot

    (tmp_path / "parser.json").write_text(json.dumps(_parser_snapshot()))
    settings = dict(
        build_root=str(tmp_path),
        budget_limits=_budget_limits(),
        extraction_profile=asdict(_profile_with_options()),
        extraction_limits=dict(max_calls=2, max_output_tokens=128),
        extraction_sentence_prefix=value,
        extraction_context=True,
        extraction_source_ids=True,
    )
    if linewrap:
        settings["extraction_linewrap_join"] = True
    (tmp_path / "settings.json").write_text(json.dumps(settings))
    with pytest.raises(ValueError, match="LOCAL_RUNTIME_CONFIG_INVALID"):
        load_local_runtime(
            dict(
                LOCAL_DATABASE_PATH=str(tmp_path / "state.sqlite3"),
                LOCAL_PARSER_PROFILE_PATH=str(tmp_path / "parser.json"),
                LOCAL_RUN_SETTINGS_PATH=str(tmp_path / "settings.json"),
                LOCAL_EXTRACTION_MODE="upstage_probe",
            )
        )
