"""QC2: native figure restrictions survive extraction and frozen interpretation."""

import json
from dataclasses import asdict

import pytest
from proofops.adapters.local.h1_native_title import native_figure_candidates
from proofops.application.claims import ClaimScope, discover_atomic_claims
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.ingest.graph_fusion import candidates_from_snapshot, fuse_candidates
from proofops.application.ingest.k5_context import sentence_context
from proofops_agent.upstage_extraction import GraphBoundExtractor, UpstageClaimExtractor
from proofops_worker.live_tagging import LiveTaggingRuntime

from tests.integration.test_parser_source_recovery import batch, block, fixture


def figure(lines):
    source, manifest, run = fixture(lines)
    caption = block(
        source,
        manifest,
        run,
        "diagram",
        "Generated description",
        None,
        kind="figure",
        context=("provider_bbox=25,30,210,140", "vision_only"),
    )
    graph = fuse_candidates((batch(source, manifest, run, [caption]),), tenant_id=source.tenant_id)
    return graph, source


@pytest.mark.parametrize(
    "lines,restriction",
    [
        (
            [
                (30, 50, "- We operate a climate committee."),
                (30, 95, "However, this plan was cancelled."),
            ],
            "cancelled",
        ),
        (
            [
                (30, 50, "- We operate a climate committee."),
                (30, 65, "However, this plan was cancelled."),
            ],
            "cancelled",
        ),
        (
            [(30, 50, "Plans for 2035"), (30, 65, "- We operate a climate committee.")],
            "Plans for 2035",
        ),
        ([(230, 50, "- We operate a climate committee.")], None),
        (
            [
                (30, 50, "However, this plan was cancelled."),
                (30, 95, "- We operate a climate committee."),
            ],
            "cancelled",
        ),
        (
            [(30, 50, "- We operate a climate committee."), (30, 95, "Plans for 2035")],
            "Plans for 2035",
        ),
        ([(30, 50, "- 2050 Carbon Neutral"), (30, 65, "- 999"), (30, 80, "- ISO 14001")], None),
    ],
)
def test_restrictions_are_source_bound_in_extraction_and_tagging_or_deferred(
    tmp_path, lines, restriction
):
    graph, source = figure(lines)

    class Selector:
        requests = []

        def complete(self, system, user, **kwargs):
            data = json.loads(user)
            self.requests.append(data)
            entries = data["untrusted_document_data"]["source_sentences"]
            return {"content": json.dumps({"sentence_ids": [e["sentence_id"] for e in entries]})}

    selector = Selector()
    extractor = UpstageClaimExtractor(
        selector,
        tmp_path,
        extraction_source_ids=True,
        extraction_context=True,
        extraction_table_rows=True,
        extraction_w9=True,
        extraction_pb1=True,
        extraction_qc_native_figures=True,
    )
    bound = GraphBoundExtractor(extractor, graph, source.content)
    discovered = discover_atomic_claims(
        bound.graph,
        ClaimScope(graph.tenant_id, graph.document_version_id, graph.parse_manifest_id),
        extractor=bound,
    )
    assert all(b in bound.graph.blocks for b in graph.blocks)
    replay = fuse_candidates(
        candidates_from_snapshot([asdict(b) for b in bound.graph.candidates]),
        tenant_id=graph.tenant_id,
    )
    assert replay.blocks == bound.graph.blocks and replay.edges == bound.graph.edges
    if restriction is None:
        assert not discovered.claims
    for claim in discovered.claims:
        assert claim.source_quality == "unverified"
        assert all(r.verification_state == "candidate" for r in claim.source_refs)
        context = sentence_context(claim, bound.graph)
        assert context and restriction in context["text"]
        assert context["rule_credit"] is False and context["verification_state"] == "candidate"
        for ref in context["source_refs"]:
            b = next(b for b in bound.graph.blocks if b.source_id == ref["source_id"])
            assert b.raw_text[ref["char_start"] : ref["char_end"]] == ref["quote"]
            assert ref["bbox"] and ref["verification_state"] == "candidate"
        requests = [
            r
            for r in selector.requests
            if r["untrusted_document_data"]["source_id"] == claim.source_refs[0].source_id
        ]
        assert len(requests) == 1
        context_blocks = requests[0]["untrusted_document_data"]["context_blocks"]
        assert restriction in "\n".join(b["text"] for b in context_blocks)
        assert all(b["source_ref"] and "sentence_id" not in b for b in context_blocks)
        from proofops.application.analysis_profile import FINALS_K5_POLICY

        runtime = object.__new__(LiveTaggingRuntime)
        runtime.graph = bound.graph
        runtime.snapshot = dict(
            analysis_profile_policy={
                k: v for k, v in FINALS_K5_POLICY.items() if k.startswith("sentence_context")
            }
        )
        packet = freeze_packet(dict(claim_id=claim.claim_id, allowed_elements=[]))
        frozen = runtime.display_packet(packet, claim=claim)
        assert frozen.to_dict()["sentence_context"] == context
        assert frozen.packet_sha256 != packet.packet_sha256
        assert runtime.display_packet(packet, claim=claim) == frozen


def test_clipped_or_oversized_context_defers_the_whole_figure():
    for lines in (
        [(30, 50, "- We operate a climate committee."), (20, 95, "However, cancelled.")],
        [(30, 50, "- We operate a climate committee.")]
        + [(30, 65 + i, "Context " * 20) for i in range(30)],
    ):
        graph, source = figure(lines)
        new, receipt = native_figure_candidates(graph, source.content)
        assert new == graph and not receipt["candidates"]
        assert receipt["unresolved"]


def test_missing_native_context_is_rejected_instead_of_silently_dropped():
    from dataclasses import replace

    from proofops.application.ingest.k6_coverage import native_figure_context_blocks

    graph, source = figure(
        [(30, 50, "Plans for 2035"), (30, 65, "- We operate a climate committee.")]
    )
    new, receipt = native_figure_candidates(graph, source.content)
    candidate = next(b for b in new.blocks if b.source_id == receipt["candidates"][0]["source_id"])
    context = native_figure_context_blocks(candidate, new)
    assert context
    broken = replace(new, blocks=tuple(b for b in new.blocks if b != context[0]))
    with pytest.raises(ValueError, match="QC_NATIVE_FIGURE_CONTEXT_INVALID"):
        native_figure_context_blocks(candidate, broken)
