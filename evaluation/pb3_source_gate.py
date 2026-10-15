"""Offline cross-platform replay of immutable PB1/PB2 original-source evidence."""

from __future__ import annotations

import argparse
import json
import pickle
import platform
import socket
from collections import Counter
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from time import monotonic

from proofops.adapters.parsing.parser_artifacts import read_parser_json


def deny_network(*args, **kwargs):
    raise AssertionError("PB3_NETWORK_FORBIDDEN")


def saved_parse_fixture(graph, parse, tables):
    """Rehydrate the Mac-validated evaluation input; never admit a product receipt."""
    from proofops.application.evidence.span_citations import span_verified_graph
    from proofops.domain.values import SourceRef

    cells = {
        source_id
        for record in tables["records"]
        for selection in record["selections"]
        for source_id in selection["promoted_source_ids"]
    }
    table_ids = {r["table_id"] for r in tables["records"] if r["selections"]}
    graph = replace(
        graph,
        blocks=tuple(
            replace(b, quality="verified") if b.source_id in cells else b for b in graph.blocks
        ),
        issues=tuple(
            replace(
                i,
                state="resolved",
                reason=(
                    "Rendered cross-check performed for the attested cells of this "
                    "table only; the remaining cells stay unchecked and unverified."
                ),
            )
            if i.kind == "table_vision_not_run" and i.source_ids and set(i.source_ids) <= table_ids
            else i
            for i in graph.issues
        ),
    )
    native = parse["native_paragraph_attestation"]
    ids = {r["source_id"] for r in native["records"] if r["status"] == "verified"}
    graph = replace(
        graph,
        blocks=tuple(
            replace(b, quality="verified") if b.source_id in ids else b for b in graph.blocks
        ),
    )
    evidence = parse.get("evidence_source_attestation")
    if evidence:
        ids = {
            sid for t in evidence["tables"] if t["status"] == "verified" for sid in t["member_ids"]
        }
        table_ids = {t["table_id"] for t in evidence["tables"] if t["status"] == "verified"}
        graph = replace(
            graph,
            blocks=tuple(
                replace(b, quality="verified") if b.source_id in ids else b for b in graph.blocks
            ),
            issues=tuple(
                replace(
                    i,
                    state="resolved",
                    reason=("EV1 native/rendered grid checked; binding undetermined"),
                )
                if i.kind == "table_vision_not_run"
                and i.source_ids
                and set(i.source_ids) <= table_ids
                else i
                for i in graph.issues
            ),
        )
        refs = tuple(
            replace(SourceRef(**r["ref"]), verification_state="verified")
            for r in evidence["records"]
            if r["kind"] == "paragraph" and r["status"] == "verified"
        )
        from proofops.domain.provenance import canonical_hash

        base = {
            k: v
            for k, v in evidence.items()
            if k not in {"artifact_sha256", "run_id", "page_collections", "rendered_reader_profile"}
        }
        graph = span_verified_graph(
            graph, (*getattr(graph, "verified_spans", ()), *refs), canonical_hash(base)
        )
    return graph


