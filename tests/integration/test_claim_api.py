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


def test_review_projection_reflects_real_pinned_tag_checkpoint_reason(tmp_path, monkeypatch):
    """review_projection must read the actual worker checkpoint, not a mock.

    A claim whose replicates never reach consensus is published with
    reason="CONSENSUS_UNRESOLVED" and no original_packet/preliminary_agreement
    (those are only set on the earlier blocked-before-tagging paths). The
    claims API must still surface that real reason and must not invent
    candidates or field agreements the checkpoint never recorded.
    """
    from proofops_api.routers.claims import build_claims_router

    from tests.integration.test_local_tag_runner import verified_setup

    service, run_id, runner, now, _ = verified_setup(tmp_path, monkeypatch)
    http, auth = client(service)
    http.app.include_router(
        build_claims_router(runner.claims, auth, tags=runner.tags, clock=lambda: now[0])
    )
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "needs_review"
    envelope = runner.tags.load_snapshot(TENANT, run_id)
    record = envelope["claims"][0]
    assert record["reason"] == "CONSENSUS_UNRESOLVED"
    assert "original_packet" not in record and "preliminary_agreement" not in record
    claim_id = record["claim_id"]
    detail = http.get(f"/v1/runs/{run_id}/claims/{claim_id}")
    assert detail.status_code == 200, detail.text
    validate("ClaimDetail", detail.json())
    projection = detail.json()["review_projection"]
    assert projection is not None
    assert projection["schema_version"] == 1
    assert projection["blocked_reason"] == "CONSENSUS_UNRESOLVED"
    assert projection["candidate_snippets"] == []
    assert projection["field_agreements"] == []


def test_review_projection_absent_before_tag_stage_starts(tmp_path, monkeypatch):
    """A run whose tag stage never started has nothing to project (None), and
    that specific absence must not be confused with a real checkpoint
    integrity failure, which must still raise instead of degrading to None."""
    from proofops.adapters.local.tag_store import LocalTagStore
    from proofops_api.routers.claims import build_claims_router

    service, run_id, runner, now, _ = extraction_setup(tmp_path, monkeypatch)
    tags = LocalTagStore(runner.store, runner.uploads, runner.parser)
    http, auth = client(service)
    http.app.include_router(
        build_claims_router(runner.claims, auth, tags=tags, clock=lambda: now[0])
    )
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    claim_id = runner.claims.list(TENANT, run_id)[0].claim_id
    detail = http.get(f"/v1/runs/{run_id}/claims/{claim_id}")
    assert detail.status_code == 200, detail.text
    validate("ClaimDetail", detail.json())
    assert detail.json()["tag_status"] == "untagged"
    assert detail.json()["review_projection"] is None


def test_review_projection_surfaces_real_blocked_candidate_quotes(tmp_path, monkeypatch):
    """A claim blocked on unresolved preliminary tagging still has a real,
    traceable candidate packet (per test_local_tag_runner's
    test_unresolved_preliminary_is_claim_block_not_failed_job). The API must
    surface the actual candidate quotes from that checkpoint, not invent or
    upgrade them, and the claim must stay in the untagged/blocked branch."""
    from proofops_api.routers.claims import build_claims_router

    from tests.integration.test_local_tag_runner import verified_setup

    service, run_id, runner, now, _ = verified_setup(tmp_path, monkeypatch)
    runner.preliminary = lambda claim, graph: None
    http, auth = client(service)
    http.app.include_router(
        build_claims_router(runner.claims, auth, tags=runner.tags, clock=lambda: now[0])
    )
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "blocked"
    record = runner.tags.load_snapshot(TENANT, run_id)["claims"][0]
    assert record["reason"] == "PRELIMINARY_TAGS_UNRESOLVED"
    expected_quotes = [
        ref["quote"]
        for candidate in record["original_packet"]["evidence_candidates"]
        for ref in candidate["source_refs"]
    ]
    assert expected_quotes
    detail = http.get(f"/v1/runs/{run_id}/claims/{record['claim_id']}")
    assert detail.status_code == 200, detail.text
    validate("ClaimDetail", detail.json())
    assert detail.json()["tag_status"] == "untagged"
    projection = detail.json()["review_projection"]
    assert projection is not None
    assert projection["schema_version"] == 1
    assert projection["blocked_reason"] == "PRELIMINARY_TAGS_UNRESOLVED"
    assert projection["candidate_snippets"] == expected_quotes
    assert projection["field_agreements"] == []


def test_review_projection_does_not_swallow_checkpoint_integrity_mismatch(tmp_path, monkeypatch):
    """A genuine tag-checkpoint integrity failure (hash mismatch) must still
    surface as an error response, not silently degrade to review_projection=None
    the way a merely-not-started tag stage does."""
    from proofops_api.routers.claims import build_claims_router

    from tests.integration.test_local_tag_runner import verified_setup

    service, run_id, runner, now, _ = verified_setup(tmp_path, monkeypatch)
    http, auth = client(service)
    http.app.include_router(
        build_claims_router(runner.claims, auth, tags=runner.tags, clock=lambda: now[0])
    )
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "needs_review"
    claim_id = runner.tags.load_snapshot(TENANT, run_id)["claims"][0]["claim_id"]
    jobs = service.store.jobs
    with jobs._transaction() as db:
        run = jobs._get(db, TENANT, run_id, "run", "META")
        run["tag_snapshot_sha256"] = "0" * 64
        jobs._put(db, TENANT, run_id, "run", "META", run)
    detail = http.get(f"/v1/runs/{run_id}/claims/{claim_id}")
    assert detail.status_code == 409, detail.text
    assert detail.json()["error"]["code"] == "ARTIFACT_UNAVAILABLE"


