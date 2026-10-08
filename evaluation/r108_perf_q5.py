"""Free Q5 attribution audit and opt-in local-role reuse experiment.

No product admission policy changes. Existing null/ambiguous maps are immutable;
the opt-in experiment supplies the existing local_relation_tags contract only
for a source with no recorded mapping at all. Paid calls are unavailable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import socket
import sqlite3
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from proofops.adapters.aws.usage import LocalSQLiteUsageStore
from proofops.adapters.cache.aws import ImmutableResponseCache, InMemoryImmutableCacheClient
from proofops.adapters.local.claim_store import LocalClaimStore
from proofops.adapters.local.run_store import LocalSQLiteRunStore
from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
from proofops.application.budget import BudgetLimits, RoleLimit, TokenUsage
from proofops.application.evidence.binding import (
    accept_binding,
    local_relation_tags,
    relation_tags_for,
)
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.ports.models import ModelBinding
from proofops.application.registry import Registry
from proofops.application.tagging.service import RawTagResponse, TaggingSettings, tag_replicates
from proofops.application.tagging.tracks import TrackCandidate
from proofops.application.uploads import UploadService
from proofops.domain.periods import is_supported_period
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.values import SourceRef
from proofops_agent.upstage_tagging import CONSISTENCY_PROFILE

from evaluation.r108_perf_q2 import LAB, ROOT, objects

CORE = ("entity", "metric", "reporting_period")


def reuse_local_roles(context, relations):
    """Never shadow an existing whole-source or scoped role map, even malformed.

    Claim axes remain literal SourceRefs and are rechecked by accept_binding.
    No external roles, metadata, synthetic years or null removal are introduced.
    """
    result = dict(relations)
    for key, roles in local_relation_tags(context).items():
        sid = key.split(":", 1)[0]
        if not any(k == sid or k.startswith(sid + ":") for k in relations):
            result[key] = roles
    return result


def diagnose(context, ref, relations, *, graph, rulepack, element_id):
    roles = relation_tags_for(ref, relations)
    binding = accept_binding(
        context,
        ref,
        roles,
        original=graph,
        tenant_id=graph.tenant_id,
        rulepack=rulepack,
        element_id=element_id,
    )
    local = any(
        s.source_id == ref.source_id and s.char_start <= ref.char_start < ref.char_end <= s.char_end
        for s in context.claim.source_refs
    )
    definitions = rulepack.file_content("rubric/elements.yaml")["elements"]
    scopes = next(e["source_scopes"] for e in definitions if e["id"] == element_id)
    direct = local and "local_claim" in scopes
    claim_missing = [k for k in CORE if context.dimensions.get(k) is None]
    evidence_missing = [k for k in CORE if (roles or {}).get(k) is None]
    optional_null = sorted(
        {
            k
            for dims in (context.dimensions, roles or {})
            for k, value in dims.items()
            if k not in CORE and value is None
        }
    )
    invalid_period = [
        value.quote
        for dims in (context.dimensions, roles or {})
        if (value := dims.get("reporting_period")) is not None
        and not is_supported_period(value.quote)
    ]
    categories = []
    if binding == "undetermined":
        if not direct and claim_missing:
            categories.append("a_claim_axis_unresolved")
        if not local and evidence_missing:
            categories.append("c_external_roles_unverified")
        if roles is None:
            categories.append("g_ambiguous_or_outside_relation_scope")
        if optional_null:
            categories.append(
                "e_local_explicit_optional_null" if direct else "e_external_explicit_optional_null"
            )
        if invalid_period:
            categories.append("f_unsupported_period_literal")
        checked = verify_source_ref(ref, graph, tenant_id=graph.tenant_id)
        if checked.verification_state != "verified":
            categories.append("h_source_unverified")
        if not categories:
            categories.append("unclassified")
    return dict(
        binding=binding,
        local=local,
        direct=direct,
        categories=categories,
        claim_missing_required=claim_missing,
        evidence_missing_required=evidence_missing,
        unresolved_optional_axes=optional_null,
        unsupported_period_literals=invalid_period,
        # d is an unconnected input, not automatically an independent causal defect:
        # metadata lacks a role SourceRef and claim-specific applicability evidence.
        report_period_unlinked=not direct and context.dimensions.get("reporting_period") is None,
        local_mapping_empty=local and roles == {},
        local_roles_all_null=local and roles is not None and not any(roles.values()),
        local_mapping_has_verified_claim_role=local and any(context.dimensions.values()),
        claim_dimensions={k: asdict(v) if v else None for k, v in context.dimensions.items()},
        evidence_dimensions=None
        if roles is None
        else {k: asdict(v) if v else None for k, v in roles.items()},
    )


def read_artifact(source):
    with sqlite3.connect((source / "state.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        artifacts = [
            json.loads(r[0])
            for r in db.execute("SELECT value FROM job_records WHERE kind='artifact'")
        ]
        snapshot = json.loads(db.execute("SELECT payload FROM run_snapshots").fetchone()[0])
    return next(a for a in artifacts if "tagging_settings" in a), snapshot


def replay_sources(source, name, artifact):
    dest = Path(".local/q5-saved-inputs") / name
    if not dest.exists():
        shutil.copytree(source, dest)
    db = dest / "state.sqlite3"
    store = LocalSQLiteRunStore(db)
    _, discovery, graph = LocalClaimStore(
        store,
        UploadService(db, dest / "objects", Registry.sqlite(db)),
        OpenDataLoaderParser(dest / "parser-prepared"),
    ).load_evidence(artifact["tenant_id"], artifact["run_id"])
    return {c.claim_id: c for c in discovery.claims}, graph


def replay_votes(item, context, relations, packet, rulepack, graph, settings, usage):
    saved = {r["request"]["replicate_id"]: r for r in item["tag_runs"]}
    dispatched = []

    def invoke(request):
        old = saved[request["replicate_id"]]
        assert request["packet_sha256"] == packet.packet_sha256
        dispatched.append(request["replicate_id"])
        return RawTagResponse(
            old["raw_response_json"],
            TokenUsage(**old["usage"]),
            settings.binding.synthetic,
            old.get("provider_response_json"),
        )

    def count_input(request):
        old = saved[request["replicate_id"]]
        if old["raw_response_json"] is None:
            # Both pre-dispatch and adapter conversion failures lack a usable
            # saved element response. Stop this offline replica before invoke;
            # retain the archive's original status/errors in the audit output.
            raise ValueError("Q5_SAVED_RESPONSE_UNAVAILABLE")
        return 32768

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
        consent_profile="perf-Q5-offline-only",
        token_counter=lambda text: 32768,
        count_input_tokens=count_input,
        now=lambda: 1791504000,
    )
    assert dispatched == [i for i, r in saved.items() if r["raw_response_json"] is not None]
    for run in runs:
        if saved[run.replicate_id]["raw_response_json"] is None:
            assert run.guarded is None
        else:
            assert run.guarded is not None, run.errors
    return [asdict(r.guarded) if r.guarded else None for r in runs]


def state_summary(votes):
    by_element = {}
    present_votes = 0
    for vote in votes:
        if vote is None:
            continue  # A failed saved request never creates a model vote.
        for element in vote["elements"]:
            by_element.setdefault(element["element_id"], []).append(element["state"])
            present_votes += element["state"] == "present"
    return dict(
        present_votes=present_votes,
        unanimous_present=sum(states == ["present"] * 3 for states in by_element.values()),
        unanimous_unknown=sum(states == ["unknown"] * 3 for states in by_element.values()),
    )


def packet_admits(packet, ref, element_id, allowed_scopes):
    """The element guard's gate BEFORE binding; a diagnostic, never admission."""
    candidate = next(
        (c for c in packet["evidence_candidates"] if c["source_id"] == ref["source_id"]), None
    )
    return bool(candidate) and (
        element_id in candidate["allowed_elements"]
        and candidate["source_scope"] in allowed_scopes
        and any(
            s["source_id"] == ref["source_id"]
            and s["char_start"] <= ref["char_start"] < ref["char_end"] <= s["char_end"]
            for c in packet["evidence_candidates"]
            for s in c["source_refs"]
        )
    )


