"""HX2 release-path regression: default public profile, real workers, offline replies."""

import io
import json
import os
import socket
import sys
import time
from copy import deepcopy
from types import ModuleType, SimpleNamespace

import pytest
from proofops.adapters.local.claim_source_policies import PAGE_OCR_PROFILES, page_ocr_profile
from proofops.application.analysis_profile import V2_POLICY
from proofops.application.ports.jobs import JobMessage
from proofops.domain.provenance import canonical_hash
from proofops_api.hosted import create_hosted_app
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    IndirectObject,
    NameObject,
    TextStringObject,
)

from deploy.public.offline_fixture import async_parse_replies, fake_llm, fake_page_ocr, source_pdf
from tests.acceptance.test_parsing import TENANT
from tests.integration.test_local_parser_runner import runner_setup
from tests.test_hosted_public import login
from tests.test_hosted_public import settings as _settings


@pytest.fixture
def settings(tmp_path):
    return _settings.__wrapped__(tmp_path)


@pytest.mark.parametrize("profile", PAGE_OCR_PROFILES)
def test_every_registered_native_policy_binds_and_remains_immutable(tmp_path, monkeypatch, profile):
    service, run, _, now, _ = runner_setup(tmp_path, monkeypatch)
    jobs = service.store.jobs
    message = JobMessage(**jobs.pending_outbox(TENANT, run, now=now[0])[0]["message"])
    lease = jobs.claim_job(message, owner="hx2", now=now[0], lease_seconds=60)
    policy = page_ocr_profile(profile).native_policy()
    jobs.bind_parser_native_policy(lease, policy, now=now[0])
    assert jobs.parser_native_policy(message) == policy

    jobs.bind_parser_native_policy(lease, deepcopy(policy), now=now[0])
    with pytest.raises(ValueError, match="NATIVE_PARAGRAPH_POLICY_MISMATCH"):
        jobs.bind_parser_native_policy(lease, policy | {"forged": True}, now=now[0])
    with pytest.raises(ValueError, match="NATIVE_PARAGRAPH_POLICY_MISMATCH"):
        jobs.bind_parser_native_policy(lease, {"mode": "upstage-ocr-page-v99"}, now=now[0])
    assert jobs.parser_native_policy(message) == policy


def test_new_registry_entry_needs_no_separate_native_binding_or_replay_allowlist(
    tmp_path, monkeypatch
):
    from proofops.adapters.local.claim_source_policies import (
        claim_source_reader,
        publication_reader,
    )
    from proofops.adapters.local.run_artifacts import accepted_native_policy_digests

    # Model a future shipped reader without inventing its verification semantics.
    # Only the registry is extended; all native gates must follow automatically.
    name = "proofops.adapters.local.hx2_future_test_reader"
    profile = "upstage-ocr-page-v17"
    module = ModuleType(name)
    policy = page_ocr_profile("upstage-ocr-page-v14").native_policy() | {"mode": profile}
    source_policy = page_ocr_profile("upstage-ocr-page-v14").claim_source_policy() | {
        "profile": profile
    }
    module.native_policy = lambda: policy
    module.claim_source_policy = lambda: source_policy
    monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setitem(PAGE_OCR_PROFILES, profile, name)
    assert claim_source_reader(source_policy) is module
    assert publication_reader(source_policy) is module
    assert canonical_hash(policy) in accepted_native_policy_digests()
    service, run, _, now, _ = runner_setup(tmp_path, monkeypatch)
    jobs = service.store.jobs
    message = JobMessage(**jobs.pending_outbox(TENANT, run, now=now[0])[0]["message"])
    lease = jobs.claim_job(message, owner="hx2-future", now=now[0], lease_seconds=60)
    jobs.bind_parser_native_policy(lease, policy, now=now[0])
    assert jobs.parser_native_policy(message) == policy
    jobs.bind_parser_native_policy(lease, deepcopy(policy), now=now[0])
    with pytest.raises(ValueError, match="NATIVE_PARAGRAPH_POLICY_MISMATCH"):
        jobs.bind_parser_native_policy(lease, policy | {"forged": True}, now=now[0])
    with pytest.raises(ValueError, match="NATIVE_PARAGRAPH_POLICY_MISMATCH"):
        jobs.bind_parser_native_policy(lease, {"mode": "upstage-ocr-page-v99"}, now=now[0])
    assert jobs.parser_native_policy(message) == policy


