from copy import deepcopy
from dataclasses import asdict, replace

import pytest
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.tagging.fact_assembly_c4 import (
    PROFILE,
    assemble,
    discover,
    publication_policy_for,
    replay,
    safety_reasons,
)
from proofops.domain.provenance import canonical_hash

from tests.unit.test_c2_assembly import seal


def prepared(code="14001", system="환경경영시스템"):
    from proofops.application.claims import Claim, ExtractionProfile, ExtractionReceipt
    from proofops.application.evidence.binding import ClaimContext
    from proofops.application.ingest.graph_fusion import (
        CandidateBatch,
        CandidateBlock,
        fuse_candidates,
    )
    from proofops.domain.documents import NativeSource, PageGeometry

    from tests.acceptance.test_citations import MANIFEST, OTHER, RUN, TENANT, VERSION
    from tests.acceptance.test_rules import pack

    text = f"당사는 2025년 국내 전 사업장에 {system} ISO {code} 인증을 취득하고 운영합니다."
    native = NativeSource(
        VERSION,
        MANIFEST,
        RUN,
        "paragraph",
        1,
        None,
        (10, 10, 500, 40),
        "pdf_bottom_left_points",
        text,
        0,
        len(text),
    )
    batch = CandidateBatch(
        TENANT,
        VERSION,
        MANIFEST,
        "a" * 64,
        RUN,
        "synthetic",
        "1",
        "synthetic",
        "b" * 64,
        (CandidateBlock("paragraph", native, PageGeometry(600, 800, 0, (0, 0, 600, 800))),),
        synthetic=True,
    )
    graph = fuse_candidates((batch,), tenant_id=TENANT)
    graph = replace(graph, blocks=tuple(replace(b, quality="verified") for b in graph.blocks))
    ref = graph.blocks[0].source_ref()
    rulepack = pack()
    profile = ExtractionProfile("c" * 64, "d" * 64, rulepack.sha256, True)
    claim = Claim(
        OTHER,
        TENANT,
        VERSION,
        MANIFEST,
        graph.source_sha256,
        ref.quote,
        (ref,),
        "verified",
        (),
        ExtractionReceipt(ref.source_id, "f" * 64, None, None, profile, "synthetic"),
    )
    candidate = discover(graph)[0]
    packet = freeze_packet(
        dict(
            tenant_id=TENANT,
            claim_id=OTHER,
            graph_sha256=canonical_hash(asdict(graph)),
            status="candidate",
            c4_candidate=candidate,
            c4_sources=[asdict(ref)],
        )
    )
    identity = dict(
        tenant_id=TENANT,
        document_version_id=VERSION,
        original_sha256=graph.source_sha256,
        parse_manifest_id=MANIFEST,
        graph_sha256=canonical_hash(asdict(graph)),
        claim_id=OTHER,
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
            activity=dict(source_index=0, quote=system),
            period=dict(source_index=0, quote="2025"),
            boundary=dict(source_index=0, quote="국내 전 사업장"),
        ),
        elements={
            f"M{i}": dict(state="present", evidence=dict(source_index=0, quote=text))
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
    return dict(
        context=ClaimContext(claim, {}), graph=graph, packet=packet, rulepack=rulepack
    ), votes


def test_report_discovery_frozen_three_votes_and_replay():
    inputs, votes = prepared()
    receipt = assemble(votes, **inputs).to_dict()
    assert receipt["candidate_auto_confirmed"]
    assert receipt["resolved_3_of_3"]
    assert receipt["engine_decision"]["evidence_grade"] == "E3"
    assert not receipt["public_auto_confirmed"]  # synthetic cannot publish
    assert replay(receipt, **inputs).to_dict() == receipt
    assert publication_policy_for(PROFILE)["enabled"]
    assert "reviewed_identity" not in publication_policy_for(PROFILE)


@pytest.mark.parametrize(
    "code,system",
    [("14001", "환경경영시스템"), ("50001", "에너지경영시스템"), ("45001", "안전보건경영시스템")],
)
def test_discovery_generalizes_named_systems_without_report_identity(code, system):
    inputs, votes = prepared(code, system)
    result = assemble(votes, **inputs).to_dict()
    assert result["candidate_auto_confirmed"]
    block = inputs["graph"].blocks[0]
    text = f"당사는 {system} ISO {code} 인증을 취득하여 국내 전 사업장에 적용하고 운영합니다."
    candidate = block.candidates[0]
    candidate = replace(
        candidate, source=replace(candidate.source, raw_text=text, char_end=len(text))
    )
    graph = replace(inputs["graph"], blocks=(replace(block, candidates=(candidate,)),))
    found = discover(graph)
    assert len(found) == 1
    assert found[0]["certificate"] == f"ISO {code}"
    assert found[0]["system"] == system


NEGATIVES = [
    ("facility", "dimensions", "boundary", {"source_index": 1, "quote": "국내"}),
    ("period", "dimensions", "period", {"source_index": 1, "quote": "2025"}),
    (
        "gri",
        "elements",
        "M3",
        {"state": "present", "evidence": {"source_index": 0, "quote": "GRI 3-3 same page"}},
    ),
    (
        "opinion-union",
        "elements",
        "M3",
        {"state": "present", "evidence": {"source_index": 1, "quote": "2025"}},
    ),
    (
        "iso-conform",
        "elements",
        "M3",
        {"state": "present", "evidence": {"source_index": 0, "quote": "ISO 14001"}},
    ),
    ("nonpossession", "elements", "M3", {"state": "unknown", "evidence": None}),
    ("adjacent-activity", "dimensions", "activity", {"source_index": 0, "quote": "제품A"}),
    (
        "partial-expansion",
        "dimensions",
        "boundary",
        {"source_index": 0, "quote": "전 세계 모든 사업장"},
    ),
    ("validity", None, "period_kind", "report_context"),
    ("conflict", "elements", "M3", {"state": "conflict", "evidence": None}),
    ("missing-m4", "elements", "M4", {"state": "unknown", "evidence": None}),
    ("disagreement", "elements", "M2", {"state": "unknown", "evidence": None}),
]


@pytest.mark.parametrize("name,section,key,value", NEGATIVES)
def test_twelve_adverse_types_never_confirm(name, section, key, value):
    inputs, votes = prepared()
    for vote in votes[2:] if name == "disagreement" else votes:
        if section:
            vote["raw"][section][key] = value
        else:
            vote["raw"][key] = value
    receipt = assemble([seal(v) for v in votes], **inputs).to_dict()
    assert not receipt["candidate_auto_confirmed"]
    assert not receipt["public_auto_confirmed"]
    assert receipt["engine_decision"] is None
    assert all(
        e["state"] != "absent"
        for d in receipt["derived_results"]
        for e in d["result"]["elements"].values()
    )


@pytest.mark.parametrize(
    "status", ["부합하는", "인증 예정", "인증 미취득", "인증 철회", "인증 취소", "인증 진행 중"]
)
def test_possession_guard_never_accepts_negative_status(status):
    assert safety_reasons("환경경영시스템 ISO 14001 " + status)


def test_duplicate_replica_and_tampered_receipt_rejected():
    inputs, votes = prepared()
    bad = deepcopy(votes)
    bad[2]["provider_request_id"] = bad[1]["provider_request_id"]
    with pytest.raises(ValueError, match="REPLAY"):
        assemble([seal(v) for v in bad], **inputs)
    result = assemble(votes, **inputs).to_dict()
    with pytest.raises(ValueError, match="RECEIPT"):
        replay(result | {"public_auto_confirmed": True}, **inputs)


def test_source_contradiction_partial_scope_is_not_universal():
    assert "PARTIAL_SCOPE_EXPANDED" in safety_reasons(
        "환경경영시스템 ISO 14001 인증을 보유하고 글로벌 전 사업장에 적용합니다. "
        "글로벌 17개 사업장 중 15개에서 인증을 완료했습니다."
    )


def test_same_paragraph_training_is_not_the_certified_activity():
    inputs, _ = prepared()
    block = inputs["graph"].blocks[0]
    candidate = block.candidates[0]
    text = (
        "당사는 환경경영시스템 ISO 14001 교육을 국내 사업장에서 실시했습니다. "
        "국내 전 사업장의 제품에 인증을 취득했습니다."
    )
    candidate = replace(
        candidate, source=replace(candidate.source, raw_text=text, char_end=len(text))
    )
    graph = replace(inputs["graph"], blocks=(replace(block, candidates=(candidate,)),))
    assert discover(graph) == []
