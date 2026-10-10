"""New grants, genuine run snapshots and real worker/ledger paths, fake HTTP only."""

import json
from copy import deepcopy
from dataclasses import asdict
from uuid import uuid4

import pytest
from proofops.adapters.aws.usage import LocalSQLiteUsageStore
from proofops.adapters.local.openrouter import CAPACITY_POLICY, OpenRouterProbe
from proofops.application.budget import BudgetLimits, RoleLimit
from proofops.application.ports.models import ModelBinding
from proofops.application.preflight import check_local_decision_binding
from proofops.application.registry import artifact_sha256
from proofops.application.tagging.decisions import MODELS, POLICY, validate_decision_snapshot
from proofops.application.tagging.service import TaggingSettings
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_preliminary import UpstagePreliminaryTransport

from evaluation.local_upstage_pilot import apply_resume_metadata, live_tagging_settings
from tests.acceptance.test_preflight import AUTH, NOW
from tests.integration.test_decisions_transport import configured as probe_setup
from tests.integration.test_live_tagging_runtime_config import (
    _consent_for,
    _draft_pack,
    _live_service,
    _register,
)
from tests.integration.test_live_tagging_worker import configured as worker_setup
from tests.integration.test_upstage_runtime import profiles
from tests.unit.test_decision_profiles import preliminary_answers
from tests.unit.test_extraction_source_id_wiring import _args


def decision_binding(common, settings, provider):
    return dict(
        common,
        provider=provider,
        runtime_binding_id=settings["binding_ids"][provider],
        schema="local_decision_binding_v1",
        role="decision",
        model_id=MODELS[provider]["model"],
        endpoint=MODELS[provider]["endpoint"],
        decision_policy_sha256=canonical_hash(POLICY),
        budget_limit_usd="3.00" if provider == "openai" else "5.00",
    )


def test_separate_model_consent_and_tenant_are_required():
    _, consent = profiles()
    cfg = live_tagging_settings(12, model_id="openai/gpt-6-luna", preliminary_profile="decision-v1")
    settings = cfg["decision_settings"]
    common = {
        k: consent[k]
        for k in (
            "tenant_id",
            "status",
            "version",
            "approved_by",
            "approved_at",
            "purpose",
            "expires_at",
        )
    }
    consent["allowed_decision_models"] = {p: c["model"] for p, c in MODELS.items()}
    for provider in MODELS:
        kwargs = dict(
            binding=decision_binding(common, settings, provider),
            consent=consent,
            auth=AUTH,
            checked_at=NOW,
            source_sha256="a" * 64,
            document_rights="report-test",
            provider=provider,
            settings=settings,
        )
        assert check_local_decision_binding(**kwargs).ready
        bad = deepcopy(consent)
        bad.pop("allowed_decision_models")
        assert not check_local_decision_binding(**(kwargs | dict(consent=bad))).ready
        assert not check_local_decision_binding(**(kwargs | dict(document_rights="foreign"))).ready
        bad["tenant_id"] = str(uuid4())
        with pytest.raises(Exception, match="profile not found"):
            check_local_decision_binding(**(kwargs | dict(consent=bad)))


