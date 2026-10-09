"""HS3 public wiring and single money boundary; no paid transports."""

import json
import sys
import time
from decimal import Decimal
from unittest.mock import patch

import pytest
from proofops_api.hosted_analysis import HostedParseProbe, operator_profiles
from proofops_api.hosted_store import HostedError, HostedStore

from evaluation.hosted_r108 import prepare_argv
from tests.test_hosted_analysis import fake_parse, source_pdf
from tests.test_hosted_public import actor, pdf
from tests.test_hosted_scope import install_plan
from tests.test_hosted_scope import settings as _settings


@pytest.fixture
def settings(tmp_path):
    return _settings.__wrapped__(tmp_path)


@pytest.mark.parametrize("profile", ["finals-unattended-v1", "finals-unattended-v2"])
def test_profile_prepares_mixed_and_approved_linux_source(tmp_path, monkeypatch, profile):
    from evaluation import local_upstage_pilot as pilot

    __import__("pypdfium2")  # Load the native library before overriding sys.platform.

    monkeypatch.setattr(sys, "platform", "linux")
    source = tmp_path / "selected.pdf"
    source.write_bytes(source_pdf())
    state = tmp_path / "state"
    config = dict(
        analysis_profile=profile,
        report_year=2024,
        period_start="2024-01-01",
        period_end="2024-12-31",
    )
    argv = prepare_argv(
        source,
        state,
        "11111111-1111-4111-8111-111111111111",
        config,
        dict(pages=[10, 20], claim_pages=[10], pipeline_profile=profile),
    )
    assert argv[argv.index("--analysis-profile") + 1] == profile
    assert argv[argv.index("--claim-pages") + 1] == "1"
    monkeypatch.setattr(sys, "argv", argv)
    assert pilot.main() == 0
    frozen = json.loads((state / "settings.json").read_text())
    parser = json.loads((state / "parser.json").read_text())
    assert parser["parser_mode"] == "mixed-v1"
    assert frozen["pipeline_profile"] == profile
    assert frozen["claim_source_policy"]["profile"] == "upstage-ocr-page-v3"
    from proofops.adapters.local.run_store import LocalSQLiteRunStore

    manifest = json.loads((state / "pilot.json").read_text())
    snapshot = LocalSQLiteRunStore(state / "state.sqlite3").snapshot(
        manifest["tenant_id"], manifest["run_id"]
    )
    assert snapshot["analysis_profile_policy"]["evidence_source"] == "evidence-source-v1"


def test_default_is_one_operator_setting(monkeypatch):
    monkeypatch.delenv("HOSTED_ANALYSIS_PROFILE", raising=False)
    assert operator_profiles({})["analysis_profile"] == "finals-unattended-v2"
    monkeypatch.setenv("HOSTED_ANALYSIS_PROFILE", "finals-unattended-v1")
    assert operator_profiles({})["analysis_profile"] == "finals-unattended-v1"
    assert (
        operator_profiles({"analysis_profile": "r108-default"})["analysis_profile"]
        == "r108-default"
    )
    assert {"finals-unattended-v1", "finals-unattended-v2"} <= set(
        operator_profiles({})["analysis_profile_options"]
    )


@pytest.mark.parametrize("profile", ["finals-unattended-v1", "finals-unattended-v2"])
def test_intake_freezes_profile_and_hash(settings, profile):
    store = HostedStore(settings)
    auth = actor(store)
    doc = store.upload(auth, pdf(3), "hs3-upload-000001", now=time.time())
    scope = install_plan(store, auth, doc)
    run = store.create_run(
        auth,
        doc["document_id"],
        None,
        "hs3-run-00000001",
        now=time.time(),
        auto_scope=True,
        pipeline_profile=profile,
        scope_selection_sha256=scope["selection"]["selection_sha256"],
    )
    with store.transaction() as db:
        job = dict(db.execute("SELECT * FROM runs WHERE run_id=?", (run["run_id"],)).fetchone())
    options = store.run_options(job)
    assert options["analysis_profile"] == profile
    assert len(options["analysis_profile_sha256"]) == 64


