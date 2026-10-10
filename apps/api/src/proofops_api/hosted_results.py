"""Tenant-scoped reads and human resolutions over unchanged R108 stores."""

import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from proofops.adapters.local.review_store import LocalSQLiteReviewStore
from proofops.adapters.local.run_store import LocalSQLiteRunStore
from proofops.adapters.local.tag_store import LocalTagStore
from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
from proofops.application.registry import Registry
from proofops.application.reviews import ReviewRejected, ReviewService
from proofops.application.uploads import UploadService

from proofops_api.hosted_ocr import ReplayOCRStore, reader_scope
from proofops_api.hosted_store import HostedError


@contextmanager
def services(path: Path, tenant: str):
    manifest = json.loads((path / "pilot.json").read_text())
    if manifest["tenant_id"] != tenant:
        raise HostedError("RESOURCE_NOT_FOUND", 404)
    database = path / "state.sqlite3"
    registry = Registry.sqlite(database)
    uploads = UploadService(database, path / "objects", registry)
    runs = LocalSQLiteRunStore(database)
    parser = OpenDataLoaderParser(path / "parser-prepared")
    tags = LocalTagStore(runs, uploads, parser)
    claims = tags.claims
    reviews = ReviewService(
        LocalSQLiteReviewStore(runs.jobs),
        load_inputs=tags.load_inputs,
        verify_context_sources=tags.verify_context_sources,
        load_run_snapshot=runs.snapshot,
    )
    try:
        with reader_scope(ReplayOCRStore(path / "upstage.sqlite3")):
            previous_cache = os.environ.get("PROOFOPS_VERIFIED_READ_CACHE")
            try:
                snapshot = runs.snapshot(tenant, manifest["run_id"])
                policy = snapshot.get("analysis_profile_policy", {})
                os.environ["PROOFOPS_VERIFIED_READ_CACHE"] = policy.get(
                    "verified_read_cache", {}
                ).get("profile", "disabled")
                yield manifest["run_id"], claims, tags, reviews
            finally:
                if previous_cache is None:
                    os.environ.pop("PROOFOPS_VERIFIED_READ_CACHE", None)
                else:
                    os.environ["PROOFOPS_VERIFIED_READ_CACHE"] = previous_cache
    finally:
        uploads.close()
        registry.close()


