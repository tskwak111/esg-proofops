"""Read MB judgments + E2E3 archived packets, without transport, keys or network.

This is an offline transfer analysis of MB's archived complete-policy questions,
not a paid E2E or exact-wire replay under the newly authored question pins. Only
12/115 claims have Decisions responses; unmeasured cases are explicitly unresolved.
Saved Luna quotes are checked against raw strings and reversible display maps;
PDF/source attestations are not rerun and no element state or grade is calculated.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from proofops.application.tagging.decisions import (
    AXES,
    POLICY,
    preliminary_questions,
    resolve_preliminary,
    resolve_relation,
    validate_answers,
)
from proofops.domain.provenance import canonical_hash


def read(path):
    return json.loads(Path(path).read_text())


def archived_quotes(case):
    """Require all three Luna replicas to return the same valid raw literal span."""
    outputs = case["cached"]
    if len(outputs) != 3 or any(not isinstance(r.get("output"), dict) for r in outputs):
        return {}
    original = json.loads(read(outputs[0]["request_path"])["request"]["user_json"])
    sources = original["untrusted_document_data"]["sources"]
    pins = case["display"]["sources"] if case.get("display") else []
    result = {}
    for axis in AXES:
        selected = [r["output"]["dimensions"].get(axis) for r in outputs]
        span = selected[0]
        if not span or not all(s == span for s in selected):
            continue
        try:
            index, quote = span["source_index"], span["quote"]
            if type(index) is not int or index < 0 or not isinstance(quote, str) or not quote:
                continue
            raw = sources[index]["text"]
            if pins:
                pin = pins[index]
                deleted = set(pin["deleted_offsets"])
                text = "".join(c for n, c in enumerate(raw) if n not in deleted)
                if text != pin["text"] or canonical_hash(raw) != pin["raw_sha256"]:
                    continue
            else:
                text = raw
            if text.count(quote) != 1:
                continue
            begin, end = text.index(quote), text.index(quote) + len(quote)
            if pins:
                boundaries = pins[index]["raw_boundaries"]
                begin, end = boundaries[begin + 1] - 1, boundaries[end]
                if (
                    "".join(
                        c for n, c in enumerate(raw[begin:end], start=begin) if n not in deleted
                    )
                    != quote
                ):
                    continue
            result[axis] = dict(
                source_index=index, quote=raw[begin:end], raw_start=begin, raw_end=end
            )
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return result


def replay(mb):
    inputs, records = read(mb / "executed-inputs.json"), read(mb / "run-records.json")
    chosen = {}
    for record in records:
        meta = record.get("meta") or {}
        if record["model"] not in ("gpt-6-luna", "typesafe/jev-1.13") or record["status"] != "ok":
            continue
        if meta.get("task") == "A" and not record["id"].endswith("-semantics"):
            continue
        chosen[record["model"], meta.get("case"), meta.get("replica")] = record
    sample = {}
    for case in inputs["A"]:
        quotes = archived_quotes(case)
        trials = []
        for replica in (1, 2):
            answers, receipts = [], []
            for model in ("gpt-6-luna", "typesafe/jev-1.13"):
                record = chosen[model, case["id"], replica]
                response = read(record["response_path"])
                request = read(Path(record["response_path"]).with_name("request.json"))
                answers.append(validate_answers(response, preliminary_questions()))
                receipts.append(
                    dict(
                        model=model,
                        response_sha256=canonical_hash(response),
                        archived_request_sha256=canonical_hash(request),
                        response_path=record["response_path"],
                    )
                )
            fields = resolve_preliminary(*answers, quotes)
            categories = [r["output"].get("safe_harbor_category") for r in case["cached"]]
            category_agreed = len(categories) == 3 and all(c == categories[0] for c in categories)
            trials.append(
                dict(
                    fields=fields,
                    receipts=receipts,
                    category_agreed=category_agreed,
                    candidate_track=fields["track"]["value"] if category_agreed else None,
                )
            )
        sample[case["id"]] = dict(
            claim_id=case["claim_id"],
            company=case["company"],
            quotes=quotes,
            trials=trials,
            expected_track=case["expected_track"],
            original_packet_sha256=case["packet_sha256"],
        )
    companies = defaultdict(Counter)
    claims = []
    for case in inputs["inventory"]:
        counter = companies[case["company"]]
        counter["packets"] += 1
        saved = sample.get(case["id"])
        primary = saved["trials"][0] if saved else None
        fields = primary["fields"] if primary else {}
        counter["measured"] += bool(saved)
        counter["track_confirmed"] += bool(primary and primary["candidate_track"])
        counter["track_review"] += not (primary and primary["candidate_track"])
        counter["axes_confirmed"] += (
            sum(fields[a]["state"] == "agreed" for a in AXES) if fields else 0
        )
        counter["axes_review"] += (
            sum(fields[a]["state"] == "unresolved" for a in AXES) if fields else 8
        )
        claims.append(
            dict(
                claim_id=case["claim_id"],
                company=case["company"],
                measured=bool(saved),
                reason="MB_ARCHIVED_PAIR" if saved else "NO_SAVED_DECISION_RESPONSES",
                analysis=saved,
            )
        )
    relation = Counter()
    relation_rows = []
    for case in inputs["B"]:
        if case["task"] != "B_relation":
            continue
        answers, receipts = [], []
        for model in ("gpt-6-luna", "typesafe/jev-1.13"):
            record = chosen[model, case["id"], 1]
            response = read(record["response_path"])
            answers.append(validate_answers(response, case["questions"])["relation"])
            receipts.append(dict(model=model, response_sha256=canonical_hash(response)))
        values = [a["choice"] if a else "unknown" for a in answers]
        resolved = resolve_relation(*values)
        relation[resolved] += 1
        relation_rows.append(
            dict(case=case["id"], resolved=resolved, model_answers=answers, receipts=receipts)
        )
    totals = dict(sum(companies.values(), Counter()))
    aligned = [s for s in sample.values() if s["expected_track"]]
    return dict(
        schema="decision-profile-offline-analysis-v1",
        policy=POLICY,
        policy_sha256=canonical_hash(POLICY),
        paid_calls=0,
        new_cost_usd="0",
        label_status="임시 정답(AI) 기준; 사람 정확도 아님",
        limitations=[
            "12/115 measured MB pairs; other 103 are unmeasured review cases",
            "archived MB complete-policy prompt transfer; not exact new-profile HTTP replay",
            "saved literal/display-map checks only; no PDF/source re-attestation",
            "0.80 is uncalibrated; threshold selected conservatively, not tuned to labels",
        ],
        totals=totals,
        companies={k: dict(v) for k, v in companies.items()},
        provisional_track_matches=sum(
            s["trials"][0]["candidate_track"] == s["expected_track"] for s in aligned
        ),
        provisional_track_comparable=len(aligned),
        measured_trial2_confirmed=sum(
            bool(s["trials"][1]["candidate_track"]) for s in sample.values()
        ),
        relation_totals=dict(relation),
        relation_rows=relation_rows,
        claims=claims,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mb", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = replay(args.mb)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {k: result[k] for k in ("paid_calls", "totals", "companies", "relation_totals")},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
