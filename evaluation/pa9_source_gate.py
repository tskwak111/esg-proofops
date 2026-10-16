"""Read-only retained-extraction source gate; no models or grading are invoked."""

import argparse
import json
import socket
import sqlite3
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from time import monotonic

from proofops.adapters.parsing.parser_artifacts import iter_parser_artifacts, read_parser_json
from proofops.application.claims import (
    Claim,
    ClaimDiscovery,
    ClaimExclusion,
    ClaimScope,
    ExtractionProfile,
    ExtractionReceipt,
)
from proofops.application.ingest.graph_fusion import (
    QualityIssue,
    candidates_from_snapshot,
    fuse_candidates,
)
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef

from evaluation.pa3_replay import checkpoint


def discovery_from_record(value):
    def receipt(record):
        return ExtractionReceipt(**(record | dict(profile=ExtractionProfile(**record["profile"]))))

    claims = tuple(
        Claim(
            **(
                c
                | dict(
                    receipt=receipt(c["receipt"]),
                    source_refs=tuple(SourceRef(**r) for r in c["source_refs"]),
                    topic_ids=tuple(c["topic_ids"]),
                )
            )
        )
        for c in value["claims"]
    )
    result = ClaimDiscovery(
        scope=ClaimScope(**value["scope"]),
        source_sha256=value["source_sha256"],
        claims=claims,
        exclusions=tuple(
            ClaimExclusion(
                **(
                    e
                    | dict(source_ref=SourceRef(**e["source_ref"]) if e.get("source_ref") else None)
                )
            )
            for e in value["exclusions"]
        ),
        processed_source_ids=tuple(value["processed_source_ids"]),
        receipts=tuple(receipt(r) for r in value["receipts"]),
        synthetic=value["synthetic"],
        quality_issues=tuple(
            QualityIssue(**(q | dict(source_ids=tuple(q["source_ids"]))))
            for q in value["quality_issues"]
        ),
    )
    assert canonical_hash(asdict(result)) == canonical_hash(value), "PA9_DISCOVERY_DECODE_CHANGED"
    return result


