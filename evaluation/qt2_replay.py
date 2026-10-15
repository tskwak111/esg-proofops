"""Offline R17 diagnostic replay. Saved E14 inputs are read-only, never published.

This measures element admission on saved receipts and optional independent Codex
sim votes, not live model accuracy. Source authority is retained from the stored
server packets/attestations, then literal/identity checked against the saved graph.
"""

import argparse
import json
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

from proofops.adapters.parsing.parser_artifacts import read_parser_json
from proofops.application.claims import Claim
from proofops.application.evidence.binding import ClaimContext, local_relation_tags
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.evidence.span_citations import span_verified_graph, verify_source_ref
from proofops.application.ingest.graph_fusion import candidates_from_snapshot, fuse_candidates
from proofops.application.tagging.qt2_context import POLICY, augment_packet
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef


def read(path):
    return read_parser_json(path)


def ref(raw):
    return SourceRef(**(raw | {"bbox": tuple(raw["bbox"]) if raw["bbox"] else None}))


def source_graph(directory, artifacts):
    manifest = next((directory / "parser-prepared").rglob("manifest.json"))
    meta = read(manifest)
    graph = fuse_candidates(
        candidates_from_snapshot(read(manifest.with_name("candidates.json"))),
        tenant_id=meta["tenant_id"],
        fusion_version=meta["fusion_version"],
        mixed_parser=True,
    )
    refs = {}

    def keep(raw):
        r = ref(raw)
        refs[(r.source_id, r.char_start, r.char_end)] = replace(r, verification_state="verified")

    # These are saved guarded source catalogs, never raw model selections or gold.
    tagging = next(v for v in artifacts if "claims" in v)
    for item in tagging["claims"]:
        packet = item.get("frozen_packet")
        if not packet:
            continue
        for r in packet["claim_source_refs"] + [
            r for c in packet["evidence_candidates"] for r in c["source_refs"]
        ]:
            if r["verification_state"] == "verified":
                keep(r)
    extraction = next(v for v in artifacts if "claim_source_attestation" in v)
    receipt = extraction["claim_source_attestation"]
    for item in receipt.get("pb1_cell_proofs", []):
        if item["status"] == "verified":
            keep(item["ref"])
            for cell in item["cell_proofs"]:
                keep(cell["source_ref"])
    graph = span_verified_graph(graph, tuple(refs.values()), canonical_hash(receipt))
    checked = [
        r
        for r in refs.values()
        if verify_source_ref(r, graph, tenant_id=graph.tenant_id).verification_state == "verified"
    ]
    if len(checked) != len(refs):
        print("source spans rejected by current graph", len(refs) - len(checked), flush=True)
    graph = span_verified_graph(graph, tuple(checked), canonical_hash(receipt))
    return graph, tagging


def cases(root, audit):
    for report in audit["reports"]:
        directory = root / report["run_id"]
        if not (directory / "job-artifacts.json").exists():
            continue
        artifacts = [r["value"] for r in read(directory / "job-artifacts.json")]
        graph, tagging = source_graph(directory, artifacts)
        by_id = {x["claim_id"]: x for x in tagging["claims"]}
        for row in report["rows"]:
            if row.get("record_type") != "claim":
                continue
            item = by_id[row["claim_id"]]
            data = item.get("frozen_packet")
            if not data or not item["tag_runs"]:
                continue
            claim = Claim(
                row["claim_id"],
                graph.tenant_id,
                graph.document_version_id,
                graph.parse_manifest_id,
                graph.source_sha256,
                data["atomic_quote"],
                tuple(ref(r) for r in data["claim_source_refs"]),
                row["source_quality"],
                (),
                None,
            )
            dims = {}
            for k, v in item["preliminary_agreement"]["dimensions"].items():
                value = v["replicate_values"][0] if v["state"] == "agreed" else None
                dims[k] = ref(value) if value else None
            context = ClaimContext(claim, dims)
            yield report, row, item, graph, context


def packet_for(item, graph, context, enabled):
    data = deepcopy(item["frozen_packet"])
    data.pop("packet_sha256")
    data["graph_sha256"] = canonical_hash(asdict(graph))
    if enabled:
        augment_packet(data, context.claim, graph, tenant_id=graph.tenant_id)
    # Display is a transport projection; this offline adapter uses literal raw refs.
    data.pop("display_text", None)
    return freeze_packet(data)


