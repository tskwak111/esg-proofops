import json
from dataclasses import replace

import pytest
from proofops.domain.provenance import canonical_hash

from tests.integration.test_upstage_tagging_v4 import configured


def test_k11_real_wire_routes_compound_baseline_without_changing_old_reader(tmp_path, monkeypatch):
    from proofops.application.analysis_profile import FINALS_I11_POLICY, FINALS_K11_POLICY
    from proofops.application.tagging.finals_i4 import K4_ELEMENTS
    from proofops.application.tagging.k4_contract import RESPONSE_POLICY
    from proofops.application.tagging.k7_wire import POLICY_K10
    from proofops.application.tagging.k11_contract import GUIDANCE, WIRE_POLICY

    adapter, _, _, request = configured(tmp_path, monkeypatch)
    authorization = adapter._authorize(adapter._settings, request)
    settings = replace(adapter._settings, system_prompt=K4_ELEMENTS)
    adapter._settings = settings
    adapter._authorize = lambda *args: authorization
    request["system_prompt"] = settings.system_for_track("goal", None)
    user = json.loads(request["user_json"])
    data = user["untrusted_document_data"]
    data.update(
        allowed_elements=[f"G{i}" for i in range(1, 9)],
        tagging_response_policy=RESPONSE_POLICY,
        tagging_wire_policy=POLICY_K10,
    )
    request["user_json"] = json.dumps(user)
    before = adapter._wire_request(request)
    data["tagging_wire_policy"] = WIRE_POLICY
    request["user_json"] = json.dumps(user)
    after = adapter._wire_request(request)
    assert GUIDANCE in after[0] and GUIDANCE not in before[0]
    assert (
        json.loads(before[1])["untrusted_document_data"]["evidence_catalog"]
        == json.loads(after[1])["untrusted_document_data"]["evidence_catalog"]
    )
    assert before[2] == after[2] and before[4] == after[4]
    assert "unknown/conflict/unreadable" in after[0]
    assert "credited_from=null" in after[0]
    assert FINALS_K11_POLICY["semantic_admission"] == FINALS_I11_POLICY["semantic_admission"]
    assert canonical_hash(FINALS_I11_POLICY) == (
        "0f7f5cd6f7b009d3e2d25bf049da7d91bc9675c595714555e365f16244f15559"
    )


def test_k11_policy_and_publication_keep_v12_and_k11_pins():
    from proofops.application.analysis_profile import (
        FINALS_I11_POLICY,
        FINALS_K10_POLICY,
        FINALS_K10_V2_POLICY,
        FINALS_K11_POLICY,
        FINALS_K11_V1_POLICY,
        V2_PROFILE,
        policy_for,
        publication_policy_for,
    )

    assert policy_for(V2_PROFILE, pinned_hash=canonical_hash(FINALS_I11_POLICY)) == (
        FINALS_I11_POLICY
    )
    assert canonical_hash(FINALS_K11_POLICY) != canonical_hash(FINALS_I11_POLICY)
    for policy in (
        FINALS_I11_POLICY,
        FINALS_K10_POLICY,
        FINALS_K10_V2_POLICY,
        FINALS_K11_V1_POLICY,
        FINALS_K11_POLICY,
    ):
        digest = canonical_hash(policy)
        assert policy_for(V2_PROFILE, pinned_hash=digest) == policy
        assert publication_policy_for(V2_PROFILE, pinned_hash=digest) == policy


