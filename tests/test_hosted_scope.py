"""HS1 public intake: real security/selection, no paid providers."""

import json
import time
from dataclasses import replace

import pytest
from proofops_api.hosted import create_hosted_app
from proofops_api.hosted_store import HostedError, HostedSettings

from evaluation.report_scope import build_plan
from evaluation.report_sections import build_map
from tests.test_hosted_public import actor, login, pdf


@pytest.fixture
def settings(tmp_path):
    return HostedSettings(
        root=tmp_path / "private",
        origin="https://app.example.com",
        secret="x" * 40,
        event_id="hs1",
        accept_uploads=True,
        consent_version="hs1-test",
        backend="r108",
        accept_runs=True,
    )


@pytest.fixture
def store(settings):
    from proofops_api.hosted_store import HostedStore

    return HostedStore(settings)


def proposal(sha, count):
    study = build_map(
        count, [dict(page=1, title="Environment", path=["Environment"], method="outline")]
    )
    study.update(
        source_sha256=sha,
        source_path="private",
        page_count=count,
        map_sha256="b" * 64,
        issues=[],
        method="pdf_navigation",
    )
    texts = {
        p: f"Environment chapter {p}\n"
        + ("climate carbon emissions renewable energy water waste biodiversity. " * 8)
        for p in range(1, count + 1)
    }
    texts = {
        p: t.replace(
            "climate carbon emissions renewable energy water waste biodiversity. " * 8,
            "climate carbon emissions renewable energy water waste biodiversity. " * (p + 3),
        )
        for p, t in texts.items()
    }
    return build_plan(study, texts)


def install_plan(store, auth, doc):
    plan = proposal(doc["sha256"], doc["page_count"])
    path = store.document_dir(auth.tenant_id, doc["document_id"])
    from evaluation.report_scope import validate_selection

    selection = validate_selection(plan, doc["sha256"], doc["page_count"])
    scope = dict(revision=1, plan=plan, selection=selection)
    store._write(path / "scope-000001.json", json.dumps(scope).encode())
    return scope


def test_runtime_dec22_and_unattended_defaults(settings):
    runtime = create_hosted_app(settings).state.composition.settings
    assert (runtime.run_usd, runtime.day_usd, runtime.event_usd) == (1, 7, 7)
    from fastapi.testclient import TestClient

    body = TestClient(create_hosted_app(settings)).get("/v1/runtime").json()
    assert body["pipeline_profile"] == "unattended-v1"
    assert body["limits"]["claim_pages"] == 10
    assert body["limits"]["evidence_pages"] == 30
    with pytest.raises(ValueError):
        replace(settings, run_usd=runtime.run_usd + 1)


def test_http_scope_edit_and_pinned_run(store, settings):
    app = create_hosted_app(settings)
    client, headers, _, _ = login(app, store)
    doc = client.post(
        "/v1/documents",
        content=pdf(12),
        headers=headers
        | {"Content-Type": "application/pdf", "Idempotency-Key": "scope-upload-0001"},
    ).json()
    # Blank PDF cannot be disguised as readable environment text.
    failed = client.post(f'/v1/documents/{doc["document_id"]}/scope-plan', json={}, headers=headers)
    assert failed.status_code == 200
    assert failed.json()["plan"]["status"] == "failed"
    auth = actor(store)
    doc = store.upload(auth, pdf(12), "scope-upload-0002", now=time.time())
    original = install_plan(store, auth, doc)
    changed = store.edit_scope(auth, doc["document_id"], [1, 2, 3], [1, 2, 3, 4], '"1"')
    assert changed["revision"] == 2
    assert original["selection"]["selection_sha256"] != changed["selection"]["selection_sha256"]
    assert (store.document_dir(auth.tenant_id, doc["document_id"]) / "scope-000001.json").exists()
    with pytest.raises(HostedError, match="SCOPE_CONFLICT"):
        store.edit_scope(auth, doc["document_id"], [1], [1], '"1"')
    with pytest.raises(HostedError):
        store.edit_scope(auth, doc["document_id"], [True], [1], '"2"')
    run = store.create_run(
        auth,
        doc["document_id"],
        None,
        "scope-run-000001",
        now=time.time(),
        auto_scope=True,
        scope_selection_sha256=changed["selection"]["selection_sha256"],
    )
    assert run["selected_pages"] == [1, 2, 3, 4]
    assert run["claim_pages"] == [1, 2, 3]
    assert run["pipeline_profile"] == "unattended-v1"
    job = store.claim(now=time.time())
    options = store.run_options(job)
    assert options["claim_pages"] == [1, 2, 3]
    prepared = store.prepare(job, now=time.time())
    from evaluation.hosted_r108 import prepare_argv

    argv = prepare_argv(
        prepared,
        settings.root / "pilot",
        auth.tenant_id,
        dict(report_year=2025, period_start="2024-01-01", period_end="2024-12-31"),
        options,
    )
    assert argv[argv.index("--claim-pages") + 1] == "1,2,3"
    assert argv[argv.index("--pipeline-profile") + 1] == "unattended-v1"
    other = actor(store)
    with pytest.raises(HostedError, match="RESOURCE_NOT_FOUND"):
        store.get_scope(other.tenant_id, doc["document_id"])


