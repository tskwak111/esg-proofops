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
    from proofops.application.tagging.fact_assembly_c3 import PROFILE as C3_PROFILE
    from proofops.application.tagging.fact_assembly_c3_v2 import PROFILE as C3_V2_PROFILE
    from proofops.application.tagging.fact_assembly_c4 import PROFILE as C4_PROFILE

    if manifest.get("publication_profile") == C4_PROFILE:
        from proofops.adapters.local.c4_publication import LocalC4Publication

        publication = LocalC4Publication(path)
        yield manifest["run_id"], None, publication, publication.service
        return

    if manifest.get("publication_profile") in (C3_PROFILE, C3_V2_PROFILE):
        from proofops.adapters.local.c3_publication import LocalC3Publication

        publication = LocalC3Publication(path)
        yield manifest["run_id"], None, publication, publication.service
        return
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
    result = _read_result(path, tenant, selected_pages)
    bounded = path / "bounded-c3"
    if (bounded / "pilot.json").is_file():
        if bounded.is_symlink() or 36 not in selected_pages:
            raise HostedError("C3_SOURCE_PAGE_MISMATCH", 409)
        extra = _read_result(bounded, tenant, [36])
        for claim in extra["claims"]:
            claim["page_num"] = selected_pages.index(36) + 1
        result["claims"].extend(extra["claims"])
        result["reviews"].extend(extra["reviews"])
    return result


