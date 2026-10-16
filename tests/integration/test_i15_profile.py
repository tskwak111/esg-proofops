"""V15 activates QA2/QC2 while preserving original parser pins and old runs."""

import json
from argparse import Namespace
from dataclasses import asdict

from proofops.adapters.local.claim_source_policies import PAGE_OCR_PROFILES, page_ocr_profile
from proofops.adapters.local.h1_native_title import native_figure_candidates
from proofops.application import analysis_profile as profiles
from proofops.application.claims import ClaimScope, discover_atomic_claims
from proofops.application.ingest.k6_coverage import FIGURE_POLICY
from proofops.application.tagging.q1_contract import (
    QA2_ELEMENT_GUIDANCE,
    QA2_POLICY,
    R12_CLASSIFICATION_GUIDANCE,
)
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import GraphBoundExtractor, UpstageClaimExtractor

from tests.integration.test_qc2_figure_context import figure


def test_v15_default_and_historical_v14_pin():
    selected = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I15_POLICY)
    )
    assert selected == profiles.FINALS_I15_POLICY
    assert selected == profiles.FINALS_I13_POLICY | dict(
        integration_profile="finals-20261014-v15",
        structural_quality_policy=QA2_POLICY,
        structural_quality_policy_sha256=canonical_hash(QA2_POLICY),
        native_figure_policy=FIGURE_POLICY,
        native_figure_policy_sha256=canonical_hash(FIGURE_POLICY),
    )
    from proofops.application.input_failures import POLICY as HX5_POLICY

    assert profiles.FINALS_HX5_POLICY == profiles.FINALS_I15_POLICY | dict(
        source="upstage-ocr-page-v16",
        input_failure_policy=HX5_POLICY,
        input_failure_policy_sha256=canonical_hash(HX5_POLICY),
    )
    assert (
        profiles.policy_for(
            profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I15_POLICY)
        )
        == profiles.FINALS_I15_POLICY
    )
    pin = "05770a9a6e8a4a42270666b28234bd0f0103634397a717a42934a96f2f89a11c"
    assert canonical_hash(selected) != pin
    assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=pin) == profiles.FINALS_I13_POLICY
    assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=pin) == (
        profiles.FINALS_I13_POLICY
    )
    assert selected["source"] in PAGE_OCR_PROFILES
    assert page_ocr_profile(selected["source"]).native_policy()["mode"] == "upstage-ocr-page-v15"
    for policy in (selected, profiles.FINALS_I13_POLICY):
        args = Namespace(
            analysis_profile=profiles.V2_PROFILE, analysis_policy_sha256=canonical_hash(policy)
        )
        profiles.apply_pilot_profile(args)
        assert args.extraction_qc_native_figures == (policy == selected)
        assert args.claim_source_profile == policy["source"]


def test_full_v15_extractor_keeps_i4_qc2_wire_pins_and_restriction_refs(tmp_path):
    from evaluation.h1_replay import flags

    graph, source = figure(
        [
            (30, 50, "Plans for 2035"),
            (30, 65, "- We operate a climate committee."),
            (30, 95, "However, this plan was cancelled."),
        ]
    )
    systems = []

    class Selector:
        def complete(self, system, user, **kwargs):
            systems.append(system)
            entries = json.loads(user)["untrusted_document_data"]["source_sentences"]
            return dict(content=json.dumps(dict(sentence_ids=[e["sentence_id"] for e in entries])))

    extractor = UpstageClaimExtractor(
        Selector(), tmp_path, **flags(profiles.FINALS_I15_POLICY), extraction_qc_native_figures=True
    )
    bound = GraphBoundExtractor(extractor, graph, source.content)
    again, _ = native_figure_candidates(bound.graph, source.content)
    assert asdict(again) == asdict(bound.graph)
    discovery = discover_atomic_claims(
        bound.graph,
        ClaimScope(graph.tenant_id, graph.document_version_id, graph.parse_manifest_id),
        extractor=bound,
    )
    assert len(discovery.claims) == 1
    assert discovery.claims[0].source_quality == "unverified"
    assert systems and all(canonical_hash(s) == extractor.profile.prompt_sha256 for s in systems)
    assert "dispatch-local selectors c0" in systems[0]
    assert "trailing cancellation" in systems[0]
    from proofops.application.ingest.k5_context import sentence_context

    context = sentence_context(discovery.claims[0], bound.graph)
    refs = context["source_refs"]
    assert any("Plans for 2035" in r["quote"] for r in refs)
    assert any("cancelled" in r["quote"] for r in refs)


def test_v15_real_hosted_transport_compiles_qa2_guidance(tmp_path, monkeypatch):
    from deploy.public.offline_fixture import fake_llm
    from tests.test_hosted_hx2 import (
        test_public_default_upload_binding_parse_extract_tag_publication,
    )
    from tests.test_hosted_public import settings

    # The actual provider wire must contain QA2 guidance in both stages.
    seen = {"preliminary": 0, "elements": 0}

    def observe(body):
        messages = body["messages"]
        system = messages[0]["content"]
        if QA2_ELEMENT_GUIDANCE in system:
            seen["elements"] += 1
        if R12_CLASSIFICATION_GUIDANCE in system:
            seen["preliminary"] += 1
        assert "structural_quality_policy" not in messages[1]["content"]
        return fake_llm(body)

    monkeypatch.setattr("tests.test_hosted_hx2.fake_llm", observe)
    test_public_default_upload_binding_parse_extract_tag_publication(
        settings.__wrapped__(tmp_path), tmp_path, monkeypatch
    )
    assert seen["preliminary"] > 0
    # This fixture intentionally holds unverified claims before element dispatch.


def test_v15_k11_element_transport_compiles_qa2_after_authorization(tmp_path, monkeypatch):
    from dataclasses import replace

    from proofops.application.tagging.finals_i4 import K4_ELEMENTS
    from proofops.application.tagging.k4_contract import RESPONSE_POLICY
    from proofops.application.tagging.k11_contract import WIRE_POLICY

    from tests.integration.test_upstage_tagging_v4 import configured

    adapter, _, calls, request = configured(tmp_path, monkeypatch)
    approval = adapter._authorize(adapter._settings, request)
    assert approval.ready
    adapter._settings = replace(adapter._settings, system_prompt=K4_ELEMENTS)
    approved = adapter._settings

    def authorize(settings, dispatched):
        assert settings == approved
        return approval

    adapter._authorize = authorize
    classification = dict(track="performance", safe_harbor_category=None)
    request["system_prompt"] = approved.system_for_track(**classification)
    data = json.loads(request["user_json"])
    data["untrusted_document_data"].update(
        tagging_response_policy=RESPONSE_POLICY,
        tagging_wire_policy=WIRE_POLICY,
        structural_quality_policy=QA2_POLICY,
    )
    request["user_json"] = json.dumps(data)
    system, wire, _, _, _ = adapter._wire_request(request)
    assert QA2_ELEMENT_GUIDANCE in system
    assert "structural_quality_policy" not in json.loads(wire)["untrusted_document_data"]
    assert len((system + wire).encode()) < 16384
    assert not calls