def test_scope_http_permissions_and_failed_plan_no_paid_run(store, settings):
    app = create_hosted_app(settings)
    client, h, _, _ = login(app, store)
    doc = client.post(
        "/v1/documents",
        content=pdf(),
        headers=h | {"Content-Type": "application/pdf", "Idempotency-Key": "scope-security-001"},
    ).json()
    url = f'/v1/documents/{doc["document_id"]}/scope-plan'
    assert client.post(url, json={}).status_code == 403
    assert client.post(url, json={}, headers=h).status_code == 200
    assert (
        client.post(
            "/v1/runs",
            json={"document_id": doc["document_id"]},
            headers=h | {"Idempotency-Key": "scope-failed-run1"},
        ).json()["error"]["code"]
        == "SCOPE_PLAN_FAILED"
    )
    assert store.budget_totals()["event_reserved_usd"] == "0.000000"


def test_hosted_subset_page_mapping_and_legacy_default(tmp_path):
    from evaluation.hosted_r108 import prepare_argv

    source = tmp_path / "selected.pdf"
    source.write_bytes(pdf())
    config = dict(report_year=2025, period_start="2024-01-01", period_end="2024-12-31")
    old = prepare_argv(source, tmp_path / "old", "tenant", config)
    assert "--pipeline-profile" not in old
    argv = prepare_argv(
        source,
        tmp_path / "new",
        "tenant",
        config,
        dict(pages=[2, 4, 5], claim_pages=[4], pipeline_profile="unattended-v1"),
    )
    assert argv[argv.index("--claim-pages") + 1] == "2"


def test_hosted_parse_batches_are_brokered_and_mapped(monkeypatch):
    from io import BytesIO

    from proofops.domain.provenance import canonical_hash
    from proofops_api.hosted_analysis import HostedParseProbe
    from pypdf import PdfReader

    calls = []

    def parse(self, content, *, request_id, mode):
        count = len(PdfReader(BytesIO(content)).pages)
        calls.append((count, request_id))
        return dict(
            model="document-parse-260128",
            raw_response=dict(
                model="document-parse-260128",
                usage=dict(pages=count, standard=list(range(1, count + 1))),
                elements=[dict(page=p) for p in range(1, count + 1)],
            ),
        )

    monkeypatch.setattr(HostedParseProbe, "parse", parse)
    probe = object.__new__(HostedParseProbe)
    response = probe.parse_async(pdf(5), request_id="hs1-parse", mode="standard")
    assert [n for n, _ in calls] == [2, 2, 1]
    assert len({request_id for _, request_id in calls}) == 3
    assert [e["page"] for batch in response["raw_batches"] for e in batch["elements"]] == [
        1,
        2,
        3,
        4,
        5,
    ]
    assert response["response_sha256"] == canonical_hash(response["raw_batches"])


def test_broker_denial_keeps_pipeline_budget_reason():
    from proofops.application.budget import BudgetExceeded
    from proofops_api.hosted_analysis import broker_dispatch

    class Denied:
        def dispatch(self):
            raise HostedError("BUDGET_EXCEEDED")

    with pytest.raises(BudgetExceeded, match="BUDGET_EXHAUSTED"):
        broker_dispatch(Denied())


def test_unattended_hosted_pipeline_publishes_projection(store, settings, monkeypatch):
    import os
    import socket

    from tests.test_hosted_analysis import fake_analysis, source_pdf

    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(
        socket, "create_connection", lambda *a, **k: pytest.fail("unexpected network")
    )
    auth = actor(store)
    doc = store.upload(auth, source_pdf(), "hs1-unattended-upload", now=time.time())
    store.create_run(
        auth, doc["document_id"], [1, 2], "hs1-unattended-run", now=time.time(), auto_scope=True
    )
    done = store.tick(now=time.time(), analysis=fake_analysis)
    assert done["status"] == "completed", done
    assert done["pipeline_profile"] == "unattended-v1"
    result = done["result"]
    assert result["claims"]
    assert not result["reviews"]
    assert all(c["decision"] is None and c["confirmed_grade"] is None for c in result["claims"])
    assert all(
        c["source_status"] and c["provisional_grade"] and c["pipeline_stage"]
        for c in result["claims"]
    )


