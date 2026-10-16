"""Offline fixtures through the real policy, packet and source admission paths."""

import json
import os
import sys
from dataclasses import asdict, replace

import pytest
from proofops.application.analysis_profile import FINALS_I24_POLICY, FINALS_I25_POLICY, V3_POLICY
from proofops.application.budget import TokenUsage
from proofops.application.evidence.binding import ClaimContext, local_relation_tags
from proofops.application.evidence.retrieval import freeze_track_packet, retrieve_evidence
from proofops.application.tagging.service import RawTagResponse, tag_replicates
from proofops.application.tagging.tracks import TrackCandidate
from proofops.domain.provenance import canonical_hash
from proofops_worker.live_tagging import LiveTaggingRuntime

from tests.acceptance.test_binding import span
from tests.acceptance.test_retrieval import SyntheticSearch
from tests.acceptance.test_tagging import setup
from tests.unit.test_k5_context import case


@pytest.mark.parametrize("active_policy", [V3_POLICY, FINALS_I25_POLICY])
def test_create_resume_pins_v3_and_rejects_wrong_prompt(tmp_path, monkeypatch, active_policy):
    from proofops_api.local_runtime import load_local_runtime

    from evaluation import local_upstage_pilot as pilot
    from tests.integration.test_finals_candidate_profile import create_argv

    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(
        sys,
        "argv",
        create_argv(tmp_path)
        + [
            "--analysis-profile",
            "finals-unattended-v2",
            "--analysis-policy-sha256",
            canonical_hash(active_policy),
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
    assert load_local_runtime(env)["analysis_policy_sha256"] == canonical_hash(active_policy)
    before = (state / "settings.json").read_bytes()
    settings = json.loads(before)
    settings["preliminary_settings"]["system_prompt"] += " forged"
    (state / "forged.json").write_text(json.dumps(settings))
    with pytest.raises(ValueError):
        load_local_runtime(env | dict(LOCAL_RUN_SETTINGS_PATH=str(state / "forged.json")))
    monkeypatch.setattr(sys, "argv", ["pilot", "--resume", "--state", str(state)])
    assert pilot.main() == 0
    assert (state / "settings.json").read_bytes() == before


@pytest.mark.parametrize("active_policy", [V3_POLICY, FINALS_I25_POLICY])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("raw_category", [None, "forward_looking"])
def test_simple_target_through_preliminary_requires_fresh_category(
    tmp_path, monkeypatch, enabled, raw_category, active_policy
):
    from tests.integration.test_live_tagging_worker import configured

    runtime, _, _, _, _, _ = configured(tmp_path, monkeypatch, context=True)
    quote = "가상기업은 2030년까지 배출량을 20% 감축하겠습니다."
    graph, claim = case([quote], (0, quote))
    runtime.graph = graph
    runtime.snapshot["analysis_profile_policy"] = active_policy if enabled else FINALS_I24_POLICY

    def replicas(prefix, selected, packet, settings, transport, records, validate, **kwargs):
        raw = dict(
            claim_id=selected.claim_id,
            track="goal",
            track_confidence=0.9,
            safe_harbor_category=raw_category,
            dimensions=dict(entity=None, metric=None, reporting_period=None),
        )
        if enabled and raw_category is None:
            with pytest.raises(ValueError, match="V3_DEC92_CATEGORY_RETAG_REQUIRED"):
                validate(raw)
        else:
            result, _ = validate(raw)
            assert result.safe_harbor_category == ("forward_looking" if enabled else raw_category)
        return None

    monkeypatch.setattr(runtime, "_source_replicas", replicas)
    assert runtime.preliminary(claim, graph) is None


PRECEDING = "가상기업은 환경투자 검토를 환경투자심의위원회 승인 절차로 운영합니다."
CLAIM = "가상기업은 환경투자 검토 체계를 갖추고 있습니다."


@pytest.mark.parametrize("active_policy", [V3_POLICY, FINALS_I25_POLICY])
@pytest.mark.parametrize(
    "enabled,raw_state,expected",
    [
        (False, "present", "unknown"),
        (True, "present", "present"),
        (True, "unknown", "unknown"),
        (True, "conflict", "conflict"),
    ],
)
def test_m1_preceding_means_through_three_source_guarded_replicas(
    tmp_path, enabled, raw_state, expected, active_policy
):
    inputs = setup(tmp_path)
    graph, claim = case([PRECEDING + " " + CLAIM], (0, CLAIM))
    ref = span(graph.blocks[0].source_ref(), PRECEDING)
    context = ClaimContext(
        claim,
        {
            "entity": span(claim.source_refs[0], "가상기업"),
            "metric": span(claim.source_refs[0], "환경투자 검토"),
            "reporting_period": None,
        },
    )
    track = TrackCandidate(claim, "management", None)
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
    runtime.snapshot = dict(analysis_profile_policy=active_policy if enabled else FINALS_I24_POLICY)
    packet = runtime.display_packet(packet, claim=claim)
    seen = []

    def respond(request):
        seen.append(request["replicate_id"])
        payload = {k: request[k] for k in ("claim_id", "packet_sha256", "replicate_id")}
        payload.update(
            track="management",
            safe_harbor_category=None,
            superlative_quote=None,
            warnings=[],
            elements=[
                dict(
                    element_id=f"M{i}",
                    state=raw_state if i == 1 else "unknown",
                    evidence_refs=[asdict(ref)] if i == 1 else [],
                    normalized_value=None,
                    credited_from=None,
                    reason_code=None,
                )
                for i in range(1, 7)
            ],
        )
        return RawTagResponse(
            json.dumps(payload),
            TokenUsage(10, 5, 0, 0, 1, "succeeded", f'v3-synthetic-{request["replicate_id"]}'),
            True,
        )

    runs = tag_replicates(
        **(
            inputs
            | dict(
                packet=packet,
                context=context,
                track=track,
                original=graph,
                relation_tags=local_relation_tags(context),
                invoke=respond,
                semantic_policy=FINALS_I24_POLICY["semantic_admission"],
            )
        )
    )
    assert seen == [1, 2, 3]
    assert all(r.guarded for r in runs), [r.errors for r in runs]
    assert [r.guarded.elements[0].state for r in runs] == [expected] * 3
    assert all(e.state == "unknown" for r in runs for e in r.guarded.elements[1:])
    assert all(json.loads(r.raw_response_json)["elements"][0]["state"] == raw_state for r in runs)


def test_v3_wire_guidance_is_pinned_and_old_wire_is_unchanged(tmp_path, monkeypatch):
    from proofops.application.tagging.v3_dec92 import ELEMENT_GUIDANCE, POLICY

    from tests.integration.test_upstage_tagging_v4 import configured

    adapter, _, calls, request = configured(tmp_path, monkeypatch)
    before = adapter._wire_request(request)
    user = json.loads(request["user_json"])
    user["untrusted_document_data"]["v3_dec92_policy"] = POLICY
    request["user_json"] = json.dumps(user)
    after = adapter._wire_request(request)
    assert ELEMENT_GUIDANCE in after[0] and ELEMENT_GUIDANCE not in before[0]
    assert before[2] == after[2]
    assert "v3_dec92_policy" not in json.loads(after[1])["untrusted_document_data"]
    user["untrusted_document_data"]["v3_dec92_policy"] = POLICY | dict(profile="forged")
    request["user_json"] = json.dumps(user)
    with pytest.raises(ValueError, match="V3_DEC92_POLICY_MISMATCH"):
        adapter._wire_request(request)
    assert not calls


def test_v3_preliminary_transport_renders_only_new_category_contract(tmp_path, monkeypatch):
    from pathlib import Path

    from proofops.application.tagging.k4_contract import RESPONSE_POLICY
    from proofops.application.tagging.pb1_classification import COMPACT_PROFILE, COMPACT_PROMPT
    from proofops.application.tagging.preliminary import preliminary_table_request
    from proofops.application.tagging.v3_dec92 import CLASSIFICATION_GUIDANCE, PRELIMINARY
    from proofops_agent.upstage_preliminary import UpstagePreliminaryTransport

    from tests.integration.test_upstage_preliminary_table_transport import configured_with_table

    old, request, _, claim, graph = configured_with_table(tmp_path, monkeypatch)
    settings = replace(
        old._settings,
        model_profile=COMPACT_PROFILE,
        system_prompt=PRELIMINARY,
        schema_json=Path("contracts/jsonschema/preliminary_tags.schema.json").read_text(),
    )
    adapter = UpstagePreliminaryTransport(
        old._probe,
        tmp_path / "v3-receipts",
        settings=settings,
        tenant_id=graph.tenant_id,
        authorize=lambda *args: None,
    )
    monkeypatch.setattr(adapter, "_authorize_request", lambda _: None)
    envelope = preliminary_table_request(
        claim,
        graph,
        tenant_id=graph.tenant_id,
        role_resolution=True,
        goal_role=True,
        actor_role=True,
        period_role=True,
    )
    envelope["prompt_sha256"] = canonical_hash(PRELIMINARY)
    envelope["preliminary_response_policy"] = RESPONSE_POLICY
    request.update(
        model_profile=settings.model_profile,
        system_prompt=settings.rendered_system,
        binding=asdict(settings.binding),
        user_json=json.dumps(envelope),
        packet_sha256=canonical_hash(envelope),
    )
    system, user, _, _, _ = adapter._wire_request(request)
    assert CLASSIFICATION_GUIDANCE in system
    assert "goal with category null" not in system
    assert "목표 선언을 일괄 세이프하버로 바꾸지 않는다" not in system
    assert "문헌조사·현장실사" in system
    assert "preliminary_response_policy" not in json.loads(user)
    envelope["prompt_sha256"] = canonical_hash(COMPACT_PROMPT)
    request.update(user_json=json.dumps(envelope), packet_sha256=canonical_hash(envelope))
    with pytest.raises(ValueError, match="PROMPT_INVALID"):
        adapter._wire_request(request)
