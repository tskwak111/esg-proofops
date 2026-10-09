import json
import sqlite3
from dataclasses import replace
from decimal import Decimal

import pytest
from proofops.adapters.local.upstage import UpstageProbe
from proofops.adapters.local.upstage_parse import UpstageParseProbe
from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser

from tests.integration.test_mixed_parser import Probe, document, profile
from tests.integration.test_upstage_parse import make_pdf


def test_async_unknown_reserves_page_price_and_shared_text_reader_accepts_it(tmp_path):
    client = UpstageParseProbe("test-secret", tmp_path / "budget.sqlite3")
    client._post_parse = lambda *_: (_ for _ in ()).throw(ValueError("UPSTAGE_HTTP_503"))
    with pytest.raises(ValueError, match="UPSTAGE_HTTP_503"):
        client.parse_async(make_pdf(3), request_id="unknown", mode="enhanced")
    text = UpstageProbe("test-secret", client.ledger)
    assert Decimal(text.summary()["committed_usd"]) == Decimal(".099")
    with sqlite3.connect(client.ledger) as db:
        assert UpstageProbe._call_total(db) == Decimal(".099")
    with pytest.raises(ValueError, match="DUPLICATE_PROBE_REQUEST"):
        client.parse_async(make_pdf(3), request_id="unknown", mode="enhanced")


def test_pending_async_state_is_polled_without_resubmission(tmp_path, monkeypatch):
    client = UpstageParseProbe("test-secret", tmp_path / "budget.sqlite3")
    posts = []
    client._post_parse = lambda *a: posts.append(a) or {"request_id": "provider-job"}
    statuses = iter(
        [
            {"status": "pending"},
            {
                "status": "completed",
                "total_pages": 1,
                "completed_pages": 1,
                "model": "document-parse-260128",
                "batches": [{"download_url": "ignored"}],
            },
        ]
    )
    client._async_status = lambda _: next(statuses)
    client._async_download = lambda _: {
        "model": "document-parse-260128",
        "elements": [],
        "usage": {"pages": 1, "standard": [1]},
    }
    monkeypatch.setattr("proofops.adapters.local.upstage_parse.sleep", lambda _: None)
    assert client.parse_async(make_pdf(1), request_id="queued")["pages"] == 1
    assert len(posts) == 1
    from proofops.domain.provenance import canonical_hash

    audit = json.loads(
        (tmp_path / "parse-dispatch" / (canonical_hash("queued") + ".json")).read_text()
    )
    assert audit["provider_request_id"] == "provider-job"
    assert audit["phase"] == "settled"


def test_enhanced_failure_preserves_standard_and_is_replayable(tmp_path, monkeypatch):
    from proofops.adapters.parsing import upstage_document

    original = upstage_document.candidate_batch

    def needs_enhanced(*a, **kw):
        batch, metrics = original(*a, **kw)
        metrics["low_grounding_pages"] = [1]
        return batch, metrics

    class FailedEnhanced(Probe):
        def parse_async(self, content, *, request_id, mode):
            if mode == "enhanced":
                self.calls.append((1, mode))
                raise ValueError("UPSTAGE_HTTP_503")
            return super().parse_async(content, request_id=request_id, mode=mode)

    monkeypatch.setattr(upstage_document, "candidate_batch", needs_enhanced)
    source = document()
    config = replace(profile(), failure_policy="partial-v1")
    probe = FailedEnhanced()
    parser = OpenDataLoaderParser(tmp_path, upstage_probe=probe)
    graph = parser.parse(source, config, tenant_id=source.tenant_id)
    assert {b.page_num for b in graph.blocks} == {1, 2}
    assert probe.calls == [(1, "standard"), (1, "enhanced")]
    assert any(i.page_num == 1 and i.kind == "parser_batch_failed" for i in graph.issues)
    assert parser.load_verified(source, config, tenant_id=source.tenant_id) == graph


def test_primary_parser_failure_preserves_remaining_evidence_pages(tmp_path):
    class FailedStandard(Probe):
        def parse_async(self, content, *, request_id, mode):
            self.calls.append((1, mode))
            raise ValueError("UPSTAGE_HTTP_503")

    source = document()
    config = replace(profile(), failure_policy="partial-v1")
    probe = FailedStandard()
    parser = OpenDataLoaderParser(tmp_path, upstage_probe=probe)
    graph = parser.parse(source, config, tenant_id=source.tenant_id)
    assert probe.calls == [(1, "standard")]
    assert {b.page_num for b in graph.blocks} == {2}
    assert any(i.page_num == 1 and i.kind == "parser_batch_failed" for i in graph.issues)
    assert parser.load_verified(source, config, tenant_id=source.tenant_id) == graph


def test_finals_pins_evidence_source_policy(tmp_path, monkeypatch):
    from proofops.adapters.local.evidence_source_verification_v1 import policy
    from proofops.application.runs import RunService

    from tests.integration.test_local_tag_runner import TENANT, verified_setup

    init = RunService.__init__

    def finals(self, *a, **kw):
        kw["pipeline_profile"] = "finals-unattended-v1"
        init(self, *a, **kw)

    monkeypatch.setattr(RunService, "__init__", finals)
    service, run_id, _, _, _ = verified_setup(tmp_path, monkeypatch)
    assert service.store.snapshot(TENANT, run_id)["evidence_source_policy"] == policy()


def test_real_parser_worker_publishes_and_replays_ev1(tmp_path, monkeypatch):
    from proofops.adapters.local.run_artifacts import load_run_evidence
    from proofops.application.ports.jobs import JobMessage
    from proofops.application.runs import RunService

    from tests.integration.test_native_paragraph_worker import TENANT, runner_setup_native

    init = RunService.__init__

    def finals(self, *a, **kw):
        kw["pipeline_profile"] = "finals-unattended-v1"
        init(self, *a, **kw)

    monkeypatch.setattr(RunService, "__init__", finals)
    service, run_id, runner, _, stream = runner_setup_native(tmp_path, monkeypatch, True)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed", stream.getvalue()
    message = JobMessage(**service.store.jobs.get_run(TENANT, run_id)["parse_job"])
    checkpoint = service.store.jobs.read_checkpoint(message)
    envelope = json.loads(checkpoint)
    assert envelope["evidence_source_attestation"]["policy"]["profile"] == "evidence-source-v1"
    evidence = load_run_evidence(
        service.store, service.uploads, runner.parser, tenant_id=TENANT, run_id=run_id
    )
    assert runner.load_graph(tenant_id=TENANT, run_id=run_id) == evidence["graph"]
    assert service.store.jobs.read_checkpoint(message) == checkpoint
