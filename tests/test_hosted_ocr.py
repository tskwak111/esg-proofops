"""P4 Linux live binding with fake HTTP, real receipts and hosted money fences."""

import os
import time
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest
from proofops.adapters.local.upstage import UpstageProbe
from proofops.adapters.local.upstage_ocr_page import PageOCRStore, render_page
from proofops_api.hosted_ocr import HostedOCRStore, ReplayOCRStore, reader_scope

from tests.integration.test_claim_source_verification import inputs
from tests.integration.test_upstage_ocr_page import response
from tests.test_hosted_analysis import fake_llm, fake_page_ocr, fake_parse, job_setup, source_pdf
from tests.test_hosted_public import settings as _settings


@pytest.fixture
def settings(tmp_path):
    return _settings.__wrapped__(tmp_path)


def ocr_store(tmp_path, settings, post):
    store, auth, job = job_setup(settings)
    ledger = tmp_path / "upstage.sqlite3"
    UpstageProbe("fake", ledger)
    ocr = HostedOCRStore(
        ledger, tmp_path / "ocr-spend.json", store=store, job=job, local_run_id="local", post=post
    )
    return store, auth, job, ocr


def test_hosted_ocr_cache_cost_and_readonly_replay(settings, tmp_path):
    calls = []
    store, auth, job, ocr = ocr_store(
        tmp_path, settings, lambda png: (calls.append(png) or response(), "fake-ocr")
    )
    source, _, _ = inputs()
    image = render_page(source, 1)
    collection = ocr.fetch(image, tenant_id=job["tenant_id"], run_id="local")
    assert ocr.fetch(image, tenant_id=job["tenant_id"], run_id="local") == collection
    assert len(calls) == 1
    assert store.budget_totals()["event_reserved_usd"] == "0.500000"
    with store.transaction() as db:
        assert tuple(
            db.execute("SELECT provider,actual,status FROM deletion.costs").fetchone()
        ) == ("upstage-ocr", 1650, "settled")
    before = ocr.ledger.read_bytes()
    replay = ReplayOCRStore(ocr.ledger)
    assert replay.fetch(image, tenant_id=job["tenant_id"], run_id="local") == collection
    with pytest.raises(ValueError, match="OCR_COLLECTION_UNTRUSTED"):
        replay.fetch(image, tenant_id="foreign", run_id="local")
    assert ocr.ledger.read_bytes() == before
    original = PageOCRStore.__dict__["from_env"]
    with reader_scope(replay):
        assert PageOCRStore.from_env() is replay
    assert PageOCRStore.__dict__["from_env"] is original


def test_ocr_budget_denial_precedes_transport(settings, tmp_path):
    calls = []
    store, auth, job, ocr = ocr_store(
        tmp_path,
        replace(settings, run_usd=Decimal(".001")),
        lambda png: (calls.append(png) or response(), "fake-ocr"),
    )
    source, _, _ = inputs()
    with pytest.raises(ValueError, match="OCR_COLLECTION_FAILED_RESERVATION_RETAINED"):
        ocr.fetch(render_page(source, 1), tenant_id=job["tenant_id"], run_id="local")
    assert not calls
    with store.transaction() as db:
        assert db.execute("SELECT count(*) FROM deletion.costs").fetchone()[0] == 0


def test_invalid_ocr_receipt_retains_money_and_never_redelivers(settings, tmp_path):
    store, auth, job, ocr = ocr_store(tmp_path, settings, lambda png: (b"{}", "bad-receipt"))
    source, _, _ = inputs()
    with pytest.raises(ValueError, match="OCR_COLLECTION_FAILED_RESERVATION_RETAINED"):
        ocr.fetch(render_page(source, 1), tenant_id=job["tenant_id"], run_id="local")
    assert store.get_run(auth.tenant_id, job["run_id"])["status"] == "accounting_pending"
    assert store.claim(now=time.time() + 1000) is None
    assert store.budget_totals()["event_reserved_usd"] == "0.500000"


