"""Fresh invocation/source guard and worker wiring, without paid inference."""

import json
from dataclasses import asdict, replace

import pytest
from proofops.application.evidence.binding import ClaimContext
from proofops.application.evidence.retrieval import freeze_track_packet, retrieve_evidence
from proofops.application.tagging.semantic_admission import DEFINITIONS, POLICY
from proofops.application.tagging.service import RawTagResponse, tag_replicates
from proofops.application.tagging.tracks import TrackCandidate
from proofops.application.tagging.unattended import ensure_range, provisional_result
from proofops.domain.rules.engine import RuleContext

from tests.acceptance.test_citations import RUN, TENANT, snapshot
from tests.acceptance.test_retrieval import SyntheticSearch
from tests.acceptance.test_tagging import setup


@pytest.mark.parametrize(
    "eid,text,track",
    [
        ("M1", "환경안전보건 개선 적극 지원", "management"),
        ("M2", "사업장별 영향을 점검하고 있습니다.", "management"),
        ("G6", "재생에너지 전환을 선언했습니다", "goal"),
    ],
)
def test_new_fresh_votes_are_guarded_but_raw_and_legacy_replay_survive(tmp_path, eid, text, track):
    inputs = setup(tmp_path)
    graph, ref = snapshot(text)
    claim = replace(
        inputs["context"].claim,
        quote=text,
        source_refs=(ref,),
        receipt=replace(inputs["context"].claim.receipt, source_id=ref.source_id),
    )
    candidate = TrackCandidate(claim, track, None)
    packet = retrieve_evidence(
        claim,
        graph,
        SyntheticSearch(graph),
        tenant_id=TENANT,
        run_id=RUN,
        index_generation="synthetic-v1",
        rulepack=inputs["rulepack"],
        document_context={},
        token_counter=lambda _: 10,
    )
    packet = freeze_track_packet(packet, track=candidate, rulepack=inputs["rulepack"])
    calls = []
    responder = inputs["invoke"]

    def invoke(request):
        calls.append(request)
        elements = [
            dict(
                element_id=e,
                state="present" if e == eid else "unknown",
                evidence_refs=[asdict(ref)] if e == eid else [],
                normalized_value=None,
                credited_from=None,
                reason_code=None,
            )
            for e in packet.to_dict()["allowed_elements"]
        ]
        payload = dict(
            claim_id=claim.claim_id,
            packet_sha256=packet.packet_sha256,
            replicate_id=request["replicate_id"],
            track=track,
            safe_harbor_category=None,
            elements=elements,
            superlative_quote=None,
            warnings=[],
        )
        usage = replace(responder(request).usage, provider_request_id=f"synthetic-{len(calls)}")
        return RawTagResponse(json.dumps(payload), usage, True)

    inputs.update(
        context=ClaimContext(claim, dict(entity=None, metric=None, reporting_period=None)),
        track=candidate,
        original=graph,
        packet=packet,
        relation_tags={ref.source_id: {}},
        invoke=invoke,
    )
    legacy = tag_replicates(**inputs)
    old_settings = inputs["settings"]
    inputs["settings"] = replace(
        old_settings, system_prompt=old_settings.system_prompt + "\n" + DEFINITIONS
    )
    new = tag_replicates(**inputs, semantic_policy=POLICY)
    assert len(calls) == 6  # a new policy cannot read old response cache as new inference
    for old, run in zip(legacy, new, strict=True):
        assert next(e for e in old.guarded.elements if e.element_id == eid).state == "present"
        element = next(e for e in run.guarded.elements if e.element_id == eid)
        assert element.state == "unknown" and element.reason_code.startswith("W8_")
        assert (
            json.loads(run.raw_response_json)["elements"]
            == json.loads(old.raw_response_json)["elements"]
        )
        assert run.prompt_sha256 != old.prompt_sha256
    recovered = tag_replicates(**(inputs | dict(settings=old_settings)))
    assert len(calls) == 6
    assert all(r.recovered for r in recovered)
    assert [r.semantic_hash for r in recovered] == [r.semantic_hash for r in legacy]


