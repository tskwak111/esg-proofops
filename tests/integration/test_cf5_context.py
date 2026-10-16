"""CF5 preserves interpretation, never source authority or majority admission."""

from copy import deepcopy

import pytest
from proofops.application.tagging import cf5_context as cf5
from proofops.application.tagging.preliminary import preliminary_table_request
from proofops.domain.provenance import canonical_hash

from tests.acceptance.test_preliminary import context_corpus


def test_context_keeps_complete_parent_without_changing_numbered_sources():
    graph, claim, info = context_corpus()
    packet = preliminary_table_request(claim, graph, tenant_id=graph.tenant_id)
    before = deepcopy(packet)
    result = cf5.preserve_context(packet, claim, graph)
    assert packet == before
    assert (
        result["untrusted_document_data"]["sources"] == before["untrusted_document_data"]["sources"]
    )
    assert result["untrusted_document_data"]["context_blocks"][0]["text"] == info["body"].raw_text
    assert result["cf5_context_policy"] == cf5.POLICY
    cf5.validate_packet(result)


def test_context_cannot_be_silently_trimmed_after_freezing():
    graph, claim, _ = context_corpus()
    packet = cf5.preserve_context(
        preliminary_table_request(claim, graph, tenant_id=graph.tenant_id), claim, graph
    )
    packet["untrusted_document_data"]["context_blocks"].clear()
    with pytest.raises(ValueError, match="CF5_CONTEXT"):
        cf5.validate_packet(packet)


def test_expansion_retains_existing_table_future_caption_and_footnote():
    from tests.unit.test_k5_context import case

    texts = [
        "2030년 감축 이행 계획",
        "추진 과제\t감축 기여도\n효율화\t3%",
        "※ 이행 계획은 조달 환경에 따라 변경될 수 있습니다.",
    ]
    graph, claim = case(texts, (1, "효율화\t3%"), kinds=["heading", "table", "paragraph"])
    packet = preliminary_table_request(claim, graph, tenant_id=graph.tenant_id)
    before = deepcopy(packet["untrusted_document_data"]["context_blocks"])
    own_ids = {ref.source_id for ref in claim.source_refs}
    result = cf5.preserve_context(packet, claim, graph)
    retained = result["untrusted_document_data"]["context_blocks"]
    assert {texts[0], texts[2]} <= {entry["text"] for entry in retained}
    for entry in before:
        if entry["source_id"] not in own_ids:
            assert any(
                {k: v for k, v in after.items() if k != "context_index"}
                == {k: v for k, v in entry.items() if k != "context_index"}
                for after in retained
            )


def test_opt_in_pin_does_not_change_v27():
    from proofops.application import analysis_profile as profiles

    assert canonical_hash(profiles.FINALS_I27_POLICY) == (
        "fcd788f4c89034141c8767913f1c1acabdaefa1c8f543cdc5231903f05fa1804"
    )
    assert (
        profiles.policy_for(
            profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I27_POLICY)
        )
        == profiles.FINALS_I27_POLICY
    )
    policy = profiles.CF5_POLICY
    assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=canonical_hash(policy)) == policy
    assert (
        profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=canonical_hash(policy))
        == policy
    )


@pytest.mark.parametrize("votes,expected", [(3, True), (2, False), (1, False)])
def test_only_three_independent_matching_headers_are_eligible(votes, expected):
    assert cf5.header_agreed([("management", None)] * votes) is expected
    assert not cf5.header_agreed([("management", None), ("management", None), ("goal", None)])
    assert not cf5.header_agreed([(None, None)] * 3)


def test_preceding_system_and_trailing_future_clause_survive_without_authority_promotion():
    from proofops.application.ingest.k5_context import preliminary_context, sentence_context

    from tests.unit.test_k5_context import case

    text = "회사는 관리 체계를 운영합니다. 공급망을 확보하고, 적용을 확대할 계획입니다."
    graph, claim = case([text], (0, "공급망을 확보하고,"), quality="unverified")
    packet = preliminary_table_request(
        claim, graph, tenant_id=graph.tenant_id, allow_unverified=True
    )
    packet = preliminary_context(packet, sentence_context(claim, graph))
    assert "체계를 운영" not in packet["untrusted_document_data"]["context_blocks"][0]["text"]
    result = cf5.preserve_context(packet, claim, graph)
    entry = result["untrusted_document_data"]["context_blocks"][0]
    assert entry["text"] == text
    assert entry["quality"] == "unverified"
    assert entry["source_ref"]["verification_state"] == "candidate"
    assert claim.source_quality == "unverified"
    assert (
        result["untrusted_document_data"]["sources"] == packet["untrusted_document_data"]["sources"]
    )


def test_table_keeps_header_row_and_future_markers_as_uncitable_context():
    from proofops.application.tagging.preliminary import validate_preliminary_table_sources

    from tests.unit.test_k5_context import case

    text = "설비\t현재 활동\t2027년 계획\n연료전지\t전력 생산\t설치 예정"
    graph, claim = case([text], (0, "연료전지"), kinds=["table"])
    packet = preliminary_table_request(claim, graph, tenant_id=graph.tenant_id)
    result = cf5.preserve_context(packet, claim, graph)
    assert result["untrusted_document_data"]["context_blocks"][0]["text"] == text
    with pytest.raises(ValueError):
        validate_preliminary_table_sources(
            claim,
            graph,
            dict(
                claim_id=claim.claim_id,
                track="management",
                safe_harbor_category=None,
                track_confidence=0.9,
                dimensions=dict(
                    entity=None,
                    reporting_period=None,
                    metric=dict(source_index=0, quote="전력 생산"),
                ),
            ),
            tenant_id=graph.tenant_id,
        )


