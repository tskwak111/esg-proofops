"""FX3: free streaming intake and isolated uncertain charges."""

import json
import ssl
import subprocess
import time
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from proofops_api.hosted import create_hosted_app
from proofops_api.hosted_store import HostedError, HostedStore

from tests.test_hosted_public import actor, login, pdf
from tests.test_hosted_scope import settings as _settings


@pytest.fixture
def settings(tmp_path):
    return _settings.__wrapped__(tmp_path)


def test_upload_150_mib_streams_to_private_file(settings, monkeypatch):
    settings = replace(settings, max_upload_bytes=150 * 1024 * 1024)
    app = create_hosted_app(settings)
    store = app.state.composition
    client, headers, _, _ = login(app, store)
    observed = []
    original = store.upload_file

    def capture(auth, path, key, *, now, ux1_metadata=None):
        assert isinstance(path, Path) and path.is_file()
        assert path.stat().st_mode & 0o077 == 0
        assert ux1_metadata is None
        observed.append(path)
        return original(auth, path, key, now=now, ux1_metadata=ux1_metadata)

    monkeypatch.setattr(store, "upload_file", capture)
    content = pdf() + b"\n%" + b"x" * (51 * 1024 * 1024)
    response = client.post(
        "/v1/documents",
        content=(content[i : i + 65536] for i in range(0, len(content), 65536)),
        headers=headers
        | {"Content-Type": "application/pdf", "Idempotency-Key": "fx3-stream-upload"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["size_bytes"] == len(content)
    assert observed and not observed[0].exists()
    with pytest.raises(ValueError):
        replace(settings, max_upload_bytes=150 * 1024 * 1024 + 1)


def test_scope_child_failure_becomes_immutable_manual_proposal(settings, monkeypatch):
    store = HostedStore(settings)
    auth = actor(store)
    doc = store.upload(auth, pdf(5), "fx3-fallback-upload", now=time.time())

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(137, "scope")

    monkeypatch.setattr("proofops_api.hosted_store.subprocess.run", fail)
    scope = store.generate_scope(auth, doc["document_id"])
    assert scope["selection"] is None and scope["plan"]["status"] == "failed"
    assert scope["plan"]["suggested_front_pages"] == [1, 2, 3]
    assert scope["plan"]["unreadable_pages"] == [1, 2, 3, 4, 5]
    edited = store.edit_scope(auth, doc["document_id"], [1, 2], [1, 2, 3], '"1"')
    assert edited["selection"]["manual_override"]
    assert edited["plan"]["unreadable_pages"] == scope["plan"]["unreadable_pages"]


@pytest.mark.parametrize("published_status", ["partial_blocked", "completed"])
def test_network_uncertainty_can_publish_without_releasing_money(
    settings, tmp_path, monkeypatch, published_status
):
    store = HostedStore(settings)
    auth = actor(store)
    doc = store.upload(auth, pdf(), "fx3-network-upload", now=time.time())
    store.create_run(auth, doc["document_id"], [1], "fx3-network-run001", now=time.time())
    job = store.claim(now=time.time())
    calls = []

    def fail(request):
        calls.append(request)
        raise ssl.SSLEOFError("injected")

    with pytest.raises(HostedError, match="PROCESSING_UNCERTAIN"):
        store.dispatch(
            job, "openai", "claim-uncertain", "a" * 64, Decimal("0.011"), fail, now=time.time()
        )
    assert store.get_run(auth.tenant_id, job["run_id"])["status"] == "running"
    with pytest.raises(HostedError, match="DISPATCH_ALREADY_RECORDED"):
        store.dispatch(
            job, "openai", "claim-uncertain", "a" * 64, Decimal("0.011"), fail, now=time.time()
        )
    source = tmp_path / "partial"
    source.mkdir()
    source.joinpath("outcome.json").write_text(
        json.dumps({"status": "partial_blocked", "reason": "PROCESSING_UNCERTAIN"})
    )
    snapshot = {
        "claims": [
            {"claim_id": "good"},
            {"claim_id": "held", "hold_reason": "PROCESSING_UNCERTAIN", "confirmed_grade": None},
        ]
    }
    monkeypatch.setattr(
        "proofops_api.hosted_results.result_snapshot",
        lambda *a: json.dumps(
            dict(tenant_id=auth.tenant_id, page_map=[1], source_hashes={}, result=snapshot)
        ).encode(),
    )
    store.publish_analysis(job, source, published_status, "PROCESSING_UNCERTAIN")
    assert store.get_result(auth.tenant_id, job["run_id"])["claims"] == snapshot["claims"]
    assert store.get_run(auth.tenant_id, job["run_id"])["result_url"]
    assert store.budget_totals()["event_reserved_usd"] == "1.000000"
    other = actor(store)
    other_doc = store.upload(other, pdf(), "fx3-other-upload", now=time.time())
    other_run = store.create_run(
        other, other_doc["document_id"], [1], "fx3-other-run0001", now=time.time()
    )
    assert store.claim(now=time.time())["run_id"] == other_run["run_id"]
    with store.transaction() as db:
        assert tuple(db.execute("SELECT bound,actual,status FROM deletion.costs").fetchone()) == (
            11000,
            None,
            "accounting_pending",
        )
    assert len(calls) == 1
    # Operators can settle the money after publication without rewriting the result.
    from proofops_api.hosted_store import digest

    from scripts.hosted_control import reconcile

    with store.transaction() as db:
        call = dict(db.execute("SELECT * FROM deletion.costs").fetchone())
    export = tmp_path / "operator-export.json"
    export.write_text('{"offline_fixture":true,"actual_usd":"0.004"}')
    receipt = dict(
        run_id=job["run_id"],
        operator="offline-test",
        reason="Provider export matched",
        provider_evidence_sha256=digest(export.read_bytes()),
        calls=[
            {k: call[k] for k in ("call_id", "request_id", "provider", "input_sha256")}
            | dict(actual_usd="0.004")
        ],
    )
    reconcile(store, receipt, export)
    assert store.budget_totals()["event_reserved_usd"] == "2.000000"
    reconcile(store, receipt, export, apply=True)
    assert store.budget_totals()["event_reserved_usd"] == "1.004000"
    assert store.get_run(auth.tenant_id, job["run_id"])["status"] == published_status
    assert store.get_result(auth.tenant_id, job["run_id"])["claims"] == snapshot["claims"]


@pytest.mark.parametrize("normalized", [False, True])
def test_uncertain_claim_in_real_local_pipeline_keeps_other_claims(
    settings, monkeypatch, normalized
):
    import os
    import socket
    from tempfile import TemporaryDirectory

    from evaluation.hosted_r108 import drive
    from tests.test_hosted_analysis import fake_llm, fake_parse, source_pdf
    from tests.test_hosted_ocr import fake_page_ocr

    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("no network"))
    store = HostedStore(settings)
    auth = actor(store)
    doc = store.upload(auth, source_pdf(), "fx3-pipeline-upload", now=time.time())
    store.create_run(
        auth, doc["document_id"], [1, 2], "fx3-pipeline-run01", now=time.time(), auto_scope=True
    )
    failed = []

    def llm(body):
        data = json.loads(body["messages"][1]["content"])["untrusted_document_data"]
        if "allowed_elements" in data and not failed:
            failed.append(True)
            if normalized:
                raise ValueError("PROCESSING_UNCERTAIN")
            raise ssl.SSLEOFError("injected once")
        return fake_llm(body)

    def analyze(store, job, prepared):
        with TemporaryDirectory() as scratch:
            workspace = Path(scratch)
            workspace.joinpath("selected.pdf").write_bytes(prepared.read_bytes())
            state, outcome = drive(
                store,
                job,
                workspace,
                dict(
                    llm_provider="openai",
                    report_year=2025,
                    period_start="2024-01-01",
                    period_end="2024-12-31",
                ),
                llm_post=llm,
                parse_post=fake_parse,
                ocr_post=fake_page_ocr,
            )
            store.publish_analysis(job, state, outcome["status"], outcome["reason"])

    done = store.tick(now=time.time(), analysis=analyze)
    assert failed and done["result_url"], done
    assert done["status"] == "completed", done
    claims = done["result"]["claims"]
    held = [claim for claim in claims if claim["hold_reason"] == "PROCESSING_UNCERTAIN"]
    others = [claim for claim in claims if claim["hold_reason"] != "PROCESSING_UNCERTAIN"]
    assert len(held) == 1 and others, claims
    assert held[0]["confirmed_grade"] is None
    assert held[0]["provisional_grade"]["evidence_grade"] is None
    with store.transaction() as db:
        unknown = db.execute(
            "SELECT bound,actual FROM deletion.costs WHERE status='accounting_pending'"
        ).fetchall()
        assert [tuple(row) for row in unknown] == [(11000, None)]
        assert (
            db.execute("SELECT amount,status FROM deletion.spend").fetchone()["status"]
            == "accounting_pending"
        )


def test_openai_trace_header_uses_durable_broker_request_id(settings, tmp_path, monkeypatch):
    from proofops_api.hosted_analysis import HostedOpenAILunaProbe

    store = HostedStore(settings)
    auth = actor(store)
    doc = store.upload(auth, pdf(), "fx3-trace-upload01", now=time.time())
    store.create_run(auth, doc["document_id"], [1], "fx3-trace-run0001", now=time.time())
    job = store.claim(now=time.time())
    traced = []

    class Response:
        status = 200

        def getheader(self, name):
            return "provider-trace" if name == "x-request-id" else None

        def read(self, size):
            return json.dumps(
                {
                    "model": "gpt-6-luna",
                    "usage": {
                        "prompt_tokens": 20,
                        "completion_tokens": 10,
                        "prompt_tokens_details": {},
                    },
                }
            ).encode()

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, headers, **kwargs):
            traced.append(headers["X-Client-Request-Id"])

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr("http.client.HTTPSConnection", Connection)
    probe = HostedOpenAILunaProbe("dummy-local-test", tmp_path / "trace.db", store=store, job=job)
    result = probe._post(probe.request_body("test", "{}", request_id="trace"))
    assert result["openai_request_id"] == "provider-trace"
    with store.transaction() as db:
        request_id = db.execute("SELECT request_id FROM deletion.costs").fetchone()[0]
    assert traced == [request_id]
