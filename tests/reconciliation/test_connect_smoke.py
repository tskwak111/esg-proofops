"""D06: an operator-created case (D05) driven through the real HTTP product surface.

The case comes from a real reviewed synthetic run via `create_case_from_claim`
(real upload/parse/extract/tag/review, real original PDF bytes). Review, policy
approval, evaluation, revision reads and source downloads then go through the
real FastAPI router with cookie sessions, CSRF, If-Match and idempotency keys.
The run's own export (the GPM decision path) is exported over HTTP before and
after, and must be unaffected. No model call, no network, no customer data.
"""

from __future__ import annotations

import json
from hashlib import sha256
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from proofops.adapters.local.auth_store import InMemoryMembershipStore, InMemorySessionStore
from proofops.adapters.local.export_store import LocalExportStore
from proofops.application.exports import ExportService
from proofops_api.auth import AuthStore
from proofops_api.routers.exports import build_exports_router
from proofops_api.routers.reconciliation import build_reconciliation_router

from evaluation.reconciliation_from_claim import create_case_from_claim
from tests.reconciliation.test_from_claim import (  # noqa: F401
    C2_TEXT,
    operator_inputs,
    reviewed,
    reviewed_c2,
)
from tests.reconciliation.test_product_http import (
    ORIGIN,
    REVIEW,
    as_role,
    headers,
    seed_sessions,
)
from tests.reconciliation.test_product_store import TENANT

APPROVAL = {"approved": True, "reason": "owner approval of the synthetic C1 policy"}


def complete_c2_inputs(reviewed, tmp_path):  # noqa: F811
    """Explicit operator evidence proposal, with no approval manufactured by the CLI."""
    from proofops.application.linkage_exchange import C2PeriodContext

    kwargs = operator_inputs(reviewed, tmp_path, "c2-same-period")
    claim = reviewed["claim"]
    draft = kwargs["draft"]
    financial = draft["packet"]["financial"]
    sr_id, fs_id = (
        claim.document_version_id,
        draft["packet"]["identity"]["financial_document_version"],
    )
    sr_source, fs_source = "sr-" + claim.source_refs[0].source_id, financial["source_id"]
    fs_ref = next(ref for ref in draft["packet"]["sources"] if ref["source_id"] == fs_source)
    fs_document = draft["documents"][fs_id]
    fs_document["coverage_units"] = [
        {"unit_id": "note-1", "kind": "note", "locator": fs_ref["locator"]}
    ]
    fs_document["source_bindings"][fs_source]["coverage_unit_id"] = "note-1"
    fs_document["fact_bindings"][fs_source]["period_binding"] = {
        "period_start": "2024-01-01",
        "period_end": "2024-12-31",
    }
    search = dict(
        state="complete",
        coverage_policy_id=draft["policy"]["coverage_policy_id"],
        required_document_ids=[sr_id, fs_id],
        reviewed_source_ids=[sr_source, fs_source],
        failed_document_ids=[],
        receipt_id="operator-proposal-1",
    )
    identity = draft["packet"]["identity"]
    receipt = {key: identity[key] for key in ("tenant_id", "company_id", "package_id")}
    receipt.update({key: value for key, value in search.items() if key != "receipt_id"})
    receipt["coverage_manifest"] = [
        dict(
            document_id=doc,
            artifact_sha256=digest,
            unit_id=unit,
            locator=locator,
            readable=True,
            reviewed=True,
            source_ids=[sid],
        )
        for doc, digest, unit, locator, sid in [
            (sr_id, claim.source_sha256, "page-1", "page:1", sr_source),
            (fs_id, fs_ref["artifact_sha256"], "note-1", fs_ref["locator"], fs_source),
        ]
    ]
    kwargs.update(
        sr_published_at="2025-06-01",
        c2_period_context=C2PeriodContext(
            "2024-01-01/2024-12-31", claim.source_refs[0].source_id, C2_TEXT
        ),
        coverage_proposal={"search": search, "coverage": {"operator-proposal-1": receipt}},
    )
    return kwargs


