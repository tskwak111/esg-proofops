"""CF2 keeps failed receipts and resolves citations inside their supplied span."""

import json
from copy import deepcopy
from dataclasses import asdict, replace

import pytest
from proofops.adapters.local import c3_processing
from proofops.application import analysis_profile as profiles
from proofops.application.evidence.binding import ClaimContext
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.tagging import fact_assembly_c3_v2 as c3
from proofops.domain.provenance import canonical_hash

from tests.unit.test_c2_assembly import case
from tests.unit.test_fxb_current_c3 import fresh_response
from tests.unit.test_fxb_current_c3 import reviewed_case as original_reviewed_case


@pytest.fixture
def reviewed_case(monkeypatch):
    return original_reviewed_case.__wrapped__(monkeypatch)


def cf2_policy():
    return profiles.CF2_C3_POLICY


def test_rejected_receipt_is_saved_before_return_and_never_published(reviewed_case, tmp_path):
    inputs, raw = reviewed_case
    raw["triggers"]["governance_claim"] = True
    result = c3_processing.process_case(
        inputs,
        b"",
        output=tmp_path,
        transport=lambda r: fresh_response(r, raw),
        analysis_policy=cf2_policy(),
    )
    receipt = result["receipt"]
    assert receipt["unresolved"] == ["CONDITIONAL_TRIGGER_REVIEW:governance_claim"]
    assert receipt["current_responses_bound_3_of_3"]
    assert not result["published"]
    target = tmp_path / result["cf2_receipt_path"]
    assert json.loads(target.read_text()) == receipt
    assert not (tmp_path / "pilot.json").exists()
    assert not (tmp_path / "state.sqlite3").exists()
    assert c3.replay(receipt, **inputs).to_dict() == receipt
    original = target.read_bytes()
    again = c3_processing.process_case(
        inputs,
        b"",
        output=tmp_path,
        transport=lambda r: fresh_response(r, raw),
        analysis_policy=cf2_policy(),
    )
    assert again == result and target.read_bytes() == original
    target.write_text("{}")
    with pytest.raises(ValueError, match="CF2_RECEIPT_CONFLICT"):
        c3_processing.process_case(
            inputs,
            b"",
            output=tmp_path,
            transport=lambda r: fresh_response(r, raw),
            analysis_policy=cf2_policy(),
        )


def repeated_case():
    inputs, votes = case()
    original = inputs["graph"]
    block = original.blocks[0]
    prefix = "환경경영시스템은 별도 문맥입니다. "
    candidate = block.candidates[0]
    text = prefix + candidate.source.raw_text
    changed = replace(
        candidate, source=replace(candidate.source, raw_text=text, char_end=len(text))
    )
    from proofops.application.ingest.graph_fusion import fuse_candidates

    from tests.unit.test_c2_assembly import seal

    batches = tuple(
        replace(batch, blocks=tuple(changed if c == candidate else c for c in batch.blocks))
        for batch in original.candidates
    )
    graph = fuse_candidates(batches, tenant_id=original.tenant_id)
    graph = replace(graph, blocks=tuple(replace(b, quality="verified") for b in graph.blocks))
    selected = next(b for b in graph.blocks if b.raw_text == text)
    ref = selected.source_ref(normalized_char_start=len(prefix), normalized_char_end=len(text))
    claim = replace(inputs["context"].claim, quote=ref.quote, source_refs=(ref,))
    packet = freeze_packet(
        inputs["packet"].to_dict()
        | dict(graph_sha256=canonical_hash(asdict(graph)), c2_sources=[asdict(ref)])
    )
    inputs.update(context=ClaimContext(claim, {}), graph=graph, packet=packet)
    for vote in votes:
        vote["identity"].update(
            graph_sha256=canonical_hash(asdict(graph)),
            claim_sha256=canonical_hash(asdict(claim)),
            packet_sha256=packet.packet_sha256,
        )
        vote["raw"]["dimensions"]["activity"]["quote"] = "환경경영시스템"
    return inputs, [seal(v) for v in votes]


