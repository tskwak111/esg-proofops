"""F8 saved-packet audit and opt-in element-only evaluation; USD0.30 hard cap.

Original artifacts are hashed and read only. Source replay runs in a private copy.
The whole cap is reserved in the R108 cumulative ledger before dispatch, and each
sequential call must fit its existing USD0.02 provider worst-case reservation.
No extraction, classification, relations, majority promotion or publication.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from proofops.adapters.aws.usage import LocalSQLiteUsageStore
from proofops.adapters.cache.aws import ImmutableResponseCache, InMemoryImmutableCacheClient
from proofops.adapters.local.claim_store import LocalClaimStore
from proofops.adapters.local.decisions import load_key
from proofops.adapters.local.glyph_display_text import GlyphDisplayCatalog
from proofops.adapters.local.openrouter import OpenRouterProbe
from proofops.adapters.local.run_store import LocalSQLiteRunStore
from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
from proofops.application.budget import BudgetLimits, RoleLimit, TokenUsage
from proofops.application.evidence.binding import ClaimContext, accept_binding, relation_tags_for
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.ports.models import ModelBinding
from proofops.application.preflight import Check, Preflight
from proofops.application.registry import Registry
from proofops.application.tagging.consensus import form_consensus
from proofops.application.tagging.service import RawTagResponse, TaggingSettings, tag_replicates
from proofops.application.tagging.tracks import TrackCandidate
from proofops.application.uploads import UploadService
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.values import SourceRef
from proofops_agent.upstage_tagging import CONSISTENCY_PROFILE, UpstageTaggingTransport

ROOT = Path("/path/to/ESG_ProofOps")
SOURCE = ROOT / ".local/r108-finals.INGDai/live"
LAB = ROOT / "outputs/agent-results/R108-redesign/lab/perf"
SPEND = ROOT / "outputs/agent-results/R108-redesign/lab/sprint3/E2E/r108-spend.json"
LEDGER = ROOT / ".local/openrouter/budget.sqlite3"
CAP = Decimal("0.30")
TASK = "perf-Q2"


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2))
    path.chmod(0o600)


def protected():
    return {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE.rglob("*") if p.is_file()
    }


def load():
    with sqlite3.connect(SOURCE.joinpath("state.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        artifacts = [
            json.loads(row[0])
            for row in db.execute("SELECT value FROM job_records WHERE kind='artifact'")
        ]
    tagging = next(a for a in artifacts if "tagging_settings" in a)
    receipts = {
        d["request"]["request_id"]: d
        for p in SOURCE.glob("tagging-receipts/*/elements/*/request.json")
        if (d := json.loads(p.read_text()))
    }
    claims = [i for i in tagging["claims"] if i.get("tag_runs")]
    assert len(claims) == 17 and sum(len(i["tag_runs"]) for i in claims) == 51
    return tagging, receipts, claims


def source_replay(tagging):
    copy = Path(".local/q2-saved-inputs")
    if not copy.exists():
        shutil.copytree(SOURCE, copy)
    db = copy / "state.sqlite3"
    store = LocalSQLiteRunStore(db)
    uploads = UploadService(db, copy / "objects", Registry.sqlite(db))
    parser = OpenDataLoaderParser(copy / "parser-prepared")
    _, discovery, graph = LocalClaimStore(store, uploads, parser).load_evidence(
        tagging["tenant_id"], tagging["run_id"]
    )
    assert {
        i["review_inputs"]["original"]["graph_sha256"]
        for i in tagging["claims"]
        if i.get("tag_runs")
    } == {canonical_hash(asdict(graph))}
    source = uploads.read_original(graph.tenant_id, graph.document_version_id)
    return {c.claim_id: c for c in discovery.claims}, graph, GlyphDisplayCatalog(graph, source)


def objects(item, claim):
    raw = item["review_inputs"]
    context = ClaimContext(
        claim, {k: SourceRef(**v) if v else None for k, v in raw["dimensions"].items()}
    )
    relations = {
        sid: {k: SourceRef(**v) if v else None for k, v in roles.items()}
        for sid, roles in raw["relation_tags"].items()
    }
    packet = freeze_packet({k: v for k, v in raw["packet"].items() if k != "packet_sha256"})
    assert packet.packet_sha256 == raw["packet_sha256"]
    return context, relations, packet, RulePackSnapshot(**raw["rulepack"])


def audit(items, receipts, claims, graph):
    rows, downgrades, all_requests = [], [], []
    for item in items:
        context, relations, packet, rulepack = objects(item, claims[item["claim_id"]])
        requests = [receipts[r["request"]["request_id"]] for r in item["tag_runs"]]
        data = [json.loads(r["request"]["user_json"])["untrusted_document_data"] for r in requests]
        all_requests.append(
            dict(
                claim_id=item["claim_id"],
                document_data_identical=data[0] == data[1] == data[2],
                wire_system_identical=len({r["wire_system"] for r in requests}) == 1,
                catalog_identical=len({canonical_hash(r["evidence_refs"]) for r in requests}) == 1,
                temperatures=[r["request"]["temperature"] for r in requests],
                seed_present=["seed" in r["request"] for r in requests],
                quote_lengths=[len(q["quote"]) for q in requests[0]["evidence_refs"].values()],
                duplicate_quotes=len(requests[0]["evidence_refs"])
                - len({q["quote"] for q in requests[0]["evidence_refs"].values()}),
            )
        )
        for eid in packet.to_dict()["allowed_elements"]:
            raw = [
                next(
                    e
                    for e in json.loads(r["raw_response_json"])["elements"]
                    if e["element_id"] == eid
                )
                for r in item["tag_runs"]
            ]
            guarded = [
                next(e for e in r["guarded"]["elements"] if e["element_id"] == eid)
                for r in item["tag_runs"]
            ]
            row = dict(
                claim_id=item["claim_id"],
                element_id=eid,
                raw=raw,
                guarded=guarded,
                requests=[r["request"]["request_id"] for r in requests],
            )
            if len({e["state"] for e in guarded}) > 1:
                row["selected_span_in_all_catalogs"] = all(
                    any(
                        q["source_id"] == ref["source_id"]
                        and q["char_start"] <= ref["char_start"] < ref["char_end"] <= q["char_end"]
                        for q in request["evidence_refs"].values()
                    )
                    for e in raw
                    for ref in e["evidence_refs"]
                    for request in requests
                )
                rows.append(row)
            if all(e["state"] == "unknown" for e in guarded) and any(
                e["state"] == "present" for e in raw
            ):
                reasons = []
                for e in raw:
                    if e["state"] != "present":
                        continue
                    for ref in e["evidence_refs"]:
                        typed = SourceRef(**ref)
                        verified = verify_source_ref(typed, graph, tenant_id=graph.tenant_id)
                        binding = accept_binding(
                            context,
                            verified,
                            relation_tags_for(verified, relations),
                            original=graph,
                            tenant_id=graph.tenant_id,
                            rulepack=rulepack,
                            element_id=eid,
                        )
                        reasons.append(
                            dict(
                                source_id=ref["source_id"],
                                quote=ref["quote"],
                                verification_state=verified.verification_state,
                                binding=binding,
                                claim_dimensions={
                                    k: v.quote if v else None for k, v in context.dimensions.items()
                                },
                                evidence_dimensions={
                                    k: v.quote if v else None
                                    for k, v in (
                                        relation_tags_for(verified, relations) or {}
                                    ).items()
                                },
                            )
                        )
                downgrades.append(row | {"guard_checks": reasons})
    return dict(requests=all_requests, flips=rows, unanimous_unknown_guard_downgrades=downgrades)


def summary(items, graph):
    unanimous = total = present = literal = refs_total = unresolved = unknown = 0
    state_flips = citation_differences = empty_vs_citation = raw_refs = raw_verified = 0
    guard_downgrades = 0
    for item in items:
        runs = item["tag_runs"]
        unresolved += "REPLICA_UNRESOLVED" in item["review_inputs"]["consensus"]["reasons"]
        for eid in item["review_inputs"]["packet"]["allowed_elements"]:
            elements = [
                next(e for e in (r["guarded"] or {}).get("elements", []) if e["element_id"] == eid)
                if r["guarded"]
                else None
                for r in runs
            ]
            total += 1
            if all(elements):
                state_flips += len({e["state"] for e in elements}) > 1
                cites = [e["evidence_refs"] for e in elements]
                citation_differences += len({canonical_hash(c) for c in cites}) > 1
                empty_vs_citation += any(not c for c in cites) and any(c for c in cites)
            keys = [
                (e["state"], e["normalized_value"], dict(r["binding_hashes"]).get(eid))
                for e, r in zip(elements, runs, strict=True)
                if e
            ]
            unanimous += len(keys) == 3 and len(set(keys)) == 1
            unknown += len(keys) == 3 and all(k[0] == "unknown" for k in keys)
            present += len(keys) == 3 and all(k[0] == "present" for k in keys)
        for run in runs:
            raw = json.loads(run["raw_response_json"] or "{}")
            states = {
                e["element_id"]: e["state"] for e in (run["guarded"] or {}).get("elements", [])
            }
            for element in raw.get("elements", []):
                guard_downgrades += (
                    element["state"] == "present" and states.get(element["element_id"]) != "present"
                )
                for ref in element["evidence_refs"]:
                    raw_refs += 1
                    raw_verified += (
                        verify_source_ref(
                            SourceRef(**ref), graph, tenant_id=graph.tenant_id
                        ).verification_state
                        == "verified"
                    )
            for element in (run["guarded"] or {}).get("elements", []):
                if element["state"] != "present":
                    continue
                for ref in element["evidence_refs"]:
                    refs_total += 1
                    literal += (
                        verify_source_ref(
                            SourceRef(**ref), graph, tenant_id=graph.tenant_id
                        ).verification_state
                        == "verified"
                    )
    return dict(
        elements=total,
        state_flips=state_flips,
        citation_differences=citation_differences,
        empty_vs_citation=empty_vs_citation,
        raw_citations=raw_refs,
        raw_citations_verified=raw_verified,
        raw_citation_validation_ratio=raw_verified / raw_refs if raw_refs else None,
        guard_downgrades=guard_downgrades,
        unanimous=unanimous,
        unanimous_ratio=unanimous / total,
        unanimous_unknown=unknown,
        unanimous_present=present,
        replica_unresolved_claims=unresolved,
        unavailable_replicas=sum(r["guarded"] is None for item in items for r in item["tag_runs"]),
        present_citations=refs_total,
        present_citations_verified=literal,
        citation_validation_ratio=literal / refs_total if refs_total else None,
    )


def present_changes(before, after):
    def selected(items):
        return {
            (item["claim_id"], eid)
            for item in items
            for eid in item["review_inputs"]["packet"]["allowed_elements"]
            if all(
                run["guarded"]
                and any(
                    e["element_id"] == eid and e["state"] == "present"
                    for e in run["guarded"]["elements"]
                )
                for run in item["tag_runs"]
            )
        }

    old, new = selected(before), selected(after)
    return dict(gained=sorted(new - old), lost=sorted(old - new))


def reserve(settle=None):
    with SPEND.with_suffix(".decisions.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(SPEND.read_text())
        total, limit = Decimal(data["cumulative_usd"]), Decimal(data["limit_usd"])
        assert total.is_finite() and limit.is_finite() and 0 <= total and 0 < limit <= 10
        entries = data.setdefault("executions", [])
        prior = [e for e in entries if e.get("task") == TASK]
        if settle is None:
            if prior:
                raise ValueError("Q2_ALREADY_RESERVED_NO_AUTOMATIC_RETRY")
            # Retain historical uncertain calls even if not in cumulative accounting.
            pending = Decimal(0)
            recorded = data.get("decision_reservations", {})
            for provider in ("openrouter", "upstage"):
                path = ROOT / ".local" / provider / "budget.sqlite3"
                with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
                    for rid, amount in db.execute(
                        "SELECT request_id,committed FROM probe_calls WHERE receipt IS NULL"
                    ):
                        if not any(
                            k.endswith(":" + rid) and Path(v["ledger"]) == path
                            for k, v in recorded.items()
                        ):
                            pending += Decimal(amount)
            if total + CAP + pending > limit:
                raise ValueError("R108_BUDGET_EXHAUSTED")
            entries.append(
                dict(
                    task=TASK,
                    status="reserved",
                    limit_usd=str(CAP),
                    delta_usd=str(CAP),
                    reserved_usd=str(CAP),
                    ledger=str(LEDGER),
                )
            )
            data["cumulative_usd"] = str(total + CAP)
        else:
            assert len(prior) == 1 and prior[0]["status"] == "reserved"
            amount = Decimal(settle["committed_usd"])
            assert 0 <= amount <= CAP
            prior[0].update(settle, reserved_usd="0", delta_usd=str(amount))
            data["cumulative_usd"] = str(total - CAP + amount)
        tmp = SPEND.with_suffix(".q2.tmp")
        write(tmp, data)
        with tmp.open("r") as stream:
            os.fsync(stream.fileno())
        tmp.replace(SPEND)


def evaluate(items, claims, graph, catalog, settings, probe, output, *, paid):
    result = []
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    usage = LocalSQLiteUsageStore(output / "usage.sqlite3")
    usage.create_budget(
        graph.tenant_id,
        items[0]["review_inputs"]["run_id"],
        graph.document_version_id,
        BudgetLimits(
            2_000_000, 300_000, (RoleLimit("tagger", 51, 32768, 4096, 36864),), max_attempts=1
        ),
    )
    dispatched, committed = [], Decimal(0)
    for item in items:
        context, relations, packet, rulepack = objects(item, claims[item["claim_id"]])
        originals = {r["request"]["replicate_id"]: r for r in item["tag_runs"]}
        auth_names = (
            "runtime_approval",
            "consent_approval",
            "model_binding",
            "document_scope",
            "document_rights",
            "data_consent",
            "tagging_settings",
            "selected_document_rights",
        )

        def authorize(selected, request):
            assert selected == settings and request["claim_id"] == item["claim_id"]
            assert request["packet_sha256"] == packet.packet_sha256
            return Preflight(
                True,
                tuple(
                    Check(n, "pass", "perf-Q2 explicit saved-input evaluation") for n in auth_names
                ),
                settings.model_sha256,
                "2026-10-09",
            )

        adapter = UpstageTaggingTransport(
            probe,
            output / "receipts",
            settings=settings,
            tenant_id=graph.tenant_id,
            authorize=authorize,
            display_catalog=catalog,
        )

        def invoke(request):
            nonlocal committed
            if not paid:
                old = originals[request["replicate_id"]]
                return RawTagResponse(
                    old["raw_response_json"],
                    TokenUsage(**old["usage"]),
                    False,
                    old["provider_response_json"],
                )
            if committed + Decimal("0.02") > CAP:
                raise ValueError("Q2_CAP_EXHAUSTED")
            dispatched.append(request["request_id"])
            response = adapter.invoke(request)
            with sqlite3.connect(LEDGER) as db:
                amount = db.execute(
                    "SELECT committed FROM probe_calls WHERE request_id=?", (request["request_id"],)
                ).fetchone()
            if amount:
                committed += Decimal(amount[0])
            if response.usage.status != "succeeded":
                raise ValueError("Q2_TRANSPORT_STOPPED_NO_RETRY")
            return response

        runs = tag_replicates(
            packet,
            context=context,
            track=TrackCandidate(
                context.claim, packet.to_dict()["track"], packet.to_dict()["safe_harbor_category"]
            ),
            original=graph,
            relation_tags=relations,
            rulepack=rulepack,
            settings=settings,
            cache=ImmutableResponseCache(InMemoryImmutableCacheClient()),
            usage_store=usage,
            invoke=invoke,
            tenant_id=graph.tenant_id,
            ensemble_id=str(uuid4()),
            consent_profile="perf-Q2-explicit-evaluation",
            token_counter=lambda text: 32768,
            count_input_tokens=lambda request: adapter.count_input_tokens(
                request, counter=lambda s, u: 32768
            ),
            now=lambda: 1791504000,
        )
        if any(r.usage and r.usage.status == "failed" for r in runs):
            raise ValueError("Q2_TRANSPORT_STOPPED_NO_RETRY")
        if not paid:
            assert [asdict(r.guarded) for r in runs] == [
                asdict_tuples(r["guarded"]) for r in item["tag_runs"]
            ]
        consensus = form_consensus(
            runs, packet=packet, rulepack=rulepack, tenant_id=graph.tenant_id, tag_revision=1
        )
        out = dict(
            claim_id=item["claim_id"],
            tag_runs=[asdict(r) for r in runs],
            review_inputs=dict(packet=packet.to_dict(), consensus=asdict(consensus)),
        )
        result.append(out)
        write(output / "results.json", result)
        print(
            f'{"paid" if paid else "replay"} {len(result)}/17 committed_usd={committed}', flush=True
        )
    return result, dispatched


def asdict_tuples(raw):
    from proofops.domain.values import llm_tags_from_dict

    return asdict(llm_tags_from_dict(raw))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--invoke", action="store_true")
    args = parser.parse_args()
    hashes = protected()
    tagging, receipts, items = load()
    claims, graph, catalog = source_replay(tagging)
    investigation = audit(items, receipts, claims, graph)
    write(LAB / "Q2-root-cause.json", investigation)
    baseline = summary(items, graph)
    print(
        "audit",
        json.dumps(
            dict(
                flips=len(investigation["flips"]),
                downgrades=len(investigation["unanimous_unknown_guard_downgrades"]),
                baseline=baseline,
            )
        ),
        flush=True,
    )
    raw = tagging["tagging_settings"]
    old = TaggingSettings(**(raw | {"binding": ModelBinding(**raw["binding"])}))
    new = replace(old, model_profile=CONSISTENCY_PROFILE)
    # Fake credential validates local wire sizes only; never used in dispatch.
    dry_probe = OpenRouterProbe("offline-wire-only", Path(".local/q2-offline/budget.sqlite3"))
    dry_output = Path(".local/q2-offline/replay")
    if not (dry_output / "results.json").exists():
        evaluate(items, claims, graph, catalog, old, dry_probe, dry_output, paid=False)
    wire_sizes = []
    for item in items:
        saved = receipts[item["tag_runs"][0]["request"]["request_id"]]
        request = saved["request"] | dict(
            model_profile=new.model_profile,
            system_prompt=new.system_for_track(
                item["review_inputs"]["packet"]["track"],
                item["review_inputs"]["packet"]["safe_harbor_category"],
            ),
        )
        assert saved["authorization"]["ready"]
        author = Preflight(
            **(
                saved["authorization"]
                | {"checks": tuple(Check(**c) for c in saved["authorization"]["checks"])}
            )
        )
        adapter = UpstageTaggingTransport(
            dry_probe,
            Path(".local/q2-offline/wire"),
            settings=new,
            tenant_id=graph.tenant_id,
            authorize=lambda s, r: author,
            display_catalog=catalog,
        )
        system, user, _, _, _ = adapter._wire_request(request)
        body = dry_probe.request_body(
            system, user, request_id=request["request_id"], max_tokens=4096, json_mode=True
        )
        wire_sizes.append(len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()))
        assert adapter.TRANSPORT_VERSION == "compact-element-consistency-v6"
    report = dict(
        profile=CONSISTENCY_PROFILE,
        baseline=baseline,
        wire_bytes=wire_sizes,
        input_hashes=hashes,
        original_unchanged=protected() == hashes,
        paid=False,
    )
    write(LAB / "Q2-preflight-analysis.json", report)
    if not args.invoke:
        print("free preflight complete", max(wire_sizes), flush=True)
        return
    output = Path(".local/q2-paid")
    if output.exists():
        raise ValueError("Q2_OUTPUT_EXISTS_NO_AUTOMATIC_RETRY")
    key = load_key("openrouter", ROOT)
    probe = OpenRouterProbe(key, LEDGER, wire_policy_version=old.wire_policy_version)
    reserve()
    output.mkdir(mode=0o700, parents=True)
    before = probe.summary()
    try:
        results, dispatched = evaluate(items, claims, graph, catalog, new, probe, output, paid=True)
        report.update(
            paid=True,
            new=summary(results, graph),
            paid_calls=len(dispatched),
            unanimous_present_changes=present_changes(items, results),
            results_path=str(output.resolve() / "results.json"),
        )
        # Every guarded present, including all increments, has passed real source + binding guards.
        assert report["new"]["present_citations"] == report["new"]["present_citations_verified"]
        report["new_present_source_validation_failures"] = 0
    finally:
        after = probe.summary()
        delta = Decimal(after["committed_usd"]) - Decimal(before["committed_usd"])
        # Other users can share the provider ledger: settle only this private receipt tree.
        with sqlite3.connect(LEDGER) as db:
            paid_ids = [p.parent.name for p in output.glob("receipts/*/request.json")]
            rows = [
                db.execute(
                    "SELECT committed,receipt FROM probe_calls WHERE request_id=?", (rid,)
                ).fetchone()
                for rid in paid_ids
            ]
        own = sum((Decimal(r[0]) for r in rows if r), Decimal(0))
        unsettled = sum(Decimal(r[0]) for r in rows if r and r[1] is None)
        reserve(
            dict(
                status="complete" if report.get("new") else "stopped",
                committed_usd=str(own),
                new_unsettled_usd=str(unsettled),
                logical_calls=len(rows),
                request_ids=paid_ids,
            )
        )
        report.update(
            cost_usd=str(own),
            unsettled_usd=str(unsettled),
            provider_ledger_delta_usd=str(delta),
            original_unchanged=protected() == hashes,
        )
        write(LAB / "Q2-analysis.json", report)
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in ("input_hashes", "wire_bytes")},
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
