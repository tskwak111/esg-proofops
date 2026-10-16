"""Compose V25 frozen diagnostics into V4's provenance-checked prediction format.

No provider calls, fresh votes, production revisions or missing inventory are
created. R17 element deltas are applied to the I24 QT2 baseline, not to the older
E14 raw element counts. V3 category changes remain retag_required.
"""

import argparse
import json
import socket
from copy import deepcopy
from pathlib import Path

from proofops.application.analysis_profile import FINALS_I25_POLICY
from proofops.domain.provenance import canonical_hash

from evaluation.qt1_v25_replay import refine_predictions
from evaluation.r19_gold_overlay import Inputs
from evaluation.r19_rescore import LAB_PATH, source_refs, validate_candidate, write
from evaluation.v3_replay import project


def refine_with_provenance(predictions):
    result = []
    for parent in predictions:
        children, changes = refine_predictions([parent])
        if not changes:
            result.append(deepcopy(parent))
            continue
        refs = source_refs(parent)
        if len(refs) != 1 or refs[0]["quote"] != parent["quote"]:
            raise ValueError("I25_CHILD_SOURCE_NOT_EXACT")
        ref = refs[0]
        for child, span in zip(children, changes[0]["children"], strict=True):
            assert parent["quote"][span["char_start"] : span["char_end"]] == child["quote"]
            child["source_refs"] = [
                ref
                | dict(
                    quote=child["quote"],
                    char_start=ref["char_start"] + span["char_start"],
                    char_end=ref["char_start"] + span["char_end"],
                    verification_state="unverified",
                )
            ]
            child["parent_prediction_id"] = parent["id"]
            child["parent_source_refs"] = deepcopy(refs)
            result.append(child)
    return result


def run(root, baseline_path, v2_path, output):
    inputs = Inputs()
    baseline = inputs.read(baseline_path)
    candidate = deepcopy(baseline)
    candidate.update(
        label="I25 v25 composed frozen diagnostic projection; not a fresh model run",
        analysis_policy_sha256=canonical_hash(FINALS_I25_POLICY),
        limitations=[
            "V1: no same-run SC1 inventory in E14; no new activity confirmations",
            "V2: literal extraction and saved P1/P2 deltas; children need source revalidation",
            "V3: category/source veto projection; missing facts require fresh retagging",
            "R17 elements use I24 QT2 baseline; grades use retained E14 plus V3 holds",
            "DL4/holdout extraction-only; element and grade metrics remain not_run",
        ],
    )
    for cohort in ("dl4", "holdout"):
        candidate["cohorts"][cohort] = refine_with_provenance(baseline["cohorts"][cohort])
    v2 = {(r["case"], r["claim_id"]): r for r in inputs.read(v2_path)}
    stored, changes = {}, []
    for case, scope in baseline["input_identity"]["scopes"].items():
        if isinstance(scope, dict) and "run_id" in scope:
            artifacts = inputs.read(
                root / LAB_PATH / "quality/QT2/stored" / scope["run_id"] / "job-artifacts.json"
            )
            tags = next(r["value"] for r in artifacts if "claims" in r.get("value", {}))
            stored.update({(case, row["claim_id"]): row for row in tags["claims"]})
    for row in candidate["cohorts"]["r17"]:
        key = (row["case"], row["claim_id"])
        pair = v2.get(key)
        if pair:
            for element in ("P1", "P2"):
                before = pair["before"]["states"].get(element, "unknown")
                after = pair["after"]["states"].get(element, "unknown")
                if element in row["element_states"] and before != after:
                    row["element_states"][element] = after
        updated, projection = project(stored[key], row["public_claim"]["quote"])
        for veto in projection["vetoes"]:
            if veto["element_id"] in row["element_states"]:
                row["element_states"][veto["element_id"]] = veto["after"]
        if projection["retag_required"]:
            row["public_claim"].update(
                provisional_grade=updated["provisional_grade"],
                confirmed_grade=None,
                decision=None,
                possible_grade_range=None,
                hold_reason=updated["reason"],
            )
            changes.append(dict(case=key[0], claim_id=key[1], **projection))
        row["grade_origin"] = "Retained E14 snapshot plus V25 V3 safety holds; no new votes"
        row["element_origin"] = "I24 QT2 states plus V2 saved-response deltas and V3 vetoes"
    validate_candidate(candidate, baseline)
    candidate["inputs_sha256"] = inputs.hashes
    candidate["changes"] = changes
    candidate["real_provider_calls"] = 0
    candidate["paid_usd"] = 0
    inputs.verify()
    if output.exists():
        raise ValueError("OUTPUT_ALREADY_EXISTS")
    write(output, candidate)
    return candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--v2-details", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    def deny(*args, **kwargs):
        raise RuntimeError("I25_REPLAY_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    result = run(args.root, args.baseline, args.v2_details, args.output)
    print(
        json.dumps(
            dict(policy=result["analysis_policy_sha256"], held_for_retag=len(result["changes"]))
        )
    )


if __name__ == "__main__":
    main()
