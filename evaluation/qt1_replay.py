"""Network-denied QT1 delta replay against frozen R17/E14, DL4 and holdout artifacts.

Usage: uv run python -m evaluation.qt1_replay --root /path/to/ESG_ProofOps
This reuses saved extraction selections; it does not run a new model/tagging vote.
"""

import argparse
import importlib.util
import json
import socket
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from proofops.adapters.parsing.parser_artifacts import iter_parser_artifacts, read_parser_json
from proofops.application.analysis_profile import QT1_POLICY, V2_POLICY
from proofops.application.ingest.graph_fusion import candidates_from_snapshot, fuse_candidates
from proofops.application.ingest.qt1_tables import candidates_for, reconcile
from proofops.domain.provenance import canonical_hash

from evaluation.d24_replay import load_scorer
from evaluation.pa9_source_gate import fixture


def load(path):
    return read_parser_json(path)


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def table_delta(graph, pages, previous, refs_fn, page_fn):
    added, tables = [], []
    for block in graph.blocks:
        if block.kind != "table" or block.page_num not in pages:
            continue
        refs = [r for p in previous for r in refs_fn(p) if r["source_id"] == block.source_id]
        spans = [
            dict(
                char_start=r["char_start"],
                char_end=r["char_end"],
                quote=r["quote"],
                kind="claim",
                reason=None,
                topic_ids=["environment"],
            )
            for r in refs
        ]
        candidates = candidates_for(block, graph)
        after, coverage = reconcile(block.normalized_text, candidates, spans)
        new = [s for s in after if s not in spans]
        tables.append(
            dict(
                source_id=block.source_id,
                page=page_fn(block.page_num),
                inventory=candidates,
                coverage=coverage,
                before=spans,
                after=after,
                added=new,
            )
        )
        for span in new:
            ref = asdict(
                block.source_ref(
                    normalized_char_start=span["char_start"],
                    normalized_char_end=span["char_end"],
                )
            )
            assert ref["quote"] == span["quote"]
            added.append(
                dict(
                    id="qt1-" + canonical_hash(ref),
                    quote=span["quote"],
                    page=page_fn(block.page_num),
                    source_ref=ref,
                    source_verified=False,
                    raw=dict(source_refs=[ref]),
                )
            )
    return added, tables


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    lab = args.root / "outputs/agent-results/R108-redesign/lab"
    inputs = lab / "quality/QT1"
    out = args.output or inputs
    out.mkdir(parents=True, exist_ok=True)

    def deny(*args, **kwargs):
        raise AssertionError("QT1_REPLAY_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    audit_path = lab / "review/R17/audit.json"
    audit = load(audit_path)
    manifests = {str(audit_path): sha256(audit_path.read_bytes()).hexdigest()}
    inventory, r17_predictions = {}, {}
    for report in audit["reports"]:
        name = report["case"]
        prep = next(iter_parser_artifacts(inputs / "inputs" / name, "candidates.json"))
        snapshot, manifest = load(prep), load(prep.parent / "manifest.json")
        graph = fuse_candidates(
            candidates_from_snapshot(snapshot),
            tenant_id=snapshot[0]["tenant_id"],
            fusion_version=manifest["fusion_version"],
            mixed_parser=True,
        )
        assert graph.to_dict() == load(prep.parent / "graph.json")
        old_path = lab / "perf/E14" / f"{name}.result.json"
        old = load(old_path)
        for path in (prep, old_path, Path(report["source_pdf"])):
            manifests[str(path)] = sha256(path.read_bytes()).hexdigest()
        assert manifests[str(Path(report["source_pdf"]))] == report["source_sha256"]
        pages = old["pipeline"]["extraction_outcome"]["selected_claim_pages"]
        r17_predictions[name], inventory[name] = table_delta(
            graph,
            pages,
            old["claims"],
            lambda p: p["source_refs"],
            lambda p: report["page_map"][p - 1],
        )
    write(out / "inventory.json", inventory)
    write(out / "r17-added.json", r17_predictions)

    score, _ = load_scorer(args.root / ".local/docling-lab/scripts")
    gold = load(next((lab / "gold-return/20261010/raw").rglob("20261007*.json")))
    dl4 = {}
    for name, state in {
        "lgchem": args.root / ".local/w7-inputs/lgchem-server",
        "naver": lab / "perf/PA9/naver-server",
        "kia": lab / "perf/PA9/kia-server",
    }.items():
        graph, _, discovery, _, _ = fixture(state)
        before = load(lab / "perf/I23/dl4" / f"{name}-after.json")
        page_map = load(state / "result-1.json")["page_map"]
        added, _ = table_delta(
            graph,
            discovery.scope.selected_pages,
            before,
            lambda p: [p["source_ref"]],
            lambda p: page_map[p - 1],
        )
        expected = [
            g
            for g in gold["sheets"]["1_전수목록"]
            if g["기업"] == name and g["비주장 여부"] == "주장"
        ]
        dl4[name] = dict(
            before=score(expected, before) if expected else None,
            after=score(expected, before + added) if expected else None,
            added=added,
        )
        if expected:
            for metric in ("strict_text_recall", "strict_text_precision"):
                assert dl4[name]["after"][metric] >= dl4[name]["before"][metric]
    scorer = args.root / ".local/g1-gold/evaluation/dl4_gold.py"
    spec = importlib.util.spec_from_file_location("qt1_frozen_holdout", scorer)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    gold = load(lab / "fix/A/paid-dec26/v1-gold-atoms.json")
    all_before, all_after, companies = [], [], {}
    for company, states in {
        "SK하이닉스": ["SK하이닉스"],
        "현대자동차": ["현대자동차-p22", "현대자동차-p41"],
        "POSCO홀딩스": ["POSCO홀딩스"],
        "삼성전자": ["삼성전자"],
    }.items():
        before = load(lab / "perf/I23/holdout/holdout" / company / "predictions.json")
        added = []
        for state in states:
            graph, _, discovery, _, _ = fixture(lab / "fix/A/paid-dec26/states" / state)
            new, _ = table_delta(
                graph,
                discovery.scope.selected_pages,
                before,
                lambda p: p["raw"]["source_refs"],
                lambda p: p,
            )
            added.extend(new)
        for prediction in added:
            prediction["company"] = company
        all_before.extend(before)
        all_after.extend(before + added)
        companies[company] = dict(added=added)
    holdout = dict(
        before=module.evaluate(gold, all_before),
        after=module.evaluate(gold, all_after),
        companies=companies,
    )
    for metric in ("recall", "precision"):
        assert holdout["after"][metric] >= holdout["before"][metric]
    write(out / "cohort-results.json", dict(dl4=dl4, holdout=holdout))
    write(
        out / "replay-manifest.json",
        dict(
            inputs=manifests,
            default_policy=canonical_hash(V2_POLICY),
            qt1_policy=canonical_hash(QT1_POLICY),
            network="denied",
            model_calls=0,
            method="saved selections + production QT1 inventory/reconcile; no fresh tagging",
            additions={k: len(v) for k, v in r17_predictions.items()},
        ),
    )
    print(
        json.dumps(
            dict(
                r17_additions={k: len(v) for k, v in r17_predictions.items()},
                dl4_additions={k: len(v["added"]) for k, v in dl4.items()},
                holdout_before=holdout["before"]["precision"],
                holdout_after=holdout["after"]["precision"],
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
