"""J7 free literal-clause replay with unchanged DL3 scoring and native source checks.

This replaces only retained J3 selections, never invents model votes or grades.
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
from proofops.application.analysis_profile import J7_POLICY
from proofops.application.claims import validate_extraction_response
from proofops.application.ingest.graph_fusion import candidates_from_snapshot, fuse_candidates
from proofops.application.ingest.j7_split import POLICY, refine_selected
from proofops.application.ingest.w9_tables import graph_cells, observations_for
from proofops.domain.provenance import canonical_hash
from pypdf import PdfReader


def native_text_key(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", value))


def scorer(root):
    namespace = dict(re=re, unicodedata=unicodedata)
    inputs = {}
    for filename, names in [
        ("dl1_score.py", {"norm"}),
        ("dl2_score.py", {"clean", "literal_edge", "bipartite", "evaluate"}),
    ]:
        path = root / ".local/docling-lab/scripts" / filename
        nodes: list[ast.stmt] = [
            n
            for n in ast.parse(path.read_text()).body
            if isinstance(n, ast.FunctionDef) and n.name in names
        ]
        assert {n.name for n in nodes if isinstance(n, ast.FunctionDef)} == names
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
    baseline_path = args.lab / "fix/J3/scores.json"
    baseline = json.loads(baseline_path.read_text())
    w9_path = args.lab / "perf/W9/pb1-scores.json"
    inputs[str(w9_path)] = sha256(w9_path.read_bytes()).hexdigest()
    gold_path = Path(json.loads(w9_path.read_text())["gold_path"])
    gold = json.loads(gold_path.read_text())["sheets"]["1_전수목록"]
    inputs[str(baseline_path)] = sha256(baseline_path.read_bytes()).hexdigest()
    inputs[str(gold_path)] = sha256(gold_path.read_bytes()).hexdigest()

    def deny(*args, **kwargs):
        raise AssertionError("J7_REPLAY_NETWORK_FORBIDDEN")

    for name in ("connect", "connect_ex"):
        setattr(socket.socket, name, deny)
    socket.create_connection = deny
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
        assert len(sources) == 1, "J7_ORIGINAL_HASH_REQUIRED"
        source = sources[0].read_bytes()
        native_pages = PdfReader(sources[0]).pages
        inputs[str(sources[0])] = graph.source_sha256
        inputs[str(path)] = sha256(path.read_bytes()).hexdigest()
        inputs[str(page_map_path)] = sha256(page_map_path.read_bytes()).hexdigest()
        records, changed_predictions = [], []
        refs_by_kind: dict[str, list] = {"paragraph": [], "table": []}
        for prediction in baseline["companies"][company]["records"]:
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
                    id=f"J7-{prediction['prediction_id']}-{index}",
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
            # Independent text-presence audit, supplementary to the unchanged
            # glyph + rendered-source admission gate; never grants verification.
            prediction["independent_native_presence"] = native_text_key(
                ref["quote"]
            ) in native_text_key(native_pages[ref["page_num"] - 1].extract_text())
        predictions[company] = records
    scores = {
        company: evaluate(
            [g for g in gold if g["기업"] == company and g["비주장 여부"] == "주장"], records
        )
        for company, records in predictions.items()
    }
    before_misses = {g for s in baseline["companies"].values() for g in s["missed_gold"]}
    after_misses = {g for s in scores.values() for g in s["missed_gold"]}
    after = dict(
        matches=sum(s["one_to_one_matches"] for s in scores.values()),
        predictions=sum(s["predictions"] for s in scores.values()),
        gold_denominator=156,
    )
    after.update(recall=after["matches"] / 156, precision=after["matches"] / after["predictions"])
    for path, digest in inputs.items():
        assert sha256(Path(path).read_bytes()).hexdigest() == digest, "J7_INPUT_MUTATED"
    changed = [p for ps in predictions.values() for p in ps if "native_proof" in p]
    false_verified = sum(
        p["source_verified"]
        and (
            p["native_proof"]["status"] != "verified"
            or p["native_proof"]["ref"] != p["source_ref"]
            or not p["independent_native_presence"]
        )
        for p in changed
    )
    result = dict(
        schema="j7-retained-clause-replay-v1",
        policy=POLICY,
        policy_sha256=canonical_hash(POLICY),
        analysis_policy=J7_POLICY,
        analysis_policy_sha256=canonical_hash(J7_POLICY),
        baseline=baseline["after"],
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
        false_verified=false_verified,
        accepted=(
            after["precision"] >= 0.95
            and after["matches"] > baseline["after"]["matches"]
            and not (after_misses - before_misses)
            and false_verified == 0
        ),
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