def test_public_default_upload_binding_parse_extract_tag_publication(
    settings, tmp_path, monkeypatch
):
    import pypdfium2  # Load the host library before the simulated Linux platform.

    from evaluation.hosted_r108 import drive

    assert pypdfium2

    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.delenv("HOSTED_ANALYSIS_PROFILE", raising=False)
    monkeypatch.setenv("PROOFOPS_RB3_HARD_DEADLINE", str(time.monotonic() + 1800))
    # Select the hosted Linux reader without changing the native parser's
    # platform-derived policy hash relative to its isolated child process.
    monkeypatch.setattr(
        "proofops_api.hosted_analysis.sys",
        SimpleNamespace(platform="linux", executable=sys.executable),
    )
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("live network"))
    app = create_hosted_app(settings)
    store = app.state.composition
    client, headers, tenant, _ = login(app, store, role="editor")
    upload = client.post(
        "/v1/documents",
        content=source_pdf(),
        headers=headers
        | {"Content-Type": "application/pdf", "Idempotency-Key": "hx2-upload-01-0000001"},
    )
    assert upload.status_code == 201, upload.text
    document = upload.json()["document_id"]
    accepted = client.post(
        "/v1/runs",
        json={"document_id": document, "selected_pages": [1, 2]},
        headers=headers | {"Idempotency-Key": "hx2-run-01-0000001"},
    )
    assert accepted.status_code == 202, accepted.text
    assert (
        accepted.json()["pipeline_profile"] == client.get("/v1/runtime").json()["pipeline_profile"]
    )
    workspace = tmp_path / "worker"
    workspace.mkdir()
    observed = []

    def offline(store, job, prepared):
        (workspace / "selected.pdf").write_bytes(prepared.read_bytes())
        state, outcome = drive(
            store,
            job,
            workspace,
            dict(report_year=2024, period_start="2024-01-01", period_end="2024-12-31"),
            llm_post=fake_llm,
            parse_post=parse_post,
            ocr_post=fake_page_ocr,
        )
        observed.append(outcome)
        assert outcome["stages"] == [
            dict(stage="parse", outcome="committed"),
            dict(stage="extract", outcome="committed"),
            dict(stage="tag", outcome="completed"),
        ], outcome
        store.publish_analysis(job, state, outcome["status"], outcome["reason"])

    with async_parse_replies() as parse_post:
        done = store.tick(now=time.time(), analysis=offline)
    assert done["status"] == "completed", done
    result = client.get(done["result_url"])
    assert result.status_code == 200, result.text
    data = result.json()
    assert len(data["claims"]) == 2, data
    assert all(c["confirmed_grade"] is None for c in data["claims"])
    assert all(e["state"] == "unknown" for c in data["claims"] for e in c["elements"])
    assert not data["hold_reasons"]
    state = store.document_dir(tenant, document) / "analysis" / done["run_id"]
    manifest = json.loads((state / "pilot.json").read_text())
    assert V2_POLICY["integration_profile"] == "finals-20261017-v29d"
    assert V2_POLICY["parser_failure_policy"] == "s3_partial-v7"
    assert V2_POLICY["located_table_context"]["profile"] == "located-table-context-p2-v1"
    assert manifest["claim_source_profile"] == "i31_claim_source_v1"
    assert manifest["analysis_policy_sha256"] == canonical_hash(V2_POLICY)
    assert manifest["extraction_qc_native_figures"] is True
    saved_settings = json.loads((state / "settings.json").read_text())
    assert saved_settings["extraction_qc_native_figures"] is True
    from proofops.application.tagging.q1_contract import QA2_POLICY

    assert V2_POLICY["structural_quality_policy"] == QA2_POLICY

    from proofops.adapters.local.run_store import LocalSQLiteRunStore

    jobs = LocalSQLiteRunStore(state / "state.sqlite3").jobs
    run = jobs.get_run(tenant, manifest["run_id"])
    message = JobMessage(**run["parse_job"])
    policy = jobs.parser_native_policy(message)
    assert policy == page_ocr_profile(manifest["claim_source_profile"]).native_policy()
    assert json.loads(jobs.read_checkpoint(message))["native_paragraph_policy_sha256"] == (
        canonical_hash(policy)
    )
    snapshot = (state / "result-1.json").read_bytes()
    # W16 and UX1 add read-time data; every frozen result field remains exact.
    frozen = create_hosted_app(settings).state.composition.get_result(tenant, done["run_id"])
    from proofops_api.hosted_ux1 import UX1_POLICY_SHA256

    projected_pipeline = data["pipeline"].copy()
    assert projected_pipeline.pop("ux1_data") == {
        "table_count": 0,
        "table_count_basis": "selected_parser_table_blocks",
        "policy_sha256": UX1_POLICY_SHA256,
    }
    assert "ux1_data" not in frozen["pipeline"]
    comparable = data | {"pipeline": projected_pipeline}
    assert {k: v for k, v in comparable.items() if k not in ("w16_source_document", "claims")} == {
        k: v for k, v in frozen.items() if k != "claims"
    }
    assert [
        {k: v for k, v in c.items() if k != "w16_source_view"} for c in data["claims"]
    ] == frozen["claims"]
    assert data["w16_source_document"]["document_id"] == document
    assert all(c["w16_source_view"]["quote"] == c["quote"] for c in data["claims"])
    assert (state / "result-1.json").read_bytes() == snapshot
    foreign, _, _, _ = login(app, store)
    assert foreign.get(done["result_url"]).status_code == 404