def prepare(root, audit, out):
    inputs = []
    for report, row, item, graph, context in cases(root, audit):
        packet = packet_for(item, graph, context, True).to_dict()
        targets = [e for e in packet["allowed_elements"] if e in ("P2", "M2", "M4")]
        if not targets:
            continue
        catalog = []
        for c in packet["evidence_candidates"]:
            allowed = [e for e in targets if e in c["allowed_elements"]]
            if not allowed:
                continue
            for r in c["source_refs"]:
                catalog.append(
                    dict(
                        id=f"e{len(catalog)}",
                        quote=r["quote"],
                        source=r["source_id"],
                        page=r["page_num"],
                        elements=allowed,
                        raw_ref=r,
                    )
                )
        inputs.append(
            dict(
                case=report["case"],
                claim_id=row["claim_id"],
                quote=context.claim.quote,
                elements=targets,
                packet_sha256=packet["packet_sha256"],
                catalog=catalog,
                table=packet.get("table_observation_evidence"),
            )
        )
    (out / "sim-input-private.json").write_text(json.dumps(inputs, ensure_ascii=False))
    # Gold, previous states and raw receipts are deliberately excluded from sim input.
    public = deepcopy(inputs)
    for c in public:
        for r in c["catalog"]:
            r.pop("raw_ref")
        if c["table"]:
            table = c["table"]
            c["table"] = {
                "current_value": table["value"]["quote"],
                "current_year": table["year"]["quote"],
                "unit": table["unit"]["quote"],
                "comparisons": [
                    {"value": x["value"]["quote"], "year": x["year"]["quote"]}
                    for x in table["comparisons"]
                ],
            }
    (out / "sim-input.json").write_text(json.dumps(public, ensure_ascii=False, indent=1))
    print(
        "sim cases",
        len(public),
        "catalog chars",
        sum(len(r["quote"]) for c in public for r in c["catalog"]),
    )


