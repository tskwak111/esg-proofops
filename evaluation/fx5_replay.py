"""Offline PR1 replay from read-only server copies; never dispatch missing calls.

Restore receipt-pinned graphs, revalidate saved preliminary responses and wire,
rebuild retrieval packets and replay CF6/SC1 decisions. Claims which failed before
dispatch have no responses to replay; capture their recovered dispatch boundary.
"""

import argparse
import json
import socket
import sqlite3
from collections import defaultdict
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from proofops.adapters.local.evidence_search import LocalEvidenceSearch
from proofops.adapters.local.glyph_display_text import GlyphDisplayCatalog
from proofops.adapters.local.gri_routing import LocalGRIRouting
from proofops.adapters.local.h1_native_title import native_figure_candidates
from proofops.adapters.local.tag_store import tagging_settings
from proofops.adapters.local.verified_read_cache import _project_owned_cells, _project_parse
from proofops.application.claims import Claim, ExtractionProfile, ExtractionReceipt
from proofops.application.evidence.relation_attribution import snapshot_policy
from proofops.application.evidence.retrieval import retrieve_evidence
from proofops.application.ingest.graph_fusion import (
    QualityIssue,
    candidates_from_snapshot,
    fuse_candidates,
)
from proofops.application.tagging.analysis_scope import InventoryIndex
from proofops.application.tagging.analysis_scope import analyze_record as sc1_analyze
from proofops.application.tagging.cf5_context import validate_packet
from proofops.application.tagging.cf6_confirmation import analyze_record as cf6_analyze
from proofops.application.tagging.v1_activity_links import policy_from_profile
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.values import SourceRef
from proofops_agent.upstage_preliminary import UpstagePreliminaryTransport
from proofops_worker.live_tagging import LiveTaggingRuntime

from evaluation.tb1_retained_graph import _EmptyDiscovery, _identity, _receipt

PIN = "f29385d0c74d1520350deb06eaa9e11b72c5829dfaefeb2417c4e8ac0fed4ebd"
RUNS = dict(
    hynix="6bf883b7-a2f6-4283-9570-bd4b32e1c479",
    hyundai="5ae64fa8-7a3a-4b90-a179-373af3188d1b",
    naver="d44a3b5b-428d-4a1d-a5c3-5b65b5896f63",
)


def read(path):
    return json.loads(path.read_bytes())


def load(stored, company):
    (directory,) = stored.glob(f"*/analysis/{RUNS[company]}")
    database = directory / "state.sqlite3"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        rows = db.execute("SELECT value FROM job_records WHERE kind='artifact'").fetchall()
        snapshot = json.loads(db.execute("SELECT payload FROM run_snapshots").fetchone()[0])
    assert snapshot["analysis_profile_policy_sha256"] == PIN
    assert canonical_hash(snapshot["analysis_profile_policy"]) == PIN
    artifacts = [json.loads(r[0]) for r in rows]
    tagging = next(a for a in artifacts if "claims" in a)
    extraction = next(
        json.loads(r[0])
        for r in rows
        if sha256(r[0]).hexdigest() == tagging["claim_snapshot_sha256"]
    )
    parse = next(
        json.loads(r[0])
        for r in rows
        if sha256(r[0]).hexdigest() == tagging["parse_checkpoint_sha256"]
    )
    manifest = next((directory / "parser-prepared").rglob("manifest.json"))
    assert sha256(manifest.read_bytes()).hexdigest() == parse["manifest_sha256"]
    meta = read(manifest)
    for name in ("candidates.json", "quality.json", "graph.json"):
        assert sha256(manifest.with_name(name).read_bytes()).hexdigest() == meta["artifacts"][name]
    graph = fuse_candidates(
        candidates_from_snapshot(read(manifest.with_name("candidates.json"))),
        tenant_id=meta["tenant_id"],
        fusion_version=meta["fusion_version"],
        mixed_parser=True,
    )
    graph = replace(
        graph,
        issues=tuple(
            QualityIssue(**i | dict(source_ids=tuple(i["source_ids"])))
            for i in read(manifest.with_name("quality.json"))
        ),
    )
    assert not parse["runtime_note_review_artifacts"]
    for key, native in (
        ("native_paragraph_attestation", True),
        ("evidence_source_attestation", False),
    ):
        receipt = parse[key]
        _receipt(receipt)
        _identity(graph, receipt["input_graph_sha256"])
        graph = _project_parse(receipt, graph, native=native)
    _identity(graph, parse["graph_sha256"])
    pdf = directory.parent.parent / f"{directory.name}.prepared.pdf"
    source = pdf.read_bytes()
    assert sha256(source).hexdigest() == graph.source_sha256
    graph, _ = native_figure_candidates(graph, source)
    receipt = extraction["claim_source_attestation"]
    _receipt(receipt)
    _identity(graph, receipt["input_graph_sha256"])
    claims = []
    for c in extraction["discovery"]["claims"]:
        er = c["receipt"]
        claims.append(
            Claim(
                **c
                | dict(
                    receipt=ExtractionReceipt(
                        **er | dict(profile=ExtractionProfile(**er["profile"]))
                    ),
                    source_refs=tuple(SourceRef(**r) for r in c["source_refs"]),
                    topic_ids=tuple(c["topic_ids"]),
                )
            )
        )
    discovery, graph = _project_owned_cells(
        receipt, graph, _EmptyDiscovery(tuple(claims)), graph.tenant_id, failed_state="candidate"
    )
    _identity(graph, tagging["sc1_inventory"]["selection"]["graph_sha256"])
    for row in tagging["claims"]:
        if row.get("frozen_packet"):
            _identity(graph, row["frozen_packet"]["graph_sha256"])
    inputs = {
        str(p.relative_to(stored)): sha256(p.read_bytes()).hexdigest()
        for p in (database, pdf, manifest)
    }
    return directory, snapshot, graph, discovery.claims, tagging, source, inputs