def run_setup(tmp_path):
    from proofops_agent.upstage_extraction import _profile

    service, body, *_ = _live_service(tmp_path)
    cfg = live_tagging_settings(
        30,
        model_id="openai/gpt-6-luna",
        preliminary_profile="decision-v1",
        relations=True,
        relation_profile="decision-gate-v1",
    )
    service.input_reservation_policy = cfg["input_reservation_policy"]
    for prefix in ("preliminary", "tagging", "relation"):
        raw = cfg[prefix + "_settings"]
        selected = TaggingSettings(**(raw | dict(binding=ModelBinding(**raw["binding"]))))
        setattr(service, prefix + "_settings", selected)
        common, _ = profiles()
        common.update(
            provider="openrouter",
            model_id=selected.model_id,
            runtime_binding_id=selected.binding.binding_id,
            role="tagger",
            endpoint="https://openrouter.ai/api/v1/chat/completions",
            budget_limit_usd="5.00",
            expires_at="2026-09-24T00:00:00Z",
            schema="local_upstage_tagger_binding_v1",
            tagging_settings_sha256=canonical_hash(raw),
            input_reservation_policy_sha256=canonical_hash(CAPACITY_POLICY),
        )
        _register(service, "runtime", common, "runtime_binding_id")
    service.decision_settings = cfg["decision_settings"]
    consent = _consent_for(service, body)
    consent.update(
        provider="openrouter",
        consent_profile_id=str(uuid4()),
        allowed_decision_models={p: c["model"] for p, c in MODELS.items()},
    )
    body["consent_profile_id"] = _register(service, "consent", consent, "consent_profile_id")
    for provider in MODELS:
        _register(
            service,
            "runtime",
            decision_binding(consent, service.decision_settings, provider),
            "runtime_binding_id",
        )
    runtime, _ = profiles()
    runtime.update(
        provider="openrouter",
        runtime_binding_id=str(uuid4()),
        model_id="openai/gpt-6-luna",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
        budget_limit_usd="5.00",
        expires_at="2026-09-24T00:00:00Z",
    )
    body["runtime_binding_id"] = _register(service, "runtime", runtime, "runtime_binding_id")
    service.extraction_profile = _profile("openai/gpt-6-luna")
    service.budget_limits = BudgetLimits(
        10**8,
        10**6,
        (
            # FX5 already reserves both possible Luna schema outputs per call.
            RoleLimit("tagger", 30, 66560, 8192, 74752),
            RoleLimit("decision", 60, 66560, 4096, 70656),
        ),
    )
    body["rule_pack_id"] = _draft_pack(service, AUTH.tenant_id).rule_pack_id
    return service, body


def test_genuine_run_freezes_and_rejects_partial_decision_pins(tmp_path):
    service, body = run_setup(tmp_path)
    result = service.create(AUTH, body, str(uuid4()))
    snapshot = service.store.snapshot(AUTH.tenant_id, result["run_id"])
    validate_decision_snapshot(snapshot)
    assert snapshot["decision_settings"]["policy"] == POLICY
    assert set(snapshot["decision_runtimes"]) == set(MODELS)
    bad = deepcopy(snapshot)
    bad.pop("decision_runtime_hashes")
    with pytest.raises(ValueError, match="DECISION_SNAPSHOT_MISMATCH"):
        validate_decision_snapshot(bad)
    bad = deepcopy(snapshot)
    bad["decision_settings"]["policy"]["threshold"] = 0.1
    with pytest.raises(ValueError):
        validate_decision_snapshot(bad)


def test_run_cannot_enable_decisions_without_grants(tmp_path):
    service, body = run_setup(tmp_path)
    service.decision_settings = None
    with pytest.raises(Exception, match="CONFIG_GATE_BLOCKED"):
        service.create(AUTH, body, str(uuid4()))


def test_resume_restores_only_frozen_profiles_and_cannot_add_them():
    args = _args()
    apply_resume_metadata(
        args,
        dict(
            source_path="/tmp/example.pdf",
            preliminary_profile="decision-v1",
            relation_profile="decision-gate-v1",
        ),
    )
    assert args.preliminary_profile == "decision-v1"
    assert args.relation_profile == "decision-gate-v1"
    with pytest.raises(ValueError, match="profile changed"):
        apply_resume_metadata(
            _args(preliminary_profile="decision-v1"), dict(source_path="/tmp/example.pdf")
        )


