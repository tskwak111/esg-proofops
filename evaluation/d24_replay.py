"""Offline DEC-24 replay of frozen PB6/PB5/RS receipts and unchanged DL3 scorer.

No model/source transport or production revision writer is available here.
Prompt guidance cannot create new semantic votes from old stored responses.
"""

import argparse
import ast
import copy
import importlib.util
import json
import re
import unicodedata
from collections import Counter
from hashlib import sha256
from pathlib import Path

from proofops.application.analysis_profile import V2_POLICY, V2_PRE_D24_POLICY
from proofops.application.tagging.dec24 import adjacent_table, table_footnote
from proofops.application.tagging.quality import hold_projection
from proofops.domain.provenance import canonical_hash


def read(path):
    return json.loads(path.read_text())


def load_scorer(scripts):
    """Execute the exact unchanged pure functions; skip external CLI imports."""
    scope = dict(re=re, unicodedata=unicodedata)
    hashes = {}
    for name, selected in (
        ("dl1_score.py", {"norm"}),
        ("dl2_score.py", {"clean", "literal_edge", "bipartite", "evaluate"}),
    ):
        source = scripts / name
        hashes[name] = sha256(source.read_bytes()).hexdigest()
        nodes = [
            n
            for n in ast.parse(source.read_text()).body
            if isinstance(n, ast.FunctionDef) and n.name in selected
        ]
        assert {n.name for n in nodes} == selected
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), scope)
    return scope["evaluate"], hashes


def distribution(records):
    return dict(
        Counter(
            "hold" if r.get("display_type") == "hold" else r.get("evidence_grade") or "range"
            for r in records
        )
    )


def replay(evidence, scorer_scripts, output):
    perf = evidence / "lab/perf"
    pb6 = perf / "PB6"
    spec = importlib.util.spec_from_file_location("d24_pb6_replay", pb6 / "pb6_replay.py")
    assert spec and spec.loader
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    score, scorer_hashes = load_scorer(scorer_scripts)
    gold_path = next((evidence / "lab/gold-return/20261010/raw").rglob("20261007*.json"))
    gold = read(gold_path)
    summary, all_records, excluded_notes, scores, inputs = {}, {}, [], {}, {}
    for label in ("rs3", "rs4", "naver", "kia"):
        folder = pb6 if label.startswith("rs") else perf / "PB5"
        context_file = pb6 / (label + "-context.json")
        claims_file = folder / (label + "-claim_snapshot_sha256.json")
        tags_file = folder / (label + "-tag_snapshot_sha256.json")
        context, claims, tags = read(context_file), read(claims_file), read(tags_file)
        graph, fusion_version = harness.graph_for(label, context, claims)
        # PB6 already replayed the unchanged production guard with precise value
        # quotes. Its before/after records are the baseline of deployed a16e118.
        baseline_file = pb6 / (label + "-replay.json")
        baseline = {r["claim_id"]: r["after"] for r in read(baseline_file)}
        anchors = {c["claim_id"]: c for c in claims["discovery"]["claims"]}
        blocks = {b.source_id: b for b in graph.blocks}
        before, after, records, predictions, retained = [], [], [], [], []
        for item in tags["claims"]:
            claim = anchors[item["claim_id"]]
            ref = claim["source_refs"][0]
            block = blocks[ref["source_id"]]
            packet = dict(untrusted_document_data=dict(source_id=block.source_id, kind=block.kind))
            note = table_footnote(
                claim["quote"], kind=block.kind, table_context=adjacent_table(packet, graph)
            )
            old = baseline[item["claim_id"]]
            updated = copy.deepcopy(item)
            updated["provisional_grade"] = old
            candidate = hold_projection(updated, profile="dec24-v1")
            for field in (
                "evidence_grade",
                "label",
                "gap_ids",
                "semantic_hash",
                "rule_pack_sha256",
                "elements",
                "grade_range",
            ):
                assert candidate.get(field) == old.get(field), (label, item["claim_id"], field)
            # DEC-24 never turns a saved unknown/conflict into a semantic present.
            before.append(old)
            if not note:
                after.append(candidate)
            records.append(
                dict(
                    claim_id=item["claim_id"],
                    quote=claim["quote"],
                    before=old,
                    after=None if note else candidate,
                    excluded_table_context=note,
                )
            )
            if note:
                excluded_notes.append(
                    dict(
                        case=label,
                        claim_id=item["claim_id"],
                        quote=claim["quote"],
                        source_ref=ref,
                        source_preserved_in_graph=True,
                        receipt_sha256=canonical_hash(claim["receipt"]),
                    )
                )
            if label in ("naver", "kia"):
                raw = read(perf / "PB5" / (label + "-result.json"))
                result = next(c for c in raw["claims"] if c["claim_id"] == item["claim_id"])
                prediction = dict(
                    id=item["claim_id"], quote=claim["quote"], page=result["original_page_num"]
                )
                predictions.append(prediction)
                if not note:
                    retained.append(prediction)
        all_records[label] = records
        summary[label] = dict(
            before=distribution(before),
            after=distribution(after),
            excluded_table_notes=sum(r["excluded_table_context"] for r in records),
            new_present=0,
            wrong_new_connections_observed=0,
            fusion_version=fusion_version,
            estimate_hold_displays=sum(
                "추정치 · 산정 근거 확인 필요" in (r["after"] or {}).get("hold_reasons", [])
                for r in records
            ),
        )
        if predictions:
            gg = [
                g
                for g in gold["sheets"]["1_전수목록"]
                if g["기업"] == label and g["비주장 여부"] == "주장"
            ]
            scores[label] = dict(before=score(gg, predictions), after=score(gg, retained))
        for path in (
            context_file,
            claims_file,
            tags_file,
            baseline_file,
            pb6 / (label + "-candidates.json"),
        ):
            inputs[str(path)] = sha256(path.read_bytes()).hexdigest()
    combined = {}
    for phase in ("before", "after"):
        count = sum(v[phase]["predictions"] for v in scores.values())
        matched = sum(v[phase]["one_to_one_matches"] for v in scores.values())
        combined[phase] = dict(predictions=count, matches=matched, precision=matched / count)
    assert combined["after"]["precision"] >= 0.95
    output.mkdir(parents=True, exist_ok=True)
    result = dict(
        schema="dec24-offline-replay-v1",
        policy_before=canonical_hash(V2_PRE_D24_POLICY),
        policy_after=canonical_hash(V2_POLICY),
        summary=summary,
        scores=scores,
        combined_score=combined,
        input_sha256=inputs,
        harness_sha256=sha256((pb6 / "pb6_replay.py").read_bytes()).hexdigest(),
        scorer_sha256=scorer_hashes,
        gold_sha256=sha256(gold_path.read_bytes()).hexdigest(),
        new_present=[],
        excluded_notes=excluded_notes,
        paid_usd=0,
        model_calls=0,
        production_revisions_written=0,
        limitations=[
            "Stored responses cannot measure new prompt semantics; fresh retagging not_run.",
            "Draft DL3 gold with unchanged 1:1 literal scorer; not human R2 or semantic precision.",
            "Conservative atomic-source binding; no PC1 opt-in or paragraph widening.",
        ],
    )
    (output / "replay.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    (output / "replay-records.json").write_text(
        json.dumps(all_records, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(dict(summary=summary, combined_score=combined), ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--scorer-scripts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    replay(args.evidence, args.scorer_scripts, args.output)
