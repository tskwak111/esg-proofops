"""CR1 saved-response semantic replay; network denied, input artifacts read-only."""

import argparse
import ast
import json
import re
import socket
import unicodedata
from collections import Counter
from hashlib import sha256
from pathlib import Path
from time import monotonic

from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.tagging.quality import hold_projection
from proofops.application.tagging.semantic_admission import POLICY, POLICY_HASH
from proofops.application.tagging.unattended import provisional_result
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.rules.engine import RuleContext

from evaluation.pt1_replay import decode_runs


def deny(*args, **kwargs):
    raise RuntimeError("W8_OFFLINE_NETWORK_FORBIDDEN")


def replay(item, pack, *, policy=None):
    data = item["frozen_packet"]
    packet = freeze_packet({k: v for k, v in data.items() if k != "packet_sha256"})
    assert packet.packet_sha256 == data["packet_sha256"]
    runs = decode_runs(item["tag_runs"])
    context = RuleContext(
        pack.tenant_id, data["document_version_id"], data["claim_id"], packet.packet_sha256
    )
    result = provisional_result(
        runs,
        packet,
        pack,
        context,
        profile="hf1-v1",
        range_profile=True,
        semantic_policy=policy,
    )
    return hold_projection(item | dict(provisional_grade=result), profile="hf1-v1")


def projection(result):
    return {
        k: result.get(k)
        for k in (
            "evidence_grade",
            "display",
            "display_type",
            "reason",
            "grade_range",
            "semantic_hash",
        )
    } | dict(states={e["element_id"]: e["state"] for e in result.get("elements", [])})


