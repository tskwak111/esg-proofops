from proofops.application.runs import RunService

from tests.integration.test_local_tag_runner import TENANT, verified_setup


def test_v2_live_run_keeps_capacity_and_analysis_policies_separate(tmp_path, monkeypatch):
    from tests.integration.test_live_tagging_pipeline import _pipeline_setup

    init = RunService.__init__

    def profile(self, *args, **kwargs):
        kwargs["pipeline_profile"] = "finals-unattended-v2"
        init(self, *args, **kwargs)

    monkeypatch.setattr(RunService, "__init__", profile)
    ctx = _pipeline_setup(tmp_path, monkeypatch)
    snapshot = ctx["service"].store.snapshot(TENANT, ctx["run_id"])
    from proofops.domain.provenance import canonical_hash

    assert (
        canonical_hash(snapshot["input_reservation_policy"])
        == snapshot["input_reservation_policy_hash"]
    )
    assert snapshot["input_reservation_policy"] != snapshot["analysis_profile_policy"]


def test_v2_tags_verified_claims_and_does_not_reuse_early_records(tmp_path, monkeypatch):
    init = RunService.__init__

    def profile(self, *args, **kwargs):
        kwargs["pipeline_profile"] = "finals-unattended-v2"
        init(self, *args, **kwargs)

    monkeypatch.setattr(RunService, "__init__", profile)
    service, run_id, runner, _, _ = verified_setup(tmp_path, monkeypatch)
    extraction, discovery, graph = runner.claims.load_evidence(TENANT, run_id)
    # Even a legacy early record must never be consumed by the v2 tag phase.
    extraction = extraction | {"page_tag_pipeline": [dict(claims=[dict(claim_id="invalid")])]}
    monkeypatch.setattr(runner.claims, "load_evidence", lambda *_: (extraction, discovery, graph))
    seen = []

    def classify(claim, _graph):
        seen.append(claim.source_quality)
        return None

    runner.preliminary = classify
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "completed"
    rows = runner.tags.load_snapshot(TENANT, run_id)["claims"]
    assert seen and set(seen) == {"verified"}
    assert all(r["provisional_grade"]["display_type"] == "hold" for r in rows)
    assert all(r["decision"] is None and r["review_inputs"] is None for r in rows)
    assert (
        service.store.snapshot(TENANT, run_id)["analysis_profile_policy"]["stage_overlap"] is False
    )


def test_v2_real_extract_worker_never_starts_page_tagging(tmp_path, monkeypatch):
    import json

    from tests.integration.test_local_extract_runner import extract_message
    from tests.integration.test_real_extract_runner import FakeProbe, inject_graph, real_setup

    init = RunService.__init__

    def profile(self, *args, **kwargs):
        kwargs["pipeline_profile"] = "finals-unattended-v2"
        init(self, *args, **kwargs)

    monkeypatch.setattr(RunService, "__init__", profile)
    probe = FakeProbe()

    def response(body):
        text = json.loads(body["messages"][-1]["content"])["untrusted_document_data"]["text"]
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
    probe.model = "gpt-6-luna"
    inject_graph(monkeypatch, service, run_id, ["paragraph"] * 3)
    monkeypatch.setattr(
        "proofops_worker.unattended_pipeline.PageTagPipeline",
        lambda *_: (_ for _ in ()).throw(AssertionError("early tagging forbidden")),
    )
    message = extract_message(service, run_id, now[0])
    assert extractor.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    envelope = json.loads(service.store.jobs.read_checkpoint(message))
    assert "page_tag_pipeline" not in envelope
    assert len(envelope["discovery"]["claims"]) == 3