def read_result(path: Path, tenant: str, selected_pages: list[int]) -> dict:
    outcome = json.loads((path / "outcome.json").read_text())
    if not (path / "pilot.json").is_file():
        return dict(
            schema="r108-hosted-result-v1",
            claims=[],
            reviews=[],
            hold_reasons=[outcome["reason"]],
            possible_grade_range=None,
            confirmed_grade=None,
            pipeline=outcome,
            page_map=selected_pages,
        )
    with services(path, tenant) as (run, claims, tags, reviews):
        state = claims.store.jobs.get_run(tenant, run)
        # No extraction publication means no invented empty successful analysis.
        if "extract_job" not in state:
            return dict(
                schema="r108-hosted-result-v1",
                claims=[],
                reviews=[],
                hold_reasons=[outcome["reason"]],
                possible_grade_range=None,
                confirmed_grade=None,
                pipeline=outcome,
                page_map=selected_pages,
            )
        rows = []
        if "tag_job" in state:
            # This existing reader verifies both the tag checkpoint pins and
            # the complete source/claim evidence. Reuse its evidence under the
            # publisher's analysis.lock instead of repeating the same replay.
            tag_snapshot, evidence = tags._load_snapshot_with_evidence(tenant, run)
        else:
            tag_snapshot, evidence = {}, claims.load_evidence(tenant, run)
        projections = {r["claim_id"]: r for r in tag_snapshot.get("claims", [])}
        reasons = {cid: r.get("reason") for cid, r in projections.items()}
        # The publisher holds analysis.lock; these source artifacts cannot change
        # while building this snapshot. Replay all source guards once, then retain
        # the same graph for every claim's identity-checked missing-evidence search.
        _, discovery, original_graph = evidence
        from proofops.application.analysis_profile import (
            V2_PB1_COMPACT_POLICY,
            V2_PB1_INITIAL_POLICY,
            V2_PB1_POLICY,
            V2_PB2_ALL_CLAIMS_POLICY,
            V2_PB2_INITIAL_POLICY,
            V2_PB2_POLICY,
            V2_PB4_POLICY,
            V2_POLICY,
            V2_PRE_PB4_POLICY,
        )
        from proofops.application.ingest.pb1_tables import observations, occurrence_groups
        from proofops.domain.provenance import canonical_hash

        pb1 = tag_snapshot.get("analysis_profile_policy_sha256") in {
            canonical_hash(V2_POLICY),
            canonical_hash(V2_PB4_POLICY),
            canonical_hash(V2_PRE_PB4_POLICY),
            canonical_hash(V2_PB2_POLICY),
            canonical_hash(V2_PB2_INITIAL_POLICY),
            canonical_hash(V2_PB2_ALL_CLAIMS_POLICY),
            canonical_hash(V2_PB1_POLICY),
            canonical_hash(V2_PB1_COMPACT_POLICY),
            canonical_hash(V2_PB1_INITIAL_POLICY),
        }
        groups = occurrence_groups(discovery.claims) if pb1 else {}
        blocks = {b.source_id: b for b in original_graph.blocks}
        from proofops.application.evidence.span_citations import verify_source_ref

        for claim in discovery.claims:
            current = claims.current_tag(tenant, run, claim.claim_id)
            summary = claims.summary(claim, current)
            if pb1:
                summary["duplicate_occurrences"] = groups.get(
                    canonical_hash(" ".join(claim.quote.split())), [claim.claim_id]
                )
                ref = claim.source_refs[0]
                block = blocks[ref.source_id]
                if block.kind == "table" and block.winner is not None:
                    context = " ".join(block.candidates[block.winner].context)
                    row = next(
                        (
                            r
                            for r in observations(block.normalized_text, context=context)
                            if r["start"] <= ref.char_start < ref.char_end <= r["end"]
                        ),
                        None,
                    )
                    if row:
                        summary["table_observation"] = row
                        if tag_snapshot.get("analysis_profile_policy_sha256") in {
                            canonical_hash(V2_POLICY),
                            canonical_hash(V2_PB4_POLICY),
                            canonical_hash(V2_PRE_PB4_POLICY),
                            canonical_hash(V2_PB2_POLICY),
                            canonical_hash(V2_PB2_INITIAL_POLICY),
                            canonical_hash(V2_PB2_ALL_CLAIMS_POLICY),
                        }:
                            from proofops.application.tagging.pb2_table_evidence import (
                                observation_sources,
                            )

                            sources = observation_sources(claim, original_graph, tenant_id=tenant)
                            summary["table_observation"] = row | dict(
                                verification_state="verified" if sources else "unresolved",
                                cell_source_refs={
                                    key: asdict(
                                        sources[key]["ref"]
                                        if key in ("value", "unit")
                                        else sources[key]
                                    )
                                    for key in ("value", "unit", "year")
                                }
                                if sources
                                else {},
                            )
            decision = summary.get("decision")
            tag = current["tag"] if current else {}
            elements = tag.get("elements", [])
            projection = projections.get(claim.claim_id, {})
            if "source_status" in projection:
                summary.update(
                    source_status=projection["source_status"],
                    provisional_grade=projection["provisional_grade"],
                    pipeline_stage=projection["stage"],
                    pipeline_status=projection["status"],
                    provisional_track=projection.get("frozen_packet", {}).get("track"),
                )
            rows.append(
                summary
                | dict(
                    original_page_num=selected_pages[summary["page_num"] - 1],
                    # New publications expose citation-level verification from
                    # this replayed graph, not the whole-claim quality label.
                    # Existing result revisions and rule inputs remain unchanged.
                    source_refs=[
                        asdict(verify_source_ref(ref, original_graph, tenant_id=tenant))
                        if ref.verification_state == "candidate"
                        else asdict(ref)
                        for ref in claim.source_refs
                    ],
                    source_quality=claim.source_quality,
                    elements=elements,
                    hold_reason=reasons.get(claim.claim_id),
                    possible_grade_range=(decision or {}).get("grade_range"),
                    confirmed_grade=(decision or {}).get("evidence_grade"),
                    missing_evidence=claims.missing_evidence(
                        tenant,
                        run,
                        claim,
                        track=summary["track"],
                        elements=elements,
                        original_graph=original_graph,
                    ),
                )
            )
        page = reviews.store.page(tenant, run, cursor=None, limit=100, now=0, cursors=claims.store)
        return dict(
            schema="r108-hosted-result-v1",
            claims=rows,
            reviews=page["items"],
            hold_reasons=[outcome["reason"]] if outcome.get("reason") else [],
            pipeline=outcome,
            page_map=selected_pages,
        )


def result_snapshot(path: Path, tenant: str, selected_pages: list[int]) -> bytes:
    """Replay once at publication; subsequent reads hash these exact source bytes."""
    result = read_result(path, tenant, selected_pages)
    sources = {
        str(source.relative_to(path)): hashlib.sha256(source.read_bytes()).hexdigest()
        for source in sorted((path / "objects" / "original").rglob("*"))
        if source.is_file()
    }
    return json.dumps(
        dict(tenant_id=tenant, page_map=selected_pages, source_hashes=sources, result=result),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


def resolve_review(path, auth, review, body, if_match, key):
    with services(path, auth.tenant_id) as (run, claims, tags, reviews):
        try:
            record = reviews.store.get(auth.tenant_id, review)
            if record["run_id"] != run:
                raise HostedError("RESOURCE_NOT_FOUND", 404)
            return reviews.resolve_review(auth, review, body, if_match, key)
        except ReviewRejected as exc:
            raise HostedError(exc.code, exc.status) from None
        except (ValueError, KeyError, TypeError):
            raise HostedError("REVIEW_INPUT_UNAVAILABLE", 409) from None


def clear_receipt_caches():
    """Purge process-local source readings without touching frozen reader code."""
    from proofops_api.hosted_reads import clear_source_cache

    clear_source_cache()
    from proofops.adapters.local import native_replay_cache as cache

    with cache._lock:
        for name in (
            "_replays",
            "_raster_replays",
            "_claim_replays",
            "_claim_attestations",
            "_claim_wrapper_receipts",
        ):
            getattr(cache, name).clear()