def annotate_packet_gates(result, items):
    """Separate unresolved bindings from earlier element source-scope stops."""
    lookup = {i["claim_id"]: i for i in items}
    for row in result["rows"]:
        item = lookup[row["claim_id"]]
        review = item["review_inputs"]
        definitions = RulePackSnapshot(**review["rulepack"]).file_content("rubric/elements.yaml")[
            "elements"
        ]
        scopes = next(d["source_scopes"] for d in definitions if d["id"] == row["element_id"])
        row["packet_admitted_before_binding"] = packet_admits(
            review["packet"], row["ref"], row["element_id"], scopes
        )
        sid = row["ref"]["source_id"]
        row["relation_mapping_keys"] = [
            key for key in review["relation_tags"] if key == sid or key.startswith(sid + ":")
        ]
        row["relation_role_receipts"] = [
            {k: r[k] for k in ("request_id", "replicate_id", "status") if k in r}
            for r in item.get("relation_records", [])
            if sid in r.get("values", {})
        ]
    unresolved = [r for r in result["rows"] if r["binding"] == "undetermined"]
    result["undetermined_also_blocked_before_binding"] = sum(
        not r["packet_admitted_before_binding"] for r in unresolved
    )
    return result


def audit_dataset(source, name, *, opt_in, saved_results=None):
    artifact, snapshot = read_artifact(source)
    claims, graph = replay_sources(source, "F8" if saved_results else name, artifact)
    settings = TaggingSettings(
        **(
            artifact["tagging_settings"]
            | {"binding": ModelBinding(**artifact["tagging_settings"]["binding"])}
        )
    )
    items = [i for i in artifact["claims"] if i.get("tag_runs")]
    if saved_results:
        from dataclasses import replace

        saved = {i["claim_id"]: i for i in json.loads(saved_results.read_text())}
        items = [i | dict(tag_runs=saved[i["claim_id"]]["tag_runs"]) for i in items]
        settings = replace(settings, model_profile=CONSISTENCY_PROFILE)
    replay_dir = Path(".local/q5-replay")
    replay_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    usage = LocalSQLiteUsageStore(replay_dir / f"{name}-{uuid4()}.sqlite3")
    usage.create_budget(
        graph.tenant_id,
        artifact["run_id"],
        graph.document_version_id,
        BudgetLimits(
            10_000_000,
            1_000_000,
            (RoleLimit("tagger", 6 * len(items), 32768, 4096, 36864),),
            max_attempts=1,
        ),
    )
    rows, binding_counts, after_counts, categories = [], Counter(), Counter(), Counter()
    summary_before, summary_after = Counter(), Counter()
    changed_mappings = changed_votes = new_accepted = verified_refs = 0
    for item in items:
        assert item["review_inputs"]["original"]["graph_sha256"] == canonical_hash(asdict(graph))
        context, relations, packet, rulepack = objects(item, claims[item["claim_id"]])
        after_roles = reuse_local_roles(context, relations) if opt_in else relations
        changed_mappings += after_roles != relations
        baseline = replay_votes(item, context, relations, packet, rulepack, graph, settings, usage)
        assert [canonical_hash(v) for v in baseline] == [
            canonical_hash(r["guarded"]) for r in item["tag_runs"]
        ], f"{name}: saved guarded response drift"
        after = replay_votes(item, context, after_roles, packet, rulepack, graph, settings, usage)
        summary_before.update(state_summary(baseline))
        summary_after.update(state_summary(after))
        changed_votes += sum(
            canonical_hash(a) != canonical_hash(b) for a, b in zip(baseline, after, strict=True)
        )
        for run in item["tag_runs"]:
            if run["raw_response_json"] is None:
                continue
            for element in json.loads(run["raw_response_json"])["elements"]:
                for raw_ref in element["evidence_refs"]:
                    ref = SourceRef(**raw_ref)
                    verified = verify_source_ref(ref, graph, tenant_id=graph.tenant_id)
                    verified_refs += verified.verification_state == "verified"
                    detail = diagnose(
                        context,
                        verified,
                        relations,
                        graph=graph,
                        rulepack=rulepack,
                        element_id=element["element_id"],
                    )
                    after_binding = accept_binding(
                        context,
                        verified,
                        relation_tags_for(verified, after_roles),
                        original=graph,
                        tenant_id=graph.tenant_id,
                        rulepack=rulepack,
                        element_id=element["element_id"],
                    )
                    binding_counts[detail["binding"]] += 1
                    after_counts[after_binding] += 1
                    new_accepted += detail["binding"] != "accepted" and after_binding == "accepted"
                    categories.update(detail["categories"])
                    rows.append(
                        detail
                        | dict(
                            claim_id=item["claim_id"],
                            claim_quote=context.claim.quote,
                            element_id=element["element_id"],
                            raw_state=element["state"],
                            replicate_id=run["request"]["replicate_id"],
                            ref=asdict(ref),
                            raw_response_sha256=hashlib.sha256(
                                run["raw_response_json"].encode()
                            ).hexdigest(),
                            after_binding=after_binding,
                        )
                    )
    unresolved = [r for r in rows if r["binding"] == "undetermined"]
    assert categories["unclassified"] == 0, name
    result = dict(
        source=str(source),
        graph_sha256=canonical_hash(asdict(graph)),
        claims=len(items),
        votes=3 * len(items),
        raw_citations=len(rows),
        unavailable_saved_responses=[
            dict(
                claim_id=i["claim_id"],
                replicate_id=r["request"]["replicate_id"],
                status=r["status"],
                errors=r["errors"],
            )
            for i in items
            for r in i["tag_runs"]
            if r["raw_response_json"] is None
        ],
        source_verified=verified_refs,
        binding_before=dict(binding_counts),
        binding_after=dict(after_counts),
        categories=dict(categories),
        primary_causes=dict(Counter(r["categories"][0] for r in unresolved)),
        local_undetermined=sum(r["local"] for r in unresolved),
        b_local_empty_mapping=sum(r["local_mapping_empty"] for r in unresolved),
        b_local_all_null_roles=sum(r["local_roles_all_null"] for r in unresolved),
        b_local_all_null_with_usable_claim_roles=sum(
            r["local_roles_all_null"] and r["local_mapping_has_verified_claim_role"]
            for r in unresolved
        ),
        d_unlinked_period=sum(r["report_period_unlinked"] for r in unresolved),
        period_metadata={
            k: snapshot["document"]["metadata"].get(k)
            for k in ("period_start", "period_end", "report_year")
        },
        changed_mappings=changed_mappings,
        changed_guarded_votes=changed_votes,
        new_accepted=new_accepted,
        before=dict(summary_before),
        after=dict(summary_after),
        rows=rows,
    )
    return annotate_packet_gates(result, items)