@pytest.mark.parametrize("object_number,accepted", [(0, True), (999, False)])
def test_upload_null_reference_preserves_original_but_missing_live_object_is_rejected(
    settings, object_number, accepted
):
    writer = PdfWriter()
    writer.add_blank_page(300, 300)
    writer.root_object[NameObject("/OptionalMetadata")] = IndirectObject(object_number, 0, writer)
    stream = io.BytesIO()
    writer.write(stream)
    original = stream.getvalue()
    app = create_hosted_app(settings)
    store = app.state.composition
    client, headers, tenant, _ = login(app, store)
    response = client.post(
        "/v1/documents",
        content=original,
        headers=headers
        | {"Content-Type": "application/pdf", "Idempotency-Key": "hx2-null-01-0000001"},
    )
    assert response.status_code == (201 if accepted else 422), response.text
    if accepted:
        directory = store.document_dir(tenant, response.json()["document_id"])
        assert (directory / "original.pdf").read_bytes() == original
        security = json.loads((directory / "upload-security.json").read_text())
        assert security["null_object_references"] == 1
        assert security["original_inspection"] == "complete"
    else:
        assert response.json()["error"]["code"] == "PDF_INVALID"


@pytest.mark.parametrize(
    "target,dangerous,accepted", [(0, False, True), (999, False, False), (0, True, False)]
)
def test_null_internal_navigation_never_bypasses_action_chain_security(
    settings, target, dangerous, accepted
):
    writer = PdfWriter()
    writer.add_blank_page(300, 300)
    action = DictionaryObject(
        {
            NameObject("/S"): NameObject("/GoTo"),
            NameObject("/D"): ArrayObject([IndirectObject(target, 0, writer), NameObject("/Fit")]),
        }
    )
    if dangerous:
        action[NameObject("/Next")] = DictionaryObject(
            {
                NameObject("/S"): NameObject("/JavaScript"),
                NameObject("/JS"): TextStringObject("app.alert('blocked')"),
            }
        )
    writer.root_object[NameObject("/OpenAction")] = action
    stream = io.BytesIO()
    writer.write(stream)
    app = create_hosted_app(settings)
    store = app.state.composition
    client, headers, _, _ = login(app, store)
    response = client.post(
        "/v1/documents",
        content=stream.getvalue(),
        headers=headers
        | {"Content-Type": "application/pdf", "Idempotency-Key": "hx2-goto-0000001"},
    )
    assert response.status_code == (201 if accepted else 422), response.text


