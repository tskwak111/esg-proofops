from proofops.application.runs import RunService

from tests.integration.test_local_tag_runner import TENANT, verified_setup


def test_every_failed_claim_gets_range_without_confirmed_revision(tmp_path, monkeypatch):
    init = RunService.__init__

    def profile(self, *args, **kwargs):
        kwargs["pipeline_profile"] = "finals-unattended-v1"
        init(self, *args, **kwargs)

    monkeypatch.setattr(RunService, "__init__", profile)
    _, run_id, runner, _, _ = verified_setup(tmp_path, monkeypatch)
    runner.preliminary = lambda *_: None
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "completed"
    items = runner.tags.load_snapshot(TENANT, run_id)["claims"]
    assert items
    for item in items:
        assert item["decision"] is None and item["review_inputs"] is None
        result = item["provisional_grade"]
        assert result["display_type"] == "range"
        assert (result["grade_range"]["floor"], result["grade_range"]["ceiling"]) == ("E0", "E3")
        assert result["label"] is None


def test_page_pipeline_records_are_reused_and_tamper_is_rejected(tmp_path, monkeypatch):
    import json

    import pytest
    from proofops.adapters.local.claim_store import extraction_profile
    from proofops.application.ports.jobs import JobMessage
    from proofops_worker.unattended_pipeline import PageTagPipeline

    from tests.integration.test_local_tag_runner import tag_message

    init = RunService.__init__

    def profile(self, *args, **kwargs):
        kwargs["pipeline_profile"] = "finals-unattended-v1"
        init(self, *args, **kwargs)

    monkeypatch.setattr(RunService, "__init__", profile)
    service, run_id, runner, now, _ = verified_setup(tmp_path, monkeypatch)
    extraction, discovery, graph = runner.claims.load_evidence(TENANT, run_id, for_extraction=True)
    snapshot = service.store.snapshot(TENANT, run_id)
    message = tag_message(service, run_id, now[0])
    lease = service.store.jobs.claim_job(message, owner="INT1-test", now=now[0], lease_seconds=300)
    run = service.store.jobs.get_run(TENANT, run_id)
    checkpoint = service.store.jobs.read_checkpoint(JobMessage(**run["parse_job"]))
    monkeypatch.setattr("proofops_worker.composition.build_composition", lambda **_: runner)
    pipeline = PageTagPipeline(
        None, snapshot, graph, extraction_profile(snapshot), lease, checkpoint
    )
    # This fixture has one original page. Reuse literal extraction receipts, no network.
    responses = {
        r["source_id"]: json.loads(r["raw_response_json"])
        for r in extraction["discovery"]["receipts"]
        if r["raw_response_json"]
    }
    page = pipeline._tag(1, responses)
    assert page["claims"] and all(c["decision"] is None for c in page["claims"])
    payload = extraction | {"page_tag_pipeline": [page]}
    monkeypatch.setattr(runner.claims, "load_evidence", lambda *_: (payload, discovery, graph))
    runner.preliminary = lambda *_: (_ for _ in ()).throw(AssertionError("must reuse"))
    final = json.loads(runner._execute(lease, snapshot, {"synthetic_calls": 0}))
    assert len(final["claims"]) == len(page["claims"])
    assert all(c["status"] != "failed" for c in final["claims"])
    page["graph_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="PIPELINE_GRAPH_MISMATCH"):
        runner._execute(lease, snapshot, {"synthetic_calls": 0})
    pipeline.pool.shutdown()


def test_real_extract_worker_publishes_page_pipeline_then_reuses_it(tmp_path, monkeypatch):
    import json
    from dataclasses import asdict

    from proofops.application.rulepacks import RulePackRecord
    from proofops_worker.tag_runner import LocalTagRunner

    from tests.acceptance.test_rules import pack
    from tests.integration import test_run_lifecycle as lifecycle
    from tests.integration.test_local_extract_runner import extract_message
    from tests.integration.test_real_extract_runner import FakeProbe, inject_graph, real_setup

    full = pack()
    monkeypatch.setattr(lifecycle, "_files", lambda: {p: full.file_content(p) for p in full.files})
    monkeypatch.setattr(
        lifecycle,
        "_pack",
        lambda: RulePackRecord(
            **{
                k: v
                for k, v in (
                    asdict(full)
                    | dict(
                        status="validated",
                        approved_by="synthetic-fixture",
                        approved_at="2026-09-08T10:00:00Z",
                    )
                ).items()
                if k != "content"
            }
        ),
    )
    init = RunService.__init__

    def profile(self, *args, **kwargs):
        kwargs["pipeline_profile"] = "finals-unattended-v1"
        init(self, *args, **kwargs)

    monkeypatch.setattr(RunService, "__init__", profile)
    probe = FakeProbe()

    def response(body):
        data = json.loads(body["messages"][-1]["content"])
        text = data["untrusted_document_data"]["text"]
        return dict(
            id="test-provider",
            model="solar-pro3",
            usage=dict(prompt_tokens=50, completion_tokens=10),
            choices=[
                dict(finish_reason="stop", message=dict(content=json.dumps({"claims": [text]})))
            ],
        )

    probe._client._post = response
    service, run_id, extractor, now, _ = real_setup(
        tmp_path, monkeypatch, limit=3, probe=probe, claim_pages=[1, 2, 3]
    )
    probe.model = "gpt-6-luna"  # HTTP is stubbed; select existing concurrency branch.
    inject_graph(monkeypatch, service, run_id, ["paragraph"] * 3)

    def tag_worker(**_):
        return LocalTagRunner(
            service.store,
            service.uploads,
            extractor.parser,
            telemetry=extractor.telemetry,
            clock=lambda: now[0],
            preliminary=lambda *_: None,
        )

    monkeypatch.setattr("proofops_worker.composition.build_composition", tag_worker)
    message = extract_message(service, run_id, now[0])
    assert extractor.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    envelope = json.loads(service.store.jobs.read_checkpoint(message))
    assert len(envelope["page_tag_pipeline"]) == 3
    assert sum(len(p["claims"]) for p in envelope["page_tag_pipeline"]) == 3
    worker = tag_worker()
    assert worker.run_once(tenant_id=TENANT, run_id=run_id) == "completed"
    records = worker.tags.load_snapshot(TENANT, run_id)["claims"]
    assert len(records) == 3
    assert all(
        r["provisional_grade"]["display_type"] == "range" and r["decision"] is None for r in records
    )
