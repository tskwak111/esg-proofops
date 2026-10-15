"""Offline V4 gold-only rescoring; reusable for V1–V3 frozen predictions.

python -m evaluation.r19_rescore --root /artifact/root --output /new/output
Then pass --predictions baseline-predictions.json (same input identity contract).
No model transport, product writer, new votes, or promotion of missing facts.
"""

import argparse
import json
import socket
import time
from collections import Counter
from pathlib import Path

from evaluation.r19_gold_overlay import (
    FOOTNOTES,
    Inputs,
    apply_overlay,
    build_overlay,
    digest,
    frozen_scorer,
    reply_provenance,
)

LAB_PATH = Path("outputs/agent-results/R108-redesign/lab")
BASE_COMMIT = "6c6241f9568e588c7add4b29c14a307378143366"


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def source_refs(prediction):
    if "source_ref" in prediction:
        return [prediction["source_ref"]]
    return prediction.get("raw", {}).get("source_refs", prediction.get("source_refs", []))


def load_baseline(root, inputs, audit):
    lab = root / LAB_PATH
    qt1 = inputs.read(lab / "perf/I24/qt1/cohort-results.json")
    qt2 = inputs.read(lab / "perf/I24/qt2/replay-metrics.json")
    cohorts, scopes = {"dl4": [], "holdout": [], "r17": []}, {}
    for company in ("naver", "kia"):
        before = inputs.read(lab / f"perf/I23/dl4/{company}-after.json")
        cohorts["dl4"].extend(
            {**p, "company": company} for p in before + qt1["dl4"][company]["added"]
        )
        state = inputs.read(lab / f"perf/PA9/{company}-server/result-1.json")
        scopes[company] = {
            "pages": state["page_map"],
            "tenant_id": state["tenant_id"],
            "source_hashes": state["source_hashes"],
        }
    for company, states in {
        "SK하이닉스": ["SK하이닉스"],
        "현대자동차": ["현대자동차-p22", "현대자동차-p41"],
        "POSCO홀딩스": ["POSCO홀딩스"],
        "삼성전자": ["삼성전자"],
    }.items():
        before = inputs.read(lab / f"perf/I23/holdout/holdout/{company}/predictions.json")
        cohorts["holdout"].extend(before + qt1["holdout"]["companies"][company]["added"])
        scopes[company] = []
        for state in states:
            pilot = inputs.read(lab / f"fix/A/paid-dec26/states/{state}/pilot.json")
            scopes[company].append(
                {
                    k: pilot[k]
                    for k in ("tenant_id", "document_version_id", "source_sha256", "selected_pages")
                }
            )
    details = {(r["case"], r["claim_id"], r["element"]): r for r in qt2["details"]}
    for report in audit["reports"]:
        inputs.record(root / report["result_path"], report["result_sha256"])
        inputs.record(Path(report["source_pdf"]), report["source_sha256"])
        scopes[report["case"]] = {
            "source_sha256": report["source_sha256"],
            "selected_pages": report["page_map"],
            "run_id": report["run_id"],
            "result_sha256": report["result_sha256"],
        }
        for row in report["rows"]:
            if row["record_type"] != "claim":
                continue
            elements = {}
            for element in row["elements"]:
                if element["scored"]:
                    key = (report["case"], row["claim_id"], element["element_id"])
                    detail = details[key]
                    if detail["gold"] != element["gold_state"]:
                        raise ValueError("R17_GOLD_STATE_CHANGED")
                    elements[element["element_id"]] = detail["after"]
            cohorts["r17"].append(
                {
                    "case": report["case"],
                    "claim_id": row["claim_id"],
                    "public_claim": row["server_claim_snapshot"],
                    "element_states": elements,
                    "grade_origin": "E14 frozen public export; v24 live grades not measured",
                    "element_origin": "I24 QT2 replay after; not fresh model votes",
                }
            )
    identity = {
        "scopes": scopes,
        "r17_audit_sha256": digest(audit),
        "r17_claim_ids": sorted((p["case"], p["claim_id"]) for p in cohorts["r17"]),
        "document_versions": {
            name: sorted(
                {
                    (p["company"], r["document_version_id"])
                    for p in cohorts[name]
                    for r in source_refs(p)
                }
            )
            for name in ("dl4", "holdout")
        },
    }
    # Round-trip tuples to JSON lists so disk-loaded candidates compare identically.
    identity = json.loads(json.dumps(identity))
    return {
        "schema": "v4_frozen_predictions_v1",
        "label": "v24_frozen_replay",
        "base_commit": BASE_COMMIT,
        "input_identity": identity,
        "input_identity_sha256": digest(identity),
        "cohorts": cohorts,
        "limitations": [
            "DL4/holdout extraction-only: grades and element states not_run",
            "R17 elements from I24 replay; grades retained from E14, not a v24 live run",
        ],
    }