def protected(paths):
    return {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for root in paths
        for p in root.rglob("*")
        if p.is_file()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse-local-roles", action="store_true", help="default OFF")
    args = parser.parse_args()

    def deny(*args, **kwargs):
        raise RuntimeError("Q5_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.create_connection = deny
    sources = {
        "F8": ROOT / ".local/r108-finals.INGDai/live",
        "RP3": ROOT / ".local/r108-finals.1SnAjL/live",
    }
    states = ROOT / "outputs/agent-results/R108-redesign/lab/sprint5/E2E3/states"
    sources.update({f"E2E3-{p.name}": p for p in sorted(states.iterdir()) if p.is_dir()})
    before = protected(sources.values())
    q2_results = Path(".local/q2-paid/results.json")
    before[str(q2_results.resolve())] = hashlib.sha256(q2_results.read_bytes()).hexdigest()
    results = {}
    for name, source in sources.items():
        print("replay", name, flush=True)
        results[name] = audit_dataset(source, name, opt_in=args.reuse_local_roles)
        print(
            name,
            {
                k: v
                for k, v in results[name].items()
                if k in ("binding_before", "binding_after", "primary_causes", "before", "after")
            },
            flush=True,
        )
    results["F8-Q2-consistency"] = audit_dataset(
        sources["F8"],
        "F8-Q2-consistency",
        opt_in=args.reuse_local_roles,
        saved_results=q2_results,
    )
    after = protected(sources.values())
    after[str(q2_results.resolve())] = hashlib.sha256(q2_results.read_bytes()).hexdigest()
    assert before == after, "Q5_ORIGINAL_ARTIFACT_CHANGED"
    output = dict(
        schema="perf-Q5-binding-audit-v1",
        local_role_reuse_opt_in=args.reuse_local_roles,
        network_calls=0,
        usd="0",
        original_files_unchanged=len(before),
        datasets=results,
        categories_overlap=True,
        period_metadata_policy="unlinked diagnostic only; no role/claim applicability SourceRef",
        product_policy_change=(
            "withheld: explicit optional null and external role gaps remain unresolved"
        ),
    )
    path = LAB / "Q5-analysis.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)
    hashes = LAB / "Q5-input-hashes.json"
    hashes.write_text(json.dumps(before, sort_keys=True, indent=2) + "\n")
    hashes.chmod(0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