def test_manual_page_edit_explicitly_accepts_unknown_without_changing_auto_guard(settings):
    from tests.test_hosted_public import pdf
    from tests.test_hosted_scope import proposal

    app = create_hosted_app(settings)
    store = app.state.composition
    client, headers, tenant, _ = login(app, store)
    doc = client.post(
        "/v1/documents",
        content=pdf(3),
        headers=headers
        | {"Content-Type": "application/pdf", "Idempotency-Key": "hx2-scope-upload001"},
    ).json()
    plan = proposal(doc["sha256"], 3)
    plan["pages"][0]["category"] = "unknown"
    plan["unknown_pages"] = [1]
    plan["pages"][0]["claim_selected"] = False
    plan["pages"][0]["evidence_selected"] = False
    plan["selected_claim_pages"] = [p for p in plan["selected_claim_pages"] if p != 1]
    plan["selected_evidence_pages"] = [p for p in plan["selected_evidence_pages"] if p != 1]
    plan["plan_sha256"] = canonical_hash({k: v for k, v in plan.items() if k != "plan_sha256"})
    path = store.document_dir(tenant, doc["document_id"]) / "scope-000001.json"
    from proofops_api.hosted_scope import scope_selection

    selection = scope_selection(plan, doc["sha256"], 3)
    store._write(path, json.dumps(dict(revision=1, plan=plan, selection=selection)).encode())
    original = path.read_bytes()
    url = f'/v1/documents/{doc["document_id"]}/scope-plan/selection'
    body = dict(selected_claim_pages=[1], selected_evidence_pages=[1, 2])
    edit_headers = headers | {"If-Match": '"1"'}
    assert client.post(url, json=body, headers=edit_headers).status_code == 422
    response = client.post(url, json=body | dict(manual_selection=True), headers=edit_headers)
    assert response.status_code == 200, response.text
    scope = response.json()
    assert scope["selection"]["manual_selection"] is True
    assert scope["plan"]["unknown_pages"] == [1]
    assert scope["plan"]["pages"][0]["category"] == "unknown"
    assert path.read_bytes() == original
    assert client.post(url, json=body, headers=edit_headers).status_code == 412
    response = client.post(
        url,
        json=body | dict(selected_claim_pages=[4], manual_selection=True),
        headers=headers | {"If-Match": '"2"'},
    )
    assert response.status_code == 422


def test_historical_failed_result_has_safe_detail_without_snapshot_rewrite(settings, tmp_path):
    from tests.test_hosted_analysis import job_setup

    store, auth, job = job_setup(settings)
    state = tmp_path / "failed"
    state.mkdir()
    (state / "outcome.json").write_text(
        json.dumps(dict(status="partial_blocked", reason="PARSER_FAILED"))
    )
    store.publish_analysis(job, state, "partial_blocked", "PARSER_FAILED")
    published = store.document_dir(auth.tenant_id, job["document_id"]) / "analysis" / job["run_id"]
    snapshot = (published / "result-1.json").read_bytes()
    result = store.get_result(auth.tenant_id, job["run_id"])
    assert result["hold_reason_details"] == [
        dict(
            code="PARSER_FAILED",
            message=(
                "문서 파싱에 실패해 분석을 중단했습니다. 처리되지 않은 원문은 판정하지 않았습니다. "
                "운영자의 파싱 확인이 필요합니다."
            ),
        )
    ]
    assert result["claims"] == [] and result["confirmed_grade"] is None
    assert (published / "result-1.json").read_bytes() == snapshot