def test_forged_native_ocr_policy_cannot_bind_parser_job(tmp_path):
    from proofops.adapters.local.job_store import LocalSQLiteJobStore
    from proofops.adapters.local.upstage_ocr_profile_v3 import native_policy

    jobs = LocalSQLiteJobStore(tmp_path / "jobs.sqlite3")
    lease = SimpleNamespace(message=SimpleNamespace(stage="parse"))
    with pytest.raises(ValueError, match="NATIVE_PARAGRAPH_POLICY_MISMATCH"):
        jobs.bind_parser_native_policy(lease, native_policy() | {"wrapper_sha256": "0" * 64}, now=1)


def test_missing_replay_ledger_does_not_create_or_fetch(tmp_path):
    source, _, _ = inputs()
    ledger = tmp_path / "missing.sqlite3"
    with pytest.raises(ValueError, match="OCR_COLLECTION_UNTRUSTED"):
        ReplayOCRStore(ledger).fetch(render_page(source, 1), tenant_id="tenant", run_id="local")
    assert not ledger.exists()


@pytest.mark.parametrize(
    "profile", ["r108-default", "r108-finals-candidate", "r108-finals-candidate-v2"]
)
def test_linux_fake_chain_uses_default_reader_and_survives_receipt_replay(
    settings, monkeypatch, profile
):
    from proofops_api import hosted_analysis

    from evaluation.hosted_r108 import drive

    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(hosted_analysis.sys, "platform", "linux")
    store, auth, job = job_setup(settings)
    with TemporaryDirectory() as scratch:
        workspace = Path(scratch)
        (workspace / "selected.pdf").write_bytes(source_pdf())
        state, outcome = drive(
            store,
            job,
            workspace,
            dict(
                report_year=2025,
                period_start="2024-01-01",
                period_end="2024-12-31",
                analysis_profile=profile,
            ),
            llm_post=fake_llm,
            parse_post=fake_parse,
            ocr_post=fake_page_ocr,
        )
        assert outcome["profiles"]["source_reader"] == "upstage-ocr-page-v5"
        assert outcome["stages"][-1]["stage"] == "tag", outcome
        store.publish_analysis(job, state, outcome["status"], outcome["reason"])
    result = store.get_result(auth.tenant_id, job["run_id"])
    assert len(result["claims"]) == 2
    with store.transaction() as db:
        assert (
            db.execute(
                "SELECT count(*) FROM deletion.costs WHERE provider='upstage-ocr'"
            ).fetchone()[0]
            == 2
        )


def test_fx5_fallback_reserves_standard_price_and_reuses_page(settings, tmp_path, monkeypatch):
    from proofops.adapters.local.upstage_parse import COST_PER_PAGE

    calls = []
    store, _, job, ocr = ocr_store(
        tmp_path, settings, lambda png: (calls.append(1) or response(), "fake")
    )
    source, _, _ = inputs()
    image = render_page(source, 1)
    bounds = []
    dispatch = store.dispatch

    def observed(*args, **kwargs):
        bounds.append(args[4])
        return dispatch(*args, **kwargs)

    monkeypatch.setattr(store, "dispatch", observed)
    with ocr.claim_fallback_scope(1):
        first = ocr.fetch(image, tenant_id=job["tenant_id"], run_id="local")
        assert ocr.fetch(image, tenant_id=job["tenant_id"], run_id="local") == first
    assert calls == [1]
    assert bounds == [COST_PER_PAGE["standard"]]
    with store.transaction() as db:
        assert tuple(db.execute("SELECT actual,status FROM deletion.costs").fetchone()) == (
            1650,
            "settled",
        )


def test_fx5_scope_excludes_evidence_and_bounds_ten_pages(settings, tmp_path):
    _, _, _, ocr = ocr_store(tmp_path, settings, lambda png: pytest.fail("scope sent HTTP"))
    ocr._claim_pages = set(range(1, 12))
    for page in range(1, 11):
        with ocr.claim_fallback_scope(page):
            pass
    with ocr.claim_fallback_scope(1):
        pass
    with pytest.raises(ValueError, match="OCR_CLAIM_FALLBACK_SCOPE_INVALID"):
        with ocr.claim_fallback_scope(11):
            pass
    ocr._claim_pages = {1}
    with pytest.raises(ValueError, match="OCR_CLAIM_FALLBACK_SCOPE_INVALID"):
        with ocr.claim_fallback_scope(2):
            pass
