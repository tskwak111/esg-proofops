"""Q1 same-input structural replay. Network denied; original revisions immutable."""

import argparse
import copy
import io
import json
import socket
import tempfile
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

import pdfplumber
from proofops.adapters.aws.usage import LocalSQLiteUsageStore
from proofops.adapters.cache.aws import ImmutableResponseCache, InMemoryImmutableCacheClient
from proofops.adapters.local.tag_store import tagging_settings
from proofops.application.analysis_profile import FINALS_Q1_POLICY
from proofops.application.budget import BudgetLimits, RoleLimit
from proofops.application.evidence.binding import ClaimContext, local_relation_tags
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.ingest.j8_cells import graph_cells
from proofops.application.tagging.service import RawTagResponse, tag_replicates
from proofops.application.tagging.tracks import TrackCandidate
from proofops.application.tagging.unattended import provisional_result
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.rules.engine import RuleContext
from proofops.domain.values import SourceRef
from proofops_agent.upstage_extraction import UpstageClaimExtractor

from evaluation.h1_replay import flags
from evaluation.k2_replay import historical_graph
from evaluation.pa3_replay import checkpoint
from evaluation.pa9_source_gate import fixture
from evaluation.pt1_replay import decode_runs
from evaluation.w7_sentence_replay import NoTransport

