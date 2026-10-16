from copy import deepcopy
from dataclasses import asdict, replace

import pytest
from proofops.application.evidence.binding import ClaimContext
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.tagging.fact_assembly_c2 import (
    PROFILE,
    assemble,
    publication_policy_for,
    replay,
)
from proofops.domain.provenance import canonical_hash

from tests.acceptance.test_binding import corpus
from tests.acceptance.test_rules import pack


def case():
    graph, claim, refs = corpus(
        claim_dimensions=dict(
            metric="환경경영시스템 ISO 14001 인증을 완료하고 내부 감사를 수행합니다",
            reporting_period="2025",
            boundary="국내",
        )
    )
    # Explicitly synthetic located prose fixture, separate from original PDF QA.
    from tests.acceptance.test_binding import change_candidate

    for ref in refs:
        graph = change_candidate(graph, ref.source_id, kind="paragraph", table_native_id=None)
    refs = tuple(b.source_ref() for b in graph.blocks)
    claim = replace(claim, source_refs=(refs[0],), quote=refs[0].quote)
    context = ClaimContext(claim, {})
    rulepack = pack()
    packet = freeze_packet(
        dict(
            tenant_id=claim.tenant_id,
            claim_id=claim.claim_id,
            graph_sha256=canonical_hash(asdict(graph)),
            status="candidate",
            c2_sources=[asdict(r) for r in refs],
        )
    )
    identity = dict(
        tenant_id=claim.tenant_id,
        document_version_id=claim.document_version_id,
        original_sha256=graph.source_sha256,
        parse_manifest_id=graph.parse_manifest_id,
        graph_sha256=canonical_hash(asdict(graph)),
        claim_id=claim.claim_id,
        claim_sha256=canonical_hash(asdict(claim)),
        claim_revision=1,
        packet_sha256=packet.packet_sha256,
        rulepack_sha256=rulepack.sha256,
    )
    raw = dict(
        track="management",
        safe_harbor_category=None,
        superlative_quote=None,
        period_kind="explicit_current",
        dimensions=dict(
            activity=dict(
                source_index=0,
                quote="환경경영시스템 ISO 14001 인증을 완료하고 내부 감사를 수행합니다",
            ),
            period=dict(source_index=0, quote="2025"),
            boundary=dict(source_index=0, quote="국내"),
        ),
        elements={
            f"M{i}": dict(state="present", evidence=dict(source_index=0, quote=refs[0].quote))
            for i in range(1, 5)
        },
        triggers=dict(governance_claim=False, compensation_link_claim=False),
    )
    votes = [
        seal(
            dict(
                identity=identity,
                replicate_id=i,
                request_id=f"request-{i}",
                request_sha256=canonical_hash(["request", i]),
                provider_request_id=f"provider-{i}",
                provider="fixture-simulated",
                simulated=True,
                model_sha256="a" * 64,
                prompt_sha256="b" * 64,
                raw=deepcopy(raw),
            )
        )
        for i in (1, 2, 3)
    ]
    return dict(context=context, graph=graph, packet=packet, rulepack=rulepack), votes


def seal(vote):
    value = {k: v for k, v in vote.items() if k not in ("vote_sha256", "raw_sha256")}
    value["raw_sha256"] = canonical_hash(value["raw"])
    return value | dict(vote_sha256=canonical_hash(value))


def test_three_direct_raw_and_matcher_results_yield_python_candidate_only():
    inputs, votes = case()
    result = assemble(votes, **inputs).to_dict()
    assert result["resolved_3_of_3"] and result["candidate_auto_confirmed"]
    assert result["engine_decision"]["evidence_grade"] == "E3"
    assert result["engine_decision"]["label"] == "SUBSTANTIATED"
    assert result["public_auto_confirmed"] is False and result["simulated"] is True
    assert result["raw_receipts"] == votes
    assert len(result["derived_results"]) == 3
    assert replay(result, **inputs).to_dict() == result


