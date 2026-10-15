import json
from dataclasses import asdict

import pytest
from proofops.application.budget import TokenUsage
from proofops.application.evidence.binding import ClaimContext, local_relation_tags
from proofops.application.evidence.retrieval import freeze_track_packet, retrieve_evidence
from proofops.application.tagging.service import RawTagResponse, tag_replicates
from proofops.application.tagging.tracks import TrackCandidate
from proofops_worker.live_tagging import LiveTaggingRuntime

from tests.acceptance.test_retrieval import SyntheticSearch
from tests.acceptance.test_tagging import setup
from tests.unit.test_k5_context import case


@pytest.mark.parametrize(
    "enabled,raw_state,text,expected",
    [
        (False, "present", "가상기업은 매월 에너지 사용량을 점검합니다.", "unknown"),
        (True, "present", "가상기업은 매월 에너지 사용량을 점검합니다.", "present"),
        (True, "unknown", "가상기업은 매월 에너지 사용량을 점검합니다.", "unknown"),
        (True, "conflict", "가상기업은 매월 에너지 사용량을 점검합니다.", "conflict"),
        (True, "present", "환경 서비스를 통해 개선하기 위해 노력합니다.", "unknown"),
    ],
)
def test_qt2_runs_through_frozen_packet_source_guards_and_three_replicas(
    tmp_path, enabled, raw_state, text, expected
):
    from proofops.application.analysis_profile import FINALS_I23_POLICY, QT2_ELEMENTS_POLICY

    inputs = setup(tmp_path)
    graph, claim = case([text], (0, text))
    context = ClaimContext(
        claim, {"entity": None, "metric": None, "reporting_period": None, "scope": None}
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
    runtime.snapshot = dict(
        analysis_profile_policy=QT2_ELEMENTS_POLICY if enabled else FINALS_I23_POLICY
    )
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
                    state=raw_state if i == 4 else "unknown",
                    evidence_refs=[asdict(claim.source_refs[0])] if i == 4 else [],
                    normalized_value=None,
                    credited_from=None,
                    reason_code=None,
                )
                for i in range(1, 7)
            ],
        )
        return RawTagResponse(
            json.dumps(payload),
            TokenUsage(10, 5, 0, 0, 1, "succeeded", f'sim-{request["replicate_id"]}'),
            True,
        )

    inputs.update(
        packet=packet,
        context=context,
        track=track,
        original=graph,
        relation_tags=local_relation_tags(context),
        invoke=respond,
        semantic_policy=FINALS_I23_POLICY["semantic_admission"],
    )
    runs = tag_replicates(**inputs)
    assert seen == [1, 2, 3]
    assert all(r.guarded is not None for r in runs), [r.errors for r in runs]
    assert [next(e for e in r.guarded.elements if e.element_id == "M4").state for r in runs] == [
        expected
    ] * 3


def test_qt2_wire_suffix_is_opt_in_and_preserves_catalog(tmp_path, monkeypatch):
    from proofops.application.tagging.qt2_context import GUIDANCE, POLICY

    from tests.integration.test_upstage_tagging_v4 import configured

    adapter, _, _, request = configured(tmp_path, monkeypatch)
    before = adapter._wire_request(request)
    user = json.loads(request["user_json"])
    user["untrusted_document_data"]["qt2_contextual_elements_policy"] = POLICY
    request["user_json"] = json.dumps(user)
    after = adapter._wire_request(request)
    assert GUIDANCE in after[0] and GUIDANCE not in before[0]
    assert before[2] == after[2]
    user["untrusted_document_data"]["qt2_contextual_elements_policy"] = POLICY | dict(
        profile="forged"
    )
    request["user_json"] = json.dumps(user)
    with pytest.raises(ValueError, match="QT2_CONTEXT_POLICY_MISMATCH"):
        adapter._wire_request(request)
