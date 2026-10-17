"""PR1's 12 saved failures: canonical sources and bounded dispatch recovery."""

import gzip
import json
from dataclasses import asdict, replace
from functools import lru_cache
from pathlib import Path

import pytest
from proofops.application.claims import Claim, ExtractionProfile, ExtractionReceipt
from proofops.application.evidence.span_citations import SpanVerifiedGraph
from proofops.application.ingest.graph_fusion import (
    CanonicalBlock,
    CanonicalEdge,
    QualityIssue,
    candidates_from_snapshot,
)
from proofops.application.ingest.k5_context import configured_context, preliminary_context
from proofops.application.tagging import cf5_context
from proofops.application.tagging.preliminary import (
    preliminary_table_request,
    validate_preliminary_table_sources,
)
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef

PIN = "f29385d0c74d1520350deb06eaa9e11b72c5829dfaefeb2417c4e8ac0fed4ebd"


@lru_cache
def saved(company):
    path = Path(__file__).parents[1] / "fixtures" / "fx5" / f"{company}.json.gz"
    data = json.loads(gzip.decompress(path.read_bytes()))
    raw = data["graph"]
    batches = candidates_from_snapshot(raw["candidates"])
    blocks = {canonical_hash(asdict(b)): b for batch in batches for b in batch.blocks}
    graph = SpanVerifiedGraph(
        **raw
        | dict(
            candidates=batches,
            blocks=tuple(
                CanonicalBlock(
                    **b
                    | dict(
                        candidates=tuple(blocks[canonical_hash(c)] for c in b["candidates"]),
                        independent_families=tuple(b["independent_families"]),
                    )
                )
                for b in raw["blocks"]
            ),
            edges=tuple(CanonicalEdge(**e) for e in raw["edges"]),
            issues=tuple(
                QualityIssue(**i | dict(source_ids=tuple(i["source_ids"]))) for i in raw["issues"]
            ),
            verified_spans=tuple(SourceRef(**r) for r in raw["verified_spans"]),
        )
    )
    assert canonical_hash(asdict(graph)) == data["graph_sha256"]
    assert canonical_hash(data["policy"]) == data["policy_sha256"] == PIN
    claims = []
    for c in data["claims"]:
        receipt = c["receipt"]
        claims.append(
            Claim(
                **c
                | dict(
                    source_refs=tuple(SourceRef(**r) for r in c["source_refs"]),
                    topic_ids=tuple(c["topic_ids"]),
                    receipt=ExtractionReceipt(
                        **receipt | dict(profile=ExtractionProfile(**receipt["profile"]))
                    ),
                )
            )
        )
    return data, graph, claims


def packet_for(claim, graph):
    return preliminary_table_request(
        claim,
        graph,
        tenant_id=graph.tenant_id,
        allow_unverified=True,
        role_resolution=True,
        goal_role=True,
        actor_role=True,
        period_role=True,
    )


