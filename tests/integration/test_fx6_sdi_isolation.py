"""SDI page 34: post-QT1 quote validation stays source-local and fail-closed."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest
from proofops.application.analysis_profile import V2_POLICY
from proofops.application.claims import ClaimScope, ExtractionOutputError, discover_atomic_claims
from proofops.application.ingest.graph_fusion import candidates_from_snapshot, fuse_candidates
from proofops_agent.upstage_extraction import UpstageClaimExtractor

from evaluation.w7_sentence_replay import NoTransport
from tests.integration.test_qt1_pipeline import flags, packet


def test_sdi_saved_input_holds_bad_table_and_discovers_other_claims(tmp_path):
    saved = json.loads(
        (Path(__file__).parents[1] / "fixtures/fx6-isolation/sdi-table.json").read_text()
    )
    graph = fuse_candidates(
        candidates_from_snapshot(saved["snapshot"]),
        tenant_id=saved["snapshot"][0]["tenant_id"],
        fusion_version=saved["fusion_version"],
        mixed_parser=True,
    )

    class RetainedModelOutput(UpstageClaimExtractor):
        def _extract(self, packet, **kwargs):
            sid = packet["untrusted_document_data"]["source_id"]
            return {"spans": saved["results"].get(sid, [])}

    extractor = RetainedModelOutput(NoTransport(), tmp_path, **flags(V2_POLICY))
    bad = next(b for b in graph.blocks if b.source_id == saved["bad_source_id"])
    for _ in range(2):
        with pytest.raises(ExtractionOutputError) as held:
            extractor.extract(packet(graph, bad), context_graph=graph)
        assert held.value.failure_code == "TABLE_QT1_SPAN_INVALID"
    # Identity failures are outside the local span-validation boundary.
    with pytest.raises(ValueError) as mismatched:
        extractor.extract(packet(graph, bad) | {"tenant_id": "0" * 36}, context_graph=graph)
    assert not isinstance(mismatched.value, ExtractionOutputError)

    class Bound:
        profile = extractor.profile

        def extract(self, data):
            return extractor.extract(data, context_graph=graph)

    discovery = discover_atomic_claims(
        graph,
        ClaimScope(graph.tenant_id, graph.document_version_id, graph.parse_manifest_id),
        extractor=Bound(),
    )
    assert discovery.claims
    assert all(c.source_refs[0].source_id == saved["good_source_id"] for c in discovery.claims)
    failure = next(e for e in discovery.exclusions if e.source_id == bad.source_id)
    assert (failure.state, failure.reason) == ("unknown", "TABLE_QT1_SPAN_INVALID")
    assert failure.source_ref.quote == bad.normalized_text
    assert not list(tmp_path.glob("qt1-*.json"))
    from proofops.adapters.local.claim_store import _RecordedExtractor

    replayed = discover_atomic_claims(
        graph,
        discovery.scope,
        extractor=_RecordedExtractor(
            extractor.profile,
            asdict(discovery)["receipts"],
            failures={bad.source_id: failure.reason},
        ),
    )
    assert replayed == discovery