def test_complete_operator_evidence_can_execute_after_authenticated_review(reviewed_c2, tmp_path):  # noqa: F811
    kwargs = complete_c2_inputs(reviewed_c2, tmp_path)
    detail = create_case_from_claim(**kwargs)
    assert detail["review_state"] == "pending" and detail["policy_approved"] is False
    auth_store = AuthStore(sessions=InMemorySessionStore(), memberships=InMemoryMembershipStore())
    tokens = seed_sessions(auth_store)
    app = FastAPI()
    app.include_router(
        build_reconciliation_router(kwargs["store"], auth_store, allowed_origin=ORIGIN)
    )
    client = TestClient(app)
    case = f"/v1/reconciliation/cases/{detail['case_id']}"
    pending = as_role(client, "editor").post(
        f"{case}/evaluate", json={}, headers=headers(tokens, "editor")
    )
    assert pending.status_code == 200, pending.text
    assert pending.json()["latest_result"]["result"]["execution_state"] == "blocked"
    approved = as_role(client, "admin").post(
        f"{case}/policy-approval",
        json=APPROVAL,
        headers=headers(tokens, "admin", if_match=pending.headers["ETag"]),
    )
    assert approved.status_code == 200, approved.text
    reviewed_case = as_role(client, "reviewer").post(
        f"{case}/review",
        json={**REVIEW, "confirm_search_coverage": True},
        headers=headers(tokens, "reviewer", if_match=approved.headers["ETag"]),
    )
    assert reviewed_case.status_code == 200, reviewed_case.text
    evaluated = as_role(client, "editor").post(
        f"{case}/evaluate",
        json={},
        headers=headers(tokens, "editor", if_match=reviewed_case.headers["ETag"]),
    )
    assert evaluated.status_code == 200, evaluated.text
    result = evaluated.json()["latest_result"]["result"]
    assert result["execution_state"] == "completed", result
    assert result["status"] == "matched", result


@pytest.mark.parametrize("invalid", ["foreign", "missing_page", "truncated", "unconfirmed"])
def test_operator_proposals_do_not_bypass_coverage_trust(reviewed_c2, tmp_path, invalid):  # noqa: F811
    from tests.reconciliation.test_product_store import auth

    kwargs = complete_c2_inputs(reviewed_c2, tmp_path)
    receipt = kwargs["coverage_proposal"]["coverage"]["operator-proposal-1"]
    if invalid == "foreign":
        receipt["tenant_id"] = str(uuid4())
    elif invalid == "missing_page":
        receipt["coverage_manifest"].pop(0)
    elif invalid == "truncated":
        for document in kwargs["draft"]["documents"].values():
            document["candidate_limit"] = {"truncated": True}
    store = kwargs["store"]
    detail = create_case_from_claim(**kwargs)
    detail = store.approve_policy(auth(), detail["case_id"], APPROVAL, '"1"', str(uuid4()))
    detail = store.review(
        auth("reviewer"),
        detail["case_id"],
        {**REVIEW, "confirm_search_coverage": invalid != "unconfirmed"},
        f'"{detail["revision"]}"',
        str(uuid4()),
    )
    result = store.evaluate(
        auth("editor"), detail["case_id"], {}, f'"{detail["revision"]}"', str(uuid4())
    )["latest_result"]["result"]
    assert result["execution_state"] == "blocked", result
    assert result["status"] is None


def gpm_state(reviewed):  # noqa: F811
    """The run's own accepted tag/decision head and immutable revision counts."""
    claims, run_id = reviewed["claims"], reviewed["run_id"]
    jobs = claims.store.jobs
    with jobs._transaction() as db:
        head = claims.current_tag(TENANT, run_id, reviewed["claim_id"], connection=db)
        counts = {
            kind: len(jobs._all(db, TENANT, run_id, kind))
            for kind in ("tag_revision", "decision_revision", "review_head")
        }
    return json.loads(json.dumps(head, sort_keys=True, default=str)), counts