def validate_candidate(candidate, baseline):
    if candidate["schema"] != "v4_frozen_predictions_v1":
        raise ValueError("PREDICTION_SCHEMA_MISMATCH")
    if candidate["input_identity"] != baseline["input_identity"] or candidate[
        "input_identity_sha256"
    ] != digest(baseline["input_identity"]):
        raise ValueError("COHORT_INPUT_IDENTITY_CHANGED")
    if set(candidate["cohorts"]) != {"dl4", "holdout", "r17"}:
        raise ValueError("COHORT_SET_CHANGED")
    expected = {(r["case"], r["claim_id"]): r for r in baseline["cohorts"]["r17"]}
    seen = set()
    for row in candidate["cohorts"]["r17"]:
        key = (row["case"], row["claim_id"])
        if key in seen or key not in expected:
            raise ValueError("R17_COHORT_CHANGED")
        seen.add(key)
        before = expected[key]
        if row["public_claim"]["claim_id"] != key[1]:
            raise ValueError("CLAIM_ID_MISMATCH")
        if row["public_claim"]["source_refs"] != before["public_claim"]["source_refs"]:
            raise ValueError("R17_SOURCE_IDENTITY_CHANGED")
        if row["public_claim"]["quote"] != before["public_claim"]["quote"]:
            raise ValueError("R17_QUOTE_CHANGED")
        if set(row["element_states"]) != set(before["element_states"]):
            raise ValueError("R17_ELEMENT_COHORT_CHANGED")
        if any(
            s
            not in {"present", "unknown", "conflict", "absent", "absent_in_scope", "not_applicable"}
            for s in row["element_states"].values()
        ):
            raise ValueError("INVALID_ELEMENT_STATE")
    if seen != set(expected):
        raise ValueError("R17_COHORT_SHRANK")
    for name in ("dl4", "holdout"):
        versions = {tuple(x) for x in baseline["input_identity"]["document_versions"][name]}
        seen = set()
        for row in candidate["cohorts"][name]:
            key = (row["company"], row["id"])
            if key in seen:
                raise ValueError("DUPLICATE_PREDICTION_ID")
            seen.add(key)
            refs = source_refs(row)
            if not refs or any(
                (row["company"], r["document_version_id"]) not in versions for r in refs
            ):
                raise ValueError("PREDICTION_DOCUMENT_CHANGED")
            scope = baseline["input_identity"]["scopes"][row["company"]]
            pages = (
                scope["pages"]
                if isinstance(scope, dict)
                else [p for s in scope for p in s["selected_pages"]]
            )
            if row["page"] not in pages:
                raise ValueError("PREDICTION_OUTSIDE_SELECTED_SCOPE")


