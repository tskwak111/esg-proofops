"""Same-input replay of three companies' v7 raw votes; network and input writes denied."""

import argparse
import json
import socket
import tempfile
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

from proofops.adapters.aws.usage import LocalSQLiteUsageStore
from proofops.adapters.cache.aws import ImmutableResponseCache, InMemoryImmutableCacheClient
from proofops.adapters.local.tag_store import tagging_settings
from proofops.application.analysis_profile import FINALS_K9_POLICY
from proofops.application.budget import BudgetLimits, RoleLimit
from proofops.application.evidence.binding import ClaimContext, local_relation_tags
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.tagging.service import RawTagResponse, tag_replicates
from proofops.application.tagging.tracks import TrackCandidate
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.values import SourceRef

from evaluation.k2_replay import historical_graph
from evaluation.pa3_replay import checkpoint
from evaluation.pa9_source_gate import fixture
from evaluation.pt1_replay import decode_runs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    def deny(*args, **kwargs):
        raise AssertionError("K9_REPLAY_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    root = Path("/path/to/ESG_ProofOps/outputs/agent-results/R108-redesign/lab/perf/I7/native")
    cases, inputs = [], {}
    with tempfile.TemporaryDirectory(prefix="proofops-k9-guard-") as directory:
        for company, suffix in (
            ("hyundai", "hyundai/product-hyundai"),
            ("sk", "sk/product-hyundai"),
            ("kia", "B/kia"),
        ):
            state = root / suffix
            inputs[str(state / "state.sqlite3")] = sha256(
                (state / "state.sqlite3").read_bytes()
            ).hexdigest()
            graph, source, discovery, snapshot, parse = fixture(state)
            graph = historical_graph(graph, parse, checkpoint(state, "extract"))
            claims = {c.claim_id: c for c in discovery.claims}
            pack = RulePackSnapshot(**snapshot["rulepack"])
            for index, item in enumerate(checkpoint(state, "tag")["claims"]):
                if not item.get("frozen_packet") or not item["tag_runs"]:
                    continue
                data = item["frozen_packet"]
                assert data["graph_sha256"] == canonical_hash(asdict(graph))
                claim = claims[item["claim_id"]]
                checked = tuple(
                    verify_source_ref(r, graph, tenant_id=graph.tenant_id)
                    for r in claim.source_refs
                )
                if item["source_status"]["status"] == "verified" and all(
                    r.verification_state == "verified" for r in checked
                ):
                    claim = replace(claim, source_refs=checked, source_quality="verified")
                rows = [
                    r["values"]
                    for r in item["preliminary_records"]
                    if r.get("status") == "validated_candidate"
                    and r["values"].get("track")
                    and r["values"]["track"]["track"] == data["track"]
                ]
                dims = {}
                for key in set().union(*(r["dimensions"] for r in rows)):
                    values = [r["dimensions"].get(key) for r in rows]
                    value = values[0] if all(v == values[0] for v in values) else None
                    dims[key] = SourceRef(**value) if value else None
                context = ClaimContext(claim, dims)
                runs = decode_runs(item["tag_runs"])
                packet = freeze_packet(
                    {k: v for k, v in data.items() if k != "packet_sha256"}
                    | dict(
                        local_implementation_binding_policy=FINALS_K9_POLICY[
                            "local_implementation_binding_policy"
                        ]
                    )
                )
                store = LocalSQLiteUsageStore(Path(directory) / f"{company}-{index}.sqlite3")
                store.create_budget(
                    graph.tenant_id,
                    data["run_id"],
                    graph.document_version_id,
                    BudgetLimits(
                        1000000, 1000000, (RoleLimit("tagger", 3, 100000, 100000, 200000),)
                    ),
                )

                def invoke(request):
                    saved = next(r for r in runs if r.replicate_id == request["replicate_id"])
                    raw = json.loads(saved.raw_response_json)
                    # Only the trusted replay envelope is rebound; source quotes,
                    # model states, replica and provider receipt remain original.
                    raw["packet_sha256"] = packet.packet_sha256
                    return RawTagResponse(
                        json.dumps(raw, ensure_ascii=False),
                        saved.usage,
                        saved.synthetic,
                        saved.provider_response_json,
                    )

                guarded = tag_replicates(
                    packet,
                    context=context,
                    track=TrackCandidate(claim, data["track"], data.get("safe_harbor_category")),
                    original=graph,
                    relation_tags=local_relation_tags(context),
                    rulepack=pack,
                    settings=tagging_settings(snapshot),
                    cache=ImmutableResponseCache(InMemoryImmutableCacheClient()),
                    usage_store=store,
                    invoke=invoke,
                    tenant_id=graph.tenant_id,
                    ensemble_id=data["run_id"],
                    consent_profile="offline-K9-same-input-raw-response-replay",
                    token_counter=lambda s: 1,
                    count_input_tokens=lambda r: 10000,
                    now=lambda: 1,
                    pipeline_profile=data["pipeline_profile"],
                    semantic_policy=FINALS_K9_POLICY["semantic_admission"],
                )
                losses = []
                for before, after in zip(runs, guarded, strict=True):
                    admitted = (
                        {e.element_id for e in after.guarded.elements if e.state == "present"}
                        if after.guarded
                        else set()
                    )
                    losses += (
                        [
                            dict(replicate=before.replicate_id, element=e.element_id)
                            for e in before.guarded.elements
                            if e.state == "present" and e.element_id not in admitted
                        ]
                        if before.guarded
                        else []
                    )
                cases.append(
                    dict(
                        company=company,
                        quote=claim.quote,
                        replicas=len(guarded),
                        lost_present=losses,
                    )
                )
    unchanged = all(sha256(Path(p).read_bytes()).hexdigest() == h for p, h in inputs.items())
    result = dict(
        cases=cases,
        losses=[c for c in cases if c["lost_present"]],
        inputs_unchanged=unchanged,
        input_sha256=inputs,
        provider_calls=0,
        paid_usd="0",
        policy_sha256=canonical_hash(FINALS_K9_POLICY),
        scope="stored v7 raw-vote attribution replay; not fresh prompt/model accuracy",
    )
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(dict(cases=len(cases), losses=len(result["losses"]), inputs_unchanged=unchanged))
    assert unchanged and not result["losses"]


if __name__ == "__main__":
    main()
