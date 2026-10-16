"""RC1 publication reuse: no real provider transport, durable tenant isolation."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from proofops.domain.provenance import canonical_hash
from proofops_api.hosted import create_hosted_app
from proofops_api.hosted_analysis import default_analysis_profile
from proofops_api.hosted_store import HostedError, HostedStore

from tests.test_hosted_public import actor, login, pdf
from tests.test_hosted_public import settings as base_settings


@pytest.fixture
def store(tmp_path):
    settings = base_settings.__wrapped__(tmp_path)
    config = tmp_path / "operator.json"
    config.write_text(
        json.dumps(dict(report_year=2025, period_start="2025-01-01", period_end="2025-12-31"))
    )
    return HostedStore(replace(settings, rc1_reuse_enabled=True, live_config=config))


def create(store, auth, content=None, *, key="rc1-create-key-0001", **kwargs):
    doc = store.upload(auth, content or pdf(), key + "-upload", now=time.time())
    return store.create_run(
        auth,
        doc["document_id"],
        [1],
        key,
        now=time.time(),
        auto_scope=True,
        pipeline_profile=default_analysis_profile(),
        **kwargs,
    )


def seal(store, auth, run, *, status="completed", claims=True, ready=True):
    """A control-DB anchored synthetic publication, not evidence/model-quality validation."""
    directory = store.document_dir(auth.tenant_id, run["document_id"]) / "analysis" / run["run_id"]
    directory.mkdir(parents=True)
    pages = run["selected_pages"]
    result = dict(
        schema="r108-hosted-result-v1",
        page_map=pages,
        reviews=[],
        hold_reasons=[],
        pipeline=dict(
            status=status,
            scope=store.run_options(
                dict(
                    tenant_id=auth.tenant_id,
                    document_id=run["document_id"],
                    run_id=run["run_id"],
                    pages=json.dumps(pages),
                )
            ),
            reporting_scope=dict(
                report_year=2025, period_start="2025-01-01", period_end="2025-12-31"
            ),
        ),
        claims=[
            dict(
                claim_id="private-claim",
                tenant_id=auth.tenant_id,
                quote="Published PDF claim",
                page_num=1,
                source_refs=[],
                confirmed_grade=None,
            )
        ]
        if claims
        else [],
    )
    content = json.dumps(
        dict(tenant_id=auth.tenant_id, page_map=pages, source_hashes={}, result=result)
    ).encode()
    with store.transaction() as db:
        store._publish_snapshot(db, run["run_id"], directory, content)
        db.execute("UPDATE runs SET status=? WHERE run_id=?", (status, run["run_id"]))
        db.execute(
            "INSERT INTO run_progress VALUES (?,'result',100,?)", (run["run_id"], int(ready))
        )
        store._settle_envelope(db, run["run_id"])
    return directory


def test_same_pdf_free_reuse_is_durable_and_source_immutable(store):
    owner = actor(store)
    first = create(store, owner)
    source = seal(store, owner, first)
    before = (source / "result-1.json").read_bytes()
    totals = store.budget_totals()
    # Cache must bypass both daily-count and budget admission, even after restart.
    cold = HostedStore(replace(store.settings, daily_runs=1, user_daily_runs=1))
    second = create(cold, owner, key="rc1-second-key-0001")
    assert second["status"] == "completed"
    reuse = second["result"]["reuse"]
    assert reuse["reused"] and reuse["analyzed_at"] and reuse["cost_usd"] == "0.000000"
    assert reuse["provider_calls"] == 0
    assert second["run_id"] != first["run_id"]
    assert second["document_id"] != first["document_id"]
    assert cold.budget_totals() == totals
    assert (source / "result-1.json").read_bytes() == before
    assert cold.claim(now=time.time()) is None
    with cold.transaction(readonly=True) as db:
        audit = db.execute(
            "SELECT * FROM rc1_reuse_audit WHERE run_id=?", (second["run_id"],)
        ).fetchone()
        assert audit["source_run_id"] == first["run_id"]
        assert db.execute("SELECT count(*) FROM deletion.spend").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM deletion.costs").fetchone()[0] == 0


@pytest.mark.parametrize(
    "status,claims,ready",
    [
        ("failed", True, True),
        ("running", True, True),
        ("completed", False, True),
        ("partial_blocked", False, True),
        ("completed", True, False),
    ],
)
def test_ineligible_publications_are_not_reused(store, status, claims, ready):
    owner = actor(store)
    seal(store, owner, create(store, owner), status=status, claims=claims, ready=ready)
    assert create(store, owner, key="rc1-ineligible-new-01")["status"] == "queued"


@pytest.mark.parametrize("change", ["pdf", "policy", "period", "pages", "scope"])
def test_cache_identity_changes_miss(store, change):
    owner = actor(store)
    first = create(store, owner)
    seal(store, owner, first)
    if change in {"policy", "pages", "scope"}:
        options_path = (
            store.document_dir(owner.tenant_id, first["document_id"])
            / f'{first["run_id"]}.options.json'
        )
        options = json.loads(options_path.read_text())
        options.pop("sha256")
        if change == "policy":
            options["analysis_profile_sha256"] = "0" * 64
        elif change == "pages":
            options["claim_pages"] = [2]
        else:
            options["scope_policy_sha256"] = "0" * 64
        options["sha256"] = canonical_hash(options)
        options_path.write_text(json.dumps(options))
    elif change == "period":
        store.settings.live_config.write_text(
            json.dumps(dict(report_year=2024, period_start="2024-01-01", period_end="2024-12-31"))
        )
    second = create(store, owner, pdf(4) if change == "pdf" else None, key="rc1-new-identity-0001")
    assert second["status"] == "queued"


def test_cross_tenant_reuse_is_independent_and_private(store):
    owner, other = actor(store), actor(store)
    first = create(store, owner)
    seal(store, owner, first, status="partial_blocked")
    second = create(store, other, key="rc1-cross-tenant-0001")
    assert second["status"] == "partial_blocked"
    public = json.dumps(second)
    for secret in (owner.tenant_id, owner.user_sub, first["run_id"], first["document_id"]):
        assert secret not in public
    assert second["result"]["claims"][0]["tenant_id"] == other.tenant_id
    store.delete_document(owner, first["document_id"], "rc1-delete-source-01", now=time.time())
    assert store.get_result(other.tenant_id, second["run_id"])["claims"]
    with pytest.raises(HostedError, match="RESOURCE_NOT_FOUND"):
        store.get_result(owner.tenant_id, second["run_id"])


def test_concurrent_uploads_and_idempotency(store):
    owner = actor(store)
    seal(store, owner, create(store, owner))
    with ThreadPoolExecutor(4) as pool:
        results = list(
            pool.map(lambda i: create(store, owner, key=f"rc1-parallel-key-{i:04}"), range(4))
        )
    assert all(r["result"]["reuse"]["reused"] for r in results)
    assert len({r["run_id"] for r in results}) == 4
    with ThreadPoolExecutor(2) as pool:
        repeated = list(
            pool.map(lambda _: create(store, owner, key="rc1-parallel-key-0000"), range(2))
        )
    assert all(r["run_id"] == results[0]["run_id"] for r in repeated)
    with store.transaction(readonly=True) as db:
        assert db.execute("SELECT count(*) FROM rc1_reuse_audit").fetchone()[0] == 4


def test_tampered_originals_and_snapshot_fail_closed(store):
    owner = actor(store)
    first = create(store, owner)
    source = seal(store, owner, first)
    original = store.document_dir(owner.tenant_id, first["document_id"]) / "original.pdf"
    original.chmod(0o600)
    original.write_bytes(b"tamper")
    assert create(store, owner, key="rc1-bad-source-key01")["status"] == "queued"
    original.write_bytes(pdf())
    snapshot = source / "result-1.json"
    snapshot.chmod(0o600)
    snapshot.write_bytes(b"{}")
    assert create(store, owner, key="rc1-bad-snapshot-key01")["status"] == "queued"
    doc = store.upload(owner, pdf(), "rc1-target-tamper-01", now=time.time())
    target = store.document_dir(owner.tenant_id, doc["document_id"]) / "original.pdf"
    target.chmod(0o600)
    target.write_bytes(b"tamper")
    with pytest.raises(HostedError, match="UPLOAD_INTEGRITY_MISMATCH"):
        store.create_run(
            owner,
            doc["document_id"],
            [1],
            "rc1-tampered-run001",
            now=time.time(),
            pipeline_profile=default_analysis_profile(),
        )


def test_force_fresh_admin_only_and_default_disabled(store):
    owner = actor(store)
    seal(store, owner, create(store, owner))
    assert create(store, owner, key="rc1-force-fresh-0001", force_fresh=True)["status"] == "queued"
    disabled = HostedStore(replace(store.settings, rc1_reuse_enabled=False))
    assert create(disabled, owner, key="rc1-disabled-key-001")["status"] == "queued"
    app = create_hosted_app(store.settings)
    client, headers, _, _ = login(app, store, tenant=owner.tenant_id, role="editor")
    doc = store.upload(owner, pdf(), "rc1-force-http-0001", now=time.time())
    response = client.post(
        "/v1/runs",
        headers=headers | {"Idempotency-Key": "rc1-force-http-0001"},
        json=dict(document_id=doc["document_id"], selected_pages=[1], force_fresh=True),
    )
    assert response.status_code == 403
    assert TestClient(app).post("/v1/runs", json={}).status_code == 401


def test_copy_preserves_domain_ids_and_removes_account_metadata(store):
    from uuid import uuid4

    from proofops_api.hosted_reuse import _private_copy

    owner, other = actor(store), actor(store)
    old = dict(tenant_id=owner.tenant_id, document_id=str(uuid4()), run_id=str(uuid4()))
    original = dict(
        claims=[
            dict(
                claim_id="private-claim",
                tenant_id=owner.tenant_id,
                topic_ids=["emissions", "energy"],
                element_id="G2",
                rule_id="goal-rule-v1",
                quote="Exact PDF quote",
                decision=dict(evidence_grade="E1", label="INCOMPLETE"),
                source_refs=[dict(source_id="private-source", verification_state="verified")],
                user_sub=owner.user_sub,
                user_hash=store.user_hash(owner.user_sub),
                w16_source_view=dict(
                    refs=[dict(source_id="private-source", ref_id="source_refs/0")]
                ),
            )
        ],
        reviews=[dict(review_id="private-review", created_by=owner.user_sub)],
        pipeline=dict(workspace="/private/workspace"),
    )
    copied = _private_copy(original, old, other, str(uuid4()), str(uuid4()))
    claim = copied["claims"][0]
    for key in ("topic_ids", "element_id", "rule_id", "quote", "decision"):
        assert claim[key] == original["claims"][0][key]
    assert claim["source_refs"][0]["source_id"] == claim["w16_source_view"]["refs"][0]["source_id"]
    assert claim["w16_source_view"]["refs"][0]["ref_id"] == "source_refs/0"
    serialized = json.dumps(copied)
    for secret in (
        owner.tenant_id,
        owner.user_sub,
        store.user_hash(owner.user_sub),
        "private-claim",
        "private-source",
        "private-review",
        "/private/workspace",
    ):
        assert secret not in serialized


def test_new_assigned_policy_and_later_human_revision_are_not_borrowed(store):
    from proofops.application.analysis_profile import FINALS_I26_POLICY

    owner, other = actor(store), actor(store)
    first = create(store, owner)
    path = seal(store, owner, first)
    initial = (path / "result-1.json").read_bytes()
    revised = json.loads(initial)
    revised["result"]["claims"][0]["quote"] = "private human correction"
    revised["result"]["claims"][0]["resolved_by"] = owner.user_sub
    with store.transaction() as db:
        store._publish_snapshot(db, first["run_id"], path, json.dumps(revised).encode())
    reused = create(store, other, key="rc1-before-policy-change")
    assert reused["result"]["claims"][0]["quote"] == "Published PDF claim"
    assert (path / "result-1.json").read_bytes() == initial
    config = json.loads(store.settings.live_config.read_text())
    config["analysis_policy_sha256"] = canonical_hash(FINALS_I26_POLICY)
    store.settings.live_config.write_text(json.dumps(config))
    changed = create(store, other, key="rc1-after-policy-change")
    assert changed["status"] == "queued" and changed["result"] is None


def test_coordinate_contention_retries_without_spend_or_freezing_missing_geometry(
    store, monkeypatch
):
    from proofops_api import hosted_source_view

    owner = actor(store)
    seal(store, owner, create(store, owner))
    totals = store.budget_totals()
    original = hosted_source_view.project_source_view

    def busy(reads, row, doc, result, **kwargs):
        return result | dict(
            claims=[dict(w16_source_view=dict(refs=[dict(w18_reason="coordinate_busy")]))]
        )

    monkeypatch.setattr(hosted_source_view, "project_source_view", busy)
    with pytest.raises(HostedError, match="REUSE_COORDINATES_BUSY") as error:
        create(store, owner, key="rc1-coordinate-retry")
    assert error.value.status == 429 and error.value.retry_after == 2
    assert store.budget_totals() == totals
    monkeypatch.setattr(hosted_source_view, "project_source_view", original)
    assert create(store, owner, key="rc1-coordinate-retry")["result"]["reuse"]["reused"]


def test_offline_pipeline_copy_keeps_w16_w18_coordinates_and_pdf(store, monkeypatch, tmp_path):
    import os
    import socket
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from proofops_api import hosted_analysis

    from deploy.public.offline_fixture import (
        async_parse_replies,
        fake_llm,
        fake_page_ocr,
        source_pdf,
    )
    from evaluation.hosted_r108 import drive

    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setenv("PROOFOPS_RB3_HARD_DEADLINE", str(time.monotonic() + 1800))
    monkeypatch.setattr(hosted_analysis.sys, "platform", "linux")
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("no network"))
    owner = actor(store)
    first = create(store, owner, source_pdf())

    def analyze(store, job, prepared):
        with TemporaryDirectory() as scratch, async_parse_replies() as parse_post:
            workspace = Path(scratch)
            (workspace / "selected.pdf").write_bytes(prepared.read_bytes())
            state, outcome = drive(
                store,
                job,
                workspace,
                json.loads(store.settings.live_config.read_text()),
                llm_post=fake_llm,
                parse_post=parse_post,
                ocr_post=fake_page_ocr,
            )
            store.publish_analysis(job, state, outcome["status"], outcome["reason"])

    done = store.tick(now=time.time(), analysis=analyze)
    assert done["result_url"] and done["result"]["claims"], done
    app = create_hosted_app(store.settings)
    client, headers, tenant, _ = login(app, store)
    source_client, *_ = login(app, store, tenant=owner.tenant_id)
    original_view = source_client.get(
        first["result_url"] or f'/v1/runs/{first["run_id"]}/result', params={"w18": True}
    ).json()
    expected = original_view["claims"][0]["w16_source_view"]["refs"][0]
    assert expected["location"] and expected["w18_line_rects"]
    budget = store.budget_totals()
    start = time.perf_counter()
    upload = client.post(
        "/v1/documents",
        headers=headers
        | {"Idempotency-Key": "rc1-http-upload-001", "Content-Type": "application/pdf"},
        content=source_pdf(),
    )
    assert upload.status_code == 201, upload.text
    doc = upload.json()
    response = client.post(
        "/v1/runs",
        headers=headers | {"Idempotency-Key": "rc1-http-run-0001"},
        json=dict(document_id=doc["document_id"], selected_pages=[1]),
    )
    assert response.status_code == 202, response.text
    run = response.json()
    assert run["result"]["reuse"]["reused"], run
    view = client.get(run["result_url"], params={"w18": True})
    assert view.status_code == 200, view.text
    elapsed = time.perf_counter() - start
    print(f"RC1 upload-to-result seconds: {elapsed:.3f}")
    copied = view.json()
    actual = copied["claims"][0]["w16_source_view"]["refs"][0]
    for field in ("location", "w18_line_rects", "w18_cell_rects", "w18_coordinates"):
        assert actual[field] == expected[field]
    assert actual["source_id"] == copied["claims"][0]["source_refs"][0]["source_id"]
    assert client.get(copied["w16_source_document"]["url"]).content == source_pdf()
    for secret in (owner.tenant_id, owner.user_sub, first["run_id"], first["document_id"]):
        assert secret not in view.text
    assert store.budget_totals() == budget
    store.delete_document(owner, first["document_id"], "rc1-real-delete-001", now=time.time())
    cold_client = TestClient(create_hosted_app(store.settings), base_url="https://api.example.com")
    cold_client.cookies.update(client.cookies)
    assert cold_client.get(run["result_url"] + "?w18=true").json() == copied
    original = store.document_dir(tenant, doc["document_id"]) / "original.pdf"
    original.chmod(0o600)
    original.write_bytes(b"tamper")
    assert cold_client.get(run["result_url"]).status_code == 409


def test_automatic_scope_hash_is_portable_but_selection_changes_miss(store):
    from proofops_api.hosted_scope import scope_selection

    from tests.test_hosted_scope import proposal

    def auto(owner, key):
        doc = store.upload(owner, pdf(5), key + "-upload", now=time.time())
        plan = proposal(doc["sha256"], 5)
        plan["source_path"] = f'{owner.tenant_id}/{doc["document_id"]}/original.pdf'
        plan["plan_sha256"] = canonical_hash({k: v for k, v in plan.items() if k != "plan_sha256"})
        period = json.loads(store.settings.live_config.read_text())
        selection = scope_selection(plan, doc["sha256"], 5, reporting_scope=period)
        scope = dict(revision=1, plan=plan, selection=selection, reporting_scope=period)
        store._write(
            store.document_dir(owner.tenant_id, doc["document_id"]) / "scope-000001.json",
            json.dumps(scope).encode(),
        )
        run = store.create_run(
            owner,
            doc["document_id"],
            None,
            key,
            now=time.time(),
            auto_scope=True,
            scope_selection_sha256=selection["selection_sha256"],
            pipeline_profile=default_analysis_profile(),
        )
        return run, selection

    owner, other = actor(store), actor(store)
    first, selection1 = auto(owner, "rc1-autoscope-first")
    seal(store, owner, first)
    second, selection2 = auto(other, "rc1-autoscope-other")
    assert selection1["selection_sha256"] != selection2["selection_sha256"]
    assert second["result"]["reuse"]["reused"]
    changed = store.edit_scope(other, second["document_id"], [1], [1, 2], '"1"')
    run = store.create_run(
        other,
        second["document_id"],
        None,
        "rc1-changed-selection",
        now=time.time(),
        auto_scope=True,
        scope_selection_sha256=changed["selection"]["selection_sha256"],
        pipeline_profile=default_analysis_profile(),
    )
    assert run["status"] == "queued"
