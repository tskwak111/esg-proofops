"""Real worker fencing and continuation, fake provider ledger, no HTTP."""

import json
from dataclasses import replace

import pytest
from proofops.application.ingest.graph_fusion import fuse_candidates
from proofops_agent.upstage_extraction import UpstageClaimExtractor

from tests.acceptance.test_upload import TENANT
from tests.integration.test_real_extract_runner import (
    _freeze_upstage_price_clock,  # noqa: F401 -- register existing offline clock fixture
    inject_graph,
    real_setup,
)


@pytest.mark.parametrize("limit", [1, 2])
def test_row_profile_routes_through_worker_and_continuation(tmp_path, monkeypatch, limit):
    service, run_id, runner, now, probe = real_setup(
        tmp_path,
        monkeypatch,
        limit=limit,
        extractor_factory=lambda p, receipts: UpstageClaimExtractor(
            p,
            receipts,
            extraction_source_ids=True,
            extraction_table_rows=True,
            extraction_recall_prompt=True,
        ),
    )
    probe.content = '{"sentence_ids":[]}'
    original = inject_graph(monkeypatch, service, run_id, ["paragraph", "table"])
    text = "지표\t단위\t2024년\n온실가스 배출량\ttCO2e\t123"
    batch = original.candidates[0]
    native = batch.blocks[1]
    new_batch = replace(
        batch,
        blocks=(
            batch.blocks[0],
            replace(native, source=replace(native.source, raw_text=text, char_end=len(text))),
        ),
    )
    graph = fuse_candidates((new_batch,), tenant_id=TENANT)
    for module in (
        "proofops.adapters.local.claim_store",
        "proofops.adapters.local.run_artifacts",
        "proofops_worker.extract_runner",
    ):
        monkeypatch.setattr(module + ".load_run_graph", lambda *a, **k: graph)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    assert len(probe.calls) == limit
    if limit == 1:
        result = runner.run_batch(tenant_id=TENANT, run_id=run_id)
        assert result["status"] == "committed"
    assert len(probe.calls) == 2
    sources = [json.loads(c["user_json"])["untrusted_document_data"] for c in probe.calls]
    assert any(
        "extraction-table-rows-v1" in s["source_sentences"][0]["sentence_id"] for s in sources
    )
    assert not runner.claims.load(TENANT, run_id).claims
