"""FX4: free regression checks for hosted isolation, evaluator quota and progress."""

import time
from dataclasses import replace
from decimal import Decimal

import pytest
from proofops_api.hosted_store import HostedError, HostedSettings, HostedStore

from evaluation.hosted_r108 import prepare_argv
from tests.test_hosted_analysis import job_setup
from tests.test_hosted_public import actor, uploaded
from tests.test_hosted_public import settings as _settings


@pytest.fixture
def settings(tmp_path):
    return _settings.__wrapped__(tmp_path)


def test_evaluator_can_run_six_reports_but_seventh_is_blocked(settings):
    store = HostedStore(replace(settings, day_usd=Decimal("7"), event_usd=Decimal("7")))
    auth = actor(store)
    doc = uploaded(store, auth)
    for n in range(6):
        store.create_run(auth, doc["document_id"], None, f"fx4-quota-run-{n:04}", now=time.time())
        job = store.claim(now=time.time())
        store.finish(job, "partial_blocked", now=time.time())
    with pytest.raises(HostedError, match="DAILY_RUN_LIMIT"):
        store.create_run(auth, doc["document_id"], None, "fx4-quota-run-last", now=time.time())
    assert store.budget_totals()["event_reserved_usd"] == "0.000000"


def test_daily_limit_is_configurable_and_validated(settings):
    env = dict(
        APP_ENV="hosted",
        MODEL_ADAPTER="disabled",
        HOSTED_DATA_DIR=str(settings.root),
        APP_ORIGIN=settings.origin,
        HOSTED_SESSION_SECRET=settings.secret,
        HOSTED_EVENT_ID=settings.event_id,
        HOSTED_USER_DAILY_RUNS="3",
    )
    assert HostedSettings.from_env(env).user_daily_runs == 3
    assert HostedSettings.from_env(env | {"HOSTED_USER_DAILY_RUNS": "6"}).user_daily_runs == 6
    for value in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            replace(settings, user_daily_runs=value)


def test_hosted_extraction_does_not_stop_at_research_preview_100(tmp_path):
    from pypdf import PdfWriter

    pdf = tmp_path / "selected.pdf"
    w = PdfWriter()
    w.add_blank_page(300, 300)
    w.write(pdf)
    argv = prepare_argv(
        pdf,
        tmp_path / "state",
        "tenant",
        dict(report_year=2025, period_start="2024-01-01", period_end="2024-12-31"),
    )
    assert argv[argv.index("--extraction-total-calls") + 1] == "2000"


def test_running_progress_counts_restart_and_tenant_fence(settings):
    store, auth, job = job_setup(settings)
    store.update_progress(job, "tag", 75, claims_extracted=51, claims_processed=12)
    run = HostedStore(settings).get_run(auth.tenant_id, job["run_id"])
    assert run["claims_extracted"] == 51 and run["claims_processed"] == 12
    assert run["result_url"] is None and run["result"] is None
    with pytest.raises(HostedError, match="RESOURCE_NOT_FOUND"):
        store.get_run("00000000-0000-4000-8000-000000000000", job["run_id"])
    store.cancel(auth, job["run_id"], now=time.time())
    with pytest.raises(HostedError, match="LEASE_LOST"):
        store.update_progress(job, "tag", 75, claims_processed=13)


def test_hosted_decisions_cannot_fall_back_to_research(settings, tmp_path, monkeypatch):
    import os
    import sys

    from proofops.adapters.local.upstage import UpstageProbe
    from proofops_api.hosted_analysis import HostedOpenAILunaProbe, HostedParseProbe
    from proofops_worker.composition import build_composition
    from pypdf import PdfWriter

    from evaluation import local_upstage_pilot as pilot

    monkeypatch.setattr(os, "environ", os.environ.copy())
    pdf = tmp_path / "selected.pdf"
    w = PdfWriter()
    w.add_blank_page(300, 300)
    w.write(pdf)
    monkeypatch.setattr(
        sys,
        "argv",
        prepare_argv(
            pdf,
            tmp_path / "state",
            "11111111-1111-4111-8111-111111111111",
            dict(report_year=2025, period_start="2024-01-01", period_end="2024-12-31"),
        ),
    )
    assert pilot.main() == 0
    UpstageProbe("fake", tmp_path / "parse.db")
    store, _, job = job_setup(settings)
    worker = build_composition(
        stage="tag",
        provider_ledgers=(tmp_path / "parse.db", tmp_path / "llm.db"),
        provider_factories={
            "parse": lambda ledger: HostedParseProbe("fake", ledger, store=store, job=job),
            "llm": lambda key, ledger, **kw: HostedOpenAILunaProbe(
                "fake", ledger, store=store, job=job, **kw
            ),
        },
    )
    try:
        with pytest.raises(ValueError, match="HOSTED_DECISION_BINDING_UNAVAILABLE"):
            worker.live_factory(
                worker,
                {"tagging_settings": {"model_id": "gpt-6-luna"}, "decision_settings": {}},
                None,
                None,
                {},
            )
    finally:
        worker.uploads.close()
        worker.uploads.registry.close()


def test_extraction_stop_still_tags_claims_and_reports_live_counts(settings, monkeypatch):
    import os

    from tests.test_hosted_analysis import fake_analysis, source_pdf

    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(
        "proofops_worker.extract_batch.run_batches",
        lambda *a, **kw: [{"stop_code": "BUDGET_EXHAUSTED"}],
    )
    store = HostedStore(settings)
    auth = actor(store)
    doc = store.upload(auth, source_pdf(), "fx4-progress-upload", now=time.time())
    run = store.create_run(
        auth,
        doc["document_id"],
        [1, 2],
        "fx4-progress-run01",
        now=time.time(),
        pipeline_profile="strict-v1",
    )
    observed = []
    original = store.update_progress

    def tracked(job, *args, **kwargs):
        original(job, *args, **kwargs)
        observed.append(store.get_run(auth.tenant_id, run["run_id"]))

    monkeypatch.setattr(store, "update_progress", tracked)
    done = store.tick(now=time.time(), analysis=fake_analysis)
    result = store.get_result(auth.tenant_id, run["run_id"])
    assert result["pipeline"]["stages"][-1] == {"stage": "tag", "outcome": "needs_review"}
    assert done["status"] == "partial_blocked" and done["error_code"] == "BUDGET_EXHAUSTED"
    assert len(result["claims"]) == 2
    assert any(row["claims_processed"] == 1 and row["result_url"] is None for row in observed)
    assert any(row["stage"] == "result" and row["progress"] == 0.95 for row in observed)
