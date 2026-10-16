"""J3 must keep literal explicit boundaries and historical W9 hashes."""

import json
from pathlib import Path

import pytest
from proofops_agent.upstage_extraction import UpstageClaimExtractor, _profile_with_options


class OfflineProbe:
    model = "solar-pro3"

    def complete(self, *args, **kwargs):
        raise AssertionError("J3_PROVIDER_CALL_FORBIDDEN")


def extractor(tmp_path, *, j3=True):
    return UpstageClaimExtractor(
        OfflineProbe(),
        tmp_path,
        extraction_source_ids=True,
        extraction_table_rows=True,
        extraction_pb1=True,
        extraction_w9=True,
        extraction_j3=j3,
    )


def test_selected_inline_bullets_are_disjoint_claims_with_literal_offsets(tmp_path):
    text = "• 환경 목표를 승인하며 성과를 모니터링 • 기후 목표 성과를 보수에 반영"
    e = extractor(tmp_path)
    packet = dict(untrusted_document_data=dict(kind="paragraph", source_id="source", text=text))
    spans, diagnostics = e._resolve_payload(
        {"sentence_ids": ["source:0"]}, text, "source", packet=packet
    )
    assert [s.quote for s in spans] == [
        "• 환경 목표를 승인하며 성과를 모니터링",
        "• 기후 목표 성과를 보수에 반영",
    ]
    assert all(text[s.char_start : s.char_end] == s.quote for s in spans)
    assert diagnostics["j3_refinements"][0]["parent_start"] == 0
    old, _ = extractor(tmp_path / "old", j3=False)._resolve_payload(
        {"sentence_ids": ["source:0"]}, text, "source", packet=packet
    )
    assert len(old) == 1


def test_refinement_never_completes_unselected_fragments_or_breaks_prose(tmp_path):
    e = extractor(tmp_path)
    for text in [
        "당사는 Scope 1 및 2 배출량을 줄였다.",
        "당사는 태양광 및 풍력 설비를 운영한다.",
        "• 기후 계획을 수립하고\n이를 실행한다.",
        "• 기후 정책을 수립한다 • 및",
    ]:
        packet = dict(untrusted_document_data=dict(kind="paragraph", source_id="source", text=text))
        spans, _ = e._resolve_payload({"sentence_ids": ["source:0"]}, text, "source", packet=packet)
        assert len(spans) == 1
        assert spans[0].quote in text


def test_selected_effect_row_splits_only_at_complete_explicit_cells():
    from proofops.application.claims import validate_extraction_response
    from proofops.application.ingest.j3_recall import refine_selected
    from proofops.application.ingest.w9_tables import grid

    case = json.loads((Path(__file__).parents[1] / "fixtures/w9/cr2-tables.json").read_text())[
        "T01"
    ]
    row = grid(case["text"], case["cells"])[3]
    selected = dict(
        char_start=row["start"],
        char_end=row["end"],
        quote=case["text"][row["start"] : row["end"]],
        kind="claim",
        reason=None,
        topic_ids=["environment"],
    )
    spans, changes = refine_selected([selected], case["text"], kind="table", cells=case["cells"])
    assert len(spans) == 5 and changes
    assert all("\t" not in s["quote"] for s in spans)
    assert all(case["text"][s["char_start"] : s["char_end"]] == s["quote"] for s in spans)
    assert all(row["start"] <= s["char_start"] < s["char_end"] <= row["end"] for s in spans)
    assert len(validate_extraction_response({"spans": spans}, case["text"])) == 5
    assert not any("2022년" in s["quote"] for s in spans)  # unselected header never donated


def test_no_unselected_content_and_no_grid_inference():
    from proofops.application.ingest.j3_recall import refine_selected

    text = "태양광 전력 절감\t풍력 전력 절감"
    assert refine_selected([], text, kind="table", cells=[])[0] == []
    selected = dict(char_start=0, char_end=len(text), quote=text)
    assert refine_selected([selected], text, kind="table")[0] == [selected]


def test_j3_profiles_are_distinct_without_mutating_w9():
    from proofops.application.analysis_profile import J3_POLICY, J3_PROFILE, V2_POLICY, policy_for
    from proofops.domain.provenance import canonical_hash

    assert policy_for(J3_PROFILE) == J3_POLICY
    assert J3_POLICY["selected_span_refinement"] == "j3-explicit-boundaries-v1"
    assert policy_for("finals-unattended-v2", pinned_hash=canonical_hash(V2_POLICY)) == V2_POLICY
    assert canonical_hash(J3_POLICY) != canonical_hash(V2_POLICY)
    assert (
        _profile_with_options(source_ids=True, extraction_pb1=True, extraction_w9=True).rule_sha256
        != _profile_with_options(
            source_ids=True, extraction_pb1=True, extraction_w9=True, extraction_j3=True
        ).rule_sha256
    )
    with pytest.raises(ValueError, match="J3"):
        _profile_with_options(extraction_j3=True)


def test_excessive_expansion_preserves_every_selected_parent():
    from proofops.application.ingest.j3_recall import refine_selected

    text = " ".join(f"• 환경 목표 {index} 달성을 위한 설비 운영" for index in range(65))
    selected = dict(char_start=0, char_end=len(text), quote=text)
    assert refine_selected([selected], text, kind="paragraph") == ([selected], [])