def decision_worker(tmp_path, monkeypatch):
    runtime, claim, graph, _, registry, usage = worker_setup(tmp_path, monkeypatch)
    cfg = live_tagging_settings(30, model_id="openai/gpt-6-luna", preliminary_profile="decision-v1")
    snapshot = runtime.snapshot
    snapshot.update(
        input_reservation_policy=CAPACITY_POLICY,
        input_reservation_policy_hash=canonical_hash(CAPACITY_POLICY),
    )
    consent = snapshot["consent"]
    consent.update(
        provider="openrouter", allowed_decision_models={p: c["model"] for p, c in MODELS.items()}
    )
    for prefix in ("preliminary", "tagging"):
        raw = cfg[prefix + "_settings"]
        selected = TaggingSettings(**(raw | dict(binding=ModelBinding(**raw["binding"]))))
        setattr(
            runtime, "preliminary_settings" if prefix == "preliminary" else "settings", selected
        )
        bound = dict(
            snapshot[prefix + "_runtime"],
            runtime_binding_id=selected.binding.binding_id,
            provider="openrouter",
            model_id=selected.model_id,
            endpoint="https://openrouter.ai/api/v1/chat/completions",
            budget_limit_usd="5.00",
            tagging_settings_sha256=canonical_hash(raw),
            input_reservation_policy_sha256=canonical_hash(CAPACITY_POLICY),
        )
        snapshot.update(
            {
                prefix + "_settings": raw,
                prefix + "_settings_hash": canonical_hash(raw),
                prefix + "_runtime": bound,
                prefix + "_runtime_artifact_hash": artifact_sha256(bound),
            }
        )
        registry[("runtime", bound["runtime_binding_id"])] = bound
    settings = cfg["decision_settings"]
    bindings = {p: decision_binding(consent, settings, p) for p in MODELS}
    registry.update({("runtime", b["runtime_binding_id"]): b for b in bindings.values()})
    snapshot.update(
        decision_settings=settings,
        decision_settings_hash=canonical_hash(settings),
        decision_runtimes=bindings,
        decision_runtime_hashes={p: artifact_sha256(b) for p, b in bindings.items()},
    )
    snapshot["input_hash"] = canonical_hash(
        {k: v for k, v in snapshot.items() if k != "input_hash"}
    )
    runtime.runner.store.usage = LocalSQLiteUsageStore(tmp_path / "dec-usage.sqlite3")
    runtime.runner.store.usage.create_budget(
        graph.tenant_id,
        snapshot["run_id"],
        graph.document_version_id,
        BudgetLimits(
            10**8,
            10**6,
            (
                RoleLimit("tagger", 30, 66560, 4096, 70656),
                RoleLimit("decision", 60, 66560, 4096, 70656),
            ),
        ),
    )
    quote = OpenRouterProbe("fake", tmp_path / "luna.sqlite3")
    calls = []

    def post(body):
        calls.append(body)
        data = dict(
            claim_id=claim.claim_id,
            track="management",
            safe_harbor_category=None,
            track_confidence=0.8,
            dimensions=dict(entity=None, metric=None, reporting_period=None),
        )
        return dict(
            id="fake-luna-" + str(len(calls)),
            model=quote.model,
            usage=dict(prompt_tokens=20, completion_tokens=10, cost=0.0001),
            choices=[dict(finish_reason="stop", message=dict(content=json.dumps(data)))],
        )

    quote._post = post
    runtime.ledger = quote.ledger
    runtime.preliminary_transport = UpstagePreliminaryTransport(
        quote,
        tmp_path / "live/preliminary",
        settings=runtime.preliminary_settings,
        tenant_id=graph.tenant_id,
        authorize=runtime._authorize,
    )
    for provider in MODELS:
        probe, _, _ = probe_setup(tmp_path / "judgments", provider)
        runtime.decision_probes[provider] = probe
    return runtime, claim, graph, calls, usage


def test_worker_decisions_override_track_but_never_create_quotes_and_replay_free(
    tmp_path, monkeypatch
):
    runtime, claim, graph, calls, usage = decision_worker(tmp_path, monkeypatch)
    result = runtime.preliminary(claim, graph)
    assert result is not None and result[0].track == "goal"  # quote-generator said management
    assert set(result[1].dimensions) == {"entity", "metric", "reporting_period"}
    assert all(v is None for v in result[1].dimensions.values())
    agreement = runtime.preliminary_agreement(claim.claim_id)
    assert agreement["fields"]["track"]["state"] == "agreed"
    assert agreement["dimensions"]["metric"]["state"] == "unresolved"
    assert agreement["dimensions"]["metric"]["diagnostic_code"] == "DECISION_NO_USABLE_QUOTE"
    assert len(agreement["decision_receipts"]) == 2
    assert len(calls) == 3
    assert usage["decision_usage"]["openai"]["settled_calls"] == 1
    for probe in runtime.decision_probes.values():
        probe._post = lambda _: pytest.fail("saved decision was billed again")
    runtime.preliminary_transport._probe._post = lambda _: pytest.fail(
        "saved quote was billed again"
    )
    assert runtime.preliminary(claim, graph) == result
    assert len(calls) == 3


