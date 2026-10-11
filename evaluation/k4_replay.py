"""Reproject authenticated I3 responses under K4; no network, no stored revision writes."""

import argparse
import importlib.util
import json
import socket
import tempfile
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from time import monotonic

from jsonschema import Draft202012Validator
from proofops.adapters.aws.usage import LocalSQLiteUsageStore
from proofops.adapters.cache.aws import ImmutableResponseCache, InMemoryImmutableCacheClient
from proofops.adapters.local.glyph_display_text import GlyphDisplayCatalog
from proofops.adapters.local.k4_facilities import restore_facilities
from proofops.adapters.local.tag_store import tagging_settings
from proofops.application.analysis_profile import FINALS_K4_POLICY
from proofops.application.budget import BudgetLimits, RoleLimit
from proofops.application.evidence.binding import ClaimContext, local_relation_tags
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.ingest.j7_split import sentence_context
from proofops.application.tagging.k4_contract import (
    RESPONSE_POLICY,
    SEMANTIC_POLICY,
    VALUE_POLICY,
    bind_response,
    estimate_evidence,
)
from proofops.application.tagging.pb2_table_evidence import ROW_UNIT_POLICY, augment_packet
from proofops.application.tagging.quality import hold_projection
from proofops.application.tagging.service import RawTagResponse, tag_replicates
from proofops.application.tagging.tracks import TrackCandidate
from proofops.application.tagging.unattended import provisional_result
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.rules.engine import RuleContext
from proofops.domain.values import SourceRef
from proofops_agent.upstage_tagging import UpstageTaggingTransport

from evaluation.k2_replay import historical_graph
from evaluation.pa9_source_gate import fixture
from evaluation.pt1_replay import decode_runs


def read(path):
    return json.loads(path.read_bytes())