def main():
    from proofops.adapters.local.claim_source_policies import page_ocr_profile
    from proofops.adapters.local.claim_store import (
        _RecordedExtractor,
        claim_scope,
        extraction_profile,
    )
    from proofops.adapters.local.evidence_source_policies import evidence_source_reader
    from proofops.adapters.local.receipt_environment_compat import (
        replay_receipt,
    )
    from proofops.application.claims import discover_atomic_claims
    from proofops.application.ingest.graph_fusion import (
        QualityIssue,
        candidates_from_snapshot,
        fuse_candidates,
    )
    from proofops.domain.provenance import canonical_hash
    from proofops.domain.values import SourceRef
    from proofops_api.hosted_ocr import ReplayOCRStore, reader_scope

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--mode", choices=("prepare", "fresh", "fixed-claims", "cells"), required=True
    )
    args = parser.parse_args()
    source_dir, output = args.input, args.output
    output.mkdir(parents=True, exist_ok=True)
    setattr(socket.socket, "connect", deny_network)
    setattr(socket.socket, "connect_ex", deny_network)
    socket.create_connection = deny_network

    def load(name):
        return read_parser_json(source_dir / name)

    def write(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    hashes = load("input-sha256.json")

    def check_inputs():
        assert hashes == {
            name: sha256((source_dir / name).read_bytes()).hexdigest() for name in hashes
        }, "PB3_INPUT_CHANGED"

    check_inputs()
    start = monotonic()
    frozen, run, parse, extract, manifest = (
        load(name)
        for name in ("snapshot.json", "run.json", "parse.json", "extract.json", "manifest.json")
    )
    assert (
        sha256((source_dir / "extract.json").read_bytes()).hexdigest()
        == (run["claim_snapshot_sha256"])
    )
    source = (source_dir / "selected.pdf").read_bytes()
    assert sha256(source).hexdigest() == parse["source_sha256"]
    graph = fuse_candidates(
        candidates_from_snapshot(load("candidates.json")),
        tenant_id=parse["tenant_id"],
        fusion_version=manifest["fusion_version"],
        mixed_parser=True,
    )
    assert graph.to_dict() == load("graph.json"), "PB3_FUSION_CHANGED"
    graph = replace(
        graph,
        issues=tuple(
            QualityIssue(**{**issue, "source_ids": tuple(issue["source_ids"])})
            for issue in load("quality.json")
        ),
    )
    policy = frozen["claim_source_policy"]
    module = page_ocr_profile(policy["profile"])
    current_policy = module.claim_source_policy()
    if args.mode == "cells":
        saved = extract["claim_source_attestation"]
        blocks = {b.source_id: b for b in graph.blocks}
        table_refs = [
            SourceRef(**r["ref"])
            for r in saved["records"]
            if blocks[r["ref"]["source_id"]].kind in {"table", "table_cell"}
        ]
        proofs = module.cell_proof(graph, source, table_refs, tenant_id=graph.tenant_id)
        before = saved.get("pb1_cell_proofs", [])
        write("cell-proofs.json", proofs)
        differences = [
            dict(index=i, mac=a, linux=b)
            for i, (a, b) in enumerate(zip(before, proofs, strict=True))
            if canonical_hash(a) != canonical_hash(b)
        ]
        write("cell-differences.json", differences)
        summary = dict(
            schema="pb3-cell-diagnostic-v1",
            reader=policy["profile"],
            platform=platform.system(),
            machine=platform.machine(),
            network="denied",
            paid_calls=0,
            numeric_promotions=0,
            gate_passed=False,
            saved_claims=len(extract["discovery"]["claims"]),
            table_claim_refs=len(table_refs),
            table_verified_before_after=[
                sum(p["status"] == "verified" for p in before),
                sum(p["status"] == "verified" for p in proofs),
            ],
            table_cell_proofs_equal=not differences,
            verified_cell_refs=sum(
                len(p.get("cell_proofs", [])) for p in proofs if p["status"] == "verified"
            ),
            full_claim_replay="blocked",
            historical_mac_receipt_portable=policy == current_policy,
            saved_runtime=policy["reader"]["local_raster"],
            fresh_runtime=current_policy["reader"]["local_raster"],
            source_verified_before_after=[
                sum(
                    c["source_status"]["status"] == "verified"
                    for c in load("published-result.json")["claims"]
                ),
                None,
            ],
            original_crop_reviews="pending",
            false_verified_observed="pending",
            input_hashes=hashes,
            elapsed_seconds=round(monotonic() - start, 3),
        )
        check_inputs()
        write("cell-summary.json", summary)
        print(json.dumps({k: v for k, v in summary.items() if k != "input_hashes"}), flush=True)
        assert not differences, "PB3_CELL_PARITY_FAILED"
        return
    if args.mode == "prepare":
        assert policy == current_policy, "PB3_READER_BYTES_CHANGED"
    with reader_scope(ReplayOCRStore(source_dir / "upstage.sqlite3")):
        reader = module.for_run(run["run_id"])
        if args.mode == "fixed-claims":
            graph = saved_parse_fixture(graph, parse, load("table-source.json"))
            assert canonical_hash(asdict(graph)) == extract["graph_sha256"], "PB3_GRAPH_CHANGED"
            native = parse["native_paragraph_attestation"]
        elif args.mode == "fresh":
            # Mint receipts under the REAL Linux CPU runtime. Never reinterpret
            # or overwrite the Mac receipt's unavailable-runtime policy.
            table_receipt = reader.attest_tables(graph, source, tenant_id=graph.tenant_id)
            write("table-receipt.json", table_receipt)
            graph = module.replay_tables(table_receipt, graph, source, tenant_id=graph.tenant_id)
            native = reader.attest_native_sources(
                graph,
                source,
                tenant_id=graph.tenant_id,
                geometry_mode=parse["native_paragraph_attestation"]["geometry_mode"],
            )
            write("native-receipt.json", native)
        else:
            graph = replay_receipt(
                module.replay_tables,
                load("table-source.json"),
                graph,
                source,
                tenant_id=graph.tenant_id,
            )
            native = parse["native_paragraph_attestation"]
        if args.mode != "fixed-claims":
            graph = reader.replay_native_sources(native, graph, source, tenant_id=graph.tenant_id)
        if "evidence_source_attestation" in parse and args.mode != "fixed-claims":
            evidence = evidence_source_reader(frozen["evidence_source_policy"])
            evidence_receipt = parse["evidence_source_attestation"]
            if args.mode == "fresh":
                evidence_receipt = evidence.attest_evidence_sources(
                    graph,
                    source,
                    tenant_id=graph.tenant_id,
                    physical_pages=evidence_receipt["physical_pages"],
                )
                write("evidence-receipt.json", evidence_receipt)
            graph = evidence.replay_evidence_sources(
                evidence_receipt, graph, source, tenant_id=graph.tenant_id
            )
        if args.mode == "prepare":
            assert canonical_hash(asdict(graph)) == extract["graph_sha256"], "PB3_GRAPH_CHANGED"
            discovery = discover_atomic_claims(
                graph,
                claim_scope(frozen, graph),
                extractor=_RecordedExtractor(
                    extraction_profile(frozen), extract["discovery"]["receipts"]
                ),
            )
        else:
            # Private evaluator fixture, generated by prepare from hash-checked
            # saved model responses; not an upload or product input boundary.
            assert "mac-discovery.pickle" in hashes, "PB3_FIXTURE_UNPINNED"
            discovery = pickle.loads((source_dir / "mac-discovery.pickle").read_bytes())
        assert canonical_hash(asdict(discovery)) == canonical_hash(
            extract["discovery"]
        ), "PB3_SAVED_EXTRACTION_CHANGED"
        if args.mode == "prepare":
            (output / "mac-discovery.pickle").write_bytes(pickle.dumps(discovery))
            check_inputs()
            print("Mac parse receipts and saved extraction reproduced", flush=True)
            return
        saved = extract["claim_source_attestation"]
        refs = tuple(SourceRef(**record["ref"]) for record in saved["records"])
        fresh = reader.attest_claim_spans(graph, source, refs, tenant_id=graph.tenant_id)
        write("receipt.json", fresh)
        rows = [
            dict(
                ref=before["ref"],
                before=before["status"],
                before_reason=before["reason"],
                after=after["status"],
                after_reason=after["reason"],
            )
            for before, after in zip(saved["records"], fresh["records"], strict=True)
        ]
        differences = [
            row
            for row in rows
            if (row["before"], row["before_reason"]) != (row["after"], row["after_reason"])
        ]
        cells_equal = canonical_hash(saved.get("pb1_cell_proofs", [])) == canonical_hash(
            fresh.get("pb1_cell_proofs", [])
        )
        write("census.json", rows)
        write("differences.json", differences)
        verified, verified_graph = module.replay_claim_spans(
            fresh, graph, source, discovery, tenant_id=graph.tenant_id
        )
    published = load("published-result.json")
    actual = {claim.claim_id for claim in verified.claims if claim.source_quality == "verified"}
    expected = {
        claim["claim_id"]
        for claim in published["claims"]
        if claim["source_status"]["status"] == "verified"
    }
    claim_difference = dict(
        mac_only=sorted(expected - actual), linux_only=sorted(actual - expected)
    )
    write("claim-differences.json", claim_difference)
    write("verified-claims.json", [asdict(c) for c in verified.claims if c.claim_id in actual])
    write(
        "verified-spans.json",
        [asdict(ref) for ref in getattr(verified_graph, "verified_spans", ())],
    )
    check_inputs()
    summary = dict(
        schema="pb3-source-gate-v1",
        reader=policy["profile"],
        platform=platform.system(),
        machine=platform.machine(),
        network="denied",
        paid_calls=0,
        numeric_promotions=0,
        saved_claims=len(discovery.claims),
        replayed_claims=len(verified.claims),
        source_verified_before_after=[len(expected), len(actual)],
        verified_claim_sets_equal=expected == actual,
        table_cell_proofs_equal=cells_equal,
        saved_runtime=policy["reader"]["local_raster"],
        fresh_runtime=current_policy["reader"]["local_raster"],
        historical_mac_receipt_portable=policy == current_policy,
        evaluation_scope=args.mode,
        native_verified_before_after=[
            sum(
                r["status"] == "verified" for r in parse["native_paragraph_attestation"]["records"]
            ),
            sum(r["status"] == "verified" for r in native["records"]),
        ],
        claim_discovery_sha256=canonical_hash(asdict(discovery)),
        verified_discovery_sha256=canonical_hash(asdict(verified)),
        verified_graph_sha256=canonical_hash(asdict(verified_graph)),
        table_claims=sum(
            len(p.get("cell_proofs", [])) > 0 for p in fresh.get("pb1_cell_proofs", [])
        ),
        verified_cell_refs=sum(
            len(p.get("cell_proofs", []))
            for p in fresh.get("pb1_cell_proofs", [])
            if p["status"] == "verified"
        ),
        after_reasons=dict(Counter(row["after_reason"] or "verified" for row in rows)),
        status_differences=len(differences),
        original_crop_reviews="pending",
        false_verified_observed="pending",
        input_hashes=hashes,
        elapsed_seconds=round(monotonic() - start, 3),
        original_artifacts_unchanged=True,
        new_tags_and_grades="not_run",
    )
    write("summary.json", summary)
    assert expected == actual and cells_equal and not differences, "PB3_PARITY_FAILED"
    assert len(discovery.claims) == len(published["claims"]), "PB3_CLAIM_COUNT_CHANGED"
    print(json.dumps({k: v for k, v in summary.items() if k != "input_hashes"}), flush=True)


if __name__ == "__main__":
    main()