def test_review_projection_raw_candidates_and_guards(tmp_path, monkeypatch):
    """R04 integration: structured raw_candidates surfaced in ReviewProjection.

    - Positive: unverified table candidate surfaced with status/reason and SourceRef.
    - Negative: tampered ref / invalid shape filtered from projection.
    - Confirmed grade guard: unverified candidate never changes elements or decision grade.
    - Compatibility: old checkpoints without raw_candidate_review default to empty list.
    """
    import copy
    from proofops_api.routers.claims import build_claims_router
    from tests.integration.test_local_tag_runner import verified_setup

    service, run_id, runner, now, _ = verified_setup(tmp_path, monkeypatch)
    http, auth = client(service)
    http.app.include_router(
        build_claims_router(runner.claims, auth, tags=runner.tags, clock=lambda: now[0])
    )
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "needs_review"
    envelope = runner.tags.load_snapshot(TENANT, run_id)
    record = envelope["claims"][0]
    claim_id = record["claim_id"]

    # 1. Base response validates ClaimDetail schema
    detail = http.get(f"/v1/runs/{run_id}/claims/{claim_id}")
    assert detail.status_code == 200, detail.text
    validate("ClaimDetail", detail.json())
    projection = detail.json()["review_projection"]
    assert projection is not None
    assert projection["schema_version"] == 1
    assert "raw_candidates" in projection
    assert isinstance(projection["raw_candidates"], list)

    # 2. Inject an unverified candidate into checkpoint and verify read-only surface
    source_ref = copy.deepcopy(detail.json()["source_refs"][0])
    source_ref["verification_state"] = "candidate"
    sample_candidate = {
        "source_ref": source_ref,
        "status": "unverified",
        "reason": "UNVERIFIED_SOURCE",
    }
    tampered_candidate = {
        "source_ref": dict(source_ref, bbox=None, location_quality="unlocated"),
        "status": "unverified",
        "reason": "UNVERIFIED_SOURCE",
    }
    record["raw_candidate_review"] = {
        "schema_version": 1,
        "candidates": [sample_candidate, tampered_candidate],
    }
    envelope["claims"][0] = record

    # Exercise the API projection at its trusted read boundary; committed
    # checkpoint/receipt integrity is covered by the storage tests.
    monkeypatch.setattr(runner.tags, "load_snapshot", lambda tenant, run: envelope)

    detail_with_candidates = http.get(f"/v1/runs/{run_id}/claims/{claim_id}")
    assert detail_with_candidates.status_code == 200, detail_with_candidates.text
    validate("ClaimDetail", detail_with_candidates.json())

    proj2 = detail_with_candidates.json()["review_projection"]
    assert proj2 is not None
    # Valid unverified candidate is surfaced
    assert len(proj2["raw_candidates"]) == 1
    surfaced = proj2["raw_candidates"][0]
    assert surfaced["status"] == "unverified"
    assert surfaced["reason"] == "UNVERIFIED_SOURCE"
    assert surfaced["source_ref"]["source_id"] == source_ref["source_id"]

    # Confirmed grade guard: unverified candidate is NEVER promoted to elements or confirmed tags
    body = detail_with_candidates.json()
    assert body["elements"] == detail.json()["elements"]
    # Grade and decision status remain identical to baseline
    assert body["claim"]["decision"] == detail.json()["claim"]["decision"]

    # 3. Unknown schema version must reject with 409, never silently display
    record["raw_candidate_review"] = {
        "schema_version": 99,
        "candidates": [sample_candidate],
    }
    envelope["claims"][0] = record

    unknown_resp = http.get(f"/v1/runs/{run_id}/claims/{claim_id}")
    assert unknown_resp.status_code == 409
    assert unknown_resp.json()["error"]["code"] == "ARTIFACT_UNAVAILABLE"

    # 4. Prohibited accepted/verified labels are filtered out
    record["raw_candidate_review"] = {
        "schema_version": 1,
        "candidates": [
            dict(sample_candidate, status="verified"),
            dict(sample_candidate, status="accepted"),
        ],
    }
    envelope["claims"][0] = record

    filtered_resp = http.get(f"/v1/runs/{run_id}/claims/{claim_id}")
    assert filtered_resp.status_code == 200
    assert len(filtered_resp.json()["review_projection"]["raw_candidates"]) == 0


    record.pop("raw_candidate_review")
    legacy = http.get(f"/v1/runs/{run_id}/claims/{claim_id}")
    assert legacy.status_code == 200
    assert legacy.json()["review_projection"]["raw_candidates"] == []
