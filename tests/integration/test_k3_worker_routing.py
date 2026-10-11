"""Synthetic graph identity under the real worker; original-source proof is separate."""

from dataclasses import replace

from proofops.application.ingest.graph_fusion import fuse_candidates
from proofops_agent.upstage_extraction import UpstageClaimExtractor

from tests.acceptance.test_upload import TENANT
from tests.integration.test_real_extract_runner import inject_graph, real_setup
from tests.unit.test_pa9_source import fixture


def test_real_worker_and_checkpoint_replay_recover_all_four_vehicle_rows(tmp_path, monkeypatch):
    def extractor(probe, directory):
        return UpstageClaimExtractor(
            probe,
            directory,
            extraction_source_ids=True,
            extraction_context=True,
            extraction_table_rows=True,
            extraction_pb1=True,
            extraction_w9=True,
            extraction_k3=True,
        )

    service, run, worker, _, probe = real_setup(
        tmp_path, monkeypatch, limit=20, extractor_factory=extractor
    )
    identity = inject_graph(monkeypatch, service, run, ["table"])
    stored, _ = fixture("kia")
    table = next(b for b in stored.blocks if b.kind == "table" and "644,685" in b.raw_text)
    native_id = table.candidates[table.winner].source.source_native_id
    batches = tuple(
        replace(
            batch,
            tenant_id=TENANT,
            document_version_id=identity.document_version_id,
            parse_manifest_id=identity.parse_manifest_id,
            source_sha256=identity.source_sha256,
            edges=tuple(e for e in batch.edges if e.target_native_id == native_id),
            blocks=tuple(
                replace(
                    c,
                    source=replace(
                        c.source,
                        document_version_id=identity.document_version_id,
                        parse_manifest_id=identity.parse_manifest_id,
                    ),
                    context=(*c.context, "pb1-w9-v1"),
                )
                for c in batch.blocks
                if c.source.source_native_id == native_id or c.table_native_id == native_id
            ),
        )
        for batch in stored.candidates
    )
    graph = fuse_candidates(batches, tenant_id=TENANT, fusion_version=5, mixed_parser=True)
    for module in (
        "proofops.adapters.local.claim_store",
        "proofops.adapters.local.run_artifacts",
        "proofops_worker.extract_runner",
    ):
        monkeypatch.setattr(module + ".load_run_graph", lambda *args, **kwargs: graph)
    assert worker.run_once(tenant_id=TENANT, run_id=run) == "committed"
    claims = worker.claims.load(TENANT, run).claims
    assert len(claims) == 4
    assert all(c.source_quality == "unverified" for c in claims)
    assert {c.quote.split("\t")[-1] for c in claims} == {
        "644,685",
        "382,764",
        "67,797",
        "194,124",
    }
    assert not probe.calls