@pytest.mark.parametrize("index", range(6))
def test_saved_joined_claim_reaches_classification_and_retrieval(index):
    from proofops.adapters.local.evidence_search import LocalEvidenceSearch
    from proofops.application.evidence.retrieval import retrieve_evidence

    from tests.acceptance.test_rules import pack

    data, graph, claims = saved("hynix")
    claim = claims[index]
    before = canonical_hash(asdict(claim))
    packet = packet_for(claim, graph)
    sources = packet["untrusted_document_data"]["sources"]
    assert sources[0]["text"] == claim.quote
    assert len(sources) == (1 if index < 5 else 3)
    # Synthetic validator input, not a fabricated PR1 model response or grade.
    result = validate_preliminary_table_sources(
        claim,
        graph,
        dict(
            claim_id=claim.claim_id,
            track="management",
            track_confidence=0.9,
            safe_harbor_category=None,
            dimensions=dict(entity=None, metric=None, reporting_period=None),
        ),
        tenant_id=graph.tenant_id,
        allow_unverified=True,
    )
    assert result.track.claim == claim
    search = LocalEvidenceSearch(
        graph,
        tenant_id=graph.tenant_id,
        pages=sorted({b.page_num for b in graph.blocks}),
        index_generation="fx5-regression",
    )
    evidence = retrieve_evidence(
        claim,
        graph,
        search,
        tenant_id=graph.tenant_id,
        run_id=data["run_id"],
        index_generation="fx5-regression",
        rulepack=replace(pack(), tenant_id=graph.tenant_id),
        document_context={},
        token_counter=lambda text: len(text.encode()),
    )
    assert evidence.to_dict()["atomic_quote"] == claim.quote
    assert canonical_hash(asdict(claim)) == before
    assert claim.source_quality == "unverified"
    assert all(r.verification_state != "verified" for r in claim.source_refs)
    from proofops.application.evidence.binding import ClaimContext, accept_binding

    # Valid PS1 lineage is not a rejected identity, but unverified authority
    # must still prevent acceptance at the downstream element-binding boundary.
    assert (
        accept_binding(
            ClaimContext(claim, {}),
            claim.source_refs[0],
            {},
            original=graph,
            tenant_id=graph.tenant_id,
            rulepack=replace(pack(), tenant_id=graph.tenant_id),
            element_id="M1",
        )
        == "undetermined"
    )


@pytest.mark.parametrize(
    "company,index",
    [("hynix", 5)] + [("hyundai", i) for i in range(4)] + [("naver", i) for i in range(2)],
)
def test_saved_oversized_context_reaches_bounded_packet(company, index):
    data, graph, claims = saved(company)
    claim = claims[index]
    packet = preliminary_context(
        packet_for(claim, graph), configured_context(claim, graph, data["policy"])
    )
    before = canonical_hash(packet)
    receipt = {}
    result = cf5_context.preserve_context(packet, claim, graph, receipt=receipt)
    entries = result["untrusted_document_data"]["context_blocks"]
    assert len(entries) <= 4
    assert sum(len(e["text"]) for e in entries) <= 2000
    focal = next(b for b in graph.blocks if b.source_id == claim.source_refs[0].source_id)
    assert entries[0]["source_id"] == focal.source_id
    assert entries[0]["text"] == focal.raw_text
    assert receipt["cf5_context_truncated"] is True
    assert "cf5_context_truncated" not in result
    assert result == cf5_context.preserve_context(packet, claim, graph)
    cf5_context.validate_packet(result)
    assert canonical_hash(packet) == before


@pytest.mark.parametrize(
    "mutation", ["foreign_ref", "offset", "missing_lineage", "quote", "primary_end", "version"]
)
def test_joined_provenance_still_rejects_unrelated_or_changed_fragments(mutation):
    from proofops.domain.errors import DomainValidationError

    _, graph, claims = saved("hynix")
    claim = claims[5]
    if mutation == "foreign_ref":
        claim = replace(claim, source_refs=(claim.source_refs[0], claims[0].source_refs[-1]))
    elif mutation == "offset":
        ref = claim.source_refs[-1]
        claim = replace(
            claim,
            source_refs=(*claim.source_refs[:-1], replace(ref, char_start=ref.char_start + 1)),
        )
    elif mutation == "missing_lineage":
        graph = replace(graph, edges=tuple(e for e in graph.edges if e.relation != "derived_from"))
    elif mutation == "primary_end":
        ref = claim.source_refs[0]
        claim = replace(claim, source_refs=(replace(ref, char_end=100000), *claim.source_refs[1:]))
    elif mutation == "version":
        from uuid import UUID

        ref = claim.source_refs[-1]
        claim = replace(
            claim,
            source_refs=(
                *claim.source_refs[:-1],
                replace(ref, document_version_id=str(UUID(int=1))),
            ),
        )
    else:
        claim = replace(claim, quote=claim.quote + " changed")
    with pytest.raises((DomainValidationError, ValueError)):
        packet_for(claim, graph)