def test_async_scheduled_parser_and_llm_share_hosted_envelope(settings, tmp_path, monkeypatch):
    from proofops.adapters.local.openai import WIRE_POLICY
    from proofops.adapters.local.upstage_parse import UpstageParseProbe
    from proofops_api.hosted_analysis import HostedOpenAILunaProbe

    from tests.test_hosted_analysis import fake_llm

    store = HostedStore(settings)
    auth = actor(store)
    doc = store.upload(auth, source_pdf(), "hs3-cost-upload001", now=time.time())
    store.create_run(auth, doc["document_id"], [1, 2], "hs3-cost-run000001", now=time.time())
    job = store.claim(now=time.time())
    statuses = iter(
        [
            dict(status="scheduled"),
            dict(
                status="completed",
                total_pages=2,
                completed_pages=2,
                model="document-parse-260128",
                batches=[dict(download_url="https://test.files.upstage.ai/result")],
            ),
        ]
    )
    sent = []

    def post(self, content, mode, path="/v1/document-digitization"):
        sent.append(path)
        return dict(request_id="hs3-provider-job")

    monkeypatch.setattr(UpstageParseProbe, "_post_parse", post)
    monkeypatch.setattr(UpstageParseProbe, "_async_status", lambda *a: next(statuses))
    monkeypatch.setattr(
        UpstageParseProbe, "_async_download", lambda *a: fake_parse(source_pdf(), "standard")
    )
    monkeypatch.setattr("proofops.adapters.local.upstage_parse.sleep", lambda *a: None)
    with patch(
        "proofops.adapters.local.profile_runtime.SpendGuard",
        side_effect=AssertionError("double ledger"),
    ):
        parser = HostedParseProbe(
            "fake-test", tmp_path / "parser.sqlite3", store=store, job=job, integrated=True
        )
        result = parser.parse_async(source_pdf(), request_id="hs3-async-001")
        assert result["pages"] == 2
        probe = HostedOpenAILunaProbe(
            "fake-test", tmp_path / "llm.sqlite3", store=store, job=job, post=fake_llm
        )
        # Exercise the brokered HTTP boundary without irrelevant tag schemas.
        body = dict(
            model="gpt-6-luna",
            messages=[
                dict(content="system"),
                dict(content=json.dumps(dict(untrusted_document_data=dict(source_sentences=[])))),
            ],
        )
        assert WIRE_POLICY["endpoint"].endswith("/chat/completions")
        probe._post(body)
    with store.transaction() as db:
        rows = db.execute("SELECT provider,bound,actual,status FROM deletion.costs").fetchall()
        assert len(rows) == 2 and all(row["status"] == "settled" for row in rows)
        assert sum(row["actual"] for row in rows) >= 22000
        assert db.execute("SELECT count(*) FROM deletion.spend").fetchone()[0] == 1
    assert sent == ["/v1/document-digitization/async"]
    with pytest.raises(HostedError, match="BUDGET_EXCEEDED"):
        store.dispatch(
            job,
            "openai",
            "too-expensive",
            "a" * 64,
            Decimal("1"),
            lambda _: pytest.fail("paid dispatch forbidden"),
            now=time.time(),
        )


def test_linux_ocr_allowance_matches_frozen_expanded_scope(settings, tmp_path):
    from proofops.adapters.local.upstage import UpstageProbe
    from proofops_api.hosted_ocr import HostedOCRStore

    store = HostedStore(settings)
    auth = actor(store)
    doc = store.upload(auth, pdf(12), "hs3-ocr-upload001", now=time.time())
    install_plan(store, auth, doc)
    store.create_run(
        auth,
        doc["document_id"],
        None,
        "hs3-ocr-run000001",
        now=time.time(),
        auto_scope=True,
        pipeline_profile="finals-unattended-v2",
    )
    job = store.claim(now=time.time())
    ledger = tmp_path / "upstage.sqlite3"
    UpstageProbe("fake-test", ledger)
    ocr = HostedOCRStore(
        ledger,
        tmp_path / "ocr-spend.json",
        store=store,
        job=job,
        local_run_id="local-test",
        post=lambda _: pytest.fail("no paid OCR"),
    )
    assert ocr.max_calls == len(json.loads(job["pages"]))
    assert ocr.max_calls > 2 and ocr.max_calls <= 30


def test_async_failure_retains_single_reservation_and_cannot_repost(
    settings, tmp_path, monkeypatch
):
    from proofops.adapters.local.upstage_parse import UpstageParseProbe

    store = HostedStore(settings)
    auth = actor(store)
    doc = store.upload(auth, source_pdf(), "hs3-fail-upload01", now=time.time())
    store.create_run(auth, doc["document_id"], [1, 2], "hs3-fail-run00001", now=time.time())
    job = store.claim(now=time.time())
    sent = []

    def fail(*args):
        sent.append(True)
        raise ValueError("UPSTAGE_HTTP_503")

    monkeypatch.setattr(UpstageParseProbe, "_post_parse", fail)
    parser = HostedParseProbe(
        "fake-test", tmp_path / "parser.sqlite3", store=store, job=job, integrated=True
    )
    with pytest.raises(ValueError, match="UPSTAGE_HTTP_503"):
        parser.parse_async(source_pdf(), request_id="hs3-failed001")
    assert store.get_run(auth.tenant_id, job["run_id"])["status"] == "accounting_pending"
    with pytest.raises(HostedError, match="LEASE_LOST"):
        parser.parse_async(source_pdf(), request_id="hs3-failed002")
    assert len(sent) == 1
    with store.transaction() as db:
        row = db.execute("SELECT bound,actual,status FROM deletion.costs").fetchone()
        assert tuple(row) == (22000, None, "accounting_pending")
        assert db.execute("SELECT count(*) FROM deletion.spend").fetchone()[0] == 1


def test_v1_overlap_uses_bound_tag_composition_not_unbrokered_default(monkeypatch):
    from types import SimpleNamespace

    from proofops_worker.unattended_pipeline import PageTagPipeline

    seen = []
    bound_runner = object()
    extractor = SimpleNamespace(tag_composition=lambda: seen.append("hosted") or bound_runner)
    monkeypatch.setattr(
        "proofops_worker.composition.build_composition",
        lambda **kw: pytest.fail("unbrokered tag composition"),
    )
    monkeypatch.setattr("proofops_worker.unattended_pipeline.claim_scope", lambda *a: None)
    pipeline = PageTagPipeline(extractor, {}, None, None, None, b"")
    try:
        assert pipeline.runner is bound_runner and seen == ["hosted"]
    finally:
        pipeline.pool.shutdown(wait=True)