def run(root, audit, out, mode):
    from proofops.adapters.aws.usage import LocalSQLiteUsageStore
    from proofops.adapters.cache.aws import ImmutableResponseCache, InMemoryImmutableCacheClient
    from proofops.application.analysis_profile import FINALS_I23_POLICY
    from proofops.application.budget import BudgetLimits, RoleLimit, TokenUsage
    from proofops.application.ports.models import ModelBinding
    from proofops.application.tagging.consensus import form_consensus
    from proofops.application.tagging.service import RawTagResponse, TaggingSettings, tag_replicates
    from proofops.application.tagging.tracks import TrackCandidate

    from tests.acceptance.test_rules import pack

    simulations = {}
    catalogs = {}
    if mode == "sim":
        catalogs = {x["claim_id"]: x for x in read(out / "sim-input-private.json")}
        for i in (1, 2, 3):
            simulations[i] = {x["claim_id"]: x for x in read(out / f"sim-{i}.json")}
    details = []
    stats = {r["case"]: Counter() for r in audit["reports"]}
    processed = set()
    for report, row, item, graph, context in cases(root, audit):
        processed.add(row["claim_id"])
        data = item["frozen_packet"]
        allowed = data["allowed_elements"]
        rules = replace(pack(), tenant_id=graph.tenant_id)
        assert rules.sha256 == data["rule_sha256"]
        settings = TaggingSettings(
            ModelBinding("qt2-offline-replay", "tagger", True),
            "stored-E14",
            "qt2-replay",
            "offline",
            "Offline stored responses; no network.",
            Path("contracts/jsonschema/llm_tags.schema.json").read_text(),
            max_tokens=100,
        )
        track = TrackCandidate(context.claim, data["track"], data.get("safe_harbor_category"))
        results = {}
        for enabled in (False, True):
            packet = packet_for(item, graph, context, enabled)
            budget_run = str(uuid4())
            packet_data = packet.to_dict()
            packet_data.pop("packet_sha256")
            packet_data["run_id"] = budget_run
            packet = freeze_packet(packet_data)
            usage = LocalSQLiteUsageStore(out / "replay-budget.sqlite3")
            usage.create_budget(
                graph.tenant_id,
                budget_run,
                graph.document_version_id,
                BudgetLimits(100000, 100000, (RoleLimit("tagger", 6, 10000, 10000, 100000),)),
            )
            raw_by_rep = {
                r["guarded"]["replicate_id"]: json.loads(r["raw_response_json"])
                for r in item["tag_runs"]
                if r.get("guarded") and r.get("raw_response_json")
            }
            if len(raw_by_rep) != 3:
                continue

            def respond(request):
                rep = request["replicate_id"]
                payload = deepcopy(raw_by_rep[rep])
                if enabled and mode == "sim" and row["claim_id"] in catalogs:
                    selections = simulations[rep][row["claim_id"]]["elements"]
                    cat = {r["id"]: r["raw_ref"] for r in catalogs[row["claim_id"]]["catalog"]}
                    for element in payload["elements"]:
                        if element["element_id"] not in selections:
                            continue
                        selected = selections[element["element_id"]]
                        element.update(
                            state=selected["state"],
                            evidence_refs=[],
                            normalized_value=selected.get("normalized_value"),
                            credited_from=None,
                            reason_code=None,
                        )
                        for choice in selected.get("evidence", []):
                            original = cat[choice["id"]]
                            q = choice["quote"]
                            assert original["quote"].count(q) == 1 and q
                            start = original["char_start"] + original["quote"].index(q)
                            element["evidence_refs"].append(
                                original | dict(quote=q, char_start=start, char_end=start + len(q))
                            )
                payload.update(
                    {k: request[k] for k in ("claim_id", "packet_sha256", "replicate_id")}
                )
                return RawTagResponse(
                    json.dumps(payload, ensure_ascii=False),
                    TokenUsage(1, 1, 0, 0, 1, "succeeded", f"offline-{rep}"),
                    True,
                )

            relations = local_relation_tags(context)
            runs = tag_replicates(
                packet=packet,
                context=context,
                track=track,
                original=graph,
                relation_tags=relations,
                rulepack=rules,
                settings=settings,
                cache=ImmutableResponseCache(InMemoryImmutableCacheClient()),
                usage_store=usage,
                invoke=respond,
                tenant_id=graph.tenant_id,
                ensemble_id=str(uuid4()),
                consent_profile="qt2-offline",
                token_counter=lambda _: 1,
                now=lambda: 1,
                semantic_policy=FINALS_I23_POLICY["semantic_admission"],
                pipeline_profile="finals-unattended-v2",
                allow_edge_whitespace=True,
            )
            assert all(r.guarded for r in runs), [r.errors for r in runs]
            consensus = form_consensus(
                runs,
                packet=packet,
                rulepack=rules,
                tenant_id=graph.tenant_id,
                tag_revision=1,
                profile=FINALS_I23_POLICY["fact_assembly_profile"],
            )
            states = {e.element_id: e.state for e in consensus.candidate_elements}
            results[enabled] = {e: states.get(e, "unknown") for e in allowed}
        for e in row["elements"]:
            if not e["scored"]:
                continue
            before = e["server_state"]
            # Keep unrelated baseline elements, and never withdraw a valid old vote
            # because this diagnostic lacks a global relation store. Changed target
            # elements use the exact new guard plus replayable local/source path.
            after = before
            if e["element_id"] in ("P2", "M2", "M4") and True in results:
                candidate = results[True][e["element_id"]]
                baseline = results[False][e["element_id"]]
                if candidate != baseline or (mode == "sim" and row["claim_id"] in catalogs):
                    after = candidate
                if before == "present" and mode == "replay":
                    from proofops.application.tagging.qt2_context import guard
                    from proofops.domain.values import llm_tags_from_dict

                    old_elements = [
                        next(
                            x
                            for x in llm_tags_from_dict(r["guarded"]).elements
                            if x.element_id == e["element_id"]
                        )
                        for r in item["tag_runs"]
                        if r.get("guarded")
                    ]
                    veto = any(
                        x.state == "present" and guard(x).state != "present" for x in old_elements
                    )
                    if veto:
                        after = "unknown"
            gold = e["gold_state"]
            st = stats[report["case"]]
            st["n"] += 1
            st["gold_present"] += gold == "present"
            for name, value in [("before", before), ("after", after)]:
                st[name + "_match"] += value == gold
                st[name + "_present_recalled"] += value == gold == "present"
                st[name + "_false_present"] += value == "present" and gold != "present"
            details.append(
                dict(
                    case=report["case"],
                    claim_id=row["claim_id"],
                    element=e["element_id"],
                    before=before,
                    after=after,
                    gold=gold,
                    raw_replay_before=results.get(False, {}).get(e["element_id"]),
                    raw_replay_after=results.get(True, {}).get(e["element_id"]),
                )
            )
    # Rows with no tagging invocation remain held and stay in the fixed denominator.
    for report in audit["reports"]:
        for row in report["rows"]:
            if row.get("record_type") != "claim" or row["claim_id"] in processed:
                continue
            for e in row["elements"]:
                if not e["scored"]:
                    continue
                st = stats[report["case"]]
                st["n"] += 1
                st["gold_present"] += e["gold_state"] == "present"
                for label in ("before", "after"):
                    st[label + "_match"] += e["server_state"] == e["gold_state"]
                    st[label + "_present_recalled"] += (
                        e["server_state"] == e["gold_state"] == "present"
                    )
                    st[label + "_false_present"] += (
                        e["server_state"] == "present" and e["gold_state"] != "present"
                    )
    result = dict(
        mode=mode,
        scope=(
            "R17 fixed diagnostic sample; saved source authority; "
            "no publication or live model accuracy claim"
        ),
        policy=POLICY,
        policy_sha256=canonical_hash(POLICY),
        stats=stats,
        details=details,
        paid_api_calls=0,
    )
    (out / f"{mode}-metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(stats, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mode", choices=["prepare", "replay", "sim"], required=True)
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args.root, read(args.audit), args.out)
    else:
        run(args.root, read(args.audit), args.out, args.mode)


if __name__ == "__main__":
    main()