@pytest.mark.parametrize(
    "company,index",
    [("hynix", i) for i in range(6)]
    + [("hyundai", i) for i in range(4)]
    + [("naver", i) for i in range(2)],
)
def test_all_saved_claims_reach_live_preliminary_dispatch(company, index):
    from types import SimpleNamespace

    from proofops_worker.live_tagging import LiveTaggingRuntime

    data, graph, claims = saved(company)
    claim = claims[index]
    runtime = object.__new__(LiveTaggingRuntime)
    runtime.snapshot = dict(
        pipeline_profile="finals-unattended-v2", analysis_profile_policy=data["policy"]
    )
    runtime.graph = graph
    runtime.auth = SimpleNamespace(tenant_id=graph.tenant_id)
    runtime.preliminary_settings = SimpleNamespace(
        model_profile="upstage-preliminary-source-quotes-pb1-compact-v1",
        system_prompt=cf5_context.PRELIMINARY,
    )
    runtime.preliminary_transport = SimpleNamespace(bound_context=lambda packet: packet)
    runtime.preliminary_records = {}
    captured = []

    def capture(prefix, actual_claim, packet, settings, transport, records, validate, **kwargs):
        assert prefix == "preliminary" and actual_claim == claim
        cf5_context.validate_packet(packet)
        receipt = kwargs.get("context_receipt", {})
        assert bool(receipt.get("cf5_context_truncated")) == (company != "hynix" or index == 5)
        captured.append(packet)
        # Stop offline at dispatch: no model output or hold is invented.
        return None

    runtime._source_replicas = capture
    runtime.preliminary(claim, graph)
    assert len(captured) == 1
    assert canonical_hash(data["policy"]) == PIN


@pytest.mark.parametrize("prefer", ["verified", "area", "source_id"])
def test_duplicate_refs_canonicalize_independently_of_input_order(prefer):
    from uuid import UUID

    from proofops.application.ingest.source_continuations import canonical_source_refs

    original = saved("hynix")[2][0].source_refs[0]
    small = replace(original, source_id=str(UUID(int=1)), bbox=(0, 0, 10, 10))
    large = replace(original, source_id=str(UUID(int=2)), bbox=(0, 0, 11, 11))
    if prefer == "verified":
        small = replace(small, verification_state="verified")
        expected = small
    elif prefer == "source_id":
        small = replace(small, bbox=large.bbox)
        expected = small
    else:
        expected = large
    assert canonical_source_refs((small, large)) == (expected,)
    assert canonical_source_refs((large, small)) == (expected,)


@pytest.mark.parametrize("difference", ["page", "version", "manifest", "text", "bbox"])
def test_dedup_keeps_genuinely_distinct_refs(difference):
    from uuid import UUID

    from proofops.application.ingest.source_continuations import canonical_source_refs

    original = saved("hynix")[2][0].source_refs[0]
    changes = dict(
        page=dict(page_num=3),
        version=dict(document_version_id=str(UUID(int=1))),
        manifest=dict(parse_manifest_id=str(UUID(int=1))),
        text=dict(quote=original.quote + "x"),
        bbox=dict(bbox=(0, 0, 1, 1)),
    )
    other = replace(original, source_id=str(UUID(int=2)), **changes[difference])
    assert canonical_source_refs((original, other)) == (original, other)


def test_joined_full_span_keeps_all_fragments_and_raw_offsets():
    from proofops.application.ingest.source_continuations import (
        claim_quote_matches_sources,
        continuations,
    )

    _, graph, claims = saved("hynix")
    claim = claims[0]
    parts = continuations(graph)[claim.source_refs[0].source_id]
    joined = next(b for b in graph.blocks if b.source_id == claim.source_refs[0].source_id)
    refs = (joined.source_ref(), *(part.source_ref() for part in parts))
    assert claim_quote_matches_sources(joined.raw_text, refs, graph)
    assert not claim_quote_matches_sources(joined.raw_text, refs[:-1], graph)
    assert not claim_quote_matches_sources(joined.raw_text, (refs[0], *reversed(refs[1:])), graph)