class PreliminaryReplay:
    def __init__(self, directory, snapshot, graph, source, tagging):
        runtime = object.__new__(LiveTaggingRuntime)
        runtime.graph, runtime.snapshot = graph, snapshot
        runtime.auth = SimpleNamespace(tenant_id=graph.tenant_id)
        runtime.preliminary_settings = tagging_settings(snapshot, preliminary=True)
        runtime.attribution_policy = snapshot_policy(snapshot)
        runtime.preliminary_records = {}
        runtime.display_catalog = GlyphDisplayCatalog(graph, source)
        transport = object.__new__(UpstagePreliminaryTransport)
        transport._settings = runtime.preliminary_settings
        transport._tenant = graph.tenant_id
        transport._display_catalog = runtime.display_catalog
        # Render only: no operational authorization, reservation, dispatch or publication.
        transport._authorize_request = lambda request: None
        runtime.preliminary_transport = transport
        runtime._source_replicas = self.replicas
        self.runtime = runtime
        self.receipts = defaultdict(list)
        self.records = {r["claim_id"]: r for r in tagging["claims"]}
        self.wire_checks = []
        self.dispatch_checks = {}
        for path in (directory / "tagging-receipts").glob("*/preliminary/*/request.json"):
            request = read(path)
            response = read(path.with_name("response.json"))
            self.receipts[request["request"]["claim_id"]].append((request, response))

    def replicas(self, prefix, claim, packet, settings, transport, records, validate, **kwargs):
        assert prefix == "preliminary"
        results, providers = [], []
        records[claim.claim_id] = []
        if not self.receipts[claim.claim_id]:
            assert "UNEXPECTED" in (self.records[claim.claim_id].get("reason") or "")
            validate_packet(packet)
            entries = packet["untrusted_document_data"]["context_blocks"]
            assert entries[0]["source_id"] == claim.source_refs[0].source_id
            ordinary = [e for e in entries if not e["role"].startswith("table_")]
            assert len(ordinary) <= 4 and sum(len(e["text"]) for e in ordinary) <= 2000
            self.dispatch_checks[claim.claim_id] = dict(
                packet_sha256=canonical_hash(packet),
                context_blocks=len(ordinary),
                context_chars=sum(len(e["text"]) for e in ordinary),
                numbered_sources=len(packet["untrusted_document_data"]["sources"]),
                cf5_context_truncated=bool(kwargs.get("context_receipt")),
                receipt=kwargs.get("context_receipt", {}),
            )
            # The product reached dispatch without exception or a local hold.
            # This offline boundary supplies no provider response or forced vote.
            return None
        retained = {
            r["request_id"]: r
            for r in self.records[claim.claim_id].get("preliminary_records", [])
            if "request_id" in r
        }
        for request, response in sorted(
            self.receipts[claim.claim_id], key=lambda pair: pair[0]["request"]["replicate_id"]
        ):
            raw_request = request["request"]
            assert canonical_hash(packet) == raw_request["packet_sha256"]
            assert canonical_hash(packet) == canonical_hash(json.loads(raw_request["user_json"]))
            assert (
                canonical_hash({k: v for k, v in raw_request.items() if k != "request_signature"})
                == raw_request["request_signature"]
            )
            system, wire, _, _, _ = transport._wire_request(raw_request)
            assert system == request["wire_system"] and wire == request["wire_user_json"]
            self.wire_checks.append(
                dict(
                    request_id=raw_request["request_id"],
                    packet_sha256=canonical_hash(packet),
                    wire_sha256=canonical_hash([system, wire]),
                    response_sha256=canonical_hash(response),
                )
            )
            record = retained[raw_request["request_id"]]
            records[claim.claim_id].append(deepcopy(record))
            if response["usage"]["status"] != "succeeded" or not response["raw_response_json"]:
                assert record["status"] == "needs_review"
                continue
            try:
                result, values = validate(json.loads(response["raw_response_json"]))
            except ValueError:
                assert record["status"] == "needs_review"
                continue
            assert record["status"] == "validated_candidate"
            assert canonical_hash(values) == canonical_hash(record["values"])
            results.append(result)
            providers.append(response["usage"]["provider_request_id"])
        assert len(providers) == len(set(providers))
        return results or None