def test_scoped_lookup_resolves_second_occurrence_without_changing_legacy():
    from proofops.application.tagging import fact_assembly_c2 as c2

    inputs, votes = repeated_case()
    old = c2.assemble(votes, **inputs).to_dict()
    assert "DIRECT_CERTIFICATION_ACTIVITY_UNRESOLVED" in old["unresolved"]
    new = c2.assemble(votes, **inputs, source_scoped_quotes=True).to_dict()
    assert new["candidate_auto_confirmed"]
    assert new["engine_decision"]["evidence_grade"] == "E3"
    assert new["raw_receipts"] == old["raw_receipts"]
    assert c2.replay(old, **inputs).to_dict() == old


def test_opt_in_does_not_change_default_or_historical_pins():
    policy = cf2_policy()
    assert policy != profiles.FINALS_I27_POLICY
    assert profiles.policy_for(profiles.V2_PROFILE) == profiles.V2_POLICY
    assert profiles.V2_POLICY != policy
    assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=canonical_hash(policy)) == policy
    assert canonical_hash(profiles.FINALS_I27_POLICY) == (
        "fcd788f4c89034141c8767913f1c1acabdaefa1c8f543cdc5231903f05fa1804"
    )
    assert (
        profiles.policy_for(
            profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I27_POLICY)
        )
        == profiles.FINALS_I27_POLICY
    )


@pytest.mark.parametrize("trigger", [True, None])
def test_conditional_trigger_is_never_rewritten(reviewed_case, tmp_path, trigger):
    inputs, raw = reviewed_case
    raw["triggers"]["governance_claim"] = trigger
    result = c3_processing.process_case(
        inputs,
        b"",
        output=tmp_path,
        transport=lambda r: fresh_response(r, raw),
        analysis_policy=cf2_policy(),
    )
    assert not result["published"]
    assert result["receipt"]["engine_decision"] is None
    assert all(
        v["raw"]["triggers"]["governance_claim"] is trigger
        for v in result["receipt"]["raw_receipts"]
    )


@pytest.mark.parametrize(
    "change",
    [
        "wire",
        "schema",
        "analysis_policy",
        "missing_bindings",
        "model",
        "prompt",
        "packet",
        "request",
        "unauthenticated",
        "replay",
        "cache",
        "missing_receipt",
        "body",
        "duplicate_origin",
        "simulated",
        "unknown",
        "conflict",
        "source_unverified",
    ],
)
def test_cf2_r16_r16b_response_and_evidence_guards(reviewed_case, tmp_path, change):
    inputs, raw = reviewed_case
    if change == "source_unverified":
        inputs["graph"] = replace(
            inputs["graph"],
            blocks=tuple(replace(b, quality="unreadable") for b in inputs["graph"].blocks),
        )
        inputs["packet"] = freeze_packet(
            inputs["packet"].to_dict() | dict(graph_sha256=canonical_hash(asdict(inputs["graph"])))
        )

    def transport(request):
        response = fresh_response(request, raw)
        if change == "simulated":
            response["simulated"] = True
        if request["replica"] != 2:
            return response
        receipt = response["transport_receipt"]
        if change in ("wire", "schema", "analysis_policy"):
            response["response_request"][change + "_sha256"] = "0" * 64
        elif change == "missing_bindings":
            for key in ("wire_sha256", "schema_sha256", "analysis_policy_sha256"):
                response["response_request"].pop(key)
        elif change in ("model", "prompt", "packet", "request"):
            receipt["binding"][change + "_sha256"] = "0" * 64
        elif change == "unauthenticated":
            receipt["authenticated"] = False
        elif change == "replay":
            response["saved_response_origin"] = dict(replay=True, fresh_model_call=False)
        elif change == "cache":
            response["response_reuse"] = dict(source_request_id="old")
        elif change == "missing_receipt":
            response.pop("transport_receipt")
        elif change == "body":
            edited = deepcopy(raw)
            edited["triggers"]["governance_claim"] = True
            response["content"] = json.dumps(edited)
        elif change == "duplicate_origin":
            response["provider_request_id"] = "fresh-provider-1"
        elif change == "simulated":
            response["simulated"] = True
        elif change in ("unknown", "conflict"):
            edited = deepcopy(raw)
            edited["elements"]["M3"] = dict(state=change, evidence=None)
            response = fresh_response(request, edited)
        return response

    if change == "duplicate_origin":
        with pytest.raises(ValueError, match="C2_RESPONSE_REPLAY"):
            c3_processing.process_case(
                inputs, b"", output=tmp_path, transport=transport, analysis_policy=cf2_policy()
            )
        return
    result = c3_processing.process_case(
        inputs, b"", output=tmp_path, transport=transport, analysis_policy=cf2_policy()
    )
    assert not result["published"]
    assert not result["receipt"]["public_auto_confirmed"]
    assert c3.replay(result["receipt"], **inputs).to_dict() == result["receipt"]


