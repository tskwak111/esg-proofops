from dataclasses import replace

import pytest
from proofops.application.tagging import preliminary as p
from proofops.domain.errors import DomainValidationError
from proofops.domain.provenance import canonical_hash

from tests.acceptance.test_citations import TENANT
from tests.acceptance.test_preliminary import context_corpus as corpus
from tests.acceptance.test_preliminary_table_sources import table_corpus


def test_sentence_profile_keeps_numbered_sources_and_verifies_context():
    graph, claim, info = corpus()
    old = p.preliminary_table_request(claim, graph, tenant_id=TENANT)
    new = p.preliminary_table_request(claim, graph, tenant_id=TENANT, sentence_context=True)
    assert new["untrusted_document_data"]["sources"] == old["untrusted_document_data"]["sources"]
    contexts = new["untrusted_document_data"]["context_blocks"]
    assert len(contexts) == 1  # same source block only; no unrelated nearby sentence
    assert contexts[0]["text"] == info["body"].raw_text
    assert contexts[0]["quality"] == "verified"
    assert new["prompt_sha256"] == canonical_hash(p.SENTENCE_CONTEXT_SYSTEM_PROMPT)
    assert old == p.preliminary_table_request(claim, graph, tenant_id=TENANT)


def test_sentence_window_is_literal_and_bounded_to_two_each_side():
    text = "First. Second. Third. Company cut 1.5 tonnes. Fifth. Sixth. Seventh."
    start = text.index("cut")
    begin, end = p._sentence_window(text, start, start + 3)
    assert text[begin:end] == "Second. Third. Company cut 1.5 tonnes. Fifth. Sixth."


def test_unterminated_sentence_is_not_presented_as_complete():
    assert p._sentence_window("First. incomplete claim", 8, 15) is None


def test_unverified_parent_is_not_promoted():
    graph, claim, info = corpus()
    graph = replace(
        graph,
        blocks=tuple(
            replace(b, quality="unverified") if b.source_id == info["body"].source_id else b
            for b in graph.blocks
        ),
    )
    with pytest.raises(DomainValidationError):
        p.preliminary_table_request(claim, graph, tenant_id=TENANT, sentence_context=True)


def test_table_headers_preserve_existing_verified_source_contract():
    graph, claim, _ = table_corpus()
    old = p.preliminary_table_request(claim, graph, tenant_id=TENANT)
    new = p.preliminary_table_request(claim, graph, tenant_id=TENANT, sentence_context=True)
    assert new["table_policy"] == old["table_policy"]
    assert new["untrusted_document_data"]["sources"] == old["untrusted_document_data"]["sources"]


def test_sentence_profile_is_exclusive_and_strict_boolean():
    graph, claim, _ = corpus()
    for kwargs in (
        {"sentence_context": "yes"},
        {"sentence_context": True, "actor_role": True, "goal_role": True, "role_resolution": True},
    ):
        with pytest.raises(DomainValidationError):
            p.preliminary_table_request(claim, graph, tenant_id=TENANT, **kwargs)


@pytest.mark.parametrize("fault", [None, "disagree", "foreign_quote", "revoked"])
def test_worker_sentence_profile_preserves_strict_three_replica_gate(tmp_path, monkeypatch, fault):
    import json
    from dataclasses import asdict

    from proofops.application.registry import artifact_sha256
    from proofops_worker.live_tagging import LiveTaggingRuntime

    from tests.integration.test_live_tagging_worker import configured

    old, claim, graph, calls, profiles, usage = configured(tmp_path, monkeypatch, context=True)
    settings = replace(
        old.preliminary_settings,
        model_profile=p.SENTENCE_CONTEXT_PROFILE,
        system_prompt=p.SENTENCE_CONTEXT_SYSTEM_PROMPT,
    )
    grant = old.snapshot["preliminary_runtime"] | dict(
        tagging_settings_sha256=canonical_hash(asdict(settings))
    )
    profiles["runtime", settings.binding.binding_id] = grant
    snapshot = {k: v for k, v in old.snapshot.items() if k != "input_hash"}
    snapshot.update(
        preliminary_settings=asdict(settings),
        preliminary_settings_hash=canonical_hash(asdict(settings)),
        preliminary_runtime=grant,
        preliminary_runtime_artifact_hash=artifact_sha256(grant),
    )
    snapshot["input_hash"] = canonical_hash(snapshot)
    runtime = LiveTaggingRuntime(
        old.runner,
        snapshot,
        graph,
        old.lease,
        usage,
        probe=old.preliminary_transport._probe,
        ledger=old.ledger,
        receipts=old.receipts,
    )
    if fault == "revoked":
        profiles["runtime", settings.binding.binding_id] = grant | dict(status="revoked")

    def post(body):
        calls.append(body)
        output = dict(
            claim_id=claim.claim_id,
            track="management",
            safe_harbor_category=None,
            track_confidence=0.8,
            dimensions=dict(entity=None, metric=None, reporting_period=None),
        )
        if fault == "disagree" and len(calls) == 2:
            output["track"] = "performance"
        if fault == "foreign_quote":
            output["dimensions"]["entity"] = dict(source_index=0, quote="another company")
        return dict(
            id=f"q3-provider-{len(calls)}",
            model=settings.model_id,
            usage=dict(prompt_tokens=20, completion_tokens=10),
            choices=[dict(finish_reason="stop", message=dict(content=json.dumps(output)))],
        )

    monkeypatch.setattr(runtime.preliminary_transport._probe, "_post", post)
    result = runtime.preliminary(claim, graph)
    assert (result is not None) is (fault is None)
    assert len(calls) == (0 if fault == "revoked" else 1 if fault == "foreign_quote" else 3)
    if calls:
        packets = [json.loads(b["messages"][1]["content"]) for b in calls]
        assert all(packet == packets[0] for packet in packets)
        assert packets[0]["prompt_sha256"] == canonical_hash(p.SENTENCE_CONTEXT_SYSTEM_PROMPT)


