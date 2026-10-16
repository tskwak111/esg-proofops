"""Free saved E2E8 replay: immutable SQLite reads, PDFium + local Vision only."""

import json
import socket
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from time import monotonic

from proofops.adapters.local import claim_source_verification_v3 as verifier
from proofops.adapters.parsing.parser_artifacts import parser_artifact_path, read_parser_json
from proofops.application.ingest.graph_fusion import candidates_from_snapshot, fuse_candidates
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef

from evaluation.sv1_source_audit import BASE, OUT, load_state


def deny(*args, **kwargs):
    raise RuntimeError("SV1_NETWORK_FORBIDDEN")


def main():
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    output = OUT / "replay"
    output.mkdir(exist_ok=True)
    summary, recovered = [], []
    for name, raw in json.loads((BASE / "state-map.json").read_text()).items():
        start = monotonic()
        state = Path(raw)
        state_hash = sha256((state / "state.sqlite3").read_bytes()).hexdigest()
        funnel, extract, parse, folder, pdf = load_state(state)
        original = pdf.read_bytes()
        batches = candidates_from_snapshot(read_parser_json(folder / "candidates.json"))
        manifest_bytes = (folder / "manifest.json").read_bytes()
        assert sha256(manifest_bytes).hexdigest() == extract["manifest_sha256"]
        manifest = json.loads(manifest_bytes)
        graph = fuse_candidates(
            batches, tenant_id=funnel["tenant_id"], fusion_version=manifest.get("fusion_version", 1)
        )
        assert graph.to_dict() == read_parser_json(folder / "graph.json")
        graph_path = parser_artifact_path(folder / "graph.json", manifest=manifest)
        assert sha256(graph_path.read_bytes()).hexdigest() == parse["artifacts"][graph_path.name]
        baseline = extract["claim_source_attestation"]
        copy = dict(baseline)
        digest = copy.pop("artifact_sha256")
        assert canonical_hash(copy) == digest
        refs = tuple(SourceRef(**r["ref"]) for r in baseline["records"])
        result = verifier._extend_receipt(
            baseline, graph, original, refs, tenant_id=graph.tenant_id
        )
        (output / (name + ".json")).write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        new = {canonical_hash(r["ref"]): r for r in result["records"]}
        gains, losses = [], []
        unresolved = Counter()
        for claim in funnel["claims"]:
            atts = claim["source_verification"]["attestations"]
            keys = [canonical_hash(r["ref"]) for r in atts]
            before = claim["source_verification"]["status"] == "verified"
            after = all(
                new.get(k, r)["status"] == "verified" for k, r in zip(keys, atts, strict=True)
            )
            if after and not before:
                records = [new[k] for k in keys]
                gains.append(claim["claim_id"])
                recovered.append(
                    dict(
                        state=name,
                        claim_id=claim["claim_id"],
                        source_path=str(pdf),
                        source_sha256=graph.source_sha256,
                        records=records,
                    )
                )
            if before and not after:
                losses.append(claim["claim_id"])
            if not after:
                for k, r in zip(keys, atts, strict=True):
                    rr = new.get(k, r)
                    if rr["status"] != "verified":
                        unresolved[rr["reason"]] += 1
        assert sha256((state / "state.sqlite3").read_bytes()).hexdigest() == state_hash
        row = dict(
            state=name,
            total=funnel["summary"]["total"],
            before=funnel["summary"]["source_verified"],
            recovered=len(gains),
            regressed=len(losses),
            after=funnel["summary"]["source_verified"] + len(gains) - len(losses),
            recovered_claim_ids=gains,
            regressed_claim_ids=losses,
            unresolved=dict(unresolved),
            elapsed_seconds=round(monotonic() - start, 3),
            state_sha256=state_hash,
            extract_sha256=funnel["checkpoint_pins"]["extract"]["sha256"],
            source_sha256=graph.source_sha256,
            baseline_policy=baseline["policy"],
            replay_graph_sha256=canonical_hash(asdict(graph)),
            stored_graph_sha256=extract["graph_sha256"],
        )
        summary.append(row)
        (OUT / "replay-summary.json").write_text(
            json.dumps(
                dict(
                    policy=verifier.claim_source_policy(),
                    states=summary,
                    recovered=recovered,
                    paid_calls=0,
                    network="denied",
                    downstream="not_run",
                ),
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        print(
            name,
            "recovered",
            len(gains),
            "regressed",
            len(losses),
            "remaining",
            dict(unresolved),
            "seconds",
            row["elapsed_seconds"],
            flush=True,
        )


if __name__ == "__main__":
    main()