def test_low_probability_track_is_reviewable_even_when_models_agree(tmp_path, monkeypatch):
    runtime, claim, graph, _, _ = decision_worker(tmp_path, monkeypatch)
    probe = runtime.decision_probes["openrouter"]

    def post(body):
        return dict(
            model=probe.model,
            answers=preliminary_answers(probability=0.79),
            usage=dict(input_tokens=100, output_tokens=0, cost=0.0000042),
        )

    probe._post = post
    assert runtime.preliminary(claim, graph) is None
    assert runtime.preliminary_agreement(claim.claim_id)["fields"]["track"]["state"] == "unresolved"


@pytest.mark.parametrize(
    "jev,expected", [("supports", "supports"), ("partial", "partial"), ("unknown", "unknown")]
)
def test_worker_relation_gate_keeps_candidates_for_review(tmp_path, monkeypatch, jev, expected):
    from proofops.application.evidence.retrieval import freeze_packet
    from proofops.application.tagging.decisions import relation_questions

    from tests.acceptance.test_binding import DIMENSIONS, bind, span, tags
    from tests.unit.test_decision_profiles import answer

    runtime, claim, graph, _, _ = decision_worker(tmp_path, monkeypatch)
    cfg = live_tagging_settings(
        30, model_id="openai/gpt-6-luna", relations=True, relation_profile="decision-gate-v1"
    )
    raw = cfg["relation_settings"]
    runtime.relation_settings = TaggingSettings(
        **(raw | dict(binding=ModelBinding(**raw["binding"])))
    )
    runtime.relation_transport = object()
    refs = [
        claim.source_refs[0],
        next(b.source_ref() for b in graph.blocks if b.source_id != claim.source_refs[0].source_id),
    ]
    runtime.preliminary_records[claim.claim_id] = [
        dict(
            status="validated_candidate",
            values=dict(dimensions={k: asdict(v) for k, v in tags(refs[0]).items()}),
        )
    ] * 3
    # Relation anchors still come from Luna, even when every decision value is null.
    runtime.decision_records[claim.claim_id] = dict(
        fields={k: dict(value=None) for k in DIMENSIONS}
    )

    def selections(prefix, claim, packet, settings, transport, records, validate, **kwargs):
        source = packet["untrusted_document_data"]["sources"][0]
        response = dict(
            relations=[
                dict(
                    source_index=0,
                    dimensions={
                        role: next(
                            c["span_id"]
                            for c in source["occurrences"]
                            if c["quote"] == quote and role in c["roles"]
                        )
                        for role, quote in DIMENSIONS.items()
                    },
                )
            ]
        )
        roles, _ = validate(response)  # real occurrence/source validation
        return [roles] * 3

    runtime._source_replicas = selections
    for provider, probe in runtime.decision_probes.items():
        choice = "supports" if provider == "openai" else jev

        def post(body, selected=choice, model=probe.model):
            state = json.loads(body["input"]) if "input" in body else body["state"]
            assert state["claim_dimensions"] == DIMENSIONS
            return dict(
                model=model,
                answers={
                    "relation": answer(selected, relation_questions()["relation"]["criteria"])
                },
                usage=dict(input_tokens=100, output_tokens=0, cost=0.0000042),
            )

        probe._post = post
    packet = freeze_packet(
        dict(
            tenant_id=graph.tenant_id,
            run_id=runtime.snapshot["run_id"],
            claim_id=claim.claim_id,
            document_version_id=graph.document_version_id,
            parse_manifest_id=graph.parse_manifest_id,
            source_sha256=graph.source_sha256,
            graph_sha256=canonical_hash(asdict(graph)),
            status="candidate",
            evidence_candidates=[dict(source_refs=[asdict(refs[1])])],
        )
    )
    result = runtime.relations(claim, packet)
    record = runtime.relation_records[claim.claim_id][-1]
    assert record["decision_relation"] == expected
    if expected == "supports":
        assert result[refs[1].source_id]["metric"].quote == DIMENSIONS["metric"]
    else:
        assert all(v is None for v in result[refs[1].source_id].values())
        assert record["review_message"] == "후보 있음·확인 필요"
    # The gate did not call/replace the binding engine or invent element states.
    assert bind(graph, claim, span(refs[1], "40%"), result[refs[1].source_id]) in (
        "accepted",
        "undetermined",
    )


