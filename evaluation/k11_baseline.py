"""K11 bounded fresh tagging on retained, source-verified packets; no publication."""

import argparse
import io
import json
import socket
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from time import monotonic
from uuid import uuid4

import pdfplumber
from proofops.adapters.aws.usage import LocalSQLiteUsageStore
from proofops.adapters.cache.aws import ImmutableResponseCache, InMemoryImmutableCacheClient
from proofops.adapters.local.glyph_display_text import GlyphDisplayCatalog
from proofops.adapters.local.openai import OpenAIProbe
from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency
from proofops.adapters.local.tag_store import tagging_settings
from proofops.application.analysis_profile import FINALS_I11_POLICY, FINALS_K11_POLICY
from proofops.application.authorization import AuthContext
from proofops.application.budget import BudgetLimits, RoleLimit
from proofops.application.evidence.binding import ClaimContext, local_relation_tags
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.preflight import check_local_upstage_tagger
from proofops.application.tagging.consensus import form_consensus
from proofops.application.tagging.service import RawTagResponse, tag_replicates
from proofops.application.tagging.tracks import TrackCandidate
from proofops.application.tagging.unattended import provisional_result
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.rules.engine import RuleContext
from proofops.domain.values import SourceRef
from proofops_agent.upstage_tagging import UpstageTaggingTransport
from proofops_api.hosted_analysis import read_key