FOCAL = (1, 7, 8, 30, 33, 52, 55, 59, 62, 63, 70, 72, 74, 77, 78, 81)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fresh-probe", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    def deny(*a, **kw):
        raise AssertionError("Q1_REPLAY_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    lab = args.root / "outputs/agent-results/R108-redesign/lab"
    source = lab / "perf/I9/cases.json"
    review = json.loads(source.read_text())
    input_hashes = {str(source): sha256(source.read_bytes()).hexdigest()}
    fresh = json.loads(args.fresh_probe.read_text())["cases"] if args.fresh_probe else []
    if args.fresh_probe:
        input_hashes[str(args.fresh_probe)] = sha256(args.fresh_probe.read_bytes()).hexdigest()
    loaded, rows = {}, []
    with tempfile.TemporaryDirectory(prefix="proofops-q1-replay-") as directory:
        for number in FOCAL:
            record = review["cases"][number - 1]
            state = Path(review["review_inputs"][record["trial"]]["after_state"])
            if state not in loaded:
                graph, pdf, discovery, snapshot, parse = fixture(state)
                graph = historical_graph(graph, parse, checkpoint(state, "extract"))
                loaded[state] = graph, pdf, discovery, snapshot, checkpoint(state, "tag")
                for path in (state / "state.sqlite3", state / "settings.json"):
                    input_hashes[str(path)] = sha256(path.read_bytes()).hexdigest()
            graph, pdf, discovery, snapshot, saved = loaded[state]
            cid = (record.get("after") or {}).get("claim_id")
            item = next((i for i in saved["claims"] if i["claim_id"] == cid), None)
            row = dict(
                case=number,
                quote=record["quote"],
                trial=record["trial"],
                before=record["after"],
                classification="model_variation",
            )
            if item and item.get("frozen_packet") and item["tag_runs"]:
                data = item["frozen_packet"]
                assert data["graph_sha256"] == canonical_hash(asdict(graph))
                claim = next(c for c in discovery.claims if c.claim_id == cid)
                refs = tuple(
                    verify_source_ref(r, graph, tenant_id=graph.tenant_id)
                    for r in claim.source_refs
                )
                if item["source_status"]["status"] == "verified" and all(
                    r.verification_state == "verified" for r in refs
                ):
                    claim = replace(claim, source_refs=refs, source_quality="verified")
                prelim = [
                    r["values"]
                    for r in item["preliminary_records"]
                    if r.get("status") == "validated_candidate"
                ]
                dims = {}
                for key in set().union(*(p["dimensions"] for p in prelim)):
                    choices = [p["dimensions"].get(key) for p in prelim]
                    value = choices[0] if all(v == choices[0] for v in choices) else None
                    dims[key] = SourceRef(**value) if value else None
                context = ClaimContext(claim, dims)
                runs = decode_runs(item["tag_runs"])
                selected_fresh = [
                    r for r in fresh if r["case"] == number and r["stage"] == "elements"
                ]
                if selected_fresh:
                    from proofops_agent.upstage_tagging import UpstageTaggingTransport

                    assert len(selected_fresh) == 3
                    if number == 81:
                        assert (
                            sum(
                                r["case"] == 81
                                and r["stage"] == "preliminary"
                                and r["response"].get("track") == "management"
                                for r in fresh
                            )
                            == 3
                        )
                        ids = ["M1", "M2", "M3", "M4", "M5", "M6"]
                        own = next(
                            c
                            for c in data["evidence_candidates"]
                            if c["source_scope"] == "local_claim"
                        )
                        data = data | dict(
                            track="management",
                            allowed_elements=ids,
                            evidence_candidates=[own | dict(allowed_elements=ids)],
                        )
                        context = ClaimContext(
                            claim, dict(entity=None, metric=None, reporting_period=None)
                        )
                    adapter = object.__new__(UpstageTaggingTransport)
                    adapter._settings = tagging_settings(snapshot)
                    from proofops.adapters.local.glyph_display_text import GlyphDisplayCatalog

                    adapter._display_catalog = GlyphDisplayCatalog(graph, pdf)
                    restored = []
                    for run in runs:
                        record = next(r for r in selected_fresh if r["replica"] == run.replicate_id)
                        transport = json.loads(Path(record["input_path"]).read_text())
                        refs = record.get("evidence_refs", transport["evidence_refs"])
                        raw = adapter.restore_payload(
                            copy.deepcopy(record["response"]),
                            refs,
                            policy=data["citation_restore_policy"],
                        )
                        raw.update(
                            claim_id=claim.claim_id,
                            packet_sha256=data["packet_sha256"],
                            replicate_id=run.replicate_id,
                        )
                        receipt = record["receipt"]
                        usage = replace(
                            run.usage,
                            provider_request_id=receipt["provider_request_id"],
                            input_tokens=receipt["input_tokens"],
                            output_tokens=receipt["output_tokens"],
                            cache_read_tokens=receipt.get("cached_tokens", 0),
                            cache_write_tokens=receipt.get("cache_write_tokens", 0),
                        )
                        restored.append(
                            replace(
                                run,
                                raw_response_json=json.dumps(raw, ensure_ascii=False),
                                provider_response_json=json.dumps(receipt),
                                usage=usage,
                            )
                        )
                    runs = tuple(restored)
                    row["inference_mode"] = (
                        "fresh-focal-response-through-production-restoration-and-guards"
                    )
                packet = freeze_packet(
                    {k: v for k, v in data.items() if k != "packet_sha256"}
                    | dict(structural_quality_policy=FINALS_Q1_POLICY["structural_quality_policy"])
                )
                store = LocalSQLiteUsageStore(Path(directory) / f"{number}.sqlite3")
                store.create_budget(
                    graph.tenant_id,
                    data["run_id"],
                    graph.document_version_id,
                    BudgetLimits(
                        1000000, 1000000, (RoleLimit("tagger", 3, 100000, 100000, 200000),)
                    ),
                )

                def invoke(request):
                    saved_run = next(r for r in runs if r.replicate_id == request["replicate_id"])
                    raw = json.loads(saved_run.raw_response_json)
                    raw["packet_sha256"] = packet.packet_sha256  # trusted evaluation envelope only
                    return RawTagResponse(
                        json.dumps(raw, ensure_ascii=False),
                        saved_run.usage,
                        saved_run.synthetic,
                        saved_run.provider_response_json,
                    )

                guarded = tag_replicates(
                    packet,
                    context=context,
                    track=TrackCandidate(claim, data["track"], data.get("safe_harbor_category")),
                    original=graph,
                    relation_tags=local_relation_tags(context),
                    rulepack=RulePackSnapshot(**snapshot["rulepack"]),
                    settings=tagging_settings(snapshot),
                    cache=ImmutableResponseCache(InMemoryImmutableCacheClient()),
                    usage_store=store,
                    invoke=invoke,
                    tenant_id=graph.tenant_id,
                    ensemble_id=data["run_id"],
                    consent_profile="offline-Q1-stored-response-replay",
                    token_counter=lambda s: 1,
                    count_input_tokens=lambda r: 10000,
                    now=lambda: 1,
                    pipeline_profile=data["pipeline_profile"],
                    semantic_policy=FINALS_Q1_POLICY["semantic_admission"],
                )
                pack = RulePackSnapshot(**snapshot["rulepack"])
                rule_context = RuleContext(
                    graph.tenant_id,
                    graph.document_version_id,
                    claim.claim_id,
                    packet.packet_sha256,
                )
                result = provisional_result(
                    guarded,
                    packet,
                    pack,
                    rule_context,
                    profile="k2-v1",
                    range_profile=True,
                    semantic_policy=FINALS_Q1_POLICY["semantic_admission"],
                    original=graph,
                )
                row["after"] = result
                row["raw_votes"] = [json.loads(r.raw_response_json)["elements"] for r in runs]
                row["guarded_runs"] = [asdict(r) for r in guarded]
                row["source_checks"] = []
                with pdfplumber.open(io.BytesIO(pdf)) as native:
                    for run in guarded:
                        for element in run.guarded.elements if run.guarded else ():
                            if element.state != "present":
                                continue
                            for ref in element.evidence_refs:
                                text = (
                                    native.pages[ref.page_num - 1]
                                    .crop(tuple(ref.bbox))
                                    .extract_text()
                                    or ""
                                )
                                row["source_checks"].append(
                                    dict(
                                        replica=run.replicate_id,
                                        element=element.element_id,
                                        quote=ref.quote,
                                        state=ref.verification_state,
                                        native_literal="".join(ref.quote.split())
                                        in "".join(text.split()),
                                    )
                                )
                row["false_verified"] = sum(
                    c["state"] == "verified" and not c["native_literal"]
                    for c in row["source_checks"]
                )
                row["classification"] = (
                    "code_guard"
                    if number in (1, 7, 30, 33, 52, 55, 59, 70, 74)
                    else "model_variation"
                )
            else:
                row["classification"] = "code_candidate_and_model_selection"
                table = next(
                    b
                    for b in graph.blocks
                    if b.page_num == 5 and b.kind == "table" and "FWU" in b.raw_text
                )
                options = flags(FINALS_Q1_POLICY)
                options["extraction_i4_identity"] = False
                options["display_text_profile"] = None
                extractor = UpstageClaimExtractor(
                    NoTransport(), args.output / "resolver", **options
                )
                packet = dict(
                    tenant_id=graph.tenant_id,
                    document_version_id=graph.document_version_id,
                    parse_manifest_id=graph.parse_manifest_id,
                    source_sha256=graph.source_sha256,
                    untrusted_document_data=dict(
                        source_id=table.source_id,
                        page_num=5,
                        kind="table",
                        text=table.normalized_text,
                    ),
                )
                entries = extractor._row_entries(
                    packet, table.normalized_text, [], context_graph=graph
                )
                from proofops.application.ingest.q1_tables import activity_spans

                spans = activity_spans(table.normalized_text, graph_cells(table, graph))
                row["after"] = dict(
                    retained_activities=spans,
                    fwu_candidates=[e for e in entries if "FWU" in e["text"]],
                    tags="not_run-new-selection-needs-fresh-model-votes",
                )
                row["source_checks"] = []
                from proofops.adapters.local import upstage_ocr_profile_v13 as native_table

                selected_refs = [
                    table.source_ref(
                        normalized_char_start=s["char_start"], normalized_char_end=s["char_end"]
                    )
                    for s in spans
                ]
                proofs = native_table.cell_proof(
                    graph, pdf, selected_refs, tenant_id=graph.tenant_id
                )
                row["native_cell_proofs"] = proofs
                with pdfplumber.open(io.BytesIO(pdf)) as native:
                    for ref, proof in zip(selected_refs, proofs, strict=True):
                        checked = verify_source_ref(ref, graph, tenant_id=graph.tenant_id)
                        text = native.pages[4].crop(tuple(ref.bbox)).extract_text() or ""
                        literal = "".join(ref.quote.split()) in "".join(text.split())
                        row["source_checks"].append(
                            dict(
                                quote=ref.quote,
                                prior_graph_state=checked.verification_state,
                                state=proof["status"],
                                native_literal=literal,
                            )
                        )
                row["false_verified"] = sum(
                    c["state"] == "verified" and not c["native_literal"]
                    for c in row["source_checks"]
                )
            rows.append(row)
    unchanged = all(sha256(Path(p).read_bytes()).hexdigest() == h for p, h in input_hashes.items())
    assert unchanged
    result = dict(
        cases=rows,
        input_sha256=input_hashes,
        inputs_unchanged=unchanged,
        provider_calls=0,
        evaluation_mode="fresh-response-local-guard-replay" if fresh else "stored-response-replay",
        paid_usd="0",
        policy_sha256=canonical_hash(FINALS_Q1_POLICY),
        false_verified=sum(r.get("false_verified", 0) for r in rows),
        limitations=[
            "Stored model omissions/conflicting values remain unresolved; no fabricated new votes.",
            "Table additions are extraction candidates; fresh tagging not_run.",
        ],
    )
    (args.output / "cases.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    for r in rows:
        after = r["after"]
        print(
            r["case"],
            r["classification"],
            [e["element_id"] for e in after.get("elements", []) if e["state"] == "present"],
            after.get("evidence_grade"),
            after.get("reason"),
            flush=True,
        )
    assert result["false_verified"] == 0


if __name__ == "__main__":
    main()