def gold_check(root, results):
    """Re-run the existing frozen draft claim matcher; no semantic accuracy claim."""
    # Load the unchanged pure functions only. The full parser scorer imports
    # BeautifulSoup for HTML work, which this textual replay never performs.
    scripts = root / ".local/docling-lab/scripts"
    namespace = dict(re=re, unicodedata=unicodedata)
    matcher_hashes = {}
    for filename, names in (
        ("dl1_score.py", {"norm"}),
        ("dl2_score.py", {"clean", "literal_edge", "bipartite", "evaluate"}),
    ):
        source = (scripts / filename).read_text()
        tree = ast.parse(source)
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        assert {f.name for f in functions} == names
        exec(compile(ast.Module(body=functions, type_ignores=[]), filename, "exec"), namespace)
        matcher_hashes[filename] = sha256(source.encode()).hexdigest()
    evaluate = namespace["evaluate"]
    GOLD = next(
        (root / "outputs/agent-results/R108-redesign/lab/gold-return/20261010/raw").rglob(
            "20261007*.json"
        )
    )
    gold = json.loads(GOLD.read_text())
    previous = json.loads(
        (root / "outputs/agent-results/R108-redesign/lab/perf/PB5/scores.json").read_text()
    )
    assert sha256(GOLD.read_bytes()).hexdigest() == previous["gold_sha256"]
    scores = {}
    for name in ("kia", "naver"):
        predictions = [
            dict(
                id=c["claim_id"],
                quote=c["quote"],
                page=c["original_page_num"],
                track=c.get("track"),
            )
            for c in results[name]["claims"]
        ]
        gg = [
            g
            for g in gold["sheets"]["1_전수목록"]
            if g["기업"] == name and g["비주장 여부"] == "주장"
        ]
        measured = evaluate(gg, predictions)
        keys = (
            "gold_denominator",
            "predictions",
            "one_to_one_matches",
            "strict_text_recall",
            "strict_text_precision",
        )
        scores[name] = {k: measured[k] for k in keys}
        assert scores[name] == {k: previous["ours_hosted"][name][k] for k in keys}
    return dict(
        gold_sha256=previous["gold_sha256"],
        matcher_sha256=matcher_hashes,
        scores=scores,
        limitation="Draft textual claim proxy; not semantic/grade accuracy.",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/path/to/ESG_ProofOps"))
    args = parser.parse_args()
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    start = monotonic()
    root = args.root
    lab = root / "outputs/agent-results/R108-redesign/lab"
    out = lab / "perf/W8"
    review_path = lab / "review/CR1/cases.json"
    review = json.loads(review_path.read_text())
    source_paths = dict(
        lgchem=out / "lgchem-tag_snapshot.json",
        kia=lab / "perf/PB5/kia-tag_snapshot_sha256.json",
        naver=lab / "perf/PB5/naver-tag_snapshot_sha256.json",
    )
    run_path = out / "lgchem-run_snapshot.json"
    results = {
        name: json.loads(Path(c["source_result"]).read_text())
        for name, c in (
            ("lgchem", review["cases"][0]),
            ("kia", next(c for c in review["cases"] if c["case_id"].startswith("KIA-"))),
            ("naver", next(c for c in review["cases"] if c["case_id"].startswith("NAVER-"))),
        )
    }
    paths = [
        review_path,
        run_path,
        *source_paths.values(),
        *(Path(c["source_result"]) for c in review["cases"]),
    ]
    input_hashes = {str(p): sha256(p.read_bytes()).hexdigest() for p in set(paths)}
    pack = RulePackSnapshot(**json.loads(run_path.read_text())["rulepack"])
    snapshots = {name: json.loads(path.read_text()) for name, path in source_paths.items()}
    by_id = {name: {c["claim_id"]: c for c in snap["claims"]} for name, snap in snapshots.items()}
    rows, changed, kept_supported, baseline_mismatches = [], [], [], []
    for case in review["cases"]:
        name = (
            "lgchem" if case["case_id"].startswith("LG-") else case["case_id"].split("-")[0].lower()
        )
        item = by_id[name][case["claim_id"]]
        saved = case["system_claim"]["provisional_grade"]
        if item.get("frozen_packet") and item.get("tag_runs"):
            before, after = replay(item, pack), replay(item, pack, policy=POLICY)
            status = "saved_replicas_reprocessed"
            # Display/hash versions can differ; compare actual evidence states/grade.
            if (before.get("evidence_grade"), projection(before)["states"]) != (
                saved.get("evidence_grade"),
                projection(saved)["states"],
            ) or before.get("semantic_hash") != saved.get("semantic_hash"):
                baseline_mismatches.append(case["case_id"])
        else:
            before = after = saved
            status = "saved_hold_preserved_no_tag_replicas"
        b, a = projection(before), projection(after)
        delta = [eid for eid, state in b["states"].items() if a["states"].get(eid) != state]
        if delta or b["evidence_grade"] != a["evidence_grade"] or b["display"] != a["display"]:
            changed.append(case["case_id"])
        for audit in case["review"].get("d_present_element_audit", []):
            if audit["verdict"] == "supported":
                assert a["states"][audit["element_id"]] == "present", (case["case_id"], audit)
                kept_supported.append([case["case_id"], audit["element_id"]])
        rows.append(
            dict(
                case_id=case["case_id"],
                claim_id=case["claim_id"],
                status=status,
                before=b,
                after=a,
                changed_elements=delta,
            )
        )
    assert not baseline_mismatches, baseline_mismatches
    mapped = {r["case_id"]: r for r in rows}
    assert mapped["LG-38"]["after"]["evidence_grade"] is None
    assert mapped["LG-34"]["after"]["states"]["M2"] == "unknown"
    assert mapped["KIA-00"]["after"]["states"]["G6"] == "unknown"
    assert mapped["KIA-00"]["after"]["states"]["G2"] == "conflict"
    for cid in ("KIA-17", "KIA-19"):
        assert mapped[cid]["after"]["display"] == "추정치 · 산정 근거 확인 필요"
        assert mapped[cid]["after"]["grade_range"] is None
    assert mapped["NAVER-05"]["after"]["evidence_grade"] is None
    gold = gold_check(root, results)
    assert input_hashes == {str(p): sha256(p.read_bytes()).hexdigest() for p in set(paths)}
    record = dict(
        schema="w8-saved-response-replay-v1",
        semantic_policy_sha256=POLICY_HASH,
        input_sha256=input_hashes,
        cases=rows,
        changed_cases=changed,
        status_counts=dict(Counter(r["status"] for r in rows)),
        supported_elements_preserved=kept_supported,
        baseline_mismatches=[],
        gold=gold,
        paid_calls=0,
        paid_cost_usd=0,
        seconds=monotonic() - start,
        limitations=[
            "Saved guarded responses; no new model inference or PDF attestation.",
            "CR1 is AI content review, not human gold.",
            "Unresolved evidence restoration, column repair and claim splitting remain outside W8.",
        ],
    )
    (out / "comparison.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    lines = ["| Case | Before | After | Changed elements |", "|---|---|---|---|"]
    for r in rows:
        elements = ", ".join(r["changed_elements"]) or "—"
        lines.append(
            f"| {r['case_id']} | {r['before']['evidence_grade'] or 'hold'} | "
            f"{r['after']['evidence_grade'] or 'hold'} | {elements} |"
        )
    (out / "before-after.md").write_text("\n".join(lines) + "\n")
    print(
        json.dumps(
            {k: record[k] for k in ("status_counts", "changed_cases", "paid_cost_usd", "seconds")},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
