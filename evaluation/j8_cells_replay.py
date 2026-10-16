"""Re-evaluate stored selections with J8 candidates; never impersonate new model calls."""

import argparse
import json
import socket
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from time import monotonic

from proofops.adapters.local import upstage_ocr_profile_v10 as native
from proofops.adapters.parsing.parser_artifacts import iter_parser_artifacts, read_parser_json
from proofops.application.analysis_profile import J8_POLICY
from proofops.application.ingest.graph_fusion import candidates_from_snapshot, fuse_candidates
from proofops.application.ingest.j8_cells import POLICY, cell_entries, graph_cells
from proofops.application.ingest.w9_tables import PROFILE as W9_PROFILE
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import UpstageClaimExtractor

from evaluation.j3_recall_replay import scorer


class OfflineProbe:
    model = "gpt-6-luna"

    def complete(self, *args, **kwargs):
        raise AssertionError("J8_REPLAY_PROVIDER_FORBIDDEN")


def extractor(probe, receipts):
    return UpstageClaimExtractor(
        probe,
        receipts,
        max_tokens=2048,
        extraction_source_ids=True,
        extraction_context=True,
        extraction_table_context=True,
        extraction_assertion_prompt=True,
        extraction_linewrap_join=True,
        extraction_fragment_guard=True,
        extraction_year_notation=True,
        extraction_table_rows=True,
        extraction_pb1=True,
        extraction_pb1_context_guard=True,
        extraction_w9=True,
        extraction_j3=True,
        extraction_j8=True,
    )


def load_case(root, case):
    company = case["company"]
    attempt = {"naver": "attempt9", "kia": "attempt8"}[company]
    state = root / ".local/perf-b/outputs/pb1/live" / company / attempt / "workspace/state"
    path = next(iter_parser_artifacts(state, "candidates.json"))
    batches = candidates_from_snapshot(read_parser_json(path))
    manifest = case["packet"]["parse_manifest_id"]
    batches = tuple(
        replace(
            b,
            parse_manifest_id=manifest,
            blocks=tuple(
                replace(
                    c,
                    source=replace(c.source, parse_manifest_id=manifest),
                    context=(*c.context, W9_PROFILE),
                )
                for c in b.blocks
            ),
        )
        for b in batches
    )
    graph = fuse_candidates(
        batches, tenant_id=batches[0].tenant_id, fusion_version=5, mixed_parser=True
    )
    table = next(b for b in graph.blocks if b.source_id == case["source_id"])
    assert table.normalized_text == case["table_text"]
    sources = [
        p
        for p in (state / "objects/original").rglob("*.pdf")
        if sha256(p.read_bytes()).hexdigest() == graph.source_sha256
    ]
    assert len(sources) == 1, "J8_ORIGINAL_HASH_REQUIRED"
    return graph, table, sources[0], path


