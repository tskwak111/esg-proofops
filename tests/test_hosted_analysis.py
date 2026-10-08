"""P2 full pipeline with fake HTTP and unchanged source/review validation."""

import io
import json
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pdfplumber
import pytest
from proofops.adapters.local.openrouter import MODEL
from proofops_api.hosted import create_hosted_app
from proofops_api.hosted_analysis import HostedLunaProbe
from proofops_api.hosted_store import HostedError, HostedStore
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from tests.test_hosted_public import actor, login, uploaded
from tests.test_hosted_public import settings as _settings


@pytest.fixture
def settings(tmp_path):
    return _settings.__wrapped__(tmp_path)


TEXT = "Acme reduced energy use by 20 percent in 2024."


def source_pdf():
    writer = PdfWriter()
    for number in range(2):
        page = writer.add_blank_page(600, 400)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 16 Tf 40 250 Td ({TEXT}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def fake_parse(content, mode):
    elements = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            elements.append(
                dict(
                    id=i,
                    page=i,
                    category="paragraph",
                    coordinates=[
                        dict(x=x, y=y)
                        for x, y in ((0.05, 0.30), (0.95, 0.30), (0.95, 0.45), (0.05, 0.45))
                    ],
                    content=dict(text=TEXT, html=f"<p>{TEXT}</p>"),
                )
            )
    return dict(
        model="document-parse-260128",
        usage={"pages": len(elements), mode: list(range(1, len(elements) + 1))},
        elements=elements,
    )


def fake_llm(body):
    user = json.loads(body["messages"][1]["content"])
    data = user["untrusted_document_data"]
    if "source_sentences" in data:
        payload = dict(sentence_ids=[s["sentence_id"] for s in data["source_sentences"]])
    elif user.get("schema") == "source-relations-occurrence-v3":
        payload = dict(
            relations=[
                dict(
                    source_index=s["source_index"],
                    dimensions=dict(entity=None, metric=None, reporting_period=None),
                )
                for s in data["sources"]
            ]
        )
    elif "allowed_elements" in data:
        payload = dict(
            claim_id=user["claim_id"],
            packet_sha256=user["packet_sha256"],
            replicate_id=user["replicate_id"],
            track="performance",
            safe_harbor_category=None,
            elements=[
                dict(
                    element_id=e,
                    state="unknown",
                    evidence_refs=[],
                    normalized_value=None,
                    credited_from=None,
                    reason_code="fixture_unresolved",
                )
                for e in data["allowed_elements"]
            ],
            superlative_quote=None,
            warnings=[],
        )
    else:
        payload = dict(
            claim_id=user["claim_id"],
            track="performance",
            safe_harbor_category=None,
            track_confidence=1,
            dimensions=dict(entity=None, metric=None, reporting_period=None),
        )
    return dict(
        id=str(uuid4()),
        model=MODEL,
        usage=dict(prompt_tokens=20, completion_tokens=10, cost=0.00001),
        choices=[dict(finish_reason="stop", message=dict(content=json.dumps(payload)))],
    )


def fake_analysis(store, job, prepared):
    from evaluation.hosted_r108 import drive

    with TemporaryDirectory() as scratch:
        workspace = Path(scratch)
        (workspace / "selected.pdf").write_bytes(prepared.read_bytes())
        saved_env = os.environ.copy()
        state, outcome = drive(
            store,
            job,
            workspace,
            dict(report_year=2025, period_start="2024-01-01", period_end="2024-12-31"),
            llm_post=fake_llm,
            parse_post=fake_parse,
        )
        os.environ.clear()
        os.environ.update(saved_env)
        store.publish_analysis(job, state, outcome["status"], outcome["reason"])


def test_fake_full_chain_upload_run_result_review_delete(settings, monkeypatch):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(
        socket, "create_connection", lambda *a, **k: pytest.fail("unexpected network")
    )
    app = create_hosted_app(settings)
    store = app.state.composition
    client, h, tenant, user = login(app, store, role="editor")
    response = client.post(
        "/v1/documents",
        content=source_pdf(),
        headers=h | {"Content-Type": "application/pdf", "Idempotency-Key": "p2-upload-00000001"},
    )
    assert response.status_code == 201, response.text
    document = response.json()["document_id"]
    accepted = client.post(
        "/v1/runs",
        json=dict(document_id=document),
        headers=h | {"Idempotency-Key": "p2-run-000000001"},
    )
    assert accepted.status_code == 202, accepted.text
    run = accepted.json()
    assert run["queue_position"] == 1 and run["progress"] == 0
    done = store.tick(now=time.time(), analysis=fake_analysis)
    assert done["status"] in ("completed", "partial_blocked"), done
    result = client.get(done["result_url"])
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["schema"] == "r108-hosted-result-v1"
    assert len(data["claims"]) == 2, data
    assert data["pipeline"]["stages"][-1]["stage"] == "tag", data
    assert data["reviews"], data
    assert all(e["state"] == "unknown" for c in data["claims"] for e in c["elements"])
    assert all(c["confirmed_grade"] is None for c in data["claims"])
    review = data["reviews"][0]
    result_path = store.document_dir(tenant, document) / "analysis" / run["run_id"]
    initial_snapshot = (result_path / "result-1.json").read_bytes()
    claim = next(c for c in data["claims"] if c["claim_id"] == review["claim_id"])
    body = dict(
        base_tag_revision=review["base_tag_revision"],
        track="performance",
        elements=claim["elements"],
        reason="Human verified unresolved evidence",
    )
    url = f"/v1/runs/{run['run_id']}/reviews/{review['review_id']}/resolve"
    assert client.post(url, json=body, headers=h).status_code == 403
    reviewer, rh, _, _ = login(app, store, tenant=tenant, role="reviewer")
    resolved = reviewer.post(
        url,
        json=body,
        headers=rh
        | {"If-Match": f'"{review["revision"]}"', "Idempotency-Key": "p2-review-00000001"},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["decision"]["review_status"] == "human_confirmed"
    assert (result_path / "result-1.json").read_bytes() == initial_snapshot
    assert (result_path / "result-2.json").is_file()
    foreign, fh, _, _ = login(app, store)
    assert foreign.get(done["result_url"]).status_code == 404
    assert foreign.post(url, json=body, headers=fh).status_code == 404
    restart = create_hosted_app(settings)
    with monkeypatch.context() as no_replay:
        no_replay.setattr(
            "proofops_api.hosted_results.read_result", lambda *a: pytest.fail("GET source replay")
        )
        refreshed = restart.state.composition.get_result(tenant, run["run_id"])
    reviewed = next(c for c in refreshed["claims"] if c["claim_id"] == claim["claim_id"])
    assert reviewed["decision"]["review_status"] == "human_confirmed"
    originals = list(
        store.document_dir(tenant, document).glob("analysis/*/objects/original/*/*.pdf")
    )
    originals = [p for p in originals if p.name.count(".") == 1]
    assert originals
    original_bytes = originals[0].read_bytes()
    originals[0].chmod(0o600)
    originals[0].write_bytes(b"tampered source")
    assert client.get(done["result_url"]).status_code == 409
    originals[0].write_bytes(original_bytes)
    originals[0].chmod(0o400)
    deleted = client.post(
        f"/v1/documents/{document}/deletion-requests",
        json=dict(reason="Uploader requested deletion"),
        headers=h | {"Idempotency-Key": "p2-delete-00000001"},
    )
    assert deleted.status_code == 202 and deleted.json()["status"] == "completed", deleted.text
    assert client.get(done["result_url"]).status_code == 404
    assert not store.document_dir(tenant, document).exists()


def test_hosted_review_accepts_json_source_refs(settings, monkeypatch):
    app = create_hosted_app(settings)
    store = app.state.composition
    client, headers, tenant, _ = login(app, store)
    run, review = str(uuid4()), str(uuid4())
    ref = dict(
        source_id=str(uuid4()),
        document_version_id=str(uuid4()),
        parse_manifest_id=str(uuid4()),
        page_num=1,
        printed_page_label=None,
        bbox=[1.0, 2.0, 3.0, 4.0],
        raw_text_sha256="a" * 64,
        quote="verified source",
        char_start=0,
        char_end=15,
        location_quality="located",
        verification_state="verified",
    )
    body = dict(
        base_tag_revision=1,
        track="management",
        elements=[
            dict(
                element_id="M1",
                state="present",
                evidence_refs=[ref],
                normalized_value=None,
                credited_from=None,
                reason_code=None,
            )
        ],
        reason="P5 rehearsal with a JSON source citation",
    )
    observed = []

    def resolve(auth, run_id, review_id, parsed, if_match, key):
        assert auth.tenant_id == tenant
        observed.append(parsed)
        return {"validated": True}

    monkeypatch.setattr(store, "resolve_review", resolve)
    response = client.post(
        f"/v1/runs/{run}/reviews/{review}/resolve",
        json=body,
        headers=headers | {"If-Match": '"1"', "Idempotency-Key": "p5-source-review-001"},
    )
    assert response.status_code == 200, response.text
    assert observed == [body]
    body["elements"][0]["evidence_refs"][0]["page_num"] = "1"
    assert (
        client.post(
            f"/v1/runs/{run}/reviews/{review}/resolve",
            json=body,
            headers=headers,
        ).status_code
        == 422
    )
    assert len(observed) == 1


def job_setup(settings):
    store = HostedStore(settings)
    auth = actor(store)
    doc = uploaded(store, auth)
    store.create_run(auth, doc["document_id"], None, "p2-run-broker-001", now=time.time())
    return store, auth, store.claim(now=time.time())


def test_each_schema_retry_reserved_and_broker_limit(settings, tmp_path):
    store, auth, job = job_setup(replace(settings, run_usd=Decimal(".02")))
    calls = []

    def invalid(body):
        calls.append(body)
        return dict(
            id=str(uuid4()),
            model=MODEL,
            usage=dict(prompt_tokens=20, completion_tokens=10, cost=0.01),
            choices=[dict(finish_reason="stop", message=dict(content="not json"))],
        )

    probe = HostedLunaProbe("fake", tmp_path / "luna.db", store=store, job=job, post=invalid)
    with pytest.raises(ValueError):
        probe.complete("test", "{}", request_id="schema-retry")
    assert len(calls) == 1  # .01 settled + .011 next bound exceeds .02
    assert store.get_run(auth.tenant_id, job["run_id"])["status"] == "running"
    with store.transaction() as db:
        assert db.execute("SELECT count(*) FROM deletion.costs").fetchone()[0] == 1
    store.finish(job, "partial_blocked", now=time.time())
    assert store.budget_totals()["event_reserved_usd"] == "0.010000"


def test_cancel_during_paid_call_settles_without_publication(settings, tmp_path):
    store, auth, job = job_setup(settings)

    def cancel(body):
        store.cancel(auth, job["run_id"], now=time.time())
        return dict(id="cancel-call", model=MODEL, usage=dict(cost=0.001))

    probe = HostedLunaProbe("fake", tmp_path / "luna.db", store=store, job=job, post=cancel)
    probe._post(probe.request_body("x", "{}", request_id="x"))
    with pytest.raises(HostedError, match="LEASE_LOST"):
        store.update_progress(job, "tag", 75)
    assert store.budget_totals()["event_reserved_usd"] == "0.001000"


def test_unknown_dispatch_restart_no_redelivery(settings, tmp_path):
    store, auth, job = job_setup(settings)

    def unknown(body):
        raise TimeoutError("unknown transport")

    probe = HostedLunaProbe("fake", tmp_path / "luna.db", store=store, job=job, post=unknown)
    with pytest.raises(TimeoutError):
        probe._post(probe.request_body("x", "{}", request_id="x"))
    restarted = HostedStore(settings)
    assert restarted.claim(now=time.time() + 1000) is None
    assert restarted.get_run(auth.tenant_id, job["run_id"])["status"] == "accounting_pending"
    assert restarted.budget_totals()["event_reserved_usd"] == "0.500000"


@pytest.mark.parametrize("reader", ["upstage-ocr-page-v1", "upstage-ocr-page-v2"])
def test_linux_reader_explicitly_unresolved_without_dispatch(
    settings, tmp_path, monkeypatch, reader
):
    from proofops_api.hosted_analysis import execute_analysis

    for name in ("luna.key", "upstage.key"):
        (tmp_path / name).write_text("test-only")
    config = tmp_path / "operator.json"
    config.write_text(
        json.dumps(
            dict(
                enabled=True,
                openrouter_key_file=str(tmp_path / "luna.key"),
                upstage_key_file=str(tmp_path / "upstage.key"),
                report_year=2025,
                period_start="2024-01-01",
                period_end="2024-12-31",
                **(
                    dict(
                        analysis_profile="r108-finals-candidate",
                        rendered_reader_profile=reader,
                        rendered_reader_gate_passed=True,
                    )
                    if reader
                    else {}
                ),
            )
        )
    )
    configured = replace(settings, live_disabled=False, live_config=config)
    store, auth, job = job_setup(configured)
    prepared = store.prepare(job, now=time.time())
    monkeypatch.setattr("proofops_api.hosted_analysis.sys.platform", "linux")
    execute_analysis(store, job, prepared)
    result = store.get_result(auth.tenant_id, job["run_id"])
    assert result["hold_reasons"] == ["LINUX_SOURCE_READER_UNRESOLVED"]
    assert not result["claims"] and result["confirmed_grade"] is None
    assert store.budget_totals()["event_reserved_usd"] == "0.000000"
    assert result["pipeline"]["profiles"]["rendered_reader_requested"] == reader


@pytest.mark.parametrize("method", ["get_run", "get_result"])
@pytest.mark.parametrize("delete", [False, True])
def test_source_replay_releases_control_writer_and_rechecks_deletion(
    settings, monkeypatch, tmp_path, method, delete
):
    store, auth, job = job_setup(settings)
    source = tmp_path / "published"
    source.mkdir()
    monkeypatch.setattr("proofops_api.hosted_results.read_result", lambda *a: {"claims": []})
    store.publish_analysis(job, source, "partial_blocked", "R108_NEEDS_REVIEW")
    entered, release = threading.Event(), threading.Event()

    def replay(*args):
        entered.set()
        assert release.wait(5)
        return {"claims": []}

    monkeypatch.setattr(store, "_result", replay)
    with ThreadPoolExecutor(2) as pool:
        reading = pool.submit(getattr(store, method), auth.tenant_id, job["run_id"])
        assert entered.wait(2)
        try:
            if delete:
                writing = pool.submit(
                    store.delete_document,
                    auth,
                    job["document_id"],
                    "p5-replay-deletion-001",
                    now=time.time(),
                )
                # Tombstone commits immediately; active source lease prevents unlink.
                assert writing.result(timeout=1)["status"] == "failed"
            else:
                writing = pool.submit(store.invite, str(uuid4()), "other", "admin", now=time.time())
                assert writing.result(timeout=1)
        finally:
            release.set()
        if delete:
            with pytest.raises(HostedError, match="RESOURCE_NOT_FOUND"):
                reading.result(timeout=2)
            assert (
                store.delete_document(
                    auth, job["document_id"], "p5-replay-deletion-001", now=time.time()
                )["status"]
                == "completed"
            )
        else:
            result = reading.result(timeout=2)
            assert (result["result"] if method == "get_run" else result) == {"claims": []}


def test_purge_fences_but_waits_for_working_source_lock(settings):
    import fcntl

    store, auth, job = job_setup(settings)
    path = store.document_dir(auth.tenant_id, job["document_id"])
    with (path / "analysis.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        deleted = store.delete_document(
            auth, job["document_id"], "p2-lock-delete-01", now=time.time()
        )
        assert deleted["status"] == "failed"
        with pytest.raises(HostedError, match="RESOURCE_NOT_FOUND"):
            store.get_run(auth.tenant_id, job["run_id"])
        with pytest.raises(HostedError):
            store.dispatch(
                job,
                "fake",
                "late",
                "a" * 64,
                Decimal(".01"),
                lambda r: pytest.fail("late dispatch"),
                now=time.time(),
            )
    store.replay_deletions(now=time.time())
    assert not path.exists()


def test_nonowner_same_tenant_cannot_delete(settings):
    app = create_hosted_app(settings)
    store = app.state.composition
    owner, h, tenant, _ = login(app, store, role="editor")
    uploaded = owner.post(
        "/v1/documents",
        content=source_pdf(),
        headers=h | {"Content-Type": "application/pdf", "Idempotency-Key": "p2-owner-upload01"},
    ).json()
    other, oh, _, _ = login(app, store, tenant=tenant, role="editor")
    response = other.post(
        f'/v1/documents/{uploaded["document_id"]}/deletion-requests',
        json=dict(reason="Unauthorized deletion"),
        headers=oh | {"Idempotency-Key": "p2-other-delete01"},
    )
    assert response.status_code == 403
    assert owner.get(f'/v1/documents/{uploaded["document_id"]}').status_code == 200


def test_schema_retry_both_attempts_reserved(settings, tmp_path):
    store, auth, job = job_setup(settings)
    calls = []

    def post(body):
        calls.append(body)
        return dict(
            id=str(uuid4()),
            model=MODEL,
            usage=dict(prompt_tokens=20, completion_tokens=10, cost=0.00001),
            choices=[
                dict(
                    finish_reason="stop",
                    message=dict(content="invalid" if len(calls) == 1 else "{}"),
                )
            ],
        )

    probe = HostedLunaProbe("fake", tmp_path / "retry.db", store=store, job=job, post=post)
    probe.complete("x", "{}", request_id="retry-two")
    with store.transaction() as db:
        assert (
            db.execute('SELECT count(*) FROM deletion.costs WHERE status="settled"').fetchone()[0]
            == 2
        )