def test_supporting_decisions_do_not_bypass_period_and_boundary_guards():
    from proofops.application.tagging.relations import relation_request, validate_relations

    from tests.acceptance.test_binding import DIMENSIONS, bind, corpus, span

    graph, claim, refs = corpus(reporting_period="2024", boundary="해외")
    evidence_dimensions = DIMENSIONS | dict(reporting_period="2024", boundary="해외")
    packet = relation_request(
        (refs[1],),
        graph,
        tenant_id=graph.tenant_id,
        profile="relation-decision-gate-v1",
        claim_text=claim.quote,
        dimensions=evidence_dimensions,
    )
    source = packet["untrusted_document_data"]["sources"][0]
    roles = {
        k: next(c["span_id"] for c in source["occurrences"] if c["quote"] == v and k in c["roles"])
        for k, v in evidence_dimensions.items()
    }
    result = validate_relations(
        (refs[1],),
        graph,
        dict(relations=[dict(source_index=0, dimensions=roles)]),
        tenant_id=graph.tenant_id,
        profile="relation-decision-gate-v1",
        claim_text=claim.quote,
        dimensions=evidence_dimensions,
    )
    assert bind(graph, claim, span(refs[1], "40%"), result[refs[1].source_id]) == "rejected"


def test_api_exposes_decision_fields_and_relation_review_notice(tmp_path, monkeypatch):
    from tests.integration.test_claim_api import _preliminary_unresolved_setup
    from tests.integration.test_run_lifecycle import validate

    worker_path = tmp_path / "worker"
    worker_path.mkdir()
    runtime, claim, graph, _, _ = decision_worker(worker_path, monkeypatch)
    runtime.preliminary(claim, graph)
    (tmp_path / "api").mkdir()
    http, run_id, runner, envelope, record, claim_id = _preliminary_unresolved_setup(
        tmp_path / "api", monkeypatch
    )
    record["preliminary_agreement"] = runtime.preliminary_agreement(claim.claim_id)
    record["relation_records"] = [
        dict(
            decision_relation="partial", status="needs_review", review_message="후보 있음·확인 필요"
        )
    ]
    envelope["claims"][0] = record
    monkeypatch.setattr(runner.tags, "load_snapshot", lambda tenant, run: envelope)
    response = http.get(f"/v1/runs/{run_id}/claims/{claim_id}")
    assert response.status_code == 200, response.text
    validate("ClaimDetail", response.json())
    projection = response.json()["review_projection"]
    track = next(f for f in projection["field_agreements"] if f["field_id"] == "track")
    assert track["replicate_values"] == ["goal", "goal"]
    assert "후보 있음·확인 필요" in projection["blocked_action"]


def test_legacy_recovery_allowance_cannot_buy_new_decision_calls(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from proofops_worker import tag_recovery

    monkeypatch.setattr(tag_recovery, "_lineage", lambda *args: (None, {}))
    tags = SimpleNamespace(load_snapshot=lambda *args: {"decision_settings": {"policy": POLICY}})
    store = SimpleNamespace(
        usage=SimpleNamespace(
            cost_data=lambda *args: pytest.fail("legacy recovery used new profile")
        )
    )
    with pytest.raises(tag_recovery.RecoveryRejected, match="DECISION_PROFILE_UNSUPPORTED"):
        tag_recovery.plan_recovery(
            store,
            tags,
            tenant_id=AUTH.tenant_id,
            run_id=str(uuid4()),
            receipts=tmp_path,
            claim_limit=1,
            max_new_requests=9,
            acknowledged_failures=(),
            authorized_by="test",
            now=1,
        )
