"""Read-only DEC-92 impact projection over retained R17, DL4 and holdout outputs.

No model invocation or publication. New categories needing facts remain retag_required.
Missing saved tagging is unmeasured, never an invented hold/absence. The before
column is the retained historical result, not a newly run v24 model evaluation.
"""

import argparse
import json
import socket
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

from proofops.application.analysis_profile import FINALS_I24_POLICY, V3_POLICY
from proofops.application.tagging.quality import hold_projection
from proofops.application.tagging.v3_dec92 import forward_candidate, guard
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import LlmElement, SourceRef

from evaluation.pa3_replay import checkpoint


def norm(text):
    return "".join(text.split())


def classification(item):
    packet = item.get("frozen_packet") or {}
    if packet.get("track"):
        return packet["track"], packet.get("safe_harbor_category")
    values = [r.get("values") or {} for r in item.get("preliminary_records", [])]
    headers = {(v.get("track") or {}).get("track") for v in values}
    return (next(iter(headers)) if len(headers) == 1 else None), None


def project(item, quote):
    updated = deepcopy(item)
    result = updated["provisional_grade"]
    track, category = classification(item)
    candidate, reason = forward_candidate(quote, track=track)
    new_category = candidate and category != candidate
    changes = []
    for element in result.get("elements", []):
        refs = tuple(SourceRef(**r) for r in element.get("evidence_refs", []))
        old = LlmElement(
            element["element_id"],
            element["state"],
            refs,
            element.get("normalized_value"),
            None,
            None,
        )
        checked = guard(old, claim_quote=quote)
        if checked.state != old.state:
            changes.append(
                dict(
                    element_id=old.element_id,
                    before=old.state,
                    after=checked.state,
                    reason=checked.reason_code,
                )
            )
            element.update(state=checked.state, reason_code=checked.reason_code)
    if new_category or changes:
        # Existing three responses cannot become fresh category/checklist votes.
        updated["reason"] = "V3_DEC92_CATEGORY_RETAG_REQUIRED"
        result.update(
            evidence_grade=None,
            label=None,
            grade_range=None,
            reason=updated["reason"],
            grade_basis="retag_required",
        )
        updated["decision"] = None
    updated["provisional_grade"] = hold_projection(updated, profile="v3-dec92-v1")
    return updated, dict(
        category_candidate=candidate,
        category_reason=reason if candidate else None,
        retag_required=bool(new_category or changes),
        vetoes=changes,
        fresh_responses=0,
        new_present_votes=0,
    )


def state(item):
    decision = item.get("decision") or {}
    result = item.get("provisional_grade") or {}
    confirmed = bool(decision.get("evidence_grade"))
    return dict(
        confirmed=int(confirmed),
        scope_confirmed=int(confirmed and decision.get("confirmation_basis") == "analysis_scope"),
        provisional=int(not confirmed and bool(result.get("evidence_grade"))),
        held=int(not confirmed and not result.get("evidence_grade")),
        present=sum(e["state"] == "present" for e in result.get("elements", [])),
    )