@pytest.mark.parametrize("provider", ["openai", "openrouter", "parse"])
def test_hosted_budget_denial_survives_provider_sanitization(tmp_path, provider, monkeypatch):
    from proofops.application.budget import BudgetExceeded
    from proofops_api.hosted_analysis import (
        HostedLunaProbe,
        HostedOpenAILunaProbe,
        HostedParseProbe,
    )

    class Denied:
        def dispatch(self, *args, **kwargs):
            raise HostedError("BUDGET_EXCEEDED")

    probe_type = {
        "openai": HostedOpenAILunaProbe,
        "openrouter": HostedLunaProbe,
        "parse": HostedParseProbe,
    }[provider]
    probe = probe_type("dummy-local-test", tmp_path / f"{provider}.sqlite3", store=Denied(), job={})
    with pytest.raises(BudgetExceeded, match="BUDGET_EXHAUSTED"):
        if provider == "parse":
            probe.parse_async(pdf(3), request_id="hs1-budget-denied")
        else:
            probe.complete("test", "{}", request_id="hs1-budget-denied", max_tokens=10)


def test_http_scope_contract_revision_and_default_profile(store, settings):
    from proofops.application.authorization import authorize

    app = create_hosted_app(settings)
    client, h, _, _ = login(app, store)
    doc = client.post(
        "/v1/documents",
        content=pdf(12),
        headers=h | {"Content-Type": "application/pdf", "Idempotency-Key": "hs1-http-upload01"},
    ).json()
    auth = authorize(
        session_id=client.cookies.get("__Host-proofops_session"),
        now=time.time(),
        session_port=store.sessions,
        membership_port=store.memberships,
        required_capability="editor",
    )
    scope = install_plan(store, auth, doc)
    url = f'/v1/documents/{doc["document_id"]}/scope-plan'
    assert client.get(url).headers["ETag"] == '"1"'
    other, _, _, _ = login(app, store)
    assert other.get(url).status_code == 404
    body = dict(selected_claim_pages=[1, 2, 3], selected_evidence_pages=[1, 2, 3, 4])
    assert client.post(url + "/selection", json=body, headers=h).status_code == 428
    edited = client.post(url + "/selection", json=body, headers=h | {"If-Match": '"1"'})
    assert edited.status_code == 200 and edited.headers["ETag"] == '"2"'
    assert (
        client.post(url + "/selection", json=body, headers=h | {"If-Match": '"1"'}).status_code
        == 412
    )
    assert (
        client.post(
            url + "/selection",
            json=body | dict(selected_claim_pages=[True]),
            headers=h | {"If-Match": '"2"'},
        ).status_code
        == 422
    )
    request = dict(
        document_id=doc["document_id"],
        scope_selection_sha256=scope["selection"]["selection_sha256"],
    )
    assert (
        client.post(
            "/v1/runs", json=request, headers=h | {"Idempotency-Key": "hs1-http-run0001"}
        ).status_code
        == 412
    )
    request["scope_selection_sha256"] = edited.json()["selection"]["selection_sha256"]
    accepted = client.post(
        "/v1/runs", json=request, headers=h | {"Idempotency-Key": "hs1-http-run0002"}
    )
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["pipeline_profile"] == "unattended-v1"
    assert accepted.json()["claim_pages"] == [1, 2, 3]
    assert accepted.json()["selected_pages"] == [1, 2, 3, 4]


def test_parse_rejects_page_outside_terminal_single_page_batch(monkeypatch):
    from proofops_api.hosted_analysis import HostedParseProbe

    def invalid(self, *args, **kwargs):
        return dict(
            model="document-parse-260128",
            raw_response=dict(
                model="document-parse-260128",
                usage=dict(pages=1, standard=[1]),
                elements=[dict(page=2)],
            ),
        )

    monkeypatch.setattr(HostedParseProbe, "parse", invalid)
    with pytest.raises(ValueError, match="HOSTED_PARSE_PAGE_INVALID"):
        object.__new__(HostedParseProbe).parse_async(pdf(1), request_id="invalid-page")