@pytest.mark.parametrize("quote", ["별도 문맥", "환경경영", "없는 인용"])
def test_scoped_lookup_never_borrows_outside_source_span(quote):
    from proofops.application.tagging import fact_assembly_c2 as c2

    from tests.unit.test_c2_assembly import seal

    inputs, votes = repeated_case()
    for vote in votes:
        vote["raw"]["dimensions"]["activity"]["quote"] = quote
    receipt = c2.assemble([seal(v) for v in votes], **inputs, source_scoped_quotes=True).to_dict()
    assert not receipt["candidate_auto_confirmed"]


def test_cf2_prompt_and_receipt_storage_require_exact_opt_in(reviewed_case, tmp_path):
    from proofops.application.tagging.c3_request_binding import CF2_SYSTEM, current_request

    inputs, raw = reviewed_case
    result = c3_processing.process_case(
        inputs,
        b"",
        output=tmp_path,
        transport=lambda r: fresh_response(r, raw),
        analysis_policy=profiles.FINALS_I27_POLICY,
    )
    assert "cf2_receipt_path" not in result
    assert not (tmp_path / "cf2-receipts").exists()
    request = current_request(
        result["receipt"]["identity"],
        inputs["context"].claim.quote,
        inputs["packet"].to_dict()["c2_sources"],
        cf2_policy(),
        1,
    )
    assert request["system"] == CF2_SYSTEM
    malformed = deepcopy(cf2_policy())
    malformed["cf2_c3_response_binding"]["quote_lookup"] = "anywhere"
    with pytest.raises(ValueError, match="CF2_C3_BINDING_POLICY_MISMATCH"):
        current_request(result["receipt"]["identity"], "", [], malformed, 1)


def test_receipt_survives_publication_failure(reviewed_case, tmp_path, monkeypatch):
    inputs, raw = reviewed_case

    class FailingPublication:
        def __init__(self, output):
            assert len(list(output.glob("cf2-receipts/*.json"))) == 1

        def initialize(self, *args, **kwargs):
            raise RuntimeError("injected publication failure")

    monkeypatch.setattr(c3_processing, "LocalC3Publication", FailingPublication)
    with pytest.raises(RuntimeError, match="injected publication failure"):
        c3_processing.process_case(
            inputs,
            b"",
            output=tmp_path,
            transport=lambda r: fresh_response(r, raw),
            analysis_policy=cf2_policy(),
        )
    receipt = json.loads(next(tmp_path.glob("cf2-receipts/*.json")).read_text())
    assert receipt["public_auto_confirmed"]
    assert c3.replay(receipt, **inputs).to_dict() == receipt
    assert not (tmp_path / "pilot.json").exists()


def test_diagnostic_directory_symlink_is_rejected(reviewed_case, tmp_path):
    inputs, raw = reviewed_case
    raw["triggers"]["governance_claim"] = True
    output = tmp_path / "output"
    output.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (output / "cf2-receipts").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="C3_UNSAFE_ARTIFACT_PATH"):
        c3_processing.process_case(
            inputs,
            b"",
            output=output,
            transport=lambda r: fresh_response(r, raw),
            analysis_policy=cf2_policy(),
        )
    assert not list(outside.iterdir())


def test_two_occurrences_inside_supplied_source_are_still_ambiguous():
    from proofops.application.tagging import fact_assembly_c2 as c2

    from tests.unit.test_c2_assembly import seal

    inputs, votes = repeated_case()
    source_id = inputs["context"].claim.source_refs[0].source_id
    block = next(b for b in inputs["graph"].blocks if b.source_id == source_id)
    inputs["packet"] = freeze_packet(
        inputs["packet"].to_dict() | dict(c2_sources=[asdict(block.source_ref())])
    )
    for vote in votes:
        vote["identity"]["packet_sha256"] = inputs["packet"].packet_sha256
    result = c2.assemble([seal(v) for v in votes], **inputs, source_scoped_quotes=True).to_dict()
    assert "ACTIVITY_PERIOD_BOUNDARY_UNRESOLVED" in result["unresolved"]
    assert not result["candidate_auto_confirmed"]