def export_bytes(client, tokens, run_id, export_id=None):
    """Create (or re-download) the run's export over HTTP and return the zip bytes."""
    if export_id is None:
        created = as_role(client, "viewer").post(
            f"/v1/runs/{run_id}/exports",
            json=dict(formats=["json", "csv", "html"], allow_partial=True),
            headers=headers(tokens, "viewer", if_match=None),
        )
        assert created.status_code == 202, created.text
        assert created.json()["state"] == "ready"
        export_id = created.json()["export_id"]
    ticket = as_role(client, "viewer").post(
        f"/v1/exports/{export_id}/download", headers=headers(tokens, "viewer", if_match=None)
    )
    assert ticket.status_code == 200, ticket.text
    content = as_role(client, "viewer").get(ticket.json()["url"])
    assert content.status_code == 200, content.text
    assert sha256(content.content).hexdigest() == ticket.json()["sha256"]
    return export_id, content.content


def stable_members(payload):
    """Every export member; only the JSON members' own generation timestamp is dropped."""
    members = {}
    with ZipFile(BytesIO(payload)) as archive:
        for name in archive.namelist():
            raw = archive.read(name)
            if name.endswith(".json"):
                value = json.loads(raw)
                value.pop("generated_at")
                members[name] = value
            else:
                members[name] = raw
    assert set(members) == {"manifest.json", "report.json", "report.csv", "report.html"}
    return members


@pytest.fixture
def connected(reviewed, tmp_path):  # noqa: F811
    auth_store = AuthStore(sessions=InMemorySessionStore(), memberships=InMemoryMembershipStore())
    tokens = seed_sessions(auth_store)
    kwargs = operator_inputs(reviewed, tmp_path)
    store = kwargs["store"]
    service = reviewed["service"]
    app = FastAPI()
    app.include_router(build_reconciliation_router(store, auth_store, allowed_origin=ORIGIN))
    exports = ExportService(LocalExportStore(service.store, reviewed["claims"]))
    app.include_router(build_exports_router(exports, auth_store, allowed_origin=ORIGIN))
    client = TestClient(app)
    before_state = gpm_state(reviewed)
    export_id, before_export = export_bytes(client, tokens, reviewed["run_id"])
    detail = create_case_from_claim(**kwargs)
    return dict(
        client=client,
        tokens=tokens,
        store=store,
        detail=detail,
        case=f"/v1/reconciliation/cases/{detail['case_id']}",
        before_state=before_state,
        export_id=export_id,
        before_export=before_export,
    )


