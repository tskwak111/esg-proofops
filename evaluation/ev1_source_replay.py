"""Offline MP1 source census and real retrieval replay; immutable saved inputs."""

import argparse
import json
import socket
import sqlite3
from collections import Counter
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from time import monotonic

from proofops.adapters.local import evidence_source_verification_v1 as verifier
from proofops.adapters.local.evidence_search import LocalEvidenceSearch
from proofops.adapters.parsing.parser_artifacts import parser_artifact_path, read_parser_json
from proofops.application.claims import Claim, ExtractionProfile, ExtractionReceipt
from proofops.application.evidence.retrieval import retrieve_evidence
from proofops.application.evidence.span_citations import span_verified_graph, verify_source_ref
from proofops.application.ingest.graph_fusion import (
    QualityIssue,
    candidates_from_snapshot,
    fuse_candidates,
)
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.values import SourceRef

ROOT = Path("/path/to/ESG_ProofOps")
BASE = ROOT / "outputs/agent-results/R108-redesign/lab/parse/MP1"
OUT = ROOT / "outputs/agent-results/R108-redesign/lab/source/EV1"


def deny(*args, **kwargs):
    raise RuntimeError("EV1_NETWORK_FORBIDDEN")


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def load(company):
    state = BASE / "states" / company
    with sqlite3.connect((state / "state.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        rows = db.execute(
            "SELECT value FROM job_records WHERE kind='artifact' "
            "AND record_id LIKE '%/checkpoint'"
        ).fetchall()
        snapshot = json.loads(db.execute("SELECT payload FROM run_snapshots").fetchone()[0])
    checkpoints = {json.loads(v)["schema"]: (json.loads(v), sha256(v).hexdigest()) for (v,) in rows}
    parse, parse_hash = checkpoints["local_parser_checkpoint_v4"]
    extract, _ = checkpoints["local_extract_checkpoint_v2"]
    assert extract["parse_checkpoint_sha256"] == parse_hash
    folder = (
        state
        / "parser-prepared"
        / parse["tenant_id"]
        / parse["document_version_id"]
        / parse["parse_manifest_id"]
    )
    manifest_bytes = (folder / "manifest.json").read_bytes()
    assert sha256(manifest_bytes).hexdigest() == parse["manifest_sha256"]
    for name, digest in parse["artifacts"].items():
        assert sha256((folder / name).read_bytes()).hexdigest() == digest
    manifest = json.loads(manifest_bytes)
    graph = fuse_candidates(
        candidates_from_snapshot(read_parser_json(folder / "candidates.json")),
        tenant_id=parse["tenant_id"],
        fusion_version=manifest["fusion_version"],
        mixed_parser=True,
    )
    assert graph.to_dict() == read_parser_json(folder / "graph.json")
    graph = replace(
        graph,
        issues=tuple(
            QualityIssue(**{**issue, "source_ids": tuple(issue["source_ids"])})
            for issue in read_parser_json(folder / "quality.json")
        ),
    )
    native = parse["native_paragraph_attestation"]
    assert native["input_graph_sha256"] == canonical_hash(asdict(graph))
    for receipt in (native, extract["claim_source_attestation"]):
        content = dict(receipt)
        digest = content.pop("artifact_sha256")
        assert canonical_hash(content) == digest
        assert receipt["source_sha256"] == graph.source_sha256
    source_path = next(
        p
        for p in (state / "objects/original").glob("**/*.pdf")
        if sha256(p.read_bytes()).hexdigest() == graph.source_sha256
    )
    inputs = {
        str(p): sha256(p.read_bytes()).hexdigest()
        for p in (
            state / "state.sqlite3",
            parser_artifact_path(folder / "candidates.json", manifest=manifest),
            folder / "manifest.json",
            parser_artifact_path(folder / "graph.json", manifest=manifest),
            source_path,
        )
    }
    return graph, source_path, parse, extract, snapshot, inputs


def historical_view(graph, parse, extract):
    # Baseline is a pinned saved artifact, not a new source approval. New evidence
    # always goes through the original-PDF verifier and its fresh replay below.
    verified = {
        r["source_id"]
        for r in parse["native_paragraph_attestation"]["records"]
        if r["status"] == "verified"
    }
    base = replace(
        graph,
        blocks=tuple(
            replace(b, quality="verified") if b.source_id in verified else b for b in graph.blocks
        ),
    )
    refs = tuple(
        replace(SourceRef(**r["ref"]), verification_state="verified")
        for r in extract["claim_source_attestation"]["records"]
        if r["status"] == "verified"
    )
    return span_verified_graph(base, refs, extract["claim_source_attestation"]["artifact_sha256"])


def claims(extract, graph):
    result = []
    for raw in extract["discovery"]["claims"]:
        values = dict(raw)
        receipt = dict(values["receipt"])
        receipt["profile"] = ExtractionProfile(**receipt["profile"])
        values["receipt"] = ExtractionReceipt(**receipt)
        values["source_refs"] = tuple(
            verify_source_ref(SourceRef(**ref), graph, tenant_id=graph.tenant_id)
            for ref in values["source_refs"]
        )
        if all(r.verification_state == "verified" for r in values["source_refs"]):
            values["source_quality"] = "verified"
        values["topic_ids"] = tuple(values["topic_ids"])
        result.append(Claim(**values))
    return result


def packets(graph, extract, snapshot):
    search = LocalEvidenceSearch(
        graph,
        tenant_id=graph.tenant_id,
        pages=sorted({b.page_num for b in graph.blocks}),
        index_generation="ev1-saved-mp1",
    )
    pack = RulePackSnapshot(**snapshot["rulepack"])
    # Stable conservative UTF-8 byte bound, no model tokenizer/network import.
    return [
        retrieve_evidence(
            claim,
            graph,
            search,
            tenant_id=graph.tenant_id,
            run_id=snapshot["run_id"],
            index_generation=search.scope.index_generation,
            rulepack=pack,
            document_context={
                "company": snapshot["document"]["company"]["legal_name"],
                "period": str(snapshot["document"]["report_year"]),
            },
            token_counter=lambda text: len(text.encode("utf-8")),
        ).to_dict()
        for claim in claims(extract, graph)
    ]


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--company", choices=["samsung", "kepco"], required=True)
    args.add_argument("--resume", action="store_true")
    options = args.parse_args()
    company = options.company
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    measurement = next(
        m for m in json.loads((BASE / "measurements.json").read_text()) if m["company"] == company
    )
    graph, source_path, parse, extract, snapshot, inputs = load(company)
    source = source_path.read_bytes()
    pages = sorted(measurement["odl_pages"] + measurement["unreadable_pages"])
    before = historical_view(graph, parse, extract)
    start = monotonic()
    # Page-sized immutable receipts allow interruption/resume without redoing
    # previously checked original bytes; policy/input hashes remain mandatory.
    receipts, records, tables = [], [], []
    directory = OUT / company
    directory.mkdir(exist_ok=True)
    after = graph
    for page in pages:
        receipt_path = directory / f"page-{page}.json"
        if options.resume and receipt_path.exists():
            receipt = json.loads(receipt_path.read_bytes())
            assert receipt["physical_pages"] == [page]
        else:
            receipt = verifier.attest_evidence_sources(
                graph, source, tenant_id=graph.tenant_id, physical_pages=(page,)
            )
            write(receipt_path, receipt)
        checked = verifier.replay_evidence_sources(
            receipt, graph, source, tenant_id=graph.tenant_id
        )
        receipts.append(receipt["artifact_sha256"])
        records.extend(receipt["records"])
        tables.extend(receipt["tables"])
        checked_ids = {b.source_id for b in checked.blocks if b.quality == "verified"}
        after = replace(
            after,
            blocks=tuple(
                replace(b, quality="verified") if b.source_id in checked_ids else b
                for b in after.blocks
            ),
            issues=tuple(
                next(i for i in checked.issues if i.issue_id == old.issue_id)
                if old.kind == "table_vision_not_run" and old.page_num == page
                else old
                for old in after.issues
            ),
        )
        after = span_verified_graph(
            after,
            tuple(getattr(after, "verified_spans", ())) + checked.verified_spans,
            canonical_hash(receipts),
        )
        print(
            company,
            page,
            dict(Counter(r["reason"] or "verified" for r in receipt["records"])),
            "seconds",
            round(monotonic() - start, 2),
            flush=True,
        )
    historical_ids = {b.source_id for b in before.blocks if b.quality == "verified"}
    after = span_verified_graph(
        replace(
            after,
            blocks=tuple(
                replace(b, quality="verified") if b.source_id in historical_ids else b
                for b in after.blocks
            ),
        ),
        before.verified_spans + after.verified_spans,
        canonical_hash(receipts),
    )
    before_packets, after_packets = (
        packets(before, extract, snapshot),
        packets(after, extract, snapshot),
    )
    write(directory / "packets-before.json", before_packets)
    write(directory / "packets-after.json", after_packets)
    old = {r["source_id"]: r for r in parse["native_paragraph_attestation"]["records"]}
    inventory = [
        dict(r, old_reason=old[r["source_id"]]["reason"], old_status=old[r["source_id"]]["status"])
        for r in records
    ]
    write(directory / "inventory.json", inventory)
    page_summary = []
    for page in pages:

        def counts(items):
            candidates = [
                (p, c)
                for p in items
                for c in p["evidence_candidates"]
                if any(r["page_num"] == page for r in c["source_refs"])
            ]
            opportunities = {
                (p["claim_id"], e) for p, c in candidates for e in c["allowed_elements"]
            }
            return dict(
                adopted_candidates=len(candidates),
                adopted_packets=len({p["claim_id"] for p, c in candidates}),
                citation_ready_element_slots=len(opportunities),
                possible_elements=sorted({e for _, e in opportunities}),
            )

        page_records = [r for r in inventory if r["page"] == page]
        page_summary.append(
            dict(
                page=page,
                before_verified_blocks=sum(r["old_status"] == "verified" for r in page_records),
                after_full_span_or_grid_verified_blocks=sum(
                    r["status"] == "verified" for r in page_records
                ),
                after_reasons=dict(Counter(r["reason"] or "verified" for r in page_records)),
                before=counts(before_packets),
                after=counts(after_packets),
                unreadable=page in measurement["unreadable_pages"],
            )
        )
    assert all(sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in inputs.items())
    summary = dict(
        company=company,
        policy=verifier.policy(),
        pages=page_summary,
        verified_tables=sum(t["status"] == "verified" for t in tables),
        tables=tables,
        input_hashes=inputs,
        source_path=str(source_path),
        elapsed_seconds=round(monotonic() - start, 3),
        paid_calls=0,
        network="denied",
        semantic_binding="undetermined",
        actual_present_and_grades="not_run",
        possible_element_definition=(
            "citation-ready packet slots; binding/semantic sufficiency not established"
        ),
    )
    write(directory / "summary.json", summary)
    print(company, "replay summary written", summary["elapsed_seconds"], flush=True)


if __name__ == "__main__":
    main()
