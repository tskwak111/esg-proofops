"""RS6's fresh element path must admit the exact pinned PB6 citation policy."""

import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from proofops.adapters.local.openai import MODEL, OpenAIProbe
from proofops.application.analysis_profile import FINALS_I5_POLICY as V2_POLICY
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.preflight import check_local_upstage_tagger
from proofops.application.tagging.service import tag_replicates
from proofops.domain.errors import DomainValidationError
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_tagging import QUOTE_V5_PROFILE, UpstageTaggingTransport

from tests.acceptance.test_tagging import setup
from tests.integration.test_upstage_tagger_preflight import configured as approvals
from tests.integration.test_upstage_tagging_v4 import configured


def failure():
    return json.loads(
        Path(__file__).with_name("hx1_lgchem_failure.json").read_text(encoding="utf-8")
    )


def with_policy(inputs, policy):
    data = inputs["packet"].to_dict()
    data.pop("packet_sha256")
    data["citation_restore_policy"] = policy
    inputs["packet"] = freeze_packet(data)


def test_rs6_policy_reaches_fresh_openai_transport_and_three_replicas(tmp_path, monkeypatch):
    captured = failure()
    assert captured["failed_claim"]["reason"] == "ELEMENTS_UNEXPECTED_DomainValidationError"
    assert captured["failed_claim"]["tag_runs"] == []
    assert V2_POLICY["citation_restore"] == captured["citation_restore_policy"]["profile"]
    adapter, _, _, _ = configured(tmp_path, monkeypatch, model_profile=QUOTE_V5_PROFILE)
    settings = replace(adapter._settings, model_id=MODEL, wire_policy_version=2)
    authorization = approvals()
    authorization.pop("settings")
    authorization["binding"].update(
        model_id=MODEL,
        tagging_settings_sha256=canonical_hash(asdict(settings)),
        provider="openai",
        endpoint="https://api.openai.com/v1/chat/completions",
        budget_limit_usd="3.00",
    )
    authorization["consent"]["provider"] = "openai"
    probe = OpenAIProbe("fixture-no-network-key", tmp_path / "openai.sqlite3")
    scope = dict(
        tenant_id=adapter._tenant,
        document=dict(sha256=captured["source_sha256"]),
        analysis_profile_policy=V2_POLICY,
        analysis_profile_policy_sha256=canonical_hash(V2_POLICY),
    )
    probe.configure_response_policy(scope, role="elements")
    transport = UpstageTaggingTransport(
        probe,
        tmp_path / "fresh-elements",
        settings=settings,
        tenant_id=adapter._tenant,
        authorize=lambda selected, request: check_local_upstage_tagger(
            settings=selected, **authorization
        ),
    )
    inputs = setup(tmp_path)
    with_policy(inputs, captured["citation_restore_policy"])
    calls = []

    def post(body):
        calls.append(body)
        wire = json.loads(body["messages"][1]["content"])
        payload = dict(
            claim_id=wire["claim_id"],
            packet_sha256=wire["packet_sha256"],
            replicate_id=wire["replicate_id"],
            track="performance",
            safe_harbor_category=None,
            elements=[
                dict(
                    element_id=element,
                    state="unknown",
                    evidence_refs=[],
                    normalized_value=None,
                    credited_from=None,
                    reason_code=None,
                )
                for element in wire["untrusted_document_data"]["allowed_elements"]
            ],
            superlative_quote=None,
            warnings=[],
        )
        return dict(
            id=f"fixture-replica-{wire['replicate_id']}",
            model=MODEL,
            usage=dict(prompt_tokens=20, completion_tokens=10),
            choices=[dict(finish_reason="stop", message=dict(content=json.dumps(payload)))],
        )

    monkeypatch.setattr(probe, "_post", post)

    def invoke(request):
        with probe.response_context(role="elements", replica=request["replicate_id"]):
            return transport.invoke(request)

    inputs.update(
        settings=settings,
        invoke=invoke,
        count_input_tokens=lambda request: transport.count_input_tokens(
            request, counter=lambda *_: 20
        ),
    )
    runs = tag_replicates(**inputs)
    assert all(r.guarded is not None for r in runs), [
        (r.status, r.errors, r.diagnostic_detail, r.provider_response_json) for r in runs
    ]
    assert len(calls) == 3
    assert [r.replicate_id for r in runs] == [1, 2, 3]
    assert all(r.guarded is not None and not r.recovered for r in runs)
    assert all(e.state == "unknown" for r in runs for e in r.guarded.elements)
    assert all(
        json.loads(r.provider_response_json)["response_request"]["replica"] == r.replicate_id
        for r in runs
    )
    assert probe.summary()["unsettled_calls"] == 0
    assert len({r.usage.provider_request_id for r in runs}) == 3


@pytest.mark.parametrize("change", ["profile", "extra", "numeric_guard"])
def test_unrecognized_policy_still_stops_before_reservation(tmp_path, change):
    inputs = setup(tmp_path)
    policy = failure()["citation_restore_policy"]
    if change == "profile":
        policy["profile"] = "unapproved"
    elif change == "extra":
        policy["allow_unverified"] = True
    else:
        policy["selected_value"] = "unbounded-numeric-substring"
    with_policy(inputs, policy)
    with pytest.raises(DomainValidationError, match="CITATION_RESTORE_POLICY_UNKNOWN"):
        tag_replicates(**inputs)
    assert inputs["invoke"].requests == []
    assert not inputs["usage_store"].cost_data(
        inputs["tenant_id"], inputs["packet"].to_dict()["run_id"]
    )