@pytest.mark.parametrize(
    "change", ["M4", "period", "activity", "facility", "unknown", "2of3", "GRI", "opinion_union"]
)
def test_unresolved_m4_period_activity_and_designated_negatives_never_confirm(change):
    inputs, votes = case()
    for v in votes:
        raw = v["raw"]
        if change in ("M4", "unknown"):
            raw["elements"]["M4" if change == "M4" else "M3"] = dict(state="unknown", evidence=None)
        elif change == "period":
            raw["dimensions"]["period"] = None
        elif change == "activity":
            raw["dimensions"]["activity"]["quote"] = "환경방침"
        elif change == "facility":
            raw["dimensions"]["boundary"]["source_index"] = 1
        elif change == "GRI":
            raw["elements"]["M3"]["evidence"]["quote"] = "GRI 3-3 same page"
        elif change == "opinion_union":
            raw["elements"]["M3"]["evidence"]["source_index"] = 1
    if change == "2of3":
        votes[2]["raw"]["elements"]["M4"] = dict(state="unknown", evidence=None)
    votes = [seal(v) for v in votes]
    result = assemble(votes, **inputs).to_dict()
    assert not result["candidate_auto_confirmed"]
    assert not result["public_auto_confirmed"]
    assert result["engine_decision"] is None
    assert not result["resolved_3_of_3"]
    assert all(
        e["state"] != "absent"
        for r in result["derived_results"]
        for e in r["result"]["elements"].values()
    )


def test_replica_copy_packet_tenant_hash_and_unknown_schema_are_refused():
    inputs, votes = case()
    for key in ("request_id", "request_sha256", "provider_request_id"):
        copied = deepcopy(votes)
        copied[2][key] = copied[1][key]
        copied[2] = seal(copied[2])
        with pytest.raises(ValueError, match="REPLAY"):
            assemble(copied, **inputs)
    bad = deepcopy(votes)
    bad[1]["identity"]["packet_sha256"] = "0" * 64
    bad = [seal(v) for v in bad]
    with pytest.raises(ValueError, match="RAW_RECEIPT"):
        assemble(bad, **inputs)
    result = assemble(votes, **inputs).to_dict()
    for altered in [
        result | dict(schema="FactAssemblyReceiptV2"),
        result | dict(public_auto_confirmed=True),
    ]:
        with pytest.raises(ValueError, match="RECEIPT"):
            replay(altered, **inputs)
    with pytest.raises(ValueError, match="IDENTITY"):
        replay(
            result,
            **(
                inputs
                | dict(
                    graph=replace(inputs["graph"], tenant_id="77777777-7777-4777-8777-777777777777")
                )
            ),
        )


def test_profile_has_no_public_activation_switch():
    with pytest.raises(ValueError, match="PUBLICATION_DISABLED"):
        publication_policy_for(PROFILE)


def test_boolean_replica_or_simulation_marker_cannot_change_authority():
    inputs, votes = case()
    for field, value in [("replicate_id", True), ("simulated", 0)]:
        bad = deepcopy(votes)
        bad[0][field] = value
        with pytest.raises(ValueError, match="PROVENANCE"):
            assemble([seal(v) for v in bad], **inputs)


def test_equivalent_verified_quote_extents_keep_three_distinct_results():
    inputs, votes = case()
    votes[2]["raw"]["dimensions"]["activity"]["quote"] = "환경경영시스템"
    votes[2]["raw"]["elements"]["M1"]["evidence"]["quote"] = (
        "환경경영시스템 ISO 14001 인증을 완료하고 내부 감사를 수행합니다"
    )
    result = assemble([seal(v) for v in votes], **inputs).to_dict()
    assert result["resolved_3_of_3"]
    assert len({r["output_sha256"] for r in result["derived_results"]}) == 2


def test_scope_is_derived_from_each_own_complete_m2_evidence_not_a_short_dimension_hint():
    inputs, votes = case()
    votes[1]["raw"]["dimensions"]["boundary"]["quote"] = inputs["context"].claim.quote
    result = assemble([seal(v) for v in votes], **inputs).to_dict()
    assert result["resolved_3_of_3"]
    votes[0]["raw"]["elements"]["M2"]["evidence"]["quote"] = "국내"
    incomplete = assemble([seal(v) for v in votes], **inputs).to_dict()
    assert not incomplete["resolved_3_of_3"]
    assert not incomplete["candidate_auto_confirmed"]