def grade_counts(rows):
    counts = Counter(hold=0, provisional=0, confirmed=0, scope_confirmed=0, not_run=0)
    records = []
    for row in rows:
        claim = row["public_claim"]
        confirmed = claim.get("confirmed_grade")
        scope = claim.get("sc1_confirmation")
        provisional = claim.get("provisional_grade") or {}
        if confirmed is not None or scope is not None:
            status = "confirmed"
            counts["scope_confirmed"] += int(scope is not None)
        elif provisional.get("display_type") == "hold":
            status = "hold"
        elif provisional.get("evidence_grade") is not None:
            status = "provisional"
        else:
            status = "not_run"
        counts[status] += 1
        records.append(
            {
                "case": row["case"],
                "claim_id": row["claim_id"],
                "status": status,
                "scope_confirmed": scope is not None,
            }
        )
    # R17 lower-bound gold is not an exact-grade/complete-scope confirmation oracle.
    counts["false_confirmed"] = 0 if counts["confirmed"] == 0 else None
    counts["unadjudicated_confirmations"] = counts["confirmed"]
    return {**counts, "records": records}


def score_r17(audit, predictions):
    gold = {
        (r["case"], r["claim_id"], e["element_id"]): e["gold_state"]
        for report in audit["reports"]
        for r in report["rows"]
        if r["record_type"] == "claim"
        for e in r["elements"]
        if e["scored"]
    }
    records = []
    for row in predictions:
        for element, state in row["element_states"].items():
            key = (row["case"], row["claim_id"], element)
            records.append(
                {
                    "case": key[0],
                    "claim_id": key[1],
                    "element": element,
                    "state": state,
                    "gold": gold[key],
                    "true_present": state == gold[key] == "present",
                    "false_present": state == "present" and gold[key] != "present",
                }
            )
    return {
        "claims": len(predictions),
        "scored_elements": len(records),
        "gold_present": sum(r["gold"] == "present" for r in records),
        "true_present": sum(r["true_present"] for r in records),
        "false_present": sum(r["false_present"] for r in records),
        "state_match": sum(r["state"] == r["gold"] for r in records),
        "grades": grade_counts(predictions),
        "records": records,
    }


def compare(audit, gold, holdout, overlay, baseline, candidate, scorer):
    validate_candidate(candidate, baseline)
    updated = apply_overlay(gold, overlay)
    result = {"label": candidate["label"], "r17": {}, "dl4": {}, "holdout": {}}
    for phase, predictions, target in (("before", baseline, gold), ("after", candidate, updated)):
        result["r17"][phase] = score_r17(audit, predictions["cohorts"]["r17"])
        for name, atoms in (("dl4", target["golds"]), ("holdout", holdout)):
            result[name][phase] = scorer.evaluate(atoms, predictions["cohorts"][name])
            result[name][phase]["grade_and_element_metrics"] = {
                "status": "not_run",
                "reason": "frozen extraction predictions contain no grading/tagging run",
                "hold": None,
                "provisional": None,
                "confirmed": None,
                "scope_confirmed": None,
                "true_present": None,
                "false_present": None,
                "false_confirmed": None,
            }
    result["dl4"]["pending_scope"] = {"before": 28, "after": 24}
    result["dl4"]["gold_semantic_change"] = list(FOOTNOTES)
    before = {
        (r["case"], r["claim_id"], r["element"]): r for r in result["r17"]["before"]["records"]
    }
    after = result["r17"]["after"]["records"]
    recovered = [
        r
        for r in after
        if r["true_present"]
        and not before[(r["case"], r["claim_id"], r["element"])]["true_present"]
    ]
    lost = [
        r
        for r in after
        if not r["true_present"]
        and before[(r["case"], r["claim_id"], r["element"])]["true_present"]
    ]
    new_false = [
        r
        for r in after
        if r["false_present"]
        and not before[(r["case"], r["claim_id"], r["element"])]["false_present"]
    ]
    result["r17"]["delta"] = {
        "recovered_present": recovered,
        "lost_present": lost,
        "new_false_present": new_false,
    }
    grades = result["r17"]["after"]["grades"]
    nondeclining = all(
        result[c]["after"][m] >= result[c]["before"][m]
        for c in ("dl4", "holdout")
        for m in ("matches", "recall", "precision")
        if result[c]["before"][m] is not None and result[c]["after"][m] is not None
    )
    result["quality_gate"] = {
        "no_new_false_present": not new_false,
        "no_lost_present": not lost,
        "fixed_extraction_cohorts_nondeclining": nondeclining,
        "no_unadjudicated_or_false_confirmation": grades["confirmed"] == 0,
        "scope": "frozen diagnostic cohorts only; missing DL4/holdout grades remain not_run",
    }
    result["quality_gate"]["passed"] = all(
        v for v in result["quality_gate"].values() if isinstance(v, bool)
    )
    result["model_improvement_claim"] = False
    return result