def replay(stored, company):
    directory, snapshot, graph, claims, tagging, source, inputs = load(stored, company)
    preliminary = PreliminaryReplay(directory, snapshot, graph, source, tagging)
    policy = snapshot["analysis_profile_policy"]
    rules = RulePackSnapshot(**snapshot["rulepack"])
    inventory = InventoryIndex(tagging["sc1_inventory"], graph)
    pages = sorted(set(snapshot["selected_pages"]) & {b.page_num for b in graph.blocks})
    generation = "local-lexical-gri-v1:" + snapshot["input_hash"]
    search = LocalEvidenceSearch(
        graph, tenant_id=graph.tenant_id, pages=pages, index_generation=generation
    )
    gri = LocalGRIRouting(graph, source, tenant_id=graph.tenant_id, pages=pages)
    old = {r["claim_id"]: r for r in tagging["claims"]}
    changes, preserved = [], []
    retrieval_checks = cf6_checks = sc1_checks = 0
    for claim in claims:
        record = old[claim.claim_id]
        failed = "UNEXPECTED" in (record.get("reason") or "")
        classification = preliminary.runtime.preliminary(claim, graph)
        entries, codes = gri.for_claim(claim.quote)
        packet = retrieve_evidence(
            claim,
            graph,
            search,
            tenant_id=graph.tenant_id,
            run_id=snapshot["run_id"],
            index_generation=generation,
            rulepack=rules,
            document_context={},
            token_counter=LiveTaggingRuntime.token_counter,
            gri_entries=entries,
            indicator_codes=codes,
        )
        if record.get("original_packet"):
            assert canonical_hash(packet.to_dict()) == canonical_hash(record["original_packet"])
            retrieval_checks += 1
        if failed:
            assert not preliminary.receipts[claim.claim_id]
            assert not record["tag_runs"] and classification is None
            changes.append(
                dict(
                    claim_id=claim.claim_id,
                    before=record["reason"],
                    after="preliminary_dispatch_reached",
                    dispatch=preliminary.dispatch_checks[claim.claim_id],
                    forced_hold=False,
                    saved_preliminary_responses=0,
                    saved_element_responses=0,
                    evidence_grade=None,
                    source_quality=claim.source_quality,
                )
            )
            continue
        assert (classification is not None) == bool(record.get("tag_runs"))
        if record.get("cf6_receipt"):
            receipt = cf6_analyze(record, claim, graph, rules, policy)
            assert canonical_hash(receipt) == canonical_hash(record["cf6_receipt"])
            cf6_checks += 1
        if record.get("sc1_scope_receipt"):
            receipt = sc1_analyze(
                record,
                claim,
                graph,
                rules,
                inventory,
                required_present_votes=policy["sc1_scope_confirmation"]["agreement"][
                    "required_present_votes"
                ],
                local_synthetic=False,
                grade_agreement_policy=policy.get("grade_required_agreement_policy"),
                v1_activity_policy=policy_from_profile(policy),
            )
            assert canonical_hash(receipt) == canonical_hash(record["sc1_scope_receipt"])
            sc1_checks += 1
        preserved.append(dict(claim_id=claim.claim_id, result_sha256=canonical_hash(record)))
    assert canonical_hash(policy) == PIN
    return dict(
        company=company,
        run_id=directory.name,
        policy_sha256=PIN,
        claims=len(claims),
        unchanged_claims=preserved,
        changes=changes,
        retrieval_packets_unchanged=retrieval_checks,
        cf6_decisions_unchanged=cf6_checks,
        sc1_decisions_unchanged=sc1_checks,
        wire_checks=preliminary.wire_checks,
        inputs_sha256=inputs,
        unexpected_exceptions=0,
        real_provider_calls=0,
        limitation=(
            "All 12 reach preliminary dispatch. No saved responses exist for them; "
            "provider tagging/grades not_run."
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stored", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    def deny(*args, **kwargs):
        raise RuntimeError("FX5_REPLAY_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    reports = []
    for company in RUNS:
        report = replay(args.stored.resolve(), company)
        reports.append(report)
        print(company, report["claims"], "claims replayed", flush=True)
    summary = dict(
        policy_sha256=PIN,
        claims=sum(r["claims"] for r in reports),
        unchanged_claims=sum(len(r["unchanged_claims"]) for r in reports),
        recovered_exception_claims=sum(len(r["changes"]) for r in reports),
        reached_preliminary_dispatch=sum(len(r["changes"]) for r in reports),
        forced_holds=sum(c["forced_hold"] for r in reports for c in r["changes"]),
        cf5_context_truncated=sum(
            c["dispatch"]["cf5_context_truncated"] for r in reports for c in r["changes"]
        ),
        wire_requests_unchanged=sum(len(r["wire_checks"]) for r in reports),
        unexpected_exceptions=0,
        real_provider_calls=0,
        reports=reports,
    )
    assert summary["claims"] == 327 and summary["unchanged_claims"] == 315
    assert summary["recovered_exception_claims"] == 12
    assert summary["cf5_context_truncated"] == 7 and summary["forced_holds"] == 0
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "reports"}))


if __name__ == "__main__":
    main()
