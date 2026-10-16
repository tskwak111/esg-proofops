"""PB4 fresh Linux source comparison; saved extraction, no tagging or provider calls."""

import argparse
import json
import pickle
import socket
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from time import monotonic

from proofops.adapters.parsing.parser_artifacts import read_parser_json
from proofops.domain.provenance import canonical_hash


def deny_network(*args, **kwargs):
    raise AssertionError("PB4_GATE_NETWORK_FORBIDDEN")


def main():
    from proofops.adapters.local import evidence_source_ocr_v1 as evidence
    from proofops.adapters.local import upstage_ocr_profile_v6 as v6
    from proofops.adapters.local import upstage_ocr_profile_v8 as v8
    from proofops.adapters.local import upstage_ocr_profile_v9 as v9
    from proofops.adapters.local.claim_source_verification import discovery_refs
    from proofops.application.ingest.graph_fusion import (
        QualityIssue,
        candidates_from_snapshot,
        fuse_candidates,
    )
    from proofops_api.hosted_ocr import ReplayOCRStore, reader_scope

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    setattr(socket.socket, "connect", deny_network)
    setattr(socket.socket, "connect_ex", deny_network)
    socket.create_connection = deny_network

    def load(name):
        return read_parser_json(args.input / name)

    def write(name, value):
        (args.output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    hashes = load("input-sha256.json")
    assert all(sha256((args.input / n).read_bytes()).hexdigest() == h for n, h in hashes.items())
    ledger_hash = sha256(args.ledger.read_bytes()).hexdigest()
    start = monotonic()
    manifest, parse, extract, run = (
        load(n) for n in ("manifest.json", "parse.json", "extract.json", "run.json")
    )
    source = (args.input / "selected.pdf").read_bytes()
    assert sha256(source).hexdigest() == parse["source_sha256"]
    graph = fuse_candidates(
        candidates_from_snapshot(load("candidates.json")),
        tenant_id=run["tenant_id"],
        fusion_version=manifest["fusion_version"],
        mixed_parser=True,
    )
    assert graph.to_dict() == load("graph.json")
    graph = replace(
        graph,
        issues=tuple(
            QualityIssue(**{**i, "source_ids": tuple(i["source_ids"])})
            for i in load("quality.json")
        ),
    )
    with reader_scope(ReplayOCRStore(args.ledger)):
        reader = v6.for_run(run["run_id"])
        tables = reader.attest_tables(graph, source, tenant_id=graph.tenant_id)
        write("table-receipt.json", tables)
        graph = reader.replay_tables(tables, graph, source, tenant_id=graph.tenant_id)
        native = reader.attest_native_sources(
            graph,
            source,
            tenant_id=graph.tenant_id,
            geometry_mode=parse["native_paragraph_attestation"]["geometry_mode"],
        )
        write("native-receipt.json", native)
        graph = reader.replay_native_sources(native, graph, source, tenant_id=graph.tenant_id)
        if "evidence_source_attestation" in parse:
            proof = evidence.attest_evidence_sources(
                graph,
                source,
                tenant_id=graph.tenant_id,
                run_id=run["run_id"],
                physical_pages=parse["evidence_source_attestation"]["physical_pages"],
            )
            write("evidence-receipt.json", proof)
            graph = evidence.replay_evidence_sources(
                proof, graph, source, tenant_id=graph.tenant_id
            )
        assert "mac-discovery.pickle" in hashes
        # A private fixture already reproduced from saved model responses in
        # PB3. Its Mac source approvals are cleared in this NEW evaluation;
        # only the freshly reconstructed Linux graph/receipts can approve them.
        discovery = pickle.loads((args.input / "mac-discovery.pickle").read_bytes())
        assert canonical_hash(asdict(discovery)) == canonical_hash(extract["discovery"])
        discovery = replace(
            discovery,
            claims=tuple(
                replace(
                    c,
                    source_quality="unverified"
                    if c.source_quality == "verified"
                    else c.source_quality,
                    source_refs=tuple(
                        replace(r, verification_state="unverified")
                        if r.verification_state == "verified"
                        else r
                        for r in c.source_refs
                    ),
                )
                for c in discovery.claims
            ),
        )
        refs = discovery_refs(discovery)
        blocks = {b.source_id: b for b in graph.blocks}
        table_indices = {
            i for i, r in enumerate(refs) if blocks[r.source_id].kind in {"table", "table_cell"}
        }
        observations = {}
        receipts = {}
        for module in (v6, v8, v9):
            phase = monotonic()
            reader = module.for_run(run["run_id"])
            receipt = reader.attest_claim_spans(graph, source, refs, tenant_id=graph.tenant_id)
            write(module.PROFILE + "-receipt.json", receipt)
            verified, scoped = module.replay_claim_spans(
                receipt, graph, source, discovery, tenant_id=graph.tenant_id
            )
            write(module.PROFILE + "-claims.json", [asdict(c) for c in verified.claims])
            write(module.PROFILE + "-spans.json", [asdict(r) for r in scoped.verified_spans])
            observations[module.PROFILE] = dict(
                claims=len(verified.claims),
                verified=sum(c.source_quality == "verified" for c in verified.claims),
                verified_claim_ids=sorted(
                    c.claim_id for c in verified.claims if c.source_quality == "verified"
                ),
                non_table_verified=sum(
                    r["status"] == "verified"
                    for i, r in enumerate(receipt["records"])
                    if i not in table_indices
                ),
                table_verified=sum(
                    r["status"] == "verified"
                    for i, r in enumerate(receipt["records"])
                    if i in table_indices
                ),
                seconds=round(monotonic() - phase, 3),
            )
            receipts[module.PROFILE] = receipt
            print(module.PROFILE, observations[module.PROFILE], flush=True)
    base, old, new = (receipts[m.PROFILE] for m in (v6, v8, v9))
    rows = []
    for i, (a, b, c) in enumerate(
        zip(base["records"], old["records"], new["records"], strict=True)
    ):
        rows.append(
            dict(
                ref=a["ref"],
                table=i in table_indices,
                v6_status=a["status"],
                v6_reason=a["reason"],
                v8_status=b["status"],
                v8_reason=b["reason"],
                v9_status=c["status"],
                v9_reason=c["reason"],
                v9_prose_record_identical_to_v6=i in table_indices or a == c,
            )
        )
    write("source-trace.json", rows)
    write(
        "v6-v8-status-differences.json",
        [
            r
            for r in rows
            if not r["table"]
            and (r["v6_status"], r["v6_reason"]) != (r["v8_status"], r["v8_reason"])
        ],
    )
    write(
        "table-changes.json",
        [
            r
            for r in rows
            if r["table"] and (r["v8_status"], r["v8_reason"]) != (r["v9_status"], r["v9_reason"])
        ],
    )
    parity = all(r["v9_prose_record_identical_to_v6"] for r in rows)
    assert canonical_hash(new["baseline_receipt"]) == canonical_hash(base), "PB4_V6_BASE_CHANGED"
    assert ledger_hash == sha256(args.ledger.read_bytes()).hexdigest()
    assert all(sha256((args.input / n).read_bytes()).hexdigest() == h for n, h in hashes.items())
    summary = dict(
        schema="pb4-source-gate-v1",
        network="none",
        paid_gate_calls=0,
        saved_claims=len(discovery.claims),
        readers=observations,
        non_table_v9_identical_to_v6=parity,
        v6_baseline_receipt_identical=True,
        source_policy=v9.claim_source_policy(),
        input_hashes=hashes,
        linux_ocr_ledger_sha256=ledger_hash,
        original_crop_reviews="pending",
        false_verified_observed="pending",
        numeric_promotions=0,
        elapsed_seconds=round(monotonic() - start, 3),
    )
    write("summary.json", summary)
    assert parity, "PB4_PROSE_REGRESSION"


if __name__ == "__main__":
    main()