def test_required_context_over_limit_fails_instead_of_cutting_future_clause():
    graph, claim, _ = context_corpus()
    packet = preliminary_table_request(claim, graph, tenant_id=graph.tenant_id)
    packet["context_policy"]["max_context_chars"] = 5
    with pytest.raises(ValueError, match="CF5_CONTEXT_TOO_LARGE"):
        cf5.preserve_context(packet, claim, graph)


@pytest.mark.parametrize("active", [True, False])
def test_worker_cf5_requires_unanimity_while_historical_behavior_is_unchanged(
    tmp_path, monkeypatch, active
):
    from dataclasses import replace

    from proofops.application.analysis_profile import CF5_POLICY, FINALS_I27_POLICY
    from proofops.application.tagging.pb1_classification import COMPACT_PROFILE
    from proofops.application.tagging.v3_dec92 import PRELIMINARY

    from tests.integration.test_live_tagging_worker import configured

    runtime, claim, graph, _, _, _ = configured(tmp_path, monkeypatch, context=True)
    runtime.snapshot.update(
        pipeline_profile="finals-unattended-v2",
        analysis_profile_policy=CF5_POLICY if active else FINALS_I27_POLICY,
    )
    runtime.preliminary_settings = replace(
        runtime.preliminary_settings,
        model_profile=COMPACT_PROFILE,
        system_prompt=cf5.PRELIMINARY if active else PRELIMINARY,
    )
    runtime.preliminary_transport._settings = runtime.preliminary_settings
    for tracks, accepted in [
        (["management"] * 3, True),
        (["management"] * 2, not active),
        (["management", "management", None], not active),
    ]:

        def replicas(prefix, selected, packet, settings, transport, records, validate, **kwargs):
            records[selected.claim_id] = []
            return [
                validate(
                    dict(
                        claim_id=selected.claim_id,
                        track=track,
                        track_confidence=0.9 if track else None,
                        safe_harbor_category=None,
                        dimensions=dict(entity=None, metric=None, reporting_period=None),
                    )
                )[0]
                for track in tracks
            ]

        runtime._source_replicas = replicas
        assert (runtime.preliminary(claim, graph) is not None) is accepted


def test_real_wire_renders_cf5_and_rejects_changed_context(tmp_path, monkeypatch):
    import json
    from dataclasses import replace
    from pathlib import Path

    from proofops.application.tagging.k4_contract import RESPONSE_POLICY
    from proofops.application.tagging.pb1_classification import COMPACT_PROFILE
    from proofops_agent.upstage_preliminary import UpstagePreliminaryTransport

    from tests.integration.test_upstage_preliminary_table_transport import configured_with_table

    old, request, _, claim, graph = configured_with_table(tmp_path, monkeypatch)
    settings = replace(
        old._settings,
        model_profile=COMPACT_PROFILE,
        system_prompt=cf5.PRELIMINARY,
        schema_json=Path("contracts/jsonschema/preliminary_tags.schema.json").read_text(),
    )
    adapter = UpstagePreliminaryTransport(
        old._probe,
        tmp_path / "cf5",
        settings=settings,
        tenant_id=graph.tenant_id,
        authorize=lambda *args: None,
    )
    monkeypatch.setattr(adapter, "_authorize_request", lambda _: None)
    packet = cf5.preserve_context(
        preliminary_table_request(claim, graph, tenant_id=graph.tenant_id), claim, graph
    )
    packet["preliminary_response_policy"] = RESPONSE_POLICY
    assert adapter.bound_context(packet) == packet
    request.update(
        system_prompt=settings.rendered_system,
        user_json=json.dumps(packet),
        packet_sha256=canonical_hash(packet),
    )
    system, wire, _, _, _ = adapter._wire_request(request)
    assert cf5.GUIDANCE in system
    assert "{{OUTPUT_SCHEMA_JSON}}" not in system
    assert (
        json.loads(wire)["untrusted_document_data"]
        == json.loads(json.dumps(packet))["untrusted_document_data"]
    )
    packet["untrusted_document_data"]["context_blocks"][0]["text"] += " future removed"
    request.update(user_json=json.dumps(packet), packet_sha256=canonical_hash(packet))
    with pytest.raises(ValueError, match="CF5_CONTEXT_PACKET_MISMATCH"):
        adapter._wire_request(request)


def test_new_cf5_run_and_resume_pin_the_new_prompt(tmp_path, monkeypatch):
    from proofops.application.analysis_profile import CF5_POLICY

    from tests.integration.test_v3_pipeline import (
        test_create_resume_pins_v3_and_rejects_wrong_prompt,
    )

    test_create_resume_pins_v3_and_rejects_wrong_prompt(tmp_path, monkeypatch, CF5_POLICY)


def test_hosted_subprocess_accepts_cf5_pin(tmp_path):
    from proofops.application.analysis_profile import CF5_POLICY, V2_PROFILE

    from evaluation.hosted_r108 import prepare_argv
    from tests.test_hosted_analysis import source_pdf

    pdf = tmp_path / "selected.pdf"
    pdf.write_bytes(source_pdf())
    pin = canonical_hash(CF5_POLICY)
    argv = prepare_argv(
        pdf,
        tmp_path / "state",
        "11111111-1111-4111-8111-111111111111",
        dict(report_year=2024, period_start="2024-01-01", period_end="2024-12-31"),
        dict(analysis_profile=V2_PROFILE, analysis_profile_sha256=pin),
    )
    assert argv[argv.index("--analysis-policy-sha256") + 1] == pin