@pytest.mark.parametrize(
    "state,value,quotes,expected",
    [
        ("present", "951만 tCO₂e", ("2019년", "951만 tCO₂e"), "present"),
        ("present", None, ("2019년", "951만 tCO₂e"), "unknown"),
        ("present", "2019년", ("2019년",), "unknown"),
        ("present", "2019년 / 951만 tCO₂e", ("2019년", "951만 tCO₂e"), "unknown"),
        ("unknown", None, (), "unknown"),
        ("conflict", None, (), "conflict"),
    ],
)
def test_k11_full_service_requires_literal_normalized_value_and_keeps_guards(
    tmp_path, state, value, quotes, expected
):
    from dataclasses import asdict

    from proofops.application.analysis_profile import FINALS_K11_POLICY
    from proofops.application.budget import TokenUsage
    from proofops.application.evidence.binding import ClaimContext, local_relation_tags
    from proofops.application.evidence.retrieval import freeze_track_packet, retrieve_evidence
    from proofops.application.tagging.service import RawTagResponse, tag_replicates
    from proofops.application.tagging.tracks import TrackCandidate
    from proofops_worker.live_tagging import LiveTaggingRuntime

    from tests.acceptance.test_binding import span
    from tests.acceptance.test_retrieval import SyntheticSearch
    from tests.acceptance.test_tagging import setup
    from tests.unit.test_k5_context import case

    inputs = setup(tmp_path)
    text = "당사는 기준연도(2019년, 951만 tCO₂e) 수준 유지를 2030년 목표로 설정했습니다."
    graph, claim = case([text], (0, text))
    context = ClaimContext(claim, {})
    track = TrackCandidate(claim, "goal", None)
    packet = retrieve_evidence(
        claim,
        graph,
        SyntheticSearch(graph),
        tenant_id=graph.tenant_id,
        run_id=inputs["packet"].to_dict()["run_id"],
        index_generation="synthetic-v1",
        rulepack=inputs["rulepack"],
        document_context={},
        token_counter=lambda text: 1,
    )
    packet = freeze_track_packet(packet, track=track, rulepack=inputs["rulepack"])
    runtime = object.__new__(LiveTaggingRuntime)
    runtime.graph = graph
    runtime.snapshot = dict(analysis_profile_policy=FINALS_K11_POLICY)
    packet = runtime.display_packet(packet, claim=claim)

    def respond(request):
        user = json.loads(request["user_json"])
        assert (
            user["untrusted_document_data"]["tagging_wire_policy"]
            == (FINALS_K11_POLICY["tagging_wire_policy"])
        )
        payload = dict(
            claim_id=request["claim_id"],
            packet_sha256=request["packet_sha256"],
            replicate_id=request["replicate_id"],
            track="goal",
            safe_harbor_category=None,
            superlative_quote=None,
            warnings=[],
            elements=[
                dict(
                    element_id=f"G{i}",
                    state=state if i == 3 else "unknown",
                    evidence_refs=[asdict(span(claim.source_refs[0], q)) for q in quotes]
                    if i == 3
                    else [],
                    normalized_value=value if i == 3 else None,
                    credited_from=None,
                    reason_code=None,
                )
                for i in range(1, 9)
            ],
        )
        return RawTagResponse(
            json.dumps(payload),
            TokenUsage(10, 5, 0, 0, 1, "succeeded", f"synthetic-{request['replicate_id']}"),
            True,
        )

    inputs.update(
        packet=packet,
        context=context,
        track=track,
        original=graph,
        relation_tags=local_relation_tags(context),
        invoke=respond,
        semantic_policy=FINALS_K11_POLICY["semantic_admission"],
    )
    runs = tag_replicates(**inputs)
    assert len(runs) == 3
    for run in runs:
        selected = next(e for e in run.guarded.elements if e.element_id == "G3")
        assert selected.state == expected
        if expected == "present":
            assert all(ref.verification_state == "verified" for ref in selected.evidence_refs)
            assert selected.normalized_value == value


def test_k11_unaffected_tracks_render_byte_identical_prompts():
    from proofops.application.tagging.k10_contract import elements as before
    from proofops.application.tagging.k11_contract import elements as after

    schema = dict(type="object", properties={}, additionalProperties=False)
    for track in ("performance", "management"):
        classification = dict(track=track, safe_harbor_category=None)
        assert before(schema, classification) == after(schema, classification)


def test_k11_create_resume_and_runtime_keep_selected_policy_pin(tmp_path, monkeypatch):
    import os
    import sys

    from proofops.application.analysis_profile import FINALS_K11_POLICY
    from proofops_api.local_runtime import load_local_runtime

    from evaluation import local_upstage_pilot as pilot
    from tests.integration.test_finals_candidate_profile import create_argv

    monkeypatch.setattr(os, "environ", os.environ.copy())
    pin = canonical_hash(FINALS_K11_POLICY)
    monkeypatch.setattr(
        sys,
        "argv",
        create_argv(tmp_path)
        + [
            "--analysis-profile",
            "finals-unattended-v2",
            "--analysis-policy-sha256",
            pin,
            "--pages",
            "1",
            "--claim-pages",
            "1",
            "--mixed-ocr-max-pages",
            "1",
        ],
    )
    assert pilot.main() == 0
    state = tmp_path / "state"
    env = dict(
        LOCAL_PARSER_PROFILE_PATH=str(state / "parser.json"),
        LOCAL_RUN_SETTINGS_PATH=str(state / "settings.json"),
        LOCAL_EXTRACTION_MODE="upstage_probe",
        LOCAL_TAGGING_MODE="upstage_local",
        LOCAL_LLM_PROVIDER="openai",
    )
    assert load_local_runtime(env)["analysis_policy_sha256"] == pin
    before = (state / "settings.json").read_bytes()
    monkeypatch.setattr(sys, "argv", ["pilot", "--resume", "--state", str(state)])
    assert pilot.main() == 0
    assert (state / "settings.json").read_bytes() == before