from evaluation.k2_replay import historical_graph
from evaluation.k8_authorization import fresh_grants
from evaluation.pa3_replay import checkpoint
from evaluation.pa9_source_gate import fixture
from evaluation.pt1_replay import decode_runs
from scripts.finals_demo import FinalsBudget


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--verify-saved", action="store_true")
    args = parser.parse_args()
    if args.live and args.verify_saved:
        raise ValueError("K11_SELECT_LIVE_OR_SAVED")
    args.output.mkdir(parents=True, exist_ok=True)
    state = args.root / "outputs/agent-results/R108-redesign/lab/fix/K10/C-lg/pipeline/lgchem"
    pins = {str(p): sha256(p.read_bytes()).hexdigest() for p in state.rglob("*") if p.is_file()}
    graph, pdf_bytes, discovery, snapshot, parse = fixture(state)
    graph = historical_graph(graph, parse, checkpoint(state, "extract"))
    item = next(
        c
        for c in checkpoint(state, "tag")["claims"]
        if "951만" in (c.get("frozen_packet") or {}).get("atomic_quote", "")
    )
    claim = next(c for c in discovery.claims if c.claim_id == item["claim_id"])
    assert item["source_status"]["status"] == "verified"
    claim = replace(
        claim,
        source_refs=tuple(
            verify_source_ref(r, graph, tenant_id=graph.tenant_id) for r in claim.source_refs
        ),
        source_quality="verified",
    )
    assert all(r.verification_state == "verified" for r in claim.source_refs)
    keys = set().union(
        *(
            r["values"]["dimensions"]
            for r in item["preliminary_records"]
            if r["status"] == "validated_candidate"
        )
    )
    dims = {}
    for key in keys:
        choices = [
            r["values"]["dimensions"].get(key)
            for r in item["preliminary_records"]
            if r["status"] == "validated_candidate"
        ]
        value = choices[0] if all(c == choices[0] for c in choices) else None
        dims[key] = SourceRef(**value) if value else None
    context = ClaimContext(claim, dims)
    rulepack = RulePackSnapshot(**snapshot["rulepack"])
    settings = tagging_settings(snapshot)
    catalog = GlyphDisplayCatalog(graph, pdf_bytes)
    probe = None
    if args.live:
        grants = fresh_grants(snapshot, approved_by="authorized-local-operator:fix-K11.md")
        settings = replace(
            settings,
            binding=replace(
                settings.binding, binding_id=grants["tagging_runtime"]["runtime_binding_id"]
            ),
        )
        grants["tagging_runtime"]["tagging_settings_sha256"] = canonical_hash(asdict(settings))
        probe = OpenAIProbe(
            read_key(str(args.root / ".env.openai.local"), "OPENAI_API_KEY"),
            args.output / "live.sqlite3",
        )
        probe.configure_response_policy(
            snapshot
            | dict(
                analysis_profile_policy=FINALS_K11_POLICY,
                analysis_profile_policy_sha256=canonical_hash(FINALS_K11_POLICY),
            ),
            role="elements",
        )
        scheduler = RoleProviderConcurrency(
            1,
            requests_per_second=4,
            scheduler_policy=FINALS_K11_POLICY["provider_scheduler"],
            resilience_directory=args.output / "provider-events",
        )
        scheduler.bind(probe)
        fence = FinalsBudget(
            args.root / "outputs/agent-results/R108-redesign/lab/sprint3/E2E/r108-spend.json",
            {"openai": probe.ledger.resolve()},
            args.output / "paid-calls.jsonl",
            task="K11-g3",
            limit_usd="0.2",
        )
        call = fence.guarded(OpenAIProbe.complete, "openai", lambda *args: Decimal(".02"))
        probe.complete = lambda *a, **kw: call(probe, *a, **kw)
    else:

        def deny(*args, **kwargs):
            raise AssertionError("K11_REPLAY_NETWORK_FORBIDDEN")

        socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
        if args.verify_saved:
            probe = OpenAIProbe("saved-verification-no-key", args.output / "live.sqlite3")
    results = {}
    for phase in ("before", "after") if args.live or args.verify_saved else ("before",):
        if args.verify_saved:
            results[phase] = json.loads((args.output / f"{phase}.json").read_text())
            continue
        policy = FINALS_I11_POLICY if phase == "before" else FINALS_K11_POLICY
        data = {k: v for k, v in item["frozen_packet"].items() if k != "packet_sha256"}
        data["tagging_wire_policy"] = policy["tagging_wire_policy"]
        packet = freeze_packet(data)
        store = LocalSQLiteUsageStore(args.output / f"{phase}-usage.sqlite3")
        store.create_budget(
            graph.tenant_id,
            data["run_id"],
            graph.document_version_id,
            BudgetLimits(1000000, 1000000, (RoleLimit("tagger", 3, 100000, 100000, 200000),)),
        )
        if phase == "after":
            adapter = UpstageTaggingTransport(
                probe,
                args.output / "receipts",
                settings=settings,
                tenant_id=graph.tenant_id,
                display_catalog=catalog,
                authorize=lambda selected, request: check_local_upstage_tagger(
                    binding=grants["tagging_runtime"],
                    consent=grants["consent"],
                    settings=selected,
                    auth=AuthContext(
                        "local-worker", graph.tenant_id, "viewer", frozenset(), data["run_id"]
                    ),
                    checked_at=datetime.now(UTC).isoformat(),
                    source_sha256=graph.source_sha256,
                    document_rights=snapshot["document"]["metadata"]["rights_profile_id"],
                ),
            )

            def invoke(request):
                with probe.response_context(role="elements", replica=request["replicate_id"]):
                    return adapter.invoke(request)
        else:
            saved = decode_runs(item["tag_runs"])

            def invoke(request):
                run = next(r for r in saved if r.replicate_id == request["replicate_id"])
                raw = json.loads(run.raw_response_json)
                raw["packet_sha256"] = packet.packet_sha256
                return RawTagResponse(
                    json.dumps(raw), run.usage, run.synthetic, run.provider_response_json
                )

        started = monotonic()
        runs = tag_replicates(
            packet,
            context=context,
            track=TrackCandidate(claim, "goal", None),
            original=graph,
            relation_tags=local_relation_tags(context),
            rulepack=rulepack,
            settings=settings,
            cache=ImmutableResponseCache(InMemoryImmutableCacheClient()),
            usage_store=store,
            invoke=invoke,
            tenant_id=graph.tenant_id,
            ensemble_id=str(uuid4()),
            consent_profile="authorized-local-fix-K11",
            token_counter=lambda s: 1,
            count_input_tokens=lambda r: 32768,
            now=lambda: 1,
            pipeline_profile=data["pipeline_profile"],
            semantic_policy=policy["semantic_admission"],
        )
        result = provisional_result(
            runs,
            packet,
            rulepack,
            RuleContext(
                graph.tenant_id, graph.document_version_id, claim.claim_id, packet.packet_sha256
            ),
        )
        results[phase] = dict(
            seconds=monotonic() - started,
            packet_sha256=packet.packet_sha256,
            runs=[asdict(r) for r in runs],
            provisional=result,
            consensus=asdict(
                form_consensus(
                    runs,
                    packet=packet,
                    rulepack=rulepack,
                    tenant_id=graph.tenant_id,
                    tag_revision=1,
                    profile="partial-facts-v2",
                )
            ),
        )
        (args.output / f"{phase}.json").write_text(
            json.dumps(results[phase], ensure_ascii=False, indent=2)
        )
    if args.live or args.verify_saved:
        runs = results["after"]["runs"]
        expected_data = {k: v for k, v in item["frozen_packet"].items() if k != "packet_sha256"}
        expected_data["tagging_wire_policy"] = FINALS_K11_POLICY["tagging_wire_policy"]
        assert results["after"]["packet_sha256"] == freeze_packet(expected_data).packet_sha256
        assert all(r["usage"]["status"] == "succeeded" and r["guarded"] for r in runs)
        assert len({r["usage"]["provider_request_id"] for r in runs}) == 3
        for run in runs:
            directory = args.output / "receipts" / run["request"]["request_id"]
            request_record = json.loads((directory / "request.json").read_text())
            response_record = json.loads((directory / "response.json").read_text())
            assert canonical_hash(request_record["request"]) == request_record["request_sha256"]
            assert request_record["request"]["replicate_id"] == run["request"]["replicate_id"]
            assert request_record["request"]["packet_sha256"] == results["after"]["packet_sha256"]
            assert response_record["raw_response_json"] == run["raw_response_json"]
            assert response_record["provider_response_json"] == run["provider_response_json"]
            receipt = json.loads(run["provider_response_json"])
            assert receipt["response_request"]["analysis_policy_sha256"] == canonical_hash(
                FINALS_K11_POLICY
            )
            originals = [
                json.loads(p.read_text())
                for p in (args.output / "live.sqlite3.responses").glob("*.json")
            ]
            original = next(
                r["provider_response"]
                for r in originals
                if r["request_id"] == receipt["request_id"]
            )
            assert canonical_hash(original) == receipt["response_sha256"]
        g3 = [next(e for e in r["guarded"]["elements"] if e["element_id"] == "G3") for r in runs]
        assert all(e["state"] == "present" for e in g3)
        assert (
            next(
                e
                for e in results["after"]["consensus"]["candidate_elements"]
                if e["element_id"] == "G3"
            )["state"]
            == "present"
        )
        assert (
            next(
                e
                for e in results["after"]["consensus"]["candidate_elements"]
                if e["element_id"] == "G2"
            )["state"]
            == "present"
        )
        assert (
            next(e for e in results["after"]["provisional"]["elements"] if e["element_id"] == "G3")[
                "state"
            ]
            == "present"
        )
        native = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for element in g3:
                for raw in element["evidence_refs"]:
                    ref = verify_source_ref(SourceRef(**raw), graph, tenant_id=graph.tenant_id)
                    assert ref.verification_state == "verified"
                    text = pdf.pages[ref.page_num - 1].crop(ref.bbox).extract_text() or ""
                    assert "".join(ref.quote.split()) in "".join(text.split())
                    native.append(dict(ref=asdict(ref), native_bbox_literal=True))
        results["native_checks"] = native
        results["spend"] = probe.summary()
    assert all(sha256(Path(p).read_bytes()).hexdigest() == h for p, h in pins.items())
    summary = dict(
        claim_id=claim.claim_id,
        quote=claim.quote,
        source_sha256=graph.source_sha256,
        input_hashes=pins,
        policy_sha256=canonical_hash(FINALS_K11_POLICY),
        live=args.live or args.verify_saved,
        publication="not_run; retained classification; new element ensemble only",
        results=results,
    )
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            dict(
                claim_id=claim.claim_id,
                live=args.live or args.verify_saved,
                states={
                    k: {e["element_id"]: e["state"] for e in v["provisional"]["elements"]}
                    for k, v in results.items()
                    if k in ("before", "after")
                },
                spend=results.get("spend"),
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