def test_estimate_category_is_held_without_losing_p1_or_reintroducing_a_range(tmp_path):
    inputs = setup(tmp_path)
    candidate = replace(inputs["track"], safe_harbor_category="emissions_estimate")
    packet = retrieve_evidence(
        inputs["context"].claim,
        inputs["original"],
        SyntheticSearch(inputs["original"]),
        tenant_id=TENANT,
        run_id=RUN,
        index_generation="synthetic-v1",
        rulepack=inputs["rulepack"],
        document_context={},
        token_counter=lambda _: 10,
    )
    packet = freeze_track_packet(packet, track=candidate, rulepack=inputs["rulepack"])
    inputs.update(track=candidate, packet=packet)
    inputs["invoke"].changes = {
        i: {"root": {"safe_harbor_category": "emissions_estimate"}} for i in (1, 2, 3)
    }
    runs = tuple(replace(r, product_variant=False) for r in tag_replicates(**inputs))
    context = RuleContext(
        TENANT,
        inputs["context"].claim.document_version_id,
        inputs["context"].claim.claim_id,
        packet.packet_sha256,
        local_synthetic=True,
    )
    result = provisional_result(
        runs, packet, inputs["rulepack"], context, range_profile=True, semantic_policy=POLICY
    )
    assert result["display"] == "추정치 · 산정 근거 확인 필요"
    assert result["evidence_grade"] is None and result["grade_range"] is None
    assert result["elements"][0]["state"] == "present"
    assert ensure_range(result, inputs["rulepack"]) == result


def test_worker_uses_pinned_semantic_policy(tmp_path, monkeypatch):
    from proofops.application.analysis_profile import FINALS_I3_POLICY
    from proofops.application.runs import RunService
    from proofops.application.tagging.k1_semantics import POLICY as INTEGRATED_SEMANTICS
    from proofops.domain.provenance import canonical_hash
    from proofops_worker import tag_runner

    from tests.integration.test_local_tag_runner import verified_setup

    init = RunService.__init__

    def profile(self, *args, **kwargs):
        kwargs["pipeline_profile"] = "finals-unattended-v2"
        kwargs["analysis_policy_sha256"] = canonical_hash(FINALS_I3_POLICY)
        init(self, *args, **kwargs)

    monkeypatch.setattr(RunService, "__init__", profile)
    service, run_id, runner, _, _ = verified_setup(tmp_path, monkeypatch)
    invoke = tag_runner.tag_replicates
    seen = []

    def checked(*args, **kwargs):
        seen.append(kwargs["semantic_policy"])
        return invoke(*args, **kwargs)

    monkeypatch.setattr(tag_runner, "tag_replicates", checked)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "completed"
    assert seen and all(p == INTEGRATED_SEMANTICS for p in seen)
    rows = runner.tags.load_snapshot(TENANT, run_id)["claims"]
    assert all(
        r["provisional_grade"].get("semantic_policy_sha256") == canonical_hash(INTEGRATED_SEMANTICS)
        for r in rows
    ), [
        (r["reason"], r["provisional_grade"], [(t["status"], t["errors"]) for t in r["tag_runs"]])
        for r in rows
    ]
    assert (
        service.store.snapshot(TENANT, run_id)["analysis_profile_policy"]["semantic_admission"]
        == INTEGRATED_SEMANTICS
    )


def test_w8_prompt_still_obeys_authorized_compact_transport_prefix(tmp_path, monkeypatch):
    from proofops_agent.upstage_tagging import QUOTE_V5_PROFILE

    from tests.integration.test_upstage_tagging import configured

    adapter, _, _, request = configured(tmp_path, monkeypatch, model_profile=QUOTE_V5_PROFILE)
    old = adapter._settings
    new = replace(old, system_prompt=old.system_prompt + "\n" + DEFINITIONS)
    adapter._settings = new
    monkeypatch.setattr(adapter, "_authorize_request", lambda _: None)
    request["system_prompt"] = new.system_for_track("performance", None)
    system, user, _, _, _ = adapter._wire_request(request)
    assert DEFINITIONS in system
    assert json.loads(user)["replicate_id"] == 1
