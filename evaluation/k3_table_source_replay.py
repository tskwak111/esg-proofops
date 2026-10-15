"""K3 source/routing evaluation over immutable I1 responses; no model dispatch."""

import argparse
import json
import socket
from hashlib import sha256
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

from proofops.adapters.local import upstage_ocr_profile_v11 as native
from proofops.adapters.parsing.parser_artifacts import iter_parser_artifacts, read_parser_json
from proofops.application.analysis_profile import K3_POLICY
from proofops.application.ingest.graph_fusion import candidates_from_snapshot, fuse_candidates
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef
from proofops_agent.upstage_extraction import UpstageClaimExtractor
from proofops_worker.extract_runner import _ContinuingExtractor, select_stable_paragraph_sources

from evaluation.w9_table_replay import OfflineProbe, packet


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--lab", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    start = monotonic()
    args.output.mkdir(parents=True, exist_ok=False)

    def deny(*args, **kwargs):
        raise AssertionError("K3_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    inputs = {}

    def read(path):
        raw = path.read_bytes()
        inputs[str(path)] = sha256(raw).hexdigest()
        return raw

    review = json.loads(read(args.lab / "review/R1/cases.json"))
    targets = [c for c in review["cases"] if c["hold_primary_cause"].startswith("source/cell")]
    assert len(targets) == 17
    results, losses, vehicles, normal = [], [], [], []
    for company in ("naver", "kia"):
        root = args.lab / "perf/I1/stage-B-compact" / company
        cp = json.loads(read(root / "extract-checkpoint.json"))
        candidate_path = next(iter_parser_artifacts(root / "parser-prepared", "candidates.json"))
        read(candidate_path)  # Retain the exact physical-file audit hash.
        raw = read_parser_json(candidate_path)
        graph = fuse_candidates(
            candidates_from_snapshot(raw),
            tenant_id=raw[0]["tenant_id"],
            fusion_version=5,
            mixed_parser=True,
        )
        pdf = next(
            p
            for p in (root / "objects/original").rglob("*.pdf")
            if sha256(p.read_bytes()).hexdigest() == graph.source_sha256
        )
        original = read(pdf)
        blocks = {b.source_id: b for b in graph.blocks}
        table_cases = [
            c
            for c in review["cases"]
            if c["case_id"].startswith(company.upper())
            and blocks[c["source_refs"][0]["source_id"]].kind == "table"
        ]
        refs = [SourceRef(**c["source_refs"][0]) for c in table_cases]
        proofs = native.cell_proof(graph, original, refs, tenant_id=graph.tenant_id)
        for case, proof in zip(table_cases, proofs, strict=True):
            if case["source_status"]["status"] == "verified":
                normal.append(case["case_id"])
                if proof["status"] != "verified":
                    losses.append(case["case_id"])
            if case not in targets:
                continue
            cause = (
                "missing-cell-coordinate-or-wrapped-label"
                if company == "kia"
                else "native-column-ownership"
                if case["physical_page"] == 88
                else "v9-reader-pinned-instead-of-v10"
            )
            if case["case_id"] == "NAVER-02":
                cause = "reordered-status-from-another-native-line"
            if case["case_id"] == "NAVER-21":
                cause = "next-facility-heading-attached-to-value"
            results.append(
                dict(
                    case_id=case["case_id"],
                    physical_page=case["physical_page"],
                    cause=cause,
                    before=case["source_attestation_records"],
                    after=proof,
                    original_quote_unchanged=True,
                )
            )
        for case in targets:
            if not case["case_id"].startswith(company.upper()):
                continue
            block = blocks[case["source_refs"][0]["source_id"]]
            if block.kind == "paragraph":
                results.append(
                    dict(
                        case_id=case["case_id"],
                        physical_page=case["physical_page"],
                        cause="clipped-prose-box-and-sensitive-spacing",
                        before=case["source_attestation_records"],
                        after=dict(
                            status="unresolved", reason="native_quote_or_sensitive_spacing_mismatch"
                        ),
                        original_quote_unchanged=True,
                    )
                )
        # Verify that the real worker admission and continuation wrapper both
        # reach deterministic W9 extraction, which must make no provider calls.
        extractor = UpstageClaimExtractor(
            OfflineProbe(),
            args.output / "receipts",
            extraction_context=True,
            extraction_source_ids=True,
            extraction_table_rows=True,
            extraction_pb1=True,
            extraction_w9=True,
            extraction_k3=True,
        )
        table = next(
            (b for b in graph.blocks if b.kind == "table" and "644,685" in b.raw_text), None
        )
        if table is not None:
            scope = SimpleNamespace(mode="declared_subset", selected_pages=(table.page_num,))
            legacy = select_stable_paragraph_sources(graph, scope, 256, extraction_table_rows=True)
            window = select_stable_paragraph_sources(
                graph, scope, 256, extraction_table_rows=True, extraction_k3=True
            )
            assert table.source_id not in legacy and table.source_id in window

            class Bound:
                def extract(self, data):
                    return extractor.extract(data, context_graph=graph)

            worker = _ContinuingExtractor(
                Bound(),
                extractor.profile,
                {},
                window,
                256,
                extraction_table_rows=True,
                extraction_k3=True,
                graph=graph,
            )
            data = packet(graph, table)
            output = worker.extract(data)
            assert worker.processed == {table.source_id}
            assert not worker.deferred
            vehicle_refs = [
                table.source_ref(
                    normalized_char_start=s["char_start"], normalized_char_end=s["char_end"]
                )
                for s in output["spans"]
            ]
            proofs = native.cell_proof(graph, original, vehicle_refs, tenant_id=graph.tenant_id)
            for span, proof in zip(output["spans"], proofs, strict=True):
                vehicles.append(dict(quote=span["quote"], proof=proof))
            assert len(vehicles) == 4
            assert all(v["proof"]["status"] == "verified" for v in vehicles)
        # Stored prose records are passed through byte-for-byte, not promoted.
        baseline = cp["claim_source_attestation"]["baseline_receipt"]
        for record in baseline["records"]:
            block = blocks[record["ref"]["source_id"]]
            if block.kind == "paragraph" and record["status"] == "verified":
                normal.append(f"{company}:prose:{block.source_id}")
    results.sort(key=lambda r: r["case_id"])
    assert len(results) == 17
    unsafe = {"NAVER-02", "NAVER-05", "NAVER-21"}
    false_verified = [
        r["case_id"]
        for r in results
        if r["case_id"] in unsafe and r["after"]["status"] == "verified"
    ]
    summary = dict(
        targets=17,
        source_verified_before=0,
        source_verified_after=sum(r["after"]["status"] == "verified" for r in results),
        preserved_holds=[r["case_id"] for r in results if r["after"]["status"] != "verified"],
        normal_cases=len(normal),
        lost_normal_cases=losses,
        false_verified=len(false_verified),
        vehicle_rows_before=0,
        vehicle_rows_after=len(vehicles),
        paid_calls=0,
        cost_usd="0",
        network="denied",
        seconds=monotonic() - start,
        new_tags_and_grades="not_run",
        fresh_model_run="not_run",
        acceptance="partial: 3 unsafe original spans still require new extraction",
    )
    assert not losses and not false_verified
    for path, digest in inputs.items():
        assert sha256(Path(path).read_bytes()).hexdigest() == digest, "K3_INPUT_MUTATED"
    artifact = dict(
        schema="k3-immutable-source-replay-v1",
        cases=results,
        vehicles=vehicles,
        normal_cases=normal,
        summary=summary,
        input_hashes=inputs,
        analysis_policy_sha256=canonical_hash(K3_POLICY),
        source_policy=native.claim_source_policy(),
    )
    (args.output / "replay.json").write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
