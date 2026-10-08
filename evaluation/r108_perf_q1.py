"""Q1 saved-result loss audit and counterfactual postprocessor replay; no paid calls.

Detection causes are an ordered source-text attribution, not human annotation:
same-page literal coverage >=90% (matching runs >=8 chars) is the explicit proxy
for parsing/selection coverage. Exact official matcher and its one-to-one policy
are unchanged. Source-validation holds are overlays, not raw-detection misses.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import socket
import sqlite3
import tempfile
from collections import Counter, defaultdict
from dataclasses import asdict
from difflib import SequenceMatcher
from pathlib import Path

from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import LINEWRAP_JOIN_POLICY, UpstageClaimExtractor

ROOT = Path("/Users/ss020/Dev/ESG_ProofOps")
LAB = ROOT / "outputs/agent-results/R108-redesign/lab"
E2E = LAB / "sprint5/E2E3"
F8 = ROOT / ".local/r108-finals.INGDai/live"
UNEXPOSED = {"sk", "hyundai", "posco"}
INPUT_HASHES = {}


def read(path):
    raw = path.read_bytes()
    INPUT_HASHES[str(path)] = hashlib.sha256(raw).hexdigest()
    return json.loads(raw)


def records(path):
    INPUT_HASHES[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        result = defaultdict(dict)
        for kind, rid, value in db.execute("SELECT kind,record_id,value FROM job_records"):
            result[kind][rid] = json.loads(value)
        return result


def load_matcher():
    path = LAB / "sprint4/SC/score_r108.py"
    INPUT_HASHES[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location("r108_matcher", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def coverage(quote, texts, matcher):
    quote = matcher.norm(quote)
    covered = set()
    for text in texts:
        text = matcher.norm(text)
        if quote and quote in text:
            return 1.0
        for a, _, size in SequenceMatcher(None, quote, text, autojunk=False).get_matching_blocks():
            if size >= 8:
                covered.update(range(a, a + size))
    return len(covered) / len(quote) if quote else 0.0


def bucket(rows, key="cause"):
    groups = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    result = {}
    for cause, values in sorted(groups.items()):
        examples, seen = [], set()
        for row in values:
            if row["claim_id"] not in seen:
                examples.append(row)
                seen.add(row["claim_id"])
            if len(examples) == 3:
                break
        result[cause] = {"count": len(values), "examples": examples}
    return result


class OfflineProbe:
    model = "openai/gpt-6-luna"
    wire_policy_version = 2

    def complete(self, *args, **kwargs):
        raise AssertionError("NETWORK_FORBIDDEN")


def replay(root, company, gold, matcher, temporary):
    settings = read(root / "settings.json")
    kwargs = {
        name: settings.get(name, False)
        for name in (
            "extraction_year_notation",
            "extraction_context",
            "extraction_table_context",
            "extraction_source_ids",
            "extraction_assertion_prompt",
            "extraction_complete_selection",
            "extraction_content_bounds",
            "extraction_atomic",
        )
    }
    kwargs["position_order"] = "position_context_order" in settings
    if "display_text_policy" in settings:
        kwargs["display_text_profile"] = "glyph-joined-display-v1"
    baseline = UpstageClaimExtractor(OfflineProbe(), temporary / company / "base", **kwargs)
    joined = UpstageClaimExtractor(
        OfflineProbe(), temporary / company / "joined", extraction_linewrap_join=True, **kwargs
    )
    before, after, packets, changes = [], [], [], []
    for path in sorted(root.glob("extraction-receipts/*/result.json")):
        result = read(path)
        packet = read(path.with_name("packet.json"))
        raw = read(path.with_name("raw_response.json"))
        assert result["packet_sha256"] == canonical_hash(packet), path
        assert result["content_sha256"] == canonical_hash(raw["content"]), path
        assert result["request_id"] == path.parent.name, path
        data = packet["untrusted_document_data"]
        payload = json.loads(raw["content"])
        spans, _ = baseline._resolve_payload(
            payload, data["text"], data["source_id"], packet=packet
        )
        assert asdict(baseline.profile) == result["profile"], path
        assert [asdict(s) | {"topic_ids": list(s.topic_ids)} for s in spans] == result["spans"]
        new, _ = joined._resolve_payload(payload, data["text"], data["source_id"], packet=packet)
        packets.append(data)
        for output, selected in ((before, spans), (after, new)):
            output.extend(
                {
                    "company_id": company,
                    "page_num": data["page_num"],
                    "quote": s.quote,
                    "claim_id": f"{company}:{data['source_id']}:{s.char_start}:{s.char_end}",
                }
                for s in selected
            )
        if spans != new:
            changes.append(
                {
                    "source_id": data["source_id"],
                    "page": data["page_num"],
                    "before": [s.quote for s in spans],
                    "after": [s.quote for s in new],
                }
            )
    old = matcher.normalize_run({"claims": before})["claims"]
    new = matcher.normalize_run({"claims": after})["claims"]
    bg, _ = matcher.align(gold, old)
    ag, _ = matcher.align(gold, new)
    return {
        "before": {"matched": len(bg), "claims": len(old), "gold": len(gold)},
        "after": {"matched": len(ag), "claims": len(new), "gold": len(gold)},
        "gained_gold_ids": [gold[i]["claim_id"] for i in sorted(set(ag) - set(bg))],
        "lost_gold_ids": [gold[i]["claim_id"] for i in sorted(set(bg) - set(ag))],
        "changes": changes,
        "counterfactual_rule_sha256": joined.profile.rule_sha256,
        "method": "Old raw sentence-ID responses decoded under new postprocessor in temp dirs; "
        "old pinned receipts checked, never rewritten or served as new-profile cache hits. "
        "Merged sources require new validation/tagging; no downstream outcomes transferred.",
    }, packets


def audit_company(company, gold, matcher, temporary):
    funnel = read(E2E / f"{company}-run/funnel.json")
    root = Path(funnel["state_path"]).parent
    saved = records(root / "state.sqlite3")
    artifacts = list(saved["artifact"].values())
    extraction = next(x for x in artifacts if "discovery" in x)
    tagging = next(x for x in artifacts if "tagging_settings" in x)
    tags = {x["claim_id"]: x for x in tagging["claims"]}
    graph_paths = list(root.rglob("graph.json"))
    assert len(graph_paths) == 1
    graph = read(graph_paths[0])
    run = matcher.normalize_run(funnel)
    # Normalize current immutable tag heads exactly as the supplied matcher does.
    gm, _ = matcher.align(gold, run["claims"])
    score = matcher.score(gold, run, gold_synthetic=True, bootstrap=0, include_slices=False)
    replay_result, packets = replay(root, company, gold, matcher, temporary)
    assert replay_result["before"]["claims"] == len(run["claims"])
    assert replay_result["before"]["matched"] == len(gm)
    parsed = [
        *graph["blocks"],
        *[{"page_num": p["page_num"], "raw_text": p["text"], "kind": p["kind"]} for p in packets],
    ]
    scope_pages = set(extraction["discovery"]["scope"]["selected_pages"])
    misses, elements = [], []
    searches = defaultdict(list)
    for x in saved["element_evidence_search"].values():
        searches[x["claim_id"]].append(x)
    for gi, g in enumerate(gold):
        if gi not in gm:
            same_page = [r for r in run["claims"] if r["_page"] == g["_page"]]
            text_cov = coverage(
                g["_quote"], [b["raw_text"] for b in parsed if b["page_num"] == g["_page"]], matcher
            )
            selected_cov = coverage(g["_quote"], [r["_quote"] for r in same_page], matcher)
            input_cov = coverage(
                g["_quote"], [p["text"] for p in packets if p["page_num"] == g["_page"]], matcher
            )
            direct = max(
                (
                    max(
                        matcher.sim(g["_quote"], r["_quote"]),
                        matcher.sim(g.get("atomic_proposition"), r["_quote"]),
                    )
                    for r in same_page
                ),
                default=0,
            )
            cause = (
                "outside_analysis_pages"
                if g["_page"] not in scope_pages
                else "matcher_unit_difference"
                if direct >= 0.82 or selected_cov >= 0.9
                else "parsing_block_gap"
                if text_cov < 0.9
                else "extraction_model_not_selected"
            )
            misses.append(
                {
                    "claim_id": g["claim_id"],
                    "page": g["_page"],
                    "cause": cause,
                    "quote": g["_quote"],
                    "parsed_coverage": text_cov,
                    "selected_coverage": selected_cov,
                    "requested_coverage": input_cov,
                    "selection_detail": (
                        "candidate_not_requested"
                        if input_cov < 0.9
                        else "partial_or_empty_model_selection"
                    )
                    if cause == "extraction_model_not_selected"
                    else None,
                    "best_official_similarity": direct,
                }
            )
        for eid, expected in g["_elements"].items():
            row = {
                "claim_id": g["claim_id"],
                "element_id": eid,
                "expected_state": expected["_state"],
            }
            if gi not in gm:
                row.update(cause="claim_unmatched_no_tagging_alignment", missing=True)
            else:
                r = run["claims"][gm[gi][0]]
                item = tags[r["claim_id"]]
                pred = r["_elements"].get(eid)
                row["system_claim_id"] = r["claim_id"]
                if pred is None:
                    reason = item["reason"]
                    cause = (
                        "tagging_not_entered"
                        if not item["tag_runs"]
                        else "element_card_not_created"
                    )
                    row.update(
                        cause=cause,
                        missing=True,
                        stop_reason=reason,
                        track=r["_track"],
                        detail="wrong_track_element"
                        if item["tag_runs"]
                        and eid not in item["review_inputs"]["packet"]["allowed_elements"]
                        else reason,
                    )
                elif pred["_state"] == "unknown":
                    ss = [
                        e
                        for search in searches[r["claim_id"]]
                        for e in search["elements"]
                        if e["element_id"] == eid
                    ]
                    not_found = bool(ss) and all(e["evidence_status"] == "not_found" for e in ss)
                    row.update(
                        cause="search_not_found" if not_found else "unknown_retained",
                        missing=False,
                        system_state="unknown",
                        search_statuses=sorted({e["evidence_status"] for e in ss}),
                        search_reasons=sorted({e.get("reason") or "" for e in ss}),
                    )
                else:
                    row.update(
                        cause="observed_nonunknown", missing=False, system_state=pred["_state"]
                    )
            elements.append(row)
    return {
        "score": {
            k: v
            for k, v in score["metrics"].items()
            if k in ("claim_detection", "element_status", "evidence_location")
        },
        "detection_misses": misses,
        "element_rows": elements,
        "replay": replay_result,
        "stage_holds": dict(Counter(x["reason"] for x in tagging["claims"])),
    }, tagging


def compact(value):
    if isinstance(value, list) and value and isinstance(value[0], dict) and "quote" in value[0]:
        return [
            {k: x.get(k) for k in ("source_id", "char_start", "char_end", "quote")} for x in value
        ]
    return value


def consensus_audit(tagging):
    fields, unresolved, claims = [], [], []
    for item in tagging["claims"]:
        if item["reason"] != "CONSENSUS_UNRESOLVED":
            continue
        inputs = item["review_inputs"]
        consensus = inputs["consensus"]
        runs = item["tag_runs"]
        for section in ("fields", "dimensions"):
            for name, field in item["preliminary_agreement"][section].items():
                if field["state"] != "agreed":
                    fields.append(
                        {
                            "claim_id": item["claim_id"],
                            "field": "axis:" + name,
                            "cause": field["state"],
                            "values": field["replicate_values"],
                        }
                    )
        guarded = [r["guarded"] for r in runs if r.get("guarded")]
        for eid in inputs["packet"]["allowed_elements"]:
            votes = [
                next((e for e in r["elements"] if e["element_id"] == eid), None) for r in guarded
            ]
            if len(votes) != 3 or any(v is None for v in votes):
                unresolved.append(
                    {
                        "claim_id": item["claim_id"],
                        "element_id": eid,
                        "cause": "replica_unavailable",
                    }
                )
                continue
            for name in ("state", "normalized_value", "evidence_refs", "reason_code"):
                values = [v[name] for v in votes]
                if len({json.dumps(v, sort_keys=True) for v in values}) <= 1:
                    continue
                cause = (
                    "null_vs_value"
                    if any(v is None for v in values)
                    else "empty_vs_citation"
                    if name == "evidence_refs" and any(not v for v in values)
                    else "citation_range_difference"
                    if name == "evidence_refs"
                    else "normalization_only"
                    if name == "normalized_value"
                    and len({" ".join(str(v).split()) for v in values}) == 1
                    else "state_difference"
                    if name == "state"
                    else "value_difference"
                )
                fields.append(
                    {
                        "claim_id": item["claim_id"],
                        "element_id": eid,
                        "field": name,
                        "cause": cause,
                        "replicate_ids": [1, 2, 3],
                        "values": [compact(v) for v in values],
                        "consensus_blocker": name in ("state", "normalized_value"),
                    }
                )
            if all(v["state"] == "unknown" for v in votes):
                raw_states = []
                for run in runs:
                    raw = json.loads(run["raw_response_json"]) if run["raw_response_json"] else {}
                    raw_states.append(
                        next(
                            (e["state"] for e in raw.get("elements", []) if e["element_id"] == eid),
                            None,
                        )
                    )
                unresolved.append(
                    {
                        "claim_id": item["claim_id"],
                        "element_id": eid,
                        "cause": "unanimous_unknown",
                        "values": [v["state"] for v in votes],
                        "raw_states": raw_states,
                        "origin": "guard_downgrade" if "present" in raw_states else "model_unknown",
                    }
                )
        claims.append(
            {
                "claim_id": item["claim_id"],
                "reasons": consensus["reasons"],
                "agreement": consensus["agreement"],
                "run_errors": [r["errors"] for r in runs],
                "binding_hash_differences": len(
                    {json.dumps(r["binding_hashes"], sort_keys=True) for r in runs}
                )
                > 1,
                "scope_differences": len(
                    {json.dumps(r["source_scopes"], sort_keys=True) for r in runs}
                )
                > 1,
            }
        )
    return {
        "claims": claims,
        "field_differences": fields,
        "by_cause": bucket(fields),
        "by_field": bucket(fields, "field"),
        "unresolved_elements": unresolved,
        "unresolved_by_cause": bucket(unresolved),
        "note": "Citation ranges/reason text are diagnostics, not strict consensus vote keys. "
        "Unanimous unknown also blocks strict confirmation; no majority threshold changed.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=LAB / "perf/Q1-analysis.json")
    args = parser.parse_args()

    def deny(*a, **k):
        raise AssertionError("NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    matcher = load_matcher()
    gold, synthetic = matcher.normalize_gold(read(LAB / "gold-v1/draft.json"))
    assert synthetic
    companies, tagging = {}, {}
    with tempfile.TemporaryDirectory(prefix="r108-q1-offline-") as directory:
        temporary = Path(directory)
        for company in ("sk", "hyundai", "posco", "samsung", "naver", "kia"):
            subset = [g for g in gold if g["_company"] == company]
            companies[company], tagging[company] = audit_company(
                company, subset, matcher, temporary
            )
        f8saved = records(F8 / "state.sqlite3")
        f8tag = next(x for x in f8saved["artifact"].values() if "tagging_settings" in x)
        f8replay, _ = replay(F8, "f8", [], matcher, temporary)
    misses = [r for co in sorted(UNEXPOSED) for r in companies[co]["detection_misses"]]
    elements = [r for co in sorted(UNEXPOSED) for r in companies[co]["element_rows"]]
    missing = [r for r in elements if r["missing"]]
    assert len(misses) == 101 and len(missing) == 778 and len(elements) == 852
    assert (
        sum(companies[c]["score"]["element_status"]["accuracy"]["numerator"] for c in UNEXPOSED)
        == 66
    )
    assert (
        sum(
            companies[c]["score"]["evidence_location"]["page_match"]["numerator"] for c in UNEXPOSED
        )
        == 30
    )
    all_sources_unchanged = all(
        hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in INPUT_HASHES.items()
    )
    assert all_sources_unchanged
    output = {
        "gold_label": "SYNTHETIC provisional AI draft, not independent human accuracy",
        "detection_attribution_policy": __doc__,
        "policy": LINEWRAP_JOIN_POLICY,
        "companies": companies,
        "detection_causes": bucket(misses),
        "detection_zero_causes": {
            "outside_analysis_pages": {"count": 0, "examples": []},
            "source_validation_rejection": {
                "count": 0,
                "examples": [],
                "note": "Official detection includes extracted claims even with a source hold.",
            },
        },
        "selection_subcauses": bucket(
            [r for r in misses if r["cause"] == "extraction_model_not_selected"], "selection_detail"
        ),
        "missing_element_causes": bucket(missing),
        "missing_tagging_stops": bucket(
            [r for r in missing if r["cause"] == "tagging_not_entered"], "stop_reason"
        ),
        "unknown_nonmissing_causes": bucket(
            [r for r in elements if r["cause"] in ("search_not_found", "unknown_retained")]
        ),
        "consensus": {co: consensus_audit(t) for co, t in tagging.items()},
        "f8": {
            "stage_holds": dict(Counter(x["reason"] for x in f8tag["claims"])),
            "consensus": consensus_audit(f8tag),
            "replay": f8replay,
        },
        "paid_calls": 0,
        "cost_usd": "0.00",
        "source_files_unchanged": all_sources_unchanged,
        "input_sha256": INPUT_HASHES,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "detection": {k: v["count"] for k, v in output["detection_causes"].items()},
                "missing_elements": {
                    k: v["count"] for k, v in output["missing_element_causes"].items()
                },
                "replay": {
                    co: {k: x["replay"][k] for k in ("before", "after")}
                    for co, x in companies.items()
                },
                "f8_replay": {k: f8replay[k] for k in ("before", "after")},
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