def run(root, output, predictions_path=None):
    started = time.monotonic()
    lab, inputs = root / LAB_PATH, Inputs()
    rules = inputs.read(lab / "review/R19/rules-delta.json")
    source_manifest = {r["path"]: r["sha256"] for r in rules["source_manifest"]}

    def source(relative):
        return inputs.read(root / relative, source_manifest.get(str(relative)))

    reply = source(LAB_PATH / "domain/TEAM-20261015/reply.json")
    gold = source(LAB_PATH / "perf/I3/dl4-reference/DL4-gold.json")
    audit = source(LAB_PATH / "review/R17/audit.json")
    returned_path = next(p for p in source_manifest if "20261007" in p and p.endswith(".json"))
    returned = source(Path(returned_path))
    scorer = frozen_scorer(root / ".local/g1-gold/evaluation/dl4_gold.py", inputs)
    workbook_path = LAB_PATH / "domain/TEAM-20261015/확인요청_회신_20261015.xlsx"
    inputs.record(root / workbook_path, source_manifest[str(workbook_path)])
    workbook = scorer.xlsx_rows(root / workbook_path)
    provenance = reply_provenance(reply, workbook, rules["reply_coverage"])
    for name in ("kia-106.png", "kia-26.png", "naver-221.png", "pdf-manifest.json"):
        path = LAB_PATH / "gold-v2/AU1" / name
        inputs.record(root / path, source_manifest[str(path)])
    decisions = lab / "autonomy/DECISION-LOG.md"
    inputs.record(decisions)
    decision_text = decisions.read_text()
    sections = {
        name: decision_text.split(f"## {name} (")[1].split("\n## DEC-")[0]
        for name in ("DEC-92", "DEC-93")
    }
    overlay = build_overlay(gold, reply, provenance, rules, returned, inputs.hashes)
    baseline = load_baseline(root, inputs, audit)
    candidate = inputs.read(predictions_path) if predictions_path else baseline
    holdout = inputs.read(lab / "fix/A/paid-dec26/v1-gold-atoms.json")
    result = compare(audit, gold, holdout, overlay, baseline, candidate, scorer)
    # Legacy 156 stays on its original literal matcher, separately named.
    from evaluation.d24_replay import load_scorer

    scripts = root / ".local/docling-lab/scripts"
    legacy_score, hashes = load_scorer(scripts)
    for name, expected in hashes.items():
        inputs.record(scripts / name, expected)
    result["legacy_dl3_156"] = {}
    for phase, predictions in (("before", baseline), ("after", candidate)):
        result["legacy_dl3_156"][phase] = {
            company: legacy_score(
                [
                    g
                    for g in returned["sheets"]["1_전수목록"]
                    if g["기업"] == company and g["비주장 여부"] == "주장"
                ],
                [p for p in predictions["cohorts"]["dl4"] if p["company"] == company],
            )
            for company in ("naver", "kia")
        }
    result["legacy_dl3_156"]["denominator"] = sum(
        g["기업"] in {"naver", "kia"} and g["비주장 여부"] == "주장"
        for g in returned["sheets"]["1_전수목록"]
    )
    if result["legacy_dl3_156"]["denominator"] != 156:
        raise ValueError("LEGACY_DENOMINATOR_CHANGED")
    result["candidate_groups"] = [
        {
            "case": report["case"],
            "physical_page": next(
                r["physical_page"]
                for r in report["rows"]
                if r.get("claim_id") in rules["gold_impact"]["r17"]["candidate_ids"]
            ),
            "claim_ids": [
                r["claim_id"]
                for r in report["rows"]
                if r.get("claim_id") in rules["gold_impact"]["r17"]["candidate_ids"]
            ],
            "status": "retag_required; source/consensus/scope gates not bypassed",
        }
        for report in audit["reports"]
    ]
    result["historical_recovery"] = inputs.read(lab / "perf/I24/qt1/recovery-equivalence.json")
    result["retained_counterexamples"] = inputs.read(lab / "perf/I24/counterexamples-summary.json")
    result["retained_counterexamples"]["execution"] = (
        "retained I24 evidence; not a new V4 execution"
    )
    result.update(
        {
            "schema": "v4_r19_rescore_v1",
            "base_commit": BASE_COMMIT,
            "overlay_sha256": overlay["overlay_sha256"],
            "policy_sha256": overlay["policy_sha256"],
            "input_identity_sha256": baseline["input_identity_sha256"],
            "candidate_label": candidate["label"],
            "candidate_limitations": candidate.get("limitations", []),
            "decision_sections": sections,
            "inputs_sha256": inputs.hashes,
            "evaluator_sha256": {
                p.name: inputs.record(p)
                for p in (Path(__file__), Path(__file__).with_name("r19_gold_overlay.py"))
            },
            "model_calls": 0,
            "paid_usd": 0,
            "production_revisions_written": 0,
            "elapsed_seconds": round(time.monotonic() - started, 6),
            "latency_scope": "offline evaluator only; no provider/end-to-end latency",
        }
    )
    inputs.verify()
    output.mkdir(parents=True, exist_ok=True)
    # Never overwrite inputs, old reports or a previous scoring run.
    artifacts = {
        "gold-overlay.json": overlay,
        "DL4-derived-gold.json": apply_overlay(gold, overlay),
        "baseline-predictions.json": baseline,
        "rescore.json": result,
    }
    for name in [*artifacts, "rescore-table.md"]:
        if (output / name).exists() or str((output / name).resolve()) in inputs.hashes:
            raise ValueError(f"OUTPUT_ALREADY_EXISTS: {name}")
    for name, value in artifacts.items():
        write(output / name, value)
    lines = ["| Cohort | Measure | Before | After |", "|---|---|---:|---:|"]
    for cohort in ("dl4", "holdout", "r17"):
        metrics = (
            ("claims", "scored_elements", "true_present", "false_present")
            if cohort == "r17"
            else ("gold_denominator", "predictions", "matches", "recall", "precision")
        )
        for metric in metrics:
            lines.append(
                f"| {cohort} | {metric} | {result[cohort]['before'][metric]} | "
                f"{result[cohort]['after'][metric]} |"
            )
    for metric in ("hold", "provisional", "confirmed", "scope_confirmed", "false_confirmed"):
        lines.append(
            f"| R17 retained grades | {metric} | "
            f"{result['r17']['before']['grades'][metric]} | "
            f"{result['r17']['after']['grades'][metric]} |"
        )
    lines.extend(
        [
            "| DL4 | pending scope | 28 | 24 |",
            "",
            (
                "Gold-only overlay on identical frozen predictions; no model improvement claim."
                if candidate == baseline
                else (
                    f"Candidate: {candidate['label']}. Frozen diagnostic comparison; "
                    "no live model improvement claim."
                )
            ),
            "DL4/holdout grades and element metrics: not_run (extraction only).",
            (
                "R17 grades are E14 exports; element states are v24 QT2 replay, "
                "not v24 live results."
                if candidate == baseline
                else (
                    "R17 candidate grade/element origins and limitations are recorded "
                    "in the prediction manifest."
                )
            ),
            "Legacy DL3 denominator 156 is separate from DL4 denominator 131.",
            "R17 source omissions 102 and QT1 recoveries are historical, not V4 gains.",
        ]
    )
    (output / "rescore-table.md").write_text("\n".join(lines) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--predictions", type=Path)
    args = parser.parse_args()

    def deny(*args, **kwargs):
        raise RuntimeError("V4_REPLAY_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    result = run(args.root, args.output, args.predictions)
    print(json.dumps({"quality_gate": result["quality_gate"], "model_calls": 0}))


if __name__ == "__main__":
    main()