def summarize(rows):
    summary: dict[str, Any] = dict(n=len(rows), measured=0, unmeasured=0, retag_required=0)
    for side in ("before", "after"):
        summary[side] = dict(confirmed=0, scope_confirmed=0, provisional=0, held=0, present=0)
    for row in rows:
        if row.get("unmeasured"):
            summary["unmeasured"] += 1
            continue
        summary["measured"] += 1
        summary["retag_required"] += row["projection"]["retag_required"]
        for side in ("before", "after"):
            for k, v in row[side].items():
                summary[side][k] += v
    summary.update(
        new_present=0,
        new_false_present=0,
        new_false_confirmed=0,
        fresh_responses=0,
        live_model_accuracy_claim=False,
    )
    for side in ("before", "after"):
        summary[side]["false_confirmed"] = 0 if summary[side]["confirmed"] == 0 else None
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    def deny(*a, **kw):
        raise AssertionError("V3_REPLAY_NETWORK_FORBIDDEN")

    for owner, name in (
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
        (socket, "create_connection"),
    ):
        setattr(owner, name, deny)
    sources = {}

    def read(path):
        sources[str(path)] = sha256(path.read_bytes()).hexdigest()
        return json.loads(path.read_text())

    def record(item, quote, **identity):
        updated, projection = project(item, quote)
        return dict(
            **identity,
            quote=quote,
            before=state(item),
            after=state(updated),
            projection=projection,
            before_grade=item["provisional_grade"].get("evidence_grade"),
            after_grade=updated["provisional_grade"].get("evidence_grade"),
        )

    audit = read(args.lab / "review/R17/audit.json")
    r17 = []
    element_scores: dict[str, Counter] = {s: Counter() for s in ("before", "after")}
    goals = []
    for report in audit["reports"]:
        path = args.lab / "quality/QT2/stored" / report["run_id"] / "job-artifacts.json"
        artifacts = read(path)
        tagged = next(r["value"] for r in artifacts if "claims" in r.get("value", {}))
        by_id = {r["claim_id"]: r for r in tagged["claims"]}
        for row in report["rows"]:
            if row.get("record_type") != "claim":
                continue
            item = by_id[row["claim_id"]]
            entry = record(
                item,
                row["claim_quote"],
                case=report["case"],
                claim_id=row["claim_id"],
                sample_index=row["sample_index"],
            )
            if row["gold_track"] == "goal":
                goals.append(entry | dict(original_notes=row["notes"], gold_track="goal"))
            vetoes = {c["element_id"] for c in entry["projection"]["vetoes"]}
            for e in row["elements"]:
                if not e["scored"]:
                    continue
                for side in ("before", "after"):
                    value = (
                        "unknown"
                        if side == "after" and e["element_id"] in vetoes
                        else e["server_state"]
                    )
                    score = element_scores[side]
                    score["n"] += 1
                    score["gold_present"] += e["gold_state"] == "present"
                    score["present_recalled"] += value == e["gold_state"] == "present"
                    score["false_present"] += value == "present" and e["gold_state"] != "present"
            r17.append(entry)

    dl4 = read(args.lab / "perf/I3/dl4-reference/DL4-gold.json")
    assert len(dl4["golds"]) == 131
    retained: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for company in ("naver", "kia"):
        claims = read(args.lab / f"perf/PB5/{company}-claim_snapshot_sha256.json")
        tags = read(args.lab / f"perf/PB5/{company}-tag_snapshot_sha256.json")
        by_id = {r["claim_id"]: r for r in tags["claims"]}
        for c in claims["discovery"]["claims"]:
            retained.setdefault((company, norm(c["quote"])), []).append(by_id[c["claim_id"]])
    dl4_rows = []
    for gold in dl4["golds"]:
        matches = retained.get((gold["company"], norm(gold["quote"])), [])
        if len(matches) == 1:
            dl4_rows.append(record(matches[0], gold["quote"], id=gold["id"]))
        else:
            dl4_rows.append(
                dict(
                    id=gold["id"],
                    quote=gold["quote"],
                    unmeasured="no_unique_exact_saved_tagging;retag_required",
                )
            )

    holdout = []
    for company in ("SK하이닉스", "현대자동차-p22", "현대자동차-p41", "POSCO홀딩스", "삼성전자"):
        path = args.lab / "fix/A/paid-dec26/states" / company
        sources[str(path / "state.sqlite3")] = sha256(
            (path / "state.sqlite3").read_bytes()
        ).hexdigest()
        claims = checkpoint(path, "extract")["discovery"]["claims"]
        tags = checkpoint(path, "tag")
        by_id = {r["claim_id"]: r for r in tags["claims"]}
        for c in claims:
            if c["claim_id"] in by_id:
                holdout.append(
                    record(
                        by_id[c["claim_id"]], c["quote"], company=company, claim_id=c["claim_id"]
                    )
                )
            else:
                holdout.append(
                    dict(
                        company=company, claim_id=c["claim_id"], unmeasured="saved_tagging_missing"
                    )
                )

    gold = read(args.lab / "gold-v2/v1-reingested.json")
    excluded = [
        r["ID"]
        for r in gold["sheets"]["3_요소검수"]
        if r["ID"] in ("R108-POSCO-C022-M4", "R108-POSCO-C022-M5") and r["검수 상태"] is None
    ]
    assert len(excluded) == 2
    summaries = {
        name: summarize(rows)
        for name, rows in [("R17", r17), ("DL4", dl4_rows), ("holdout", holdout)]
    }
    summaries["R17"]["element_scores"] = element_scores
    summaries["R17"]["per_report"] = {
        name: summarize([r for r in r17 if r["case"] == name])
        for name in sorted({r["case"] for r in r17})
    }
    for name in ("DL4", "holdout"):
        summaries[name]["false_present"] = None
        summaries[name]["false_present_status"] = "not_scored_without_matched_element_adjudication"
    for name, rows in (("R17", r17), ("DL4", dl4_rows), ("holdout", holdout)):
        (args.output / f"{name}-rows.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
        )
    result = dict(
        schema="v3-retained-output-impact-v1",
        summaries=summaries,
        baseline_code_sha="6c6241f",
        baseline_policy_sha256=canonical_hash(FINALS_I24_POLICY),
        opt_in_policy_sha256=canonical_hash(V3_POLICY),
        input_sha256=sources,
        R17_goal_review=goals,
        excluded_unanswered_gold=excluded,
        AP05="naver-221-P2 conflict retained; not scored",
        limits=[
            "Retained E14/PB5/A outputs, not fresh v24/v25 model runs.",
            "Category changes are retag_required, never three fabricated new responses.",
            "DL4 denominator is all 131 atoms; unmatched tagging is explicitly unmeasured.",
            "No scope-search completion, independent human review or publication inferred.",
            "R17 element gold is the original single-reviewer audit, not new independent gold.",
        ],
        paid_api_calls=0,
        source_mutations=0,
    )
    assert all(sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in sources.items())
    (args.output / "measurement.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(summaries, ensure_ascii=False))


if __name__ == "__main__":
    main()