def test_operator_case_reviews_approves_evaluates_and_leaves_gpm_export_untouched(
    connected,
    reviewed,  # noqa: F811
):
    client, tokens, case = connected["client"], connected["tokens"], connected["case"]
    detail = connected["detail"]
    claim = reviewed["claim"]

    listed = as_role(client, "viewer").get(
        f"/v1/runs/{reviewed['run_id']}/claims/{reviewed['claim_id']}/reconciliation"
    )
    assert listed.status_code == 200, listed.text
    assert detail["case_id"] in {item["case_id"] for item in listed.json()["items"]}
    read = as_role(client, "viewer").get(case)
    assert read.status_code == 200 and read.headers["ETag"] == '"1"'
    assert read.json()["review_state"] == "pending" and read.json()["policy_approved"] is False

    # The SR source downloads as the exact original uploaded PDF bytes.
    original = reviewed["service"].uploads.read_original(TENANT, claim.document_version_id)
    for source in read.json()["sources"]:
        content = as_role(client, "viewer").get(f"{case}/sources/{source['source_id']}/content")
        assert content.status_code == 200, content.text
        assert content.headers["Content-Disposition"].startswith("attachment;")
        assert sha256(content.content).hexdigest() == source["artifact_sha256"]
        if source["document_id"] == claim.document_version_id:
            assert content.content == original

    reviewed_case = as_role(client, "reviewer").post(
        f"{case}/review", json=REVIEW, headers=headers(tokens, "reviewer")
    )
    assert reviewed_case.status_code == 200, reviewed_case.text
    assert reviewed_case.headers["ETag"] == '"2"'
    assert reviewed_case.json()["review_state"] == "reviewed"
    stale = as_role(client, "reviewer").post(
        f"{case}/review", json=REVIEW, headers=headers(tokens, "reviewer")
    )
    assert stale.status_code == 409, stale.text

    approved = as_role(client, "admin").post(
        f"{case}/policy-approval", json=APPROVAL, headers=headers(tokens, "admin", if_match='"2"')
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["policy_approved"] is True
    stale_approval = as_role(client, "admin").post(
        f"{case}/policy-approval", json=APPROVAL, headers=headers(tokens, "admin", if_match='"2"')
    )
    assert stale_approval.status_code == 409, stale_approval.text

    evaluated = as_role(client, "editor").post(
        f"{case}/evaluate",
        json={},
        headers=headers(tokens, "editor", if_match=approved.headers["ETag"]),
    )
    assert evaluated.status_code == 200, evaluated.text
    latest = evaluated.json()["latest_result"]
    result = latest["result"]
    assert result["schema_version"] == "1.1"
    assert "policy_unapproved" not in result["reason_codes"]
    # Known, fail-closed limitation: main's upload contract has no SR publication
    # date, so the SR document's available_on is null and the date gate blocks.
    assert result["execution_state"] == "blocked" and result["status"] is None
    assert result["reason_codes"] == ["document_date_invalid"]
    assert result["packet_sha256"]
    snapshot = as_role(client, "viewer").get(f"{case}/revisions/{latest['revision']}")
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["result"] == result
    assert (
        snapshot.json()
        == as_role(client, "viewer").get(f"{case}/revisions/{latest['revision']}").json()
    )

    # The run's own GPM decision and its export bytes are unchanged by reconciliation.
    assert gpm_state(reviewed) == connected["before_state"]
    _, again = export_bytes(client, tokens, reviewed["run_id"], connected["export_id"])
    assert again == connected["before_export"]
    _, fresh = export_bytes(client, tokens, reviewed["run_id"])
    assert stable_members(fresh) == stable_members(connected["before_export"])


def test_foreign_tenant_gets_not_found_on_every_case_route(connected):
    client, tokens, case = connected["client"], connected["tokens"], connected["case"]
    source = connected["detail"]["sources"][0]["source_id"]
    assert as_role(client, "foreign").get(case).status_code == 404
    assert as_role(client, "foreign").get(f"{case}/revisions/1").status_code == 404
    assert as_role(client, "foreign").get(f"{case}/sources/{source}/content").status_code == 404
    for path, body in (("review", REVIEW), ("policy-approval", APPROVAL), ("evaluate", {})):
        response = as_role(client, "foreign").post(
            f"{case}/{path}", json=body, headers=headers(tokens, "foreign")
        )
        assert response.status_code == 404, (path, response.text)
    assert as_role(client, "viewer").get(case).headers["ETag"] == '"1"'


def test_tampered_managed_original_is_refused_and_never_served(connected, reviewed):  # noqa: F811
    client, store, case = connected["client"], connected["store"], connected["case"]
    claim = reviewed["claim"]
    (source,) = {
        s["source_id"]
        for s in connected["detail"]["sources"]
        if s["document_id"] == claim.document_version_id
    }
    path = store.managed_path(TENANT, connected["detail"]["case_id"], source)
    path.write_bytes(path.read_bytes().replace(b"%PDF-", b"%PDX-", 1))
    response = as_role(client, "viewer").get(f"{case}/sources/{source}/content")
    assert response.status_code == 409, response.text
    assert b"%PDX-" not in response.content
    # The uploaded original itself is untouched and still verifies.
    original = reviewed["service"].uploads.read_original(TENANT, claim.document_version_id)
    assert sha256(original).hexdigest() == claim.source_sha256


def test_unknown_case_and_idempotent_replay(connected):
    client, tokens, case = connected["client"], connected["tokens"], connected["case"]
    assert as_role(client, "viewer").get(f"/v1/reconciliation/cases/{uuid4()}").status_code == 404
    key = str(uuid4())
    first = as_role(client, "reviewer").post(
        f"{case}/review", json=REVIEW, headers=headers(tokens, "reviewer", key=key)
    )
    second = as_role(client, "reviewer").post(
        f"{case}/review", json=REVIEW, headers=headers(tokens, "reviewer", key=key)
    )
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert as_role(client, "viewer").get(case).json()["revision"] == 2
