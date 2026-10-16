"""J3 free literal-span replay with unchanged DL3 scoring and native source checks.

This replaces only retained W9 selections, never invents model votes or grades.
The AI draft includes source context; its score is a textual proxy, not accuracy.
"""

import argparse
import ast
import json
import re
import socket
import unicodedata
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from time import monotonic

from proofops.adapters.local import claim_source_verification as paragraphs
from proofops.adapters.local import upstage_ocr_profile_v10 as tables
from proofops.adapters.parsing.parser_artifacts import iter_parser_artifacts, read_parser_json
from proofops.application.analysis_profile import J3_POLICY
from proofops.application.claims import validate_extraction_response
from proofops.application.ingest.graph_fusion import candidates_from_snapshot, fuse_candidates
from proofops.application.ingest.j3_recall import POLICY, refine_selected
from proofops.application.ingest.w9_tables import graph_cells, observations_for
from proofops.domain.provenance import canonical_hash


def scorer(root):
    namespace = dict(re=re, unicodedata=unicodedata)
    inputs = {}
    for filename, names in [
        ("dl1_score.py", {"norm"}),
        ("dl2_score.py", {"clean", "literal_edge", "bipartite", "evaluate"}),
    ]:
        path = root / ".local/docling-lab/scripts" / filename
        nodes = [
            n
            for n in ast.parse(path.read_text()).body
            if isinstance(n, ast.FunctionDef) and n.name in names
        ]
        assert {n.name for n in nodes} == names
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
        inputs[str(path)] = sha256(path.read_bytes()).hexdigest()
    return namespace["evaluate"], inputs


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--lab", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    root = args.lab.resolve().parents[3]
    args.output.mkdir(parents=True, exist_ok=False)
    start = monotonic()
    evaluate, inputs = scorer(root)
    baseline_path = args.lab / "perf/W9/pb1-scores.json"
    baseline = json.loads(baseline_path.read_text())
    gold_path = Path(baseline["gold_path"])
    gold = json.loads(gold_path.read_text())["sheets"]["1_전수목록"]
    inputs[str(baseline_path)] = sha256(baseline_path.read_bytes()).hexdigest()
    inputs[str(gold_path)] = sha256(gold_path.read_bytes()).hexdigest()

    def deny(*args, **kwargs):
        raise AssertionError("J3_REPLAY_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    predictions, changes = {}, []
    for company, attempt in [("naver", "attempt9"), ("kia", "attempt8")]:
        state = root / ".local/perf-b/outputs/pb1/live" / company / attempt / "workspace/state"
        path = next(iter_parser_artifacts(state, "candidates.json"))
        batches = candidates_from_snapshot(read_parser_json(path))
        graph = fuse_candidates(
            batches, tenant_id=batches[0].tenant_id, fusion_version=5, mixed_parser=True
        )
        page_map_path = args.lab / "perf/PB1" / f"{company}-result.json"
        page_map = json.loads(page_map_path.read_text())["page_map"]
        sources = [
            p
            for p in (state / "objects/original").rglob("*.pdf")
            if sha256(p.read_bytes()).hexdigest() == graph.source_sha256
        ]
        assert len(sources) == 1, "J3_ORIGINAL_HASH_REQUIRED"
        source = sources[0].read_bytes()
        inputs[str(sources[0])] = graph.source_sha256
        inputs[str(path)] = sha256(path.read_bytes()).hexdigest()
        inputs[str(page_map_path)] = sha256(page_map_path.read_bytes()).hexdigest()
        records, refs_by_kind, changed_predictions = [], {"paragraph": [], "table": []}, []
        for prediction in baseline["companies"][company]["after_candidate_projection"]["records"]:
            quote = prediction["quote"]
            original = dict(
                id=prediction["prediction_id"],
                quote=quote,
                page=prediction["page"],
                source_verified=prediction["source_verified"],
            )
            blocks = [
                b
                for b in graph.blocks
                if b.kind in {"paragraph", "table"}
                and page_map[b.page_num - 1] == prediction["page"]
                and quote in b.normalized_text
            ]
            if not blocks:
                records.append(original)
                continue
            block = blocks[0]
            a = block.normalized_text.index(quote)
            selected = dict(
                char_start=a,
                char_end=a + len(quote),
                quote=quote,
                kind="claim",
                reason=None,
                topic_ids=["environment"],
            )
            numeric = block.kind == "table" and bool(observations_for(block, graph))
            new, refinements = refine_selected(
                [selected],
                block.normalized_text,
                kind=block.kind,
                cells=graph_cells(block, graph) if block.kind == "table" and not numeric else None,
            )
            try:
                validate_extraction_response(
                    {"spans": new}, block.normalized_text, reject_unclosed_quotations=True
                )
            except ValueError:
                refinements = []
            if not refinements:
                records.append(original)
                continue
            changes.append(
                dict(
                    company=company,
                    page=prediction["page"],
                    old_quote=quote,
                    new_quotes=[s["quote"] for s in new],
                    refinements=refinements,
                )
            )
            for index, span in enumerate(new):
                ref = block.source_ref(
                    normalized_char_start=span["char_start"], normalized_char_end=span["char_end"]
                )
                candidate = dict(
                    id=f"J3-{prediction['prediction_id']}-{index}",
                    quote=span["quote"],
                    page=prediction["page"],
                    source_ref=asdict(ref),
                    source_verified=False,
                    kind=block.kind,
                )
                records.append(candidate)
                changed_predictions.append(candidate)
                refs_by_kind[block.kind].append(ref)
        proofs = {}
        if refs_by_kind["paragraph"]:
            receipt = paragraphs.attest_claim_spans(
                graph, source, refs_by_kind["paragraph"], tenant_id=graph.tenant_id
            )
            for proof in receipt["records"]:
                ref = proof["ref"]
                proofs[(ref["source_id"], ref["char_start"], ref["char_end"])] = proof
        for proof in tables.cell_proof(
            graph, source, refs_by_kind["table"], tenant_id=graph.tenant_id
        ):
            ref = proof["ref"]
            proofs[(ref["source_id"], ref["char_start"], ref["char_end"])] = proof
        for prediction in changed_predictions:
            ref = prediction["source_ref"]
            proof = proofs[(ref["source_id"], ref["char_start"], ref["char_end"])]
            prediction["native_proof"] = proof
            prediction["source_verified"] = proof["status"] == "verified"
        predictions[company] = records
    scores = {
        company: evaluate(
            [g for g in gold if g["기업"] == company and g["비주장 여부"] == "주장"], records
        )
        for company, records in predictions.items()
    }
    before_misses = {
        g
        for s in baseline["companies"].values()
        for g in s["after_candidate_projection"]["missed_gold"]
    }
    after_misses = {g for s in scores.values() for g in s["missed_gold"]}
    after = dict(
        matches=sum(s["one_to_one_matches"] for s in scores.values()),
        predictions=sum(s["predictions"] for s in scores.values()),
        gold_denominator=156,
    )
    after.update(recall=after["matches"] / 156, precision=after["matches"] / after["predictions"])
    for path, digest in inputs.items():
        assert sha256(Path(path).read_bytes()).hexdigest() == digest, "J3_INPUT_MUTATED"
    changed = [p for ps in predictions.values() for p in ps if "native_proof" in p]
    result = dict(
        schema="j3-retained-span-replay-v1",
        policy=POLICY,
        policy_sha256=canonical_hash(POLICY),
        analysis_policy=J3_POLICY,
        analysis_policy_sha256=canonical_hash(J3_POLICY),
        baseline=baseline["summary"]["after_candidate_projection"],
        after=after,
        companies=scores,
        predictions=predictions,
        changes=changes,
        recovered_gold=sorted(before_misses - after_misses),
        lost_gold=sorted(after_misses - before_misses),
        changed_source_spans=len(changed),
        changed_native_verified=sum(p["source_verified"] for p in changed),
        changed_native_unresolved=sum(not p["source_verified"] for p in changed),
        input_hashes=inputs,
        seconds=monotonic() - start,
        network="denied",
        paid_usd="0",
        criterion=(
            "unchanged DL3 strict one-to-one AI draft proxy; " "retained selections, not fresh E2E"
        ),
        tags_and_grades="not_run",
        precision_floor=0.95,
        accepted=after["precision"] >= 0.95,
    )
    (args.output / "scores.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            dict(
                after=after,
                changed_spans=len(changed),
                native_verified=result["changed_native_verified"],
                seconds=result["seconds"],
                accepted=result["accepted"],
            )
        )
    )


if __name__ == "__main__":
    main()
