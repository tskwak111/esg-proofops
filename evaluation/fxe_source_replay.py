"""Offline E14 saved-claim replay on the pinned Linux server image; no provider calls."""

import argparse
import json
import platform
import socket
from collections import Counter
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from time import monotonic
from unittest.mock import patch

from proofops.adapters.local import upstage_ocr_profile_fxe as fxe
from proofops.adapters.local.claim_source_verification import discovery_refs
from proofops.adapters.local.upstage_ocr_page import PageOCRStore
from proofops.adapters.local.verified_read_cache import _project_owned_cells, _project_parse
from proofops.adapters.parsing.parser_artifacts import parser_artifact_path, read_parser_json
from proofops.application.ingest.graph_fusion import (
    QualityIssue,
    candidates_from_snapshot,
    fuse_candidates,
)
from proofops.domain.provenance import canonical_hash

from evaluation.pa9_source_gate import discovery_from_record


def load_fixture(path):
    def read(name):
        return read_parser_json(path / name)

    snapshot, manifest = read("snapshot.json"), read("manifest.json")
    parse, extract = read("parse.json"), read("extract.json")
    assert sha256((path / "manifest.json").read_bytes()).hexdigest() == extract["manifest_sha256"]
    for name in ("graph.json", "quality.json", "candidates.json"):
        artifact = parser_artifact_path(path / name, manifest=manifest)
        assert sha256(artifact.read_bytes()).hexdigest() == manifest["artifacts"][artifact.name]
    source = (path / "selected.pdf").read_bytes()
    assert sha256(source).hexdigest() == extract["source_sha256"] == manifest["source_sha256"]
    graph = fuse_candidates(
        candidates_from_snapshot(read("candidates.json")),
        tenant_id=snapshot["tenant_id"],
        fusion_version=manifest["fusion_version"],
        mixed_parser=True,
    )
    assert graph.to_dict() == read("graph.json")
    graph = replace(
        graph,
        issues=tuple(
            QualityIssue(**(q | dict(source_ids=tuple(q["source_ids"]))))
            for q in read("quality.json")
        ),
    )
    # Reconstruct the exact saved input, checking every graph boundary. This is
    # fixture decoding, not new source admission; the claim reader recomputes
    # its complete historical receipt and every new proof from original bytes.
    for key, native in (
        ("native_paragraph_attestation", True),
        ("evidence_source_attestation", False),
    ):
        receipt = parse[key]
        assert receipt["artifact_sha256"] == canonical_hash(
            {k: v for k, v in receipt.items() if k != "artifact_sha256"}
        )
        assert receipt["input_graph_sha256"] == canonical_hash(asdict(graph))
        graph = _project_parse(receipt, graph, native=native)
    assert canonical_hash(asdict(graph)) == parse["graph_sha256"] == extract["graph_sha256"]
    assert (
        canonical_hash(asdict(graph)) == extract["claim_source_attestation"]["input_graph_sha256"]
    )
    return (
        graph,
        source,
        discovery_from_record(extract["discovery"]),
        extract["claim_source_attestation"],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    def write(name, data):
        (args.output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    def deny(*args, **kwargs):
        raise AssertionError("FXE_NETWORK_FORBIDDEN")

    class Offline:
        validate = staticmethod(PageOCRStore.validate)

        def fetch(self, *args, **kwargs):
            raise ValueError("OCR_REPLAY_PAGE_MISSING")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    hashes = {
        f.name: sha256(f.read_bytes()).hexdigest() for f in args.input.iterdir() if f.is_file()
    }
    graph, source, discovery, baseline = load_fixture(args.input)
    refs = discovery_refs(discovery)
    before, _ = _project_owned_cells(
        baseline, graph, discovery, graph.tenant_id, failed_state="candidate"
    )
    start = monotonic()
    with patch.object(fxe.PageOCRStore, "from_env", return_value=Offline()):
        reader = fxe.for_run(baseline["run_id"])
        # The public API authenticates the saved baseline by exact recomputation.
        receipt = reader.attest_claim_spans(
            graph,
            source,
            refs,
            tenant_id=graph.tenant_id,
            previous_receipt=baseline,
        )
        write("new-receipt.json", receipt)
        print("fresh receipt", Counter(r["status"] for r in receipt["records"]), flush=True)
        cold = fxe.for_run(baseline["run_id"]).recompute_claim_receipt(
            receipt,
            graph,
            source,
            refs,
            tenant_id=graph.tenant_id,
        )
        assert cold == receipt
        after, _ = _project_owned_cells(
            cold, graph, discovery, graph.tenant_id, failed_state="candidate"
        )
    before_ids = {c.claim_id for c in before.claims if c.source_quality == "verified"}
    after_ids = {c.claim_id for c in after.claims if c.source_quality == "verified"}
    gained = after_ids - before_ids
    assert before_ids <= after_ids
    assert gained
    assert hashes == {
        f.name: sha256(f.read_bytes()).hexdigest() for f in args.input.iterdir() if f.is_file()
    }
    summary = dict(
        platform=platform.platform(),
        source_sha256=sha256(source).hexdigest(),
        claims=len(discovery.claims),
        before_verified=len(before_ids),
        after_verified=len(after_ids),
        gained_claims=[asdict(c) for c in after.claims if c.claim_id in gained],
        baseline_reasons=dict(Counter(r.get("reason") or r["status"] for r in baseline["records"])),
        after_reasons=dict(Counter(r.get("reason") or r["status"] for r in receipt["records"])),
        exact_historical_receipt_recomputed=True,
        new_cold_replay_equal=True,
        input_hashes=hashes,
        inputs_unchanged=True,
        paid_calls=0,
        network="denied",
        seconds=monotonic() - start,
    )
    write("summary.json", summary)
    print(
        {k: v for k, v in summary.items() if k not in {"gained_claims", "input_hashes"}}, flush=True
    )


if __name__ == "__main__":
    main()
