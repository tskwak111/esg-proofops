"""QI1 regression contracts; existing profiles and source guards remain intact."""

from types import SimpleNamespace

import pytest


def test_v2_policy_keeps_ev1_and_disables_overlap():
    from proofops.application.analysis_profile import POLICY, V2_POLICY, apply_pilot_profile

    assert POLICY["pipeline_graph"] == "full-parse-only-v1"
    assert V2_POLICY["stage_overlap"] is False
    assert V2_POLICY["max_http_workers"] == 16
    assert V2_POLICY["evidence_source"] == "evidence-source-v1"
    args = SimpleNamespace(analysis_profile="finals-unattended-v2", resume=False)
    apply_pilot_profile(args)
    assert args.pipeline_profile == "finals-unattended-v2"
    assert args.verify_claim_spans and args.extraction_fragment_guard


def test_v2_prompt_is_opt_in_and_pins_definition_hash():
    from proofops.application.analysis_profile import V2_POLICY
    from proofops.application.tagging.quality import ELEMENT_DEFINITIONS, ELEMENT_DEFINITIONS_HASH

    from evaluation.local_upstage_pilot import live_tagging_settings

    old = live_tagging_settings(10, model_id="gpt-6-luna")
    new = live_tagging_settings(10, model_id="gpt-6-luna", element_definition_profile="qi1-v1")
    assert ELEMENT_DEFINITIONS not in old["tagging_settings"]["system_prompt"]
    assert ELEMENT_DEFINITIONS in new["tagging_settings"]["system_prompt"]
    assert (
        old["preliminary_settings"]["system_prompt"] == new["preliminary_settings"]["system_prompt"]
    )
    assert V2_POLICY["element_definitions_sha256"] == ELEMENT_DEFINITIONS_HASH


@pytest.mark.parametrize(
    "source,track,reason",
    [
        ("unverified", "management", "원문 미검증"),
        ("verified", None, "트랙 미합의"),
        ("verified", "management", "규칙 미정"),
    ],
)
def test_full_range_becomes_hold_with_track_ladder(source, track, reason):
    from proofops.application.tagging.quality import hold_projection

    result = dict(
        evidence_grade=None,
        display_type="range",
        grade_range=dict(floor="E0", ceiling="E3", rule_gap=True),
        elements=[],
    )
    item = dict(
        provisional_grade=result,
        source_status=dict(status=source),
        frozen_packet=dict(track=track) if track else {},
        preliminary_agreement=None,
    )
    projected = hold_projection(item)
    assert projected["display_type"] == "hold" and projected["display"] == "판정 보류"
    assert reason in projected["hold_reasons"]
    assert projected["needed_evidence"]
    if track:
        assert {r["track"] for r in projected["needed_evidence"]} == {track}
    assert result["display_type"] == "range"


def test_narrow_range_and_numeric_stay_unchanged():
    from proofops.application.tagging.quality import hold_projection

    for result in (
        dict(evidence_grade="E1", display_type="numeric"),
        dict(evidence_grade=None, display_type="range", grade_range=dict(floor="E1", ceiling="E3")),
    ):
        assert hold_projection(dict(provisional_grade=result)) == result


def test_fragment_is_joined_only_with_selected_date_continuation_or_excluded():
    from proofops_agent.upstage_extraction import join_selected_linewraps

    def span(text, start, end):
        return dict(char_start=start, char_end=end, quote=text[start:end])

    text = "공장 효율 개선사업 시행(2023.\n09), 태양광 발전 870MWh 생산"
    cut = text.index("\n")
    spans = [span(text, 0, cut), span(text, cut + 1, len(text))]
    assert len(join_selected_linewraps(spans, text)) == 2
    joined = join_selected_linewraps(spans, text, fragment_guard=True)
    assert joined == [span(text, 0, len(text))]
    assert join_selected_linewraps(spans[1:], text, fragment_guard=True) == []
    bullet = "2) 폐기물 재활용 체계를 운영한다."
    assert join_selected_linewraps([span(bullet, 0, len(bullet))], bullet, fragment_guard=True)


def test_fragment_guard_gets_its_own_extraction_rule_hash():
    from proofops_agent.upstage_extraction import _profile_with_options

    old = _profile_with_options(source_ids=True, extraction_linewrap_join=True)
    new = _profile_with_options(
        source_ids=True, extraction_linewrap_join=True, extraction_fragment_guard=True
    )
    assert old.prompt_sha256 == new.prompt_sha256
    assert old.rule_sha256 != new.rule_sha256
    with pytest.raises(ValueError, match="FRAGMENT_GUARD"):
        _profile_with_options(source_ids=True, extraction_fragment_guard=True)


def test_unverified_claim_packet_keeps_verified_external_spans_without_promoting_claim():
    from dataclasses import replace

    from proofops.application.evidence.retrieval import unattended_packet

    from tests.acceptance.test_retrieval import retrieve
    from tests.acceptance.test_retrieval_verified_spans import SPAN_QUOTE, scoped_graph

    graph, claim, ref = scoped_graph()
    unverified = replace(claim, source_quality="unverified")
    packet = unattended_packet(retrieve(graph, unverified), profile="finals-unattended-v2")
    external = next(
        c for c in packet.to_dict()["evidence_candidates"] if c["source_id"] == ref.source_id
    )
    assert [r["quote"] for r in external["source_refs"]] == [SPAN_QUOTE]
    assert all(r["verification_state"] == "verified" for r in external["source_refs"])
    assert unverified.source_quality == "unverified"
