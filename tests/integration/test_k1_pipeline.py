"""K1 fresh candidate, worker pin, compact wire and extraction integration."""

import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from proofops.application.evidence.binding import ClaimContext
from proofops.application.evidence.retrieval import freeze_track_packet, retrieve_evidence
from proofops.application.tagging.k1_semantics import DEFINITIONS, GUIDANCE, POLICY
from proofops.application.tagging.service import RawTagResponse, tag_replicates
from proofops.application.tagging.tracks import TrackCandidate
from proofops.application.tagging.unattended import provisional_result
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.engine import RuleContext

from tests.acceptance.test_citations import RUN, TENANT, snapshot
from tests.acceptance.test_retrieval import SyntheticSearch
from tests.acceptance.test_tagging import setup


@pytest.mark.parametrize(
    "eid,text,track",
    [
        ("M1", "PUE(전력사용효율지수)2) 1.1x 유지", "management"),
        ("M2", "기아는 RE100 이행을 위해", "management"),
        ("P1", "PUE(전력사용효율지수)2) 1.1x 유지", "performance"),
    ],
)
def test_fresh_votes_keep_raw_receipts_and_require_semantic_review(tmp_path, eid, text, track):
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
        payload = dict(
            claim_id=claim.claim_id,
            packet_sha256=packet.packet_sha256,
            replicate_id=request["replicate_id"],
            track=track,
            safe_harbor_category=None,
            elements=[
                dict(
                    element_id=e,
                    state="present" if e == eid else "unknown",
                    evidence_refs=[asdict(ref)] if e == eid else [],
                    normalized_value=None,
                    credited_from=None,
                    reason_code=None,
                )
                for e in packet.to_dict()["allowed_elements"]
            ],
            superlative_quote=None,
            warnings=[],
        )
        return RawTagResponse(
            json.dumps(payload),
            replace(responder(request).usage, provider_request_id=f"synthetic-{len(calls)}"),
            True,
        )

    inputs.update(
        context=ClaimContext(claim, dict(entity=None, metric=None, reporting_period=None)),
        track=candidate,
        original=graph,
        packet=packet,
        relation_tags={ref.source_id: {}},
        invoke=invoke,
    )
    original_settings = inputs["settings"]
    old = tag_replicates(**inputs)
    inputs["settings"] = replace(
        original_settings, system_prompt=original_settings.system_prompt + "\n" + DEFINITIONS
    )
    new = tag_replicates(**inputs, semantic_policy=POLICY)
    for a, b in zip(old, new, strict=True):
        assert json.loads(a.raw_response_json) == json.loads(b.raw_response_json)
        element = next(e for e in b.guarded.elements if e.element_id == eid)
        assert element.state == "unknown"
        assert element.evidence_refs == (ref,)
        assert b.prompt_sha256 != a.prompt_sha256
    if "PUE" in text:
        context = RuleContext(
            TENANT,
            claim.document_version_id,
            claim.claim_id,
            packet.packet_sha256,
            local_synthetic=True,
        )
        result = provisional_result(
            new,
            packet,
            inputs["rulepack"],
            context,
            range_profile=True,
            semantic_policy=POLICY,
            original=graph,
        )
        assert result["evidence_grade"] is None and result["grade_range"] is None
    recovered = tag_replicates(**(inputs | dict(settings=original_settings)))
    assert len(calls) == 6 and all(r.recovered for r in recovered)
    assert [r.semantic_hash for r in recovered] == [r.semantic_hash for r in old]


def test_k1_worker_uses_the_explicit_pin_and_leaves_default_unchanged(tmp_path, monkeypatch):
    from proofops.application.analysis_profile import K1_POLICY, policy_for
    from proofops.application.runs import RunService
    from proofops_worker import tag_runner

    from tests.integration.test_local_tag_runner import verified_setup

    init = RunService.__init__

    def profile(self, *args, **kwargs):
        kwargs.update(
            pipeline_profile="finals-unattended-v2",
            analysis_policy_sha256=canonical_hash(K1_POLICY),
        )
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
    assert seen and all(p == POLICY for p in seen)
    assert service.store.snapshot(TENANT, run_id)["analysis_profile_policy"] == K1_POLICY
    rows = runner.tags.load_snapshot(TENANT, run_id)["claims"]
    assert all(
        r["provisional_grade"]["semantic_policy_sha256"] == canonical_hash(POLICY) for r in rows
    )
    assert policy_for("finals-unattended-v2") != K1_POLICY