def _read_result(path: Path, tenant: str, selected_pages: list[int]) -> dict:
    from proofops.application.tagging.fact_assembly_c3 import PROFILE as C3_PROFILE
    from proofops.application.tagging.fact_assembly_c3_v2 import PROFILE as C3_V2_PROFILE
    from proofops.application.tagging.fact_assembly_c4 import PROFILE as C4_PROFILE

    if (path / "pilot.json").is_file():
        manifest = json.loads((path / "pilot.json").read_text())
        if manifest.get("publication_profile") == C4_PROFILE:
            if manifest["tenant_id"] != tenant:
                raise HostedError("RESOURCE_NOT_FOUND", 404)
            if selected_pages != manifest["selected_pages"]:
                raise HostedError("C4_SOURCE_PAGE_MISMATCH", 409)
            from proofops.adapters.local.c4_publication import LocalC4Publication

            return LocalC4Publication(path).result(tenant, manifest["run_id"], manifest["claim_id"])
        if manifest.get("publication_profile") in (C3_PROFILE, C3_V2_PROFILE):
            if manifest["tenant_id"] != tenant:
                raise HostedError("RESOURCE_NOT_FOUND", 404)
            if selected_pages != [36]:
                raise HostedError("C3_SOURCE_PAGE_MISMATCH", 409)
            from proofops.adapters.local.c3_publication import LocalC3Publication

            return LocalC3Publication(path).result(tenant, manifest["run_id"], manifest["claim_id"])
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
        from proofops.application.analysis_profile import (
            FINALS_C24_POLICY,
            FINALS_E05_POLICY,
            FINALS_F1_INITIAL_POLICY,
            FINALS_F1_POLICY,
            FINALS_F1_TRANSPORT_POLICY,
            FINALS_H4_POLICY,
            FINALS_H6_POLICY,
            FINALS_I7_POLICY,
            FINALS_I8_POLICY,
            FINALS_I9_POLICY,
            FINALS_I10_POLICY,
            FINALS_I11_POLICY,
            FINALS_K10_POLICY,
            FINALS_K10_V2_POLICY,
            FINALS_Q1_POLICY,
            QT1_POLICY,
            S4_POLICY,
        )
        from proofops.application.provider_resilience import PROJECTION_POLICY, claim_hold_reason
        from proofops.domain.provenance import canonical_hash

        f1 = tag_snapshot.get("analysis_profile_policy_sha256") in {
            canonical_hash(FINALS_H4_POLICY),
            canonical_hash(FINALS_H6_POLICY),
            canonical_hash(FINALS_C24_POLICY),
            canonical_hash(FINALS_I10_POLICY),
            canonical_hash(FINALS_I11_POLICY),
            canonical_hash(FINALS_K10_POLICY),
            canonical_hash(FINALS_K10_V2_POLICY),
            canonical_hash(FINALS_Q1_POLICY),
            canonical_hash(FINALS_E05_POLICY),
            canonical_hash(FINALS_F1_INITIAL_POLICY),
            canonical_hash(FINALS_F1_POLICY),
            canonical_hash(FINALS_F1_TRANSPORT_POLICY),
            canonical_hash(FINALS_I7_POLICY),
            canonical_hash(FINALS_I8_POLICY),
            canonical_hash(FINALS_I9_POLICY),
            canonical_hash(S4_POLICY),
        }
        if f1:
            for cid, projection in projections.items():
                if reason := claim_hold_reason(projection):
                    reasons[cid] = reason
            # Each newly published result identifies its display contract. Old
            # result snapshots continue to be served by their immutable bytes.
            outcome = outcome | dict(
                provider_failure_projection_sha256=canonical_hash(PROJECTION_POLICY)
            )
        # The publisher holds analysis.lock; these source artifacts cannot change
        # while building this snapshot. Replay all source guards once, then retain
        # the same graph for every claim's identity-checked missing-evidence search.
        extraction_checkpoint, discovery, original_graph = evidence
        # Older claim-store facades retain their existing result contract.
        # The concrete store's projection checks the admitted checkpoint hash.
        if project_outcome := getattr(claims, "outcome_projection", None):
            outcome = outcome | project_outcome(
                tenant, run, admitted_checkpoint=extraction_checkpoint
            )
            from proofops.application.rb4_memory import enabled as rb4_memory_enabled

            if rb4_memory_enabled(claims.store.snapshot(tenant, run)):
                # Source replay, tag pins and outcome admission are complete.
                # Legacy facades without outcome admission keep their contract.
                del evidence, extraction_checkpoint
        from proofops.application.analysis_profile import (
            CF6_POLICY,
            CF6_V2_POLICY,
            FINALS_I1_INITIAL_POLICY,
            FINALS_I3_POLICY,
            FINALS_I4_POLICY,
            FINALS_I5_POLICY,
            FINALS_I6_POLICY,
            FINALS_I23_POLICY,
            FINALS_I26_POLICY,
            FINALS_I27_POLICY,
            FINALS_I27_PRE_RB2_POLICY,
            FINALS_I28_POLICY,
            FINALS_I29_INITIAL_POLICY,
            FINALS_I29_POLICY,
            FINALS_I29B_POLICY,
            FINALS_I30_POLICY,
            S1_POLICY,
            S2_POLICY,
            S5_LIVE_POLICY,
            SPE_POLICY,
            SPG_POLICY,
            SPP_POLICY,
            SPT_POLICY,
            V2_D24_POLICY,
            V2_PA9_POLICY,
            V2_PB1_COMPACT_POLICY,
            V2_PB1_INITIAL_POLICY,
            V2_PB1_POLICY,
            V2_PB2_ALL_CLAIMS_POLICY,
            V2_PB2_INITIAL_POLICY,
            V2_PB2_POLICY,
            V2_PB4_POLICY,
            V2_PB7_POLICY,
            V2_POLICY,
            V2_PRE_D24_POLICY,
            V2_PRE_PA7_POLICY,
            V2_PRE_PA8_POLICY,
            V2_PRE_PA9_POLICY,
            V2_PRE_PB4_POLICY,
            V2_PRE_W8_POLICY,
            V2_PRE_W9_POLICY,
            V2_W8_POLICY,
            V2_W9_POLICY,
            W3_POLICY,
        )
        from proofops.application.ingest.pb1_tables import occurrence_groups
        from proofops.application.ingest.w9_tables import observations_for
        from proofops.domain.provenance import canonical_hash

        pb1 = tag_snapshot.get("analysis_profile_policy_sha256") in {
            canonical_hash(CF6_POLICY),
            canonical_hash(CF6_V2_POLICY),
            canonical_hash(FINALS_H4_POLICY),
            canonical_hash(FINALS_H6_POLICY),
            canonical_hash(FINALS_C24_POLICY),
            canonical_hash(FINALS_Q1_POLICY),
            canonical_hash(FINALS_E05_POLICY),
            canonical_hash(FINALS_F1_INITIAL_POLICY),
            canonical_hash(FINALS_F1_POLICY),
            canonical_hash(FINALS_F1_TRANSPORT_POLICY),
            canonical_hash(S2_POLICY),
            canonical_hash(S4_POLICY),
            canonical_hash(V2_POLICY),
            canonical_hash(S5_LIVE_POLICY),
            canonical_hash(SPT_POLICY),
            canonical_hash(SPE_POLICY),
            canonical_hash(SPG_POLICY),
            canonical_hash(FINALS_I26_POLICY),
            canonical_hash(FINALS_I27_POLICY),
            canonical_hash(FINALS_I27_PRE_RB2_POLICY),
            canonical_hash(FINALS_I28_POLICY),
            canonical_hash(FINALS_I30_POLICY),
            canonical_hash(FINALS_I29B_POLICY),
            canonical_hash(FINALS_I29_POLICY),
            canonical_hash(FINALS_I29_INITIAL_POLICY),
            canonical_hash(SPP_POLICY),
            canonical_hash(FINALS_I23_POLICY),
            canonical_hash(QT1_POLICY),
            canonical_hash(FINALS_I10_POLICY),
            canonical_hash(FINALS_K10_POLICY),
            canonical_hash(FINALS_K10_V2_POLICY),
            canonical_hash(FINALS_I8_POLICY),
            canonical_hash(FINALS_I3_POLICY),
            canonical_hash(FINALS_I4_POLICY),
            canonical_hash(FINALS_I5_POLICY),
            canonical_hash(FINALS_I6_POLICY),
            canonical_hash(S1_POLICY),
            canonical_hash(FINALS_I1_INITIAL_POLICY),
            canonical_hash(V2_D24_POLICY),
            canonical_hash(V2_W9_POLICY),
            canonical_hash(W3_POLICY),
            canonical_hash(V2_PRE_W9_POLICY),
            canonical_hash(V2_PRE_W8_POLICY),
            canonical_hash(V2_W8_POLICY),
            canonical_hash(V2_PRE_D24_POLICY),
            canonical_hash(V2_PA9_POLICY),
            canonical_hash(V2_PB7_POLICY),
            canonical_hash(V2_PRE_PA7_POLICY),
            canonical_hash(V2_PRE_PA8_POLICY),
            canonical_hash(V2_PRE_PA9_POLICY),
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
        from proofops.adapters.local.spg_search_projection import begin as spg_projection
        from proofops.application.evidence.span_citations import verify_source_ref

        search_projection = (
            spg_projection(claims, tenant, run, original_graph)
            if hasattr(claims.store, "snapshot")
            else None
        )
        current_tags = None
        if search_projection is not None:
            with claims.store.jobs._transaction() as db:
                current_tags = {
                    c.claim_id: claims.current_tag(tenant, run, c.claim_id, connection=db)
                    for c in discovery.claims
                }

        for claim in discovery.claims:
            current = (
                current_tags[claim.claim_id]
                if current_tags is not None
                else claims.current_tag(tenant, run, claim.claim_id)
            )
            summary = claims.summary(claim, current)
            if tag_snapshot.get("analysis_profile_policy_sha256") == canonical_hash(QT1_POLICY):
                from proofops.application.ingest.qt1_tables import candidates_for

                ref = claim.source_refs[0]
                table = blocks[ref.source_id]
                summary["qt1_table_recovery"] = [
                    r
                    for r in candidates_for(table, original_graph)
                    if r["start"] <= ref.char_start < ref.char_end <= r["end"]
                ]
            if pb1:
                summary["duplicate_occurrences"] = groups.get(
                    canonical_hash(" ".join(claim.quote.split())), [claim.claim_id]
                )
                ref = claim.source_refs[0]
                block = blocks[ref.source_id]
                if block.kind == "table" and block.winner is not None:
                    row = next(
                        (
                            r
                            for r in observations_for(block, original_graph)
                            if r["start"] <= ref.char_start < ref.char_end <= r["end"]
                        ),
                        None,
                    )
                    if row:
                        summary["table_observation"] = row
                        if tag_snapshot.get("analysis_profile_policy_sha256") in {
                            canonical_hash(CF6_POLICY),
                            canonical_hash(CF6_V2_POLICY),
                            canonical_hash(FINALS_H4_POLICY),
                            canonical_hash(FINALS_H6_POLICY),
                            canonical_hash(FINALS_C24_POLICY),
                            canonical_hash(FINALS_Q1_POLICY),
                            canonical_hash(FINALS_E05_POLICY),
                            canonical_hash(FINALS_F1_INITIAL_POLICY),
                            canonical_hash(FINALS_F1_POLICY),
                            canonical_hash(FINALS_F1_TRANSPORT_POLICY),
                            canonical_hash(S2_POLICY),
                            canonical_hash(S4_POLICY),
                            canonical_hash(V2_POLICY),
                            canonical_hash(S5_LIVE_POLICY),
                            canonical_hash(SPT_POLICY),
                            canonical_hash(SPE_POLICY),
                            canonical_hash(SPG_POLICY),
                            canonical_hash(FINALS_I26_POLICY),
                            canonical_hash(FINALS_I27_POLICY),
                            canonical_hash(FINALS_I27_PRE_RB2_POLICY),
                            canonical_hash(FINALS_I28_POLICY),
                            canonical_hash(FINALS_I30_POLICY),
                            canonical_hash(FINALS_I29B_POLICY),
                            canonical_hash(FINALS_I29_POLICY),
                            canonical_hash(FINALS_I29_INITIAL_POLICY),
                            canonical_hash(SPP_POLICY),
                            canonical_hash(FINALS_I23_POLICY),
                            canonical_hash(QT1_POLICY),
                            canonical_hash(FINALS_I10_POLICY),
                            canonical_hash(FINALS_K10_POLICY),
                            canonical_hash(FINALS_K10_V2_POLICY),
                            canonical_hash(FINALS_I8_POLICY),
                            canonical_hash(FINALS_I3_POLICY),
                            canonical_hash(FINALS_I4_POLICY),
                            canonical_hash(FINALS_I5_POLICY),
                            canonical_hash(FINALS_I6_POLICY),
                            canonical_hash(S1_POLICY),
                            canonical_hash(FINALS_I1_INITIAL_POLICY),
                            canonical_hash(V2_D24_POLICY),
                            canonical_hash(V2_W9_POLICY),
                            canonical_hash(W3_POLICY),
                            canonical_hash(V2_PRE_W9_POLICY),
                            canonical_hash(V2_PRE_W8_POLICY),
                            canonical_hash(V2_W8_POLICY),
                            canonical_hash(V2_PRE_D24_POLICY),
                            canonical_hash(V2_PA9_POLICY),
                            canonical_hash(V2_PB7_POLICY),
                            canonical_hash(V2_PRE_PA7_POLICY),
                            canonical_hash(V2_PRE_PA8_POLICY),
                            canonical_hash(V2_PRE_PA9_POLICY),
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
                if f1 and reasons.get(claim.claim_id) in {
                    "PROVIDER_PROCESSING_FAILED",
                    "PROVIDER_CIRCUIT_OPEN",
                }:
                    summary["pipeline_status"] = "needs_review"
                    summary["decision"] = decision = None
            if "rb1_input_hold" in projection:
                summary["rb1_input_hold"] = projection["rb1_input_hold"]
            # SC1 is a separate additive result, preserving legacy grade semantics.
            if "sc1_confirmation" in projection:
                summary.update(
                    {
                        k: projection.get(k)
                        for k in (
                            "sc1_confirmation",
                            "sc1_elements",
                            "sc1_hold_reason",
                        )
                    }
                )
            if "cf6_confirmation" in projection:
                summary["cf6_confirmation"] = projection["cf6_confirmation"]
                if decision is None and projection["cf6_confirmation"] is not None:
                    decision = projection["cf6_confirmation"]
                    summary["decision"] = decision
                summary["cf6_status"] = (
                    "confirmed" if (decision or {}).get("evidence_grade") else "held"
                )
                summary["cf6_elements"] = projection.get("cf6_receipt", {}).get("elements", [])
                summary["cf6_hold_reasons"] = projection.get("cf6_receipt", {}).get(
                    "reasons", [projection.get("reason") or "CF6_TAGGING_INCOMPLETE"]
                )
                summary["cf6_track"] = (
                    projection.get("frozen_packet", {}).get("track")
                    if projection["cf6_confirmation"] is not None
                    else None
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
        if search_projection is not None:
            search_projection.finish()
        page = reviews.store.page(tenant, run, cursor=None, limit=100, now=0, cursors=claims.store)
        return dict(
            schema="r108-hosted-result-v1",
            claims=rows,
            reviews=page["items"],
            hold_reasons=list(
                dict.fromkeys(
                    ([outcome["reason"]] if outcome.get("reason") else [])
                    + (
                        [outcome["extraction_outcome"]["code"]]
                        if outcome.get("extraction_outcome", {}).get("code") not in (None, "OK")
                        else []
                    )
                )
            ),
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
    if (path / "c3-evidence.json").is_file():
        for name in ("original.pdf", "c3-evidence.json", "pilot.json"):
            sources[name] = hashlib.sha256((path / name).read_bytes()).hexdigest()
    if (path / "c4-evidence.json").is_file():
        for name in ("original.pdf", "c4-evidence.json", "pilot.json"):
            sources[name] = hashlib.sha256((path / name).read_bytes()).hexdigest()
    if (path / "bounded-c3" / "pilot.json").is_file():
        for name in ("original.pdf", "c3-evidence.json", "pilot.json"):
            key = "bounded-c3/" + name
            sources[key] = hashlib.sha256((path / key).read_bytes()).hexdigest()
    return json.dumps(
        dict(tenant_id=tenant, page_map=selected_pages, source_hashes=sources, result=result),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


def resolve_review(path, auth, review, body, if_match, key):
    bounded = path / "bounded-c3"
    if (bounded / "pilot.json").is_file():
        extra = _read_result(bounded, auth.tenant_id, [36])
        if any(row["review_id"] == review for row in extra["reviews"]):
            path = bounded
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
    from proofops.adapters.local.pa7_raster_cache import clear as clear_raster_cache

    clear_raster_cache()
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