def main(*, inputs_dir="perf/I3/stage-B-complete", integration_policy=FINALS_K4_POLICY):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extraction", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    started = monotonic()

    def deny(*a, **kw):
        raise AssertionError("K4_REPLAY_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    lab = args.root / "outputs/agent-results/R108-redesign/lab"
    inputs = lab / inputs_dir
    hashes = {str(p): sha256(p.read_bytes()).hexdigest() for p in inputs.rglob("*") if p.is_file()}
    rows, losses, false_verified, causes = [], [], [], []
    with tempfile.TemporaryDirectory(prefix="proofops-k4-replay-") as tmp:
        for company in ("naver", "kia"):
            state = inputs / company
            graph, source, discovery, snapshot, parse = fixture(state)
            graph = historical_graph(graph, parse, read(state / "extract-checkpoint.json"))
            checkpoint = read(state / "tag-checkpoint.json")
            claims = {c.claim_id: c for c in discovery.claims}
            pack, settings = RulePackSnapshot(**snapshot["rulepack"]), tagging_settings(snapshot)
            catalog = GlyphDisplayCatalog(graph, source)
            transport = object.__new__(UpstageTaggingTransport)
            transport._settings, transport._display_catalog = settings, catalog
            facilities = restore_facilities(
                graph, source, discovery.claims, tenant_id=graph.tenant_id
            )
            for index, item in enumerate(checkpoint["claims"]):
                case_id = f"B-{company.upper()}-{index:02}"
                claim = claims[item["claim_id"]]
                claim = replace(
                    claim,
                    source_quality="verified",
                    source_refs=tuple(
                        verify_source_ref(r, graph, tenant_id=graph.tenant_id)
                        for r in claim.source_refs
                    ),
                )
                if integration_policy.get("risk_classification_policy"):
                    from proofops.application.tagging.k6_citations import risk_without_commitment

                    if risk_without_commitment(claim.quote):
                        rows.append(
                            dict(
                                case_id=case_id,
                                quote=claim.quote,
                                before=item["provisional_grade"],
                                after=dict(
                                    evidence_grade=None,
                                    reason="K6_RISK_WITHOUT_COMPANY_COMMITMENT",
                                    elements=item["provisional_grade"].get("elements", []),
                                ),
                                classification="review; no-company-goal-majority",
                                raw_preliminary_records=item["preliminary_records"],
                            )
                        )
                        continue
                data = {k: v for k, v in item["frozen_packet"].items() if k != "packet_sha256"}
                saved = decode_runs(item["tag_runs"])
                data.update(
                    tagging_response_policy=RESPONSE_POLICY, selected_quantity_policy=VALUE_POLICY
                )
                if integration_policy.get("coverage_policy"):
                    from proofops.application.tagging.k6_citations import POLICY as K6_RESTORE

                    data["citation_restore_policy"] = K6_RESTORE
                if data.get(
                    "safe_harbor_category"
                ) == "emissions_estimate" and not estimate_evidence(data, graph):
                    data["safe_harbor_category"] = None
                data = augment_packet(
                    data, claim, graph, tenant_id=graph.tenant_id, policy=ROW_UNIT_POLICY
                )
                data["display_text"] = catalog.element_pins(data)
                packet = freeze_packet(data)
                prelim = [
                    r["values"]
                    for r in item["preliminary_records"]
                    if r.get("status") == "validated_candidate"
                ]
                dims = {}
                for key in set().union(*(p["dimensions"] for p in prelim)):
                    choices = [p["dimensions"].get(key) for p in prelim]
                    value = choices[0] if all(c == choices[0] for c in choices) else None
                    dims[key] = SourceRef(**value) if value else None
                context = ClaimContext(claim, dims)
                relations = local_relation_tags(context)
                if item.get("review_inputs"):
                    relations = {
                        sid: {k: SourceRef(**r) if r else None for k, r in roles.items()}
                        for sid, roles in item["review_inputs"]["relation_tags"].items()
                    }
                store = LocalSQLiteUsageStore(Path(tmp) / f"{case_id}.sqlite3")
                store.create_budget(
                    graph.tenant_id,
                    data["run_id"],
                    graph.document_version_id,
                    BudgetLimits(
                        1000000, 1000000, (RoleLimit("tagger", 3, 100000, 100000, 200000),)
                    ),
                )

                def invoke(request):
                    old = next(r for r in saved if r.replicate_id == request["replicate_id"])
                    directory = (
                        state
                        / "tagging-receipts"
                        / data["run_id"]
                        / "elements"
                        / old.request.request_id
                    )
                    recorded = read(directory / "request.json")
                    response = read(directory / "response.json")
                    assert response["provider_response_json"] == old.provider_response_json
                    assert recorded["request_sha256"] == canonical_hash(recorded["request"])
                    trusted = recorded["request"]
                    assert (
                        trusted["claim_id"],
                        trusted["packet_sha256"],
                        trusted["replicate_id"],
                        trusted["tenant_id"],
                    ) == (
                        claim.claim_id,
                        item["frozen_packet"]["packet_sha256"],
                        old.replicate_id,
                        graph.tenant_id,
                    )
                    raw = json.loads(json.loads(old.provider_response_json)["content"])
                    schema = json.JSONDecoder().raw_decode(
                        recorded["wire_system"].split("Output JSON schema:\n", 1)[1]
                    )[0]
                    expects_identity = "claim_id" in schema["properties"]
                    mismatches = [
                        k
                        for k in ("claim_id", "packet_sha256", "replicate_id")
                        if (raw.get(k) != trusted[k] if expects_identity else k in raw)
                    ]
                    if mismatches or old.status in ("invalid_response", "citation_unresolved"):
                        causes.append(
                            dict(
                                case_id=case_id,
                                replicate=old.replicate_id,
                                identity_mismatches=mismatches,
                                status=old.status,
                                response_bytes=len((old.raw_response_json or "").encode()),
                            )
                        )
                        # X1 coordinator instruction: failed historical identity
                        # responses remain failed. Only new wire responses may
                        # receive dispatch-owned identity; never approve these.
                        return RawTagResponse(
                            old.raw_response_json,
                            old.usage,
                            old.synthetic,
                            old.provider_response_json,
                        )
                    # Measure the redesigned server-owned envelope on retained
                    # semantic content, not a fresh model success or legacy repair.
                    for field in ("claim_id", "packet_sha256", "replicate_id"):
                        schema["properties"].pop(field, None)
                        if field in schema["required"]:
                            schema["required"].remove(field)
                    semantic = {
                        k: v
                        for k, v in raw.items()
                        if k not in ("claim_id", "packet_sha256", "replicate_id")
                    }
                    Draft202012Validator(schema).validate(semantic)
                    decoded = bind_response(semantic, request, policy=RESPONSE_POLICY)
                    # Python's negative category veto is not a new positive vote.
                    if (
                        raw["safe_harbor_category"] == "emissions_estimate"
                        and data["safe_harbor_category"] is None
                    ):
                        decoded["safe_harbor_category"] = None
                    decoded = transport.restore_payload(
                        decoded, recorded["evidence_refs"], policy=data["citation_restore_policy"]
                    )
                    return RawTagResponse(
                        json.dumps(decoded, ensure_ascii=False),
                        old.usage,
                        old.synthetic,
                        old.provider_response_json,
                    )

                runs = tag_replicates(
                    packet,
                    context=context,
                    track=TrackCandidate(claim, data["track"], data.get("safe_harbor_category")),
                    original=graph,
                    relation_tags=relations,
                    rulepack=pack,
                    settings=settings,
                    cache=ImmutableResponseCache(InMemoryImmutableCacheClient()),
                    usage_store=store,
                    invoke=invoke,
                    tenant_id=graph.tenant_id,
                    ensemble_id=data["run_id"],
                    consent_profile="offline-authenticated-saved-response-k4",
                    token_counter=lambda _: 1,
                    count_input_tokens=lambda _: 10000,
                    now=lambda: 1,
                    pipeline_profile=data["pipeline_profile"],
                    semantic_policy=SEMANTIC_POLICY,
                )
                result = provisional_result(
                    runs,
                    packet,
                    pack,
                    RuleContext(
                        graph.tenant_id,
                        graph.document_version_id,
                        claim.claim_id,
                        packet.packet_sha256,
                    ),
                    range_profile=True,
                    profile="k2-v1",
                    semantic_policy=SEMANTIC_POLICY,
                    original=graph,
                )
                result = hold_projection(
                    item
                    | dict(
                        provisional_grade=result,
                        frozen_packet=packet.to_dict(),
                        tag_runs=[asdict(r) for r in runs],
                    ),
                    profile="k2-v1",
                )
                before = item["provisional_grade"]
                before_present = {
                    e["element_id"] for e in before.get("elements", []) if e["state"] == "present"
                }
                after_present = {
                    e["element_id"] for e in result.get("elements", []) if e["state"] == "present"
                }
                if before_present - after_present:
                    losses.append(
                        dict(case_id=case_id, lost=sorted(before_present - after_present))
                    )
                for run in runs:
                    for element in run.guarded.elements if run.guarded else ():
                        if element.state == "present":
                            false_verified.extend(
                                dict(case_id=case_id, element=element.element_id, ref=asdict(ref))
                                for ref in element.evidence_refs
                                if verify_source_ref(
                                    ref, graph, tenant_id=graph.tenant_id
                                ).verification_state
                                != "verified"
                            )
                rows.append(
                    dict(
                        case_id=case_id,
                        quote=claim.quote,
                        before=before,
                        after=result,
                        statuses=[r.status for r in runs],
                        p1_votes=[
                            next(
                                (e.state for e in r.guarded.elements if e.element_id == "P1"), None
                            )
                            if r.guarded
                            else None
                            for r in runs
                        ],
                        table_observation=bool(data.get("table_observation_evidence")),
                        category_before=item["frozen_packet"].get("safe_harbor_category"),
                        category_after=data.get("safe_harbor_category"),
                        source_dimensions=facilities.get(claim.claim_id),
                        sentence_context=sentence_context(claim, graph),
                    )
                )
    scores = None
    if args.extraction:
        scorer_path = args.root / ".local/g1-gold/evaluation/dl4_gold.py"
        spec = importlib.util.spec_from_file_location("k4_g1_scorer", scorer_path)
        scorer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scorer)
        gold = read(lab / "perf/I3/dl4-reference/DL4-gold.json")
        scores = {
            phase: {
                mode: scorer.evaluate(
                    gold["golds"],
                    [
                        p | dict(company=c)
                        for c in ("naver", "kia")
                        for p in read(folder / f"{c}-after.json")
                    ],
                    mode,
                )
                for mode in ("strict", "lenient")
            }
            for phase, folder in (
                ("before", lab / "perf/I3/stage-A-delivery"),
                ("after", args.extraction),
            )
        }
        hashes[str(scorer_path)] = sha256(scorer_path.read_bytes()).hexdigest()
        assert all(
            scores["after"][m]["precision"] >= scores["before"][m]["precision"]
            for m in scores["before"]
        )
    unchanged = all(sha256(Path(p).read_bytes()).hexdigest() == h for p, h in hashes.items())
    assert unchanged and not losses and not false_verified
    report = dict(
        policy=integration_policy,
        policy_sha256=canonical_hash(integration_policy),
        elapsed_seconds=round(monotonic() - started, 3),
        inputs_unchanged=unchanged,
        provider_calls=0,
        cost_usd="0",
        replay_kind="new-contract-projection-of-authenticated-retained-content",
        existing_normal_losses=losses,
        false_verified=false_verified,
        dl4=scores,
        causes=causes,
        cases=rows,
        input_sha256=hashes,
    )
    (args.output / "replay.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "elapsed_seconds",
                    "inputs_unchanged",
                    "provider_calls",
                    "existing_normal_losses",
                    "false_verified",
                )
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