def fixture(path):
    with sqlite3.connect((path / "state.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        snapshot = json.loads(db.execute("SELECT payload FROM run_snapshots").fetchone()[0])
    parse = checkpoint(path, "parse")
    extract = checkpoint(path, "extract")
    prep = next(iter_parser_artifacts(path / "parser-prepared", "candidates.json")).parent
    manifest = json.loads((prep / "manifest.json").read_text())
    graph = fuse_candidates(
        candidates_from_snapshot(read_parser_json(prep / "candidates.json")),
        tenant_id=snapshot["tenant_id"],
        fusion_version=manifest["fusion_version"],
        mixed_parser=True,
    )
    assert graph.to_dict() == read_parser_json(prep / "graph.json"), "PA9_GRAPH_CHANGED"
    graph = replace(
        graph,
        issues=tuple(
            QualityIssue(**(q | dict(source_ids=tuple(q["source_ids"]))))
            for q in json.loads((prep / "quality.json").read_text())
        ),
    )
    source = (
        path
        / "objects/original"
        / snapshot["tenant_id"]
        / (snapshot["document"]["version_id"] + ".pdf")
    ).read_bytes()
    assert (
        sha256(source).hexdigest()
        == snapshot["document"]["sha256"]
        == extract["source_sha256"]
        == manifest["source_sha256"]
    )
    return graph, source, discovery_from_record(extract["discovery"]), snapshot, parse


def main():
    from proofops.adapters.local import evidence_source_ocr_v1 as evidence
    from proofops.adapters.local import upstage_ocr_profile_v6 as v6
    from proofops.adapters.local import upstage_ocr_profile_v9 as v9
    from proofops.adapters.local import upstage_ocr_profile_v10 as v10
    from proofops.adapters.local.claim_source_verification import discovery_refs
    from proofops_api.hosted_ocr import ReplayOCRStore, reader_scope

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)

    def write(name, value):
        (args.output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    def deny(*args, **kwargs):
        raise AssertionError("PA9_SOURCE_GATE_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    names = ("state.sqlite3", "upstage.sqlite3", "luna.sqlite3", "pilot.json")
    hashes = {n: sha256((args.input / n).read_bytes()).hexdigest() for n in names}
    graph, source, discovery, snapshot, parse = fixture(args.input)
    discovery = replace(
        discovery,
        claims=tuple(
            replace(
                c,
                source_quality="unverified",
                source_refs=tuple(
                    replace(r, verification_state="candidate") for r in c.source_refs
                ),
            )
            for c in discovery.claims
        ),
    )
    write("input-discovery.json", asdict(discovery))
    write("input-graph.json", asdict(graph))
    start = monotonic()
    stages = {}
    receipts = {}
    outputs = {}
    with reader_scope(ReplayOCRStore(args.input / "upstage.sqlite3")):
        reader = v6.for_run(snapshot["run_id"])
        phase = monotonic()
        table = reader.attest_tables(graph, source, tenant_id=graph.tenant_id)
        graph = reader.replay_tables(table, graph, source, tenant_id=graph.tenant_id)
        native = reader.attest_native_sources(
            graph,
            source,
            tenant_id=graph.tenant_id,
            geometry_mode=parse["native_paragraph_attestation"]["geometry_mode"],
        )
        graph = reader.replay_native_sources(native, graph, source, tenant_id=graph.tenant_id)
        if "evidence_source_attestation" in parse:
            proof = evidence.attest_evidence_sources(
                graph,
                source,
                tenant_id=graph.tenant_id,
                run_id=snapshot["run_id"],
                physical_pages=parse["evidence_source_attestation"]["physical_pages"],
            )
            graph = evidence.replay_evidence_sources(
                proof, graph, source, tenant_id=graph.tenant_id
            )
        stages["prepare_native_graph"] = monotonic() - phase
        blocks = {b.source_id: b for b in graph.blocks}
        refs = discovery_refs(discovery)
        indices = {
            i for i, r in enumerate(refs) if blocks[r.source_id].kind in ("table", "table_cell")
        }

        def is_table(c):
            return any(blocks[r.source_id].kind in ("table", "table_cell") for r in c.source_refs)

        for module in (v6, v9, v10):
            phase = monotonic()
            reader = module.for_run(snapshot["run_id"])
            receipt = reader.attest_claim_spans(graph, source, refs, tenant_id=graph.tenant_id)
            verified, scoped = module.replay_claim_spans(
                receipt, graph, source, discovery, tenant_id=graph.tenant_id
            )
            stages[module.PROFILE] = monotonic() - phase
            receipts[module.PROFILE] = receipt
            outputs[module.PROFILE] = verified
            write(module.PROFILE + "-receipt.json", receipt)
            write(module.PROFILE + "-claims.json", [asdict(c) for c in verified.claims])
            write(module.PROFILE + "-spans.json", [asdict(r) for r in scoped.verified_spans])
            print(
                json.dumps(
                    dict(
                        profile=module.PROFILE,
                        verified=sum(c.source_quality == "verified" for c in verified.claims),
                        seconds=stages[module.PROFILE],
                    )
                ),
                flush=True,
            )
    base = receipts[v6.PROFILE]
    old = receipts[v9.PROFILE]
    new = receipts[v10.PROFILE]
    assert new["baseline_receipt"] == old["baseline_receipt"] == base, "PA9_V6_BASE_CHANGED"
    assert all(
        new["records"][i] == base["records"][i] for i in range(len(refs)) if i not in indices
    ), "PA9_PROSE_CHANGED"
    summaries = {}
    for profile, result in outputs.items():
        assert len(result.claims) == len(discovery.claims)
        summaries[profile] = dict(
            claims=len(result.claims),
            verified=sum(c.source_quality == "verified" for c in result.claims),
            table_claims=sum(is_table(c) for c in result.claims),
            table_verified=sum(
                is_table(c) and c.source_quality == "verified" for c in result.claims
            ),
            non_table_verified=sum(
                not is_table(c) and c.source_quality == "verified" for c in result.claims
            ),
            seconds=stages[profile],
        )
    trace = [
        dict(
            ref=r,
            table=i in indices,
            v9_status=old["records"][i]["status"],
            v9_reason=old["records"][i]["reason"],
            v10_status=new["records"][i]["status"],
            v10_reason=new["records"][i]["reason"],
            recovery_reason=new["records"][i].get("recovery_reason"),
        )
        for i, r in enumerate([asdict(r) for r in refs])
    ]
    write("source-trace.json", trace)
    for n, h in hashes.items():
        assert sha256((args.input / n).read_bytes()).hexdigest() == h, "PA9_SOURCE_ARTIFACT_CHANGED"
    summary = dict(
        schema="pa9-linux-source-gate-v1",
        input_hashes=hashes,
        source_sha256=sha256(source).hexdigest(),
        reader_policy=v10.claim_source_policy(),
        readers=summaries,
        stages=stages,
        non_table_identical_to_v6=True,
        baseline_receipt_identical=True,
        network="none",
        live_provider_calls=0,
        paid_usd="0",
        source_artifacts_unchanged=True,
        new_tags_and_grades="not_run",
        original_crop_reviews="pending",
        false_verified_observed="pending",
        seconds=monotonic() - start,
    )
    write("summary.json", summary)
    print(json.dumps(summary["readers"]), flush=True)


if __name__ == "__main__":
    main()
