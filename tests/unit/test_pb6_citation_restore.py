"""PB6 keeps literal values/offsets and all legacy selection guards."""

from copy import deepcopy
from types import SimpleNamespace

import pytest


def element(value="약 3만 톤"):
    return dict(
        element_id="P1",
        state="present",
        normalized_value=value,
        evidence_refs=[
            dict(source_id="same", quote="약 3만 톤의 온실가스를 저감", char_start=30, char_end=49)
        ],
        credited_from=None,
    )


def test_selected_value_adds_only_unique_subspan_and_preserves_context():
    from proofops.application.tagging.pb6_citation_restore import refine_selected_value

    e = element()
    before = deepcopy(e)
    refine_selected_value(e)
    assert e["evidence_refs"][0] == before["evidence_refs"][0]
    assert e["evidence_refs"][1] == before["evidence_refs"][0] | dict(
        quote="약 3만 톤", char_start=30, char_end=36
    )
    assert e["normalized_value"] == before["normalized_value"]
    refine_selected_value(e)
    assert len(e["evidence_refs"]) == 2


@pytest.mark.parametrize(
    "raw,value",
    [
        ("100%와 100%", "100%"),
        ("100%", "10%"),
        ("180 톤", "80 톤"),
        ("10.5 MWh", "5 MWh"),
        ("전력 100 %", "100%"),
        ("1,000 톤", "000 톤"),
        ("10 톤", "9 톤"),
        ("−80 톤", "80 톤"),
    ],
)
def test_refinement_never_changes_numbers_units_or_ambiguity(raw, value):
    from proofops.application.tagging.pb6_citation_restore import refine_selected_value

    e = element(value)
    e["evidence_refs"][0].update(quote=raw, char_end=30 + len(raw))
    before = deepcopy(e)
    refine_selected_value(e)
    assert e == before


def test_same_value_in_two_sources_is_not_resolved():
    from proofops.application.tagging.pb6_citation_restore import refine_selected_value

    e = element()
    e["evidence_refs"].append(e["evidence_refs"][0] | dict(source_id="other"))
    before = deepcopy(e)
    refine_selected_value(e)
    assert e == before


def test_transport_requires_new_policy_and_preserves_legacy():
    from proofops.application.tagging.pb2_citation_restore import POLICY as OLD
    from proofops.application.tagging.pb6_citation_restore import POLICY
    from proofops_agent.upstage_tagging import UpstageTaggingTransport

    t = object.__new__(UpstageTaggingTransport)
    t._settings = SimpleNamespace(model_profile="upstage-compact-source-quotes-v5")
    t._display_catalog = None
    e = element()
    e["evidence_refs"] = [dict(id="e0", quote="약 3만 톤의 온실가스를 저감")]
    p = dict(elements=[e], warnings=[])
    refs = {
        "e0": dict(
            source_id="same", quote="약 3만 톤의 온실가스를 저감", char_start=30, char_end=49
        )
    }
    assert (
        len(t.restore_payload(deepcopy(p), refs, policy=OLD)["elements"][0]["evidence_refs"]) == 1
    )
    assert (
        len(t.restore_payload(deepcopy(p), refs, policy=POLICY)["elements"][0]["evidence_refs"])
        == 2
    )


def test_new_policy_hash_and_old_default_replay():
    from proofops.application.analysis_profile import V2_POLICY, V2_PRE_PB6_POLICY, policy_for
    from proofops.domain.provenance import canonical_hash

    assert V2_POLICY != V2_PRE_PB6_POLICY
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(V2_PRE_PB6_POLICY))
        == V2_PRE_PB6_POLICY
    )


@pytest.mark.parametrize("source_verified", [True, False])
def test_added_span_still_runs_original_source_and_binding_guards(tmp_path, source_verified):
    import json
    from dataclasses import asdict, replace

    from proofops.application.evidence.retrieval import freeze_packet
    from proofops.application.tagging.pb6_citation_restore import refine_selected_value
    from proofops.application.tagging.service import tag_replicates

    from tests.acceptance.test_tagging import setup

    inputs = setup(tmp_path)
    original = inputs["original"]
    ref = inputs["context"].claim.source_refs[0]
    selected = replace(ref, quote=ref.quote, verification_state="candidate")
    if not source_verified:
        original = replace(
            original,
            blocks=tuple(
                replace(b, quality="unverified") if b.source_id == ref.source_id else b
                for b in original.blocks
            ),
        )
        from proofops.application.evidence.span_citations import verify_source_ref
        from proofops.domain.provenance import canonical_hash

        data = inputs["packet"].to_dict()
        data.pop("packet_sha256")
        data["graph_sha256"] = canonical_hash(asdict(original))
        data["claim_source_refs"] = [
            asdict(verify_source_ref(r, original, tenant_id=inputs["tenant_id"]))
            for r in inputs["context"].claim.source_refs
        ]
        inputs["packet"] = freeze_packet(data)
        inputs["original"] = original
        claim = replace(inputs["context"].claim, source_quality="unverified")
        inputs["context"] = replace(inputs["context"], claim=claim)
        inputs["track"] = replace(inputs["track"], claim=claim)
        inputs["pipeline_profile"] = "finals-unattended-v2"
        data = inputs["packet"].to_dict()
        data.pop("packet_sha256")
        data["pipeline_profile"] = "finals-unattended-v2"
        inputs["packet"] = freeze_packet(data)
    responder = inputs["invoke"]

    def invoke(request):
        response = responder(request)
        payload = json.loads(response.raw_response_json)
        e = payload["elements"][0]
        e["evidence_refs"] = [asdict(selected)]
        refine_selected_value(e)
        assert len(e["evidence_refs"]) == 2
        return replace(response, raw_response_json=json.dumps(payload))

    inputs["invoke"] = invoke
    if not source_verified:
        from proofops.domain.errors import DomainValidationError

        with pytest.raises(DomainValidationError, match="original evidence text required"):
            tag_replicates(**inputs)
        assert responder.requests == []
        return
    runs = tag_replicates(**inputs)
    assert all(r.guarded.elements[0].state == "present" for r in runs)