def test_frozen_analysis_policy_is_unchanged():
    from proofops.application.analysis_profile import V2_PROFILE, policy_for

    assert canonical_hash(policy_for(V2_PROFILE, pinned_hash=PIN)) == PIN


def test_truncation_flag_is_retained_in_replica_receipts(tmp_path, monkeypatch):
    from tests.integration.test_live_tagging_worker import configured

    runtime, claim, graph, calls, _, _ = configured(tmp_path, monkeypatch)
    original = runtime._source_replicas

    def with_receipt(*args, **kwargs):
        return original(*args, **kwargs, context_receipt=dict(cf5_context_truncated=True))

    runtime._source_replicas = with_receipt
    assert runtime.preliminary(claim, graph) is not None
    assert len(calls) == 3
    records = runtime.preliminary_records[claim.claim_id]
    assert len(records) == 3
    assert all(r["status"] == "validated_candidate" and r["cf5_context_truncated"] for r in records)
    assert all("cf5_context_truncated" not in str(call) for call in calls)


def test_overflow_selects_nearest_whole_blocks_within_character_bound():
    from copy import deepcopy

    from tests.unit.test_k5_context import case

    texts = ["focal", "near" * 600, "second", "third", "fourth", "fifth"]
    graph, claim = case(texts, (0, "focal"))
    packet = packet_for(claim, graph)
    packet["untrusted_document_data"]["context_blocks"] = [
        dict(
            context_index=i,
            role="nearby",
            source_id=b.source_id,
            page_num=b.page_num,
            quality=b.quality,
            text=b.raw_text,
            source_ref={k: v for k, v in asdict(b.source_ref()).items() if k != "quote"},
        )
        for i, b in enumerate(reversed(graph.blocks[1:]))
    ]
    receipt = {}
    result = cf5_context.preserve_context(packet, claim, graph, receipt=receipt)
    entries = result["untrusted_document_data"]["context_blocks"]
    assert [e["text"] for e in entries] == ["focal", "second", "third", "fourth"]
    assert len(entries) == 4 and sum(len(e["text"]) for e in entries) <= 2000
    assert receipt["cf5_context_truncated"]
    reordered = deepcopy(packet)
    reordered["untrusted_document_data"]["context_blocks"].reverse()
    other = cf5_context.preserve_context(reordered, claim, graph)
    assert other["untrusted_document_data"]["context_blocks"] == entries
    assert set(receipt["cf5_omitted_source_ids"]) == {graph.blocks[i].source_id for i in (1, 5)}


def test_duplicate_normalization_preserves_canonical_literal_quote():
    from proofops.application.ingest.source_continuations import canonical_source_refs

    left, right = saved("hynix")[2][0].source_refs
    right = replace(right, quote=" ".join(right.quote.split()))
    assert canonical_source_refs((right, left)) == (left,)
    assert left.quote != right.quote


def test_duplicate_refs_do_not_authorize_a_repeated_claim_quote():
    from proofops.domain.errors import DomainValidationError

    _, graph, claims = saved("hynix")
    claim = claims[0]
    doubled = replace(claim, quote=" ".join(r.quote for r in claim.source_refs))
    with pytest.raises(DomainValidationError, match="identity or quality mismatch"):
        packet_for(doubled, graph)


def test_duplicate_cannot_hide_out_of_bounds_candidate_span():
    from proofops.domain.errors import DomainValidationError

    from tests.unit.test_k5_context import case

    graph, claim = case(["literal whole block"], (0, "literal whole block"), quality="unverified")
    ref = claim.source_refs[0]
    malformed = replace(ref, char_end=ref.char_end + 1)
    claim = replace(claim, source_refs=(ref, malformed))
    with pytest.raises(DomainValidationError, match="candidate literal source mismatch"):
        packet_for(claim, graph)