def selection_receipt(directory, case, profile, inputs):
    """Bind evaluation votes to the original request, raw content and profile."""
    matches = []
    for path in directory.glob("*/result.json"):
        result = json.loads(path.read_text())
        if result.get("profile") == profile and result.get("spans") == case["spans"]:
            packet_path = path.parent / "packet.json"
            if json.loads(packet_path.read_text()) == case["packet"]:
                matches.append(path)
    assert len(matches) == 1, "J8_SELECTION_RECEIPT_REQUIRED"
    path = matches[0]
    result = json.loads(path.read_text())
    request = json.loads((path.parent / "request.json").read_text())
    raw = json.loads((path.parent / "raw_response.json").read_text())
    assert canonical_hash(raw["content"]) == result["content_sha256"]
    assert raw["response_sha256"] == result["response_sha256"]
    wire = json.loads(request["user_json"])
    candidates = {s["sentence_id"]: s for s in wire["untrusted_document_data"]["source_sentences"]}
    ids = json.loads(raw["content"])["sentence_ids"]
    selected = {(candidates[s]["char_start"], candidates[s]["char_end"]) for s in ids}
    assert selected == {(s["char_start"], s["char_end"]) for s in case["spans"]}
    for name in (
        "identity.json",
        "packet.json",
        "request.json",
        "raw_response.json",
        "result.json",
    ):
        p = path.parent / name
        inputs[str(p)] = sha256(p.read_bytes()).hexdigest()
    return dict(
        path=str(path.parent),
        profile=profile,
        request_id=result["request_id"],
        content_sha256=result["content_sha256"],
    )


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--lab", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--fresh", type=Path)
    args = cli.parse_args()
    root = args.lab.resolve().parents[3]
    args.output.mkdir(parents=True, exist_ok=False)
    start = monotonic()

    def deny(*args, **kwargs):
        raise AssertionError("J8_REPLAY_NETWORK_FORBIDDEN")

    for owner, name in (
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
        (socket, "create_connection"),
    ):
        setattr(owner, name, deny)
    evaluate, inputs = scorer(root)
    baseline_path = args.lab / "fix/J3/accepted-replay/scores.json"
    live_path = args.lab / "fix/J3/live-cells.json"
    w9_path = args.lab / "perf/W9/pb1-scores.json"
    baseline = json.loads(baseline_path.read_text())
    historical = json.loads(live_path.read_text())
    gold_path = Path(json.loads(w9_path.read_text())["gold_path"])
    gold = json.loads(gold_path.read_text())["sheets"]["1_전수목록"]
    for p in (baseline_path, live_path, w9_path, gold_path):
        inputs[str(p)] = sha256(p.read_bytes()).hexdigest()
    manifest_path = args.lab / "fix/J3/artifact-sha256.json"
    manifest = json.loads(manifest_path.read_text())
    inputs[str(manifest_path)] = sha256(manifest_path.read_bytes()).hexdigest()
    for p in (baseline_path, live_path):
        assert inputs[str(p)] == manifest[str(p.relative_to(manifest_path.parent))]
    cases = [
        ("J3-stored-selection", c, historical["extraction_profile"], live_path.parent)
        for c in historical["cases"]
    ]
    fresh_budget = dict(calls=0, committed_usd="0")
    if args.fresh:
        fresh = json.loads(args.fresh.read_text())
        cases += [
            ("J8-fresh-selection", c, fresh["profile"], args.fresh.parent) for c in fresh["cases"]
        ]
        fresh_budget = fresh["budget"]
        inputs[str(args.fresh)] = sha256(args.fresh.read_bytes()).hexdigest()
    predictions = baseline["predictions"]
    additions, excluded, candidate_sets = [], [], []
    e = extractor(OfflineProbe(), args.output / "unused-receipts")
    for origin, case, profile, original in cases:
        receipt = selection_receipt(original / "live-receipts", case, profile, inputs)
        graph, table, source, snapshot = load_case(root, case)
        for p in (source, snapshot):
            inputs[str(p)] = sha256(p.read_bytes()).hexdigest()
        entries = cell_entries(
            table.normalized_text, graph_cells(table, graph), source_id=table.source_id
        )
        by_offset = {(s["char_start"], s["char_end"]): s for s in entries}
        ids = []
        for s in case["spans"]:
            candidate = by_offset.get((s["char_start"], s["char_end"]))
            if candidate is None:
                excluded.append(
                    dict(
                        company=case["company"],
                        page=case["physical_page"],
                        origin=origin,
                        quote=s["quote"],
                    )
                )
            else:
                assert candidate["text"] == s["quote"]
                ids.append(candidate["sentence_id"])
        # Projection of stored votes for evaluation only. This deliberately does
        # not create J8 provider receipts or claim that J3 saw the new wire.
        spans, diagnostics = e._resolve_payload(
            {"sentence_ids": ids},
            table.normalized_text,
            table.source_id,
            packet=case["packet"],
            context_graph=graph,
        )
        refs = [
            table.source_ref(normalized_char_start=s.char_start, normalized_char_end=s.char_end)
            for s in spans
        ]
        proofs = native.cell_proof(graph, source.read_bytes(), refs, tenant_id=graph.tenant_id)
        candidate_sets.append(
            dict(
                origin=origin,
                company=case["company"],
                page=case["physical_page"],
                candidates=entries,
                diagnostics=diagnostics,
                selection_receipt=receipt,
                projection_profile=asdict(e.profile),
            )
        )
        for s, ref, proof in zip(spans, refs, proofs, strict=True):
            records = predictions[case["company"]]
            if any(p["page"] == case["physical_page"] and p["quote"] == s.quote for p in records):
                continue
            item = dict(
                id=f"J8-{origin}-{table.source_id}-{s.char_start}-{s.char_end}",
                page=case["physical_page"],
                quote=s.quote,
                source_ref=asdict(ref),
                source_verified=proof["status"] == "verified",
                native_proof=proof,
                vote_origin=origin,
                binding_status="undetermined",
                tags_and_grades="not_run",
            )
            records.append(item)
            additions.append(item)
    scores = {
        c: evaluate([g for g in gold if g["기업"] == c and g["비주장 여부"] == "주장"], p)
        for c, p in predictions.items()
    }
    before_misses = {g for s in baseline["companies"].values() for g in s["missed_gold"]}
    after_misses = {g for s in scores.values() for g in s["missed_gold"]}
    after = dict(
        matches=sum(s["one_to_one_matches"] for s in scores.values()),
        predictions=sum(s["predictions"] for s in scores.values()),
        gold_denominator=156,
    )
    after.update(recall=after["matches"] / 156, precision=after["matches"] / after["predictions"])
    for p, digest in inputs.items():
        assert sha256(Path(p).read_bytes()).hexdigest() == digest, "J8_INPUT_MUTATED"
    result = dict(
        schema="j8-stored-vote-projection-v1",
        baseline=baseline["after"],
        after=after,
        companies=scores,
        predictions=predictions,
        additions=additions,
        excluded=excluded,
        candidate_sets=candidate_sets,
        policy=POLICY,
        policy_sha256=canonical_hash(POLICY),
        analysis_policy=J8_POLICY,
        analysis_policy_sha256=canonical_hash(J8_POLICY),
        input_hashes=inputs,
        recovered_gold=sorted(before_misses - after_misses),
        lost_gold=sorted(after_misses - before_misses),
        network="denied",
        fresh_budget=fresh_budget,
        seconds=monotonic() - start,
        new_native_verified=sum(p["source_verified"] for p in additions),
        new_native_unresolved=sum(not p["source_verified"] for p in additions),
        criterion="unchanged strict DL3 one-to-one AI draft proxy; additive stored votes, "
        "not fresh full pipeline or semantic/tag/grade accuracy",
        accepted=after["precision"] >= 0.95 and not (after_misses - before_misses),
    )
    (args.output / "scores.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "after",
                    "recovered_gold",
                    "lost_gold",
                    "accepted",
                    "new_native_verified",
                    "new_native_unresolved",
                    "seconds",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