def test_k1_compact_preliminary_prompt_is_exactly_pinned_and_unknown_suffix_fails(
    tmp_path, monkeypatch
):
    from proofops.application.tagging.pb1_classification import COMPACT_PROFILE, COMPACT_PROMPT
    from proofops.application.tagging.preliminary import preliminary_table_request
    from proofops_agent.upstage_preliminary import UpstagePreliminaryTransport

    from tests.integration.test_upstage_preliminary_table_transport import configured_with_table

    adapter, request, _, claim, graph = configured_with_table(tmp_path, monkeypatch)
    settings = replace(
        adapter._settings,
        model_profile=COMPACT_PROFILE,
        system_prompt=COMPACT_PROMPT + "\n" + GUIDANCE,
        schema_json=Path("contracts/jsonschema/preliminary_tags.schema.json").read_text(),
    )
    adapter = UpstagePreliminaryTransport(
        adapter._probe,
        tmp_path / "k1-receipts",
        settings=settings,
        tenant_id=TENANT,
        authorize=lambda *args: None,
    )
    monkeypatch.setattr(adapter, "_authorize_request", lambda _: None)
    envelope = preliminary_table_request(
        claim,
        graph,
        tenant_id=TENANT,
        role_resolution=True,
        goal_role=True,
        actor_role=True,
        period_role=True,
    )
    envelope["prompt_sha256"] = canonical_hash(settings.system_prompt)
    request.update(
        model_profile=settings.model_profile,
        system_prompt=settings.rendered_system,
        binding=asdict(settings.binding),
        user_json=json.dumps(envelope),
        packet_sha256=canonical_hash(envelope),
    )
    system, user, _, _, _ = adapter._wire_request(request)
    assert GUIDANCE in system and json.loads(user)["claim_id"] == claim.claim_id
    envelope["prompt_sha256"] = canonical_hash(COMPACT_PROMPT)
    request.update(user_json=json.dumps(envelope), packet_sha256=canonical_hash(envelope))
    with pytest.raises(ValueError, match="PROMPT_INVALID"):
        adapter._wire_request(request)
    with pytest.raises(ValueError, match="BINDING_INVALID"):
        UpstagePreliminaryTransport(
            adapter._probe,
            tmp_path / "bad-receipts",
            settings=replace(settings, system_prompt=settings.system_prompt + " unapproved"),
            tenant_id=TENANT,
            authorize=lambda *args: None,
        )


def test_k1_pilot_selects_new_extraction_hash_and_preserves_resume_pin():
    from argparse import Namespace

    from proofops.application.analysis_profile import K1_POLICY, apply_pilot_profile
    from proofops_agent.upstage_extraction import _profile_with_options

    from evaluation.local_upstage_pilot import live_tagging_settings

    args = Namespace(
        analysis_profile="finals-unattended-v2", analysis_policy_sha256=canonical_hash(K1_POLICY)
    )
    apply_pilot_profile(args)
    assert args.extraction_k1
    settings = live_tagging_settings(
        6,
        model_id="gpt-6-luna",
        element_definition_profile="k1-v1",
        preliminary_context=True,
        preliminary_table_context=True,
        preliminary_table_role=True,
        preliminary_goal_role=True,
        preliminary_actor_role=True,
        preliminary_pb1=True,
    )
    assert GUIDANCE in settings["preliminary_settings"]["system_prompt"]
    assert DEFINITIONS in settings["tagging_settings"]["system_prompt"]
    options = dict(source_ids=True, extraction_table_rows=True)
    assert (
        _profile_with_options(**options).rule_sha256
        != _profile_with_options(**options, extraction_k1=True).rule_sha256
    )
    with pytest.raises(ValueError, match="K1_INVALID"):
        _profile_with_options(extraction_k1=True)
