"""Tenant-scoped immutable extraction reads; pending tags are not invented."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyCookie
from proofops.adapters.local.catalog_pages import CatalogCapacityExceeded, InvalidCatalogCursor
from proofops.application.assurance import ClaimContext as AssuranceContext
from proofops.application.assurance import match_assurance
from proofops.application.runs import RunRejected
from proofops.domain.provenance import canonical_hash
from proofops_api.auth import (
    SESSION_COOKIE_NAME,
    _authorize,
    _error_response,
    _request_limit_response,
)
from proofops_api.dto import Decision
from proofops_api.routers.documents import StrictDTO
from proofops_api.routers.reviews import Element
from proofops_api.routers.sources import SourceRef
from proofops_api.rulepacks import _ERROR_RESPONSES
from pydantic import Field

Track = Literal["goal", "performance", "management"]
Grade = Literal["E0", "E1", "E2", "E3"]
ReviewStatus = Literal["auto_confirmed", "needs_review", "human_confirmed"]


class ClaimSummary(StrictDTO):
    claim_id: UUID
    page_num: Annotated[int, Field(ge=1)]
    quote: str
    track: Track | None
    topic_ids: list[str]
    decision: Decision | None
    revision: Annotated[int, Field(ge=1)]


class ClaimSummaryPage(StrictDTO):
    items: list[ClaimSummary]
    next_cursor: str | None
    snapshot_epoch: Annotated[int, Field(ge=0)] | None


class AssuranceMatch(StrictDTO):
    status: Literal["covered", "not_covered", "undetermined"]
    level: Literal["limited", "reasonable", "none"] | None
    provider: str | None
    statement_id: UUID | None
    metric_match: Literal["yes", "no", "unknown"]
    period_match: Literal["yes", "no", "unknown"]
    boundary_match: Literal["yes", "no", "unknown"]
    evidence_refs: list[SourceRef]


class BasisRef(StrictDTO):
    standard: str
    clause: str | None
    summary: str
    verification_status: Literal["verified", "unverified", "unlicensed"]


class ClaimDetail(StrictDTO):
    claim: ClaimSummary
    source_refs: list[SourceRef]
    elements: list[Element]
    assurance: AssuranceMatch
    replicate_request_ids: list[str]
    packet_sha256: Annotated[str, Field(pattern="^[0-9a-f]{64}$")] | None
    suggestion: str | None
    basis_refs: list[BasisRef]
    tag_status: Literal["tagged", "untagged"] | None = None


def build_claims_router(claims, auth_store, *, tags=None, clock=time.time):
    router = APIRouter(
        responses=_ERROR_RESPONSES,
        dependencies=[
            Security(
                APIKeyCookie(
                    name=SESSION_COOKIE_NAME, scheme_name="sessionCookie", auto_error=False
                )
            )
        ],
    )
    contract = {
        "x-minimum-role": "viewer",
        "x-idempotency-required": False,
        "x-rate-limit": "120/min/user",
    }
    store = claims.store

    def load(request, run_id, operation):
        now = time.time()
        auth = _authorize(request, auth_store, now, "viewer")
        if isinstance(auth, JSONResponse):
            return auth
        limited = _request_limit_response(
            auth_store, user_sub=auth.user_sub, operation_id=operation, requests=120, now=now
        )
        if limited is not None:
            return limited
        return claims.load(auth.tenant_id, run_id)

    def failure(exc):
        if isinstance(exc, InvalidCatalogCursor):
            return _error_response(
                400, "INVALID_CURSOR", "Pagination cursor is invalid or expired."
            )
        if isinstance(exc, CatalogCapacityExceeded):
            return _error_response(
                503, "CATALOG_CAPACITY_EXCEEDED", "Snapshot capacity is temporarily exhausted."
            )
        if isinstance(exc, RunRejected):
            return _error_response(exc.status, exc.code, "Claim request could not be processed.")
        return _error_response(
            409, "ARTIFACT_UNAVAILABLE", "Claims are pending or failed integrity checks."
        )

    @router.get(
        "/v1/runs/{run_id}/claims",
        response_model=ClaimSummaryPage,
        operation_id="claims_list",
        openapi_extra=contract,
    )
    def listed(
        request: Request,
        run_id: UUID,
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        track: Track | None = None,
        grade: Grade | None = None,
        review_status: ReviewStatus | None = None,
    ):
        try:
            discovery = load(request, str(run_id), "claims_list")
            if isinstance(discovery, JSONResponse):
                return discovery
            if tags is not None:
                return JSONResponse(
                    claims.page(
                        discovery,
                        str(run_id),
                        cursor=cursor,
                        limit=limit,
                        now=int(clock()),
                        track=track,
                        grade=grade,
                        review_status=review_status,
                    ),
                    headers={"Cache-Control": "no-store"},
                )
            tenant = discovery.scope.tenant_id
            digest, now = canonical_hash(asdict(discovery)), int(clock())
            filters = [track, grade, review_status]
            page = (
                store._decode_cursor(cursor, tenant, str(run_id), limit, now, endpoint="claims")
                if cursor
                else dict(
                    scope=[tenant, str(run_id), "claims", limit],
                    expires=now + 900,
                    after=0,
                    snapshot=digest,
                    filters=filters,
                    epoch=store.get(tenant, str(run_id))["mutation_epoch"],
                )
            )
            if page["snapshot"] != digest or page["filters"] != filters:
                raise RunRejected("INVALID_CURSOR", 400)
            items = [
                claim.to_summary()
                for claim in sorted(
                    discovery.claims, key=lambda c: (c.source_refs[0].page_num, c.claim_id)
                )
            ]
            items = [
                item
                for item in items
                if (track is None or item["track"] == track)
                and (grade is None or (item["decision"] or {}).get("evidence_grade") == grade)
                and (
                    review_status is None
                    or (item["decision"] or {}).get("review_status") == review_status
                )
            ]
            after = page["after"] + limit
            return JSONResponse(
                dict(
                    items=items[page["after"] : after],
                    next_cursor=store._encode_cursor(dict(page, after=after))
                    if after < len(items)
                    else None,
                    snapshot_epoch=page["epoch"],
                ),
                headers={"Cache-Control": "no-store"},
            )
        except (ValueError, KeyError, sqlite3.DatabaseError) as exc:
            return failure(exc)

    @router.get(
        "/v1/runs/{run_id}/claims/{claim_id}",
        operation_id="claim_get",
        openapi_extra=contract,
        response_model=ClaimDetail,
    )
    def detail(request: Request, run_id: UUID, claim_id: UUID):
        try:
            discovery = load(request, str(run_id), "claim_get")
            if isinstance(discovery, JSONResponse):
                return discovery
            claim = next((c for c in discovery.claims if c.claim_id == str(claim_id)), None)
            if claim is None:
                raise RunRejected("RESOURCE_NOT_FOUND", 404)
            current = claims.current_tag(claim.tenant_id, str(run_id), claim.claim_id)
            assurance = match_assurance(
                None,
                AssuranceContext(
                    claim.tenant_id, claim.document_version_id, claim.claim_id, None, None, (), ()
                ),
            )
            if current is None:
                # Extraction-only review: tagging not yet published. Return the
                # original extraction refs without inventing tag artifacts
                # (no elements, replicate ids, or tag packet) and without an
                # ETag, so no tag edits can be conditioned until a tag exists.
                # Dedicated assurance extraction has not been published in this
                # local path; the matcher preserves that absence as undetermined.
                summary = claims.summary(claim, None)
                body = dict(
                    claim=summary,
                    source_refs=[asdict(ref) for ref in claim.source_refs],
                    elements=[],
                    assurance=assurance.to_dict(),
                    replicate_request_ids=[],
                    packet_sha256=None,
                    suggestion=None,
                    basis_refs=[],
                    tag_status="untagged",
                )
                return JSONResponse(
                    ClaimDetail.model_validate_json(json.dumps(body)).model_dump(mode="json"),
                    headers={"Cache-Control": "no-store"},
                )
            if tags is None:
                raise RunRejected("TAGGING_NOT_PUBLISHED")
            inputs = tags.load_inputs(claim.tenant_id, str(run_id), claim.claim_id)
            tag = current["tag"]
            summary = claims.summary(claim, current)
            # Dedicated assurance extraction has not been published in this local path.
            # The existing matcher preserves that absence as undetermined.
            body = dict(
                claim=summary,
                source_refs=[asdict(ref) for ref in claim.source_refs],
                elements=tag["elements"],
                assurance=assurance.to_dict(),
                replicate_request_ids=[run.request.request_id for run in inputs.tag_runs],
                packet_sha256=inputs.packet.packet_sha256,
                suggestion=None,
                basis_refs=[],
                tag_status="tagged",
            )
            return JSONResponse(
                ClaimDetail.model_validate_json(json.dumps(body)).model_dump(mode="json"),
                headers={"Cache-Control": "no-store", "ETag": f'"{tag["tag_revision"]}"'},
            )
        except (ValueError, KeyError, sqlite3.DatabaseError) as exc:
            return failure(exc)

    return router