def test_pilot_sentence_context_is_opt_in():
    from evaluation.local_upstage_pilot import live_tagging_settings

    flags = dict(
        preliminary_context=True,
        preliminary_table_context=True,
        preliminary_table_role=True,
        preliminary_goal_role=True,
        preliminary_actor_role=True,
    )
    before = live_tagging_settings(9, **flags)
    after = live_tagging_settings(9, **flags, preliminary_sentence_context=True)
    assert before["preliminary_settings"]["model_profile"] != p.SENTENCE_CONTEXT_PROFILE
    assert after["preliminary_settings"]["model_profile"] == p.SENTENCE_CONTEXT_PROFILE
    with pytest.raises(ValueError):
        live_tagging_settings(9, preliminary_sentence_context=True)


def test_trimmed_sentence_context_has_exact_raw_offsets_and_no_citable_promotion():
    from proofops.application.evidence.span_citations import verify_source_ref
    from proofops.domain.values import _source_ref_from_dict

    graph, claim, info = corpus()
    body = info["body"]
    text = "First. Second. Third. " + body.raw_text + " Fifth. Sixth. Seventh."
    candidate = body.candidates[0]
    native = replace(candidate.source, raw_text=text, char_start=0, char_end=len(text))
    block = replace(body, candidates=(replace(candidate, source=native),))
    graph = replace(
        graph,
        blocks=tuple(block if b.source_id == body.source_id else b for b in graph.blocks),
        candidates=tuple(
            replace(
                batch,
                blocks=tuple(block.candidates[0] if c == candidate else c for c in batch.blocks),
            )
            for batch in graph.candidates
        ),
    )
    start = text.index(claim.quote)
    ref = replace(
        block.source_ref(), char_start=start, char_end=start + len(claim.quote), quote=claim.quote
    )
    claim = replace(claim, source_refs=(ref,))
    packet = p.preliminary_table_request(claim, graph, tenant_id=TENANT, sentence_context=True)
    context = packet["untrusted_document_data"]["context_blocks"][0]
    assert context["text"] == "Second. Third. " + body.raw_text + " Fifth. Sixth."
    checked = _source_ref_from_dict(context["source_ref"] | dict(quote=context["text"]))
    assert verify_source_ref(checked, graph, tenant_id=TENANT).verification_state == "verified"
    assert text[checked.char_start : checked.char_end] == context["text"]
    assert packet["untrusted_document_data"]["sources"] == [dict(source_index=0, text=claim.quote)]
    response = dict(
        claim_id=claim.claim_id,
        track="performance",
        safe_harbor_category=None,
        track_confidence=0.9,
        dimensions=dict(
            entity=dict(source_index=0, quote="Second"), metric=None, reporting_period=None
        ),
    )
    with pytest.raises(DomainValidationError):
        p.validate_preliminary_table_sources(claim, graph, response, tenant_id=TENANT)


def test_sentence_window_omitted_whole_when_over_budget():
    graph, claim, info = corpus()
    packet = p.preliminary_table_request(
        claim, graph, tenant_id=TENANT, sentence_context=True, max_context_chars=5
    )
    assert packet["untrusted_document_data"]["context_blocks"] == []
    assert info["body"].source_id in packet["untrusted_document_data"]["omitted_source_ids"]


@pytest.mark.parametrize(
    "profile,prompt",
    [
        (p.SENTENCE_CONTEXT_PROFILE, p.SENTENCE_CONTEXT_SYSTEM_PROMPT),
        (p.SENTENCE_FALLBACK_PROFILE, p.SENTENCE_FALLBACK_SYSTEM_PROMPT),
    ],
)
def test_new_run_accepts_and_pins_sentence_profile(tmp_path, profile, prompt):
    from dataclasses import asdict
    from uuid import uuid4

    from tests.integration.test_live_tagging_runtime_config import (
        AUTH,
        _draft_pack,
        _live_service,
        _register,
        _tagger_binding,
    )

    service, body, *_ = _live_service(tmp_path)
    settings = replace(
        service.preliminary_settings,
        binding=replace(service.preliminary_settings.binding, binding_id=str(uuid4())),
        model_profile=profile,
        system_prompt=prompt,
    )
    _register(
        service,
        "runtime",
        _tagger_binding(settings.binding.binding_id, settings),
        "runtime_binding_id",
    )
    service.preliminary_settings = settings
    body["rule_pack_id"] = _draft_pack(service, AUTH.tenant_id).rule_pack_id
    result = service.create(AUTH, body, str(uuid4()))
    snapshot = service.store.snapshot(AUTH.tenant_id, result["run_id"])
    assert snapshot["preliminary_settings"] == asdict(settings)
    assert snapshot["preliminary_settings_hash"] == canonical_hash(asdict(settings))


