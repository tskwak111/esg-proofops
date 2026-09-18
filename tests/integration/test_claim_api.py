"""Read actual immutable extracted claims without inventing pending tag results."""

from dataclasses import replace
from uuid import uuid4

from proofops.application.authorization import MembershipRecord

from tests.acceptance.test_upload import FOREIGN, TENANT
from tests.integration.test_local_extract_runner import extraction_setup
from tests.integration.test_run_lifecycle import client, validate


def test_extracted_claim_api_preserves_sources_filters_and_pending_details(tmp_path, monkeypatch):
    from proofops_api.routers.claims import build_claims_router

    service, run_id, runner, now, _ = extraction_setup(tmp_path, monkeypatch)
    http, auth = client(service)
    http.app.include_router(build_claims_router(runner.claims, auth, clock=lambda: now[0]))
    url = f"/v1/runs/{run_id}/claims"
    assert http.get(url).status_code == 409
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    actual = runner.claims.list(TENANT, run_id)
    listed = http.get(url)
    assert listed.status_code == 200
    assert listed.headers["cache-control"] == "no-store"
    validate("ClaimSummaryPage", listed.json())
    assert {item["claim_id"] for item in listed.json()["items"]} == {
        claim.claim_id for claim in actual
    }
    assert all(item["decision"] is None for item in listed.json()["items"])
    detail = http.get(url + "/" + actual[0].claim_id)
    assert detail.status_code == 200, detail.text
    validate("ClaimDetail", detail.json())
    assert detail.json()["claim"]["track"] is None
    assert detail.json()["claim"]["decision"] is None
    assert detail.json()["elements"] == []
    assert detail.json()["replicate_request_ids"] == []
    assert detail.json()["packet_sha256"] is None
    assert detail.json()["tag_status"] == "untagged"
    assert detail.json()["source_refs"]
    assert http.get(url + "/" + str(uuid4())).status_code == 404
    assert http.get(url, params={"track": "goal"}).json()["items"] == []
    assert http.get(url, params={"grade": "E3"}).json()["items"] == []
    assert http.get(url, params={"review_status": "human_confirmed"}).json()["items"] == []
    assert http.get(url, params={"grade": "E4"}).status_code == 422
    assert http.get(url, params={"limit": 0}).status_code == 422
    first = http.get(url, params={"limit": 1}).json()
    assert first["next_cursor"]
    seen = list(first["items"])
    cursor = first["next_cursor"]
    while cursor:
        assert (
            http.get(url, params={"limit": 1, "cursor": cursor, "track": "goal"}).status_code == 400
        )
        page = http.get(url, params={"limit": 1, "cursor": cursor}).json()
        assert page["snapshot_epoch"] == first["snapshot_epoch"]
        seen.extend(page["items"])
        cursor = page["next_cursor"]
    assert seen == listed.json()["items"]
    if first["next_cursor"]:
        now[0] += 900
        assert http.get(url, params={"limit": 1, "cursor": first["next_cursor"]}).status_code == 400
    auth.sessions.put(replace(auth.sessions.get("admin-session"), active_tenant_id=FOREIGN))
    auth.memberships.put(MembershipRecord(FOREIGN, "admin-user", "admin", "active"))
    assert http.get(url).status_code == 404
    assert http.get(url + "/" + actual[0].claim_id).status_code == 404
    http.cookies.clear()
    assert http.get(url).status_code == 401


def test_published_tags_and_human_revision_are_read_through_real_claim_api(tmp_path, monkeypatch):
    from dataclasses import asdict

    from proofops.adapters.local.review_store import LocalSQLiteReviewStore
    from proofops.application.reviews import ReviewService
    from proofops_api.routers.claims import build_claims_router
    from proofops_api.routers.reviews import build_reviews_router

    from tests.integration.test_local_tag_runner import verified_setup

    service, run_id, runner, now, _ = verified_setup(tmp_path, monkeypatch)
    http, auth = client(service)
    reviews = ReviewService(
        LocalSQLiteReviewStore(service.store.jobs), load_inputs=runner.tags.load_inputs
    )
    http.app.include_router(
        build_claims_router(runner.claims, auth, tags=runner.tags, clock=lambda: now[0])
    )
    http.app.include_router(
        build_reviews_router(
            reviews, auth, allowed_origin="https://testserver", run_store=service.store
        )
    )
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "needs_review"
    claim_id = runner.tags.load_snapshot(TENANT, run_id)["claims"][0]["claim_id"]
    url = f"/v1/runs/{run_id}/claims/{claim_id}"
    detail = http.get(url)
    assert detail.status_code == 200, detail.text
    validate("ClaimDetail", detail.json())
    initial = detail.json()
    assert initial["claim"]["track"] == "performance"
    assert initial["claim"]["decision"] is None
    assert len(set(initial["replicate_request_ids"])) == 3
    assert initial["assurance"]["status"] == "undetermined"
    assert all(e["state"] == "unknown" for e in initial["elements"])
    assert "raw_response" not in detail.text and "reviewer_sub" not in detail.text
    inputs = runner.tags.load_inputs(TENANT, run_id, claim_id)
    queue = http.get(f"/v1/runs/{run_id}/reviews").json()
    review = queue["items"][0]
    response = http.post(
        f'/v1/reviews/{review["review_id"]}/resolve',
        headers={"If-Match": f'"{review["revision"]}"'},
        json=dict(
            base_tag_revision=1,
            track="performance",
            elements=[asdict(e) for e in inputs.consensus.candidate_elements],
            reason="Keep unverified elements unresolved.",
        ),
    )
    assert response.status_code == 200, response.text
    latest = http.get(url).json()
    validate("ClaimDetail", latest)
    assert latest["claim"]["revision"] == 2
    assert latest["claim"]["decision"]["review_status"] == "human_confirmed"
    assert latest["claim"]["decision"]["evidence_grade"] is None
    assert latest["packet_sha256"] == initial["packet_sha256"]
    assert latest["replicate_request_ids"] == initial["replicate_request_ids"]
    listed = http.get(f"/v1/runs/{run_id}/claims", params={"review_status": "human_confirmed"})
    assert listed.status_code == 200, listed.text
    validate("ClaimSummaryPage", listed.json())
    assert listed.json()["items"] == [latest["claim"]]