def test_verified_complete_span_does_not_require_whole_block_promotion():
    from proofops.application.evidence.span_citations import span_verified_graph

    graph, claim, info = corpus()
    full = replace(info["body"].source_ref(), verification_state="verified")
    graph = replace(
        graph,
        blocks=tuple(
            replace(b, quality="unverified") if b.source_id == full.source_id else b
            for b in graph.blocks
        ),
    )
    graph = span_verified_graph(graph, (full,), "a" * 64)
    packet = p.preliminary_table_request(claim, graph, tenant_id=TENANT, sentence_context=True)
    assert packet["untrusted_document_data"]["context_blocks"][0]["text"] == full.quote
    assert packet["untrusted_document_data"]["context_blocks"][0]["quality"] == "verified"
    assert next(b for b in graph.blocks if b.source_id == full.source_id).quality == "unverified"


def test_verified_atomic_span_cannot_verify_unattested_sentence_neighbors():
    from proofops.application.evidence.span_citations import span_verified_graph

    graph, claim, info = corpus()
    graph = replace(
        graph,
        blocks=tuple(
            replace(b, quality="unverified") if b.source_id == info["body"].source_id else b
            for b in graph.blocks
        ),
    )
    graph = span_verified_graph(
        graph, (replace(claim.source_refs[0], verification_state="verified"),), "a" * 64
    )
    packet = p.preliminary_table_request(claim, graph, tenant_id=TENANT, sentence_context=True)
    assert packet["untrusted_document_data"]["context_blocks"] == []


def test_worker_does_not_dispatch_sentence_profile_without_complete_verified_context(
    tmp_path, monkeypatch
):
    from dataclasses import asdict

    from proofops.application.registry import artifact_sha256
    from proofops_worker import live_tagging

    from tests.integration.test_live_tagging_worker import configured

    old, claim, graph, calls, profiles, usage = configured(tmp_path, monkeypatch, context=True)
    settings = replace(
        old.preliminary_settings,
        model_profile=p.SENTENCE_CONTEXT_PROFILE,
        system_prompt=p.SENTENCE_CONTEXT_SYSTEM_PROMPT,
    )
    grant = old.snapshot["preliminary_runtime"] | dict(
        tagging_settings_sha256=canonical_hash(asdict(settings))
    )
    profiles["runtime", settings.binding.binding_id] = grant
    snapshot = {k: v for k, v in old.snapshot.items() if k != "input_hash"}
    snapshot.update(
        preliminary_settings=asdict(settings),
        preliminary_settings_hash=canonical_hash(asdict(settings)),
        preliminary_runtime=grant,
        preliminary_runtime_artifact_hash=artifact_sha256(grant),
    )
    snapshot["input_hash"] = canonical_hash(snapshot)
    runtime = live_tagging.LiveTaggingRuntime(
        old.runner,
        snapshot,
        graph,
        old.lease,
        usage,
        probe=old.preliminary_transport._probe,
        ledger=old.ledger,
        receipts=old.receipts,
    )
    original = p.preliminary_table_request

    def missing(*args, **kwargs):
        packet = original(*args, **kwargs)
        packet["untrusted_document_data"]["context_blocks"] = []
        return packet

    monkeypatch.setattr(live_tagging, "preliminary_table_request", missing)
    assert runtime.preliminary(claim, graph) is None
    assert calls == []


def test_context_admission_requires_verified_span_or_verified_own_table_headers():
    from copy import deepcopy

    graph, claim, _ = corpus()
    packet = p.preliminary_table_request(claim, graph, tenant_id=TENANT, sentence_context=True)
    assert p.sentence_context_ready(claim, packet)
    unverified = deepcopy(packet)
    unverified["untrusted_document_data"]["context_blocks"][0]["quality"] = "unverified"
    assert not p.sentence_context_ready(claim, unverified)
    unverified = deepcopy(packet)
    unverified["untrusted_document_data"]["context_blocks"][0]["source_ref"]["char_end"] -= 20
    assert not p.sentence_context_ready(claim, unverified)
    graph, claim, _ = table_corpus()
    packet = p.preliminary_table_request(claim, graph, tenant_id=TENANT, sentence_context=True)
    assert p.sentence_context_ready(claim, packet)
    packet["table_policy"]["lineage"] = "unresolved"
    assert not p.sentence_context_ready(claim, packet)
