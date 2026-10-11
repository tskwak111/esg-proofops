"""K1 read-only I1 saved-response replay. No new votes or production revisions."""

import argparse
import io
import json
import socket
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

import pdfplumber
from proofops.application.analysis_profile import FINALS_I1_POLICY, K1_POLICY, policy_for
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.tagging.k1_semantics import POLICY as K1_SEMANTICS
from proofops.application.tagging.quality import hold_projection
from proofops.application.tagging.semantic_admission import POLICY as W8_POLICY
from proofops.application.tagging.unattended import provisional_result
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.rules.engine import RuleContext
from proofops_agent.upstage_extraction import UpstageClaimExtractor

from evaluation.pa9_source_gate import fixture
from evaluation.pt1_replay import decode_runs
from evaluation.w7_sentence_replay import NoTransport


def read(path):
    return json.loads(path.read_text())


def norm(text):
    return "".join(text.split())


def replay(item, pack, graph, policy):
    if not item.get("frozen_packet") or not item.get("tag_runs"):
        return item["provisional_grade"]
    data = item["frozen_packet"]
    packet = freeze_packet({k: v for k, v in data.items() if k != "packet_sha256"})
    assert packet.packet_sha256 == data["packet_sha256"]
    result = provisional_result(
        decode_runs(item["tag_runs"]),
        packet,
        pack,
        RuleContext(
            pack.tenant_id, data["document_version_id"], data["claim_id"], packet.packet_sha256
        ),
        range_profile=True,
        profile="hf1-v1",
        semantic_policy=policy,
        original=graph,
    )
    return hold_projection(item | dict(provisional_grade=result), profile="hf1-v1")


def view(result):
    return {
        k: result.get(k)
        for k in (
            "evidence_grade",
            "display",
            "display_type",
            "reason",
            "grade_range",
            "semantic_hash",
            "semantic_policy_sha256",
            "gap_ids",
        )
    } | dict(states={e["element_id"]: e["state"] for e in result.get("elements", [])})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    def deny(*a, **kw):
        raise AssertionError("K1_REPLAY_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    started = monotonic()
    lab = args.root / "outputs/agent-results/R108-redesign/lab"
    review_path = lab / "review/R1/cases.json"
    review = read(review_path)
    inputs = {str(review_path): sha256(review_path.read_bytes()).hexdigest()}
    rows, preserved, literal_checks, boundaries = [], [], [], []
    for name in ("naver", "kia"):
        state = lab / "perf/I1/stage-B-compact" / name
        graph, source, discovery, snapshot, _ = fixture(state)
        assert snapshot["analysis_profile_policy"] == FINALS_I1_POLICY
        assert (
            policy_for(
                "finals-unattended-v2", pinned_hash=snapshot["analysis_profile_policy_sha256"]
            )
            == FINALS_I1_POLICY
        )
        pack = RulePackSnapshot(**snapshot["rulepack"])
        tag = read(state / "tag-checkpoint.json")
        by_id = {c["claim_id"]: c for c in tag["claims"]}
        claims = {c.claim_id: c for c in discovery.claims}
        for path in [
            state / "state.sqlite3",
            state / "settings.json",
            state / "tag-checkpoint.json",
            state / "extract-checkpoint.json",
            *list((state / "parser-prepared").rglob("*.json")),
            *list((state / "objects/original").rglob("*.pdf")),
        ]:
            inputs[str(path)] = sha256(path.read_bytes()).hexdigest()
        with pdfplumber.open(io.BytesIO(source)) as pdf:
            for case in [c for c in review["cases"] if c["case_id"].startswith(name.upper())]:
                item = by_id[case["claim_id"]]
                old, new = [replay(item, pack, graph, p) for p in (W8_POLICY, K1_SEMANTICS)]
                assert canonical_hash(old) == canonical_hash(item["provisional_grade"]), (
                    case["case_id"],
                    "historical replay",
                )
                assert canonical_hash(old) == canonical_hash(case["provisional_grade"]), (
                    case["case_id"],
                    "R1 baseline",
                )
                before, after = view(old), view(new)
                for e in case["elements"]:
                    if e["state"] == "present" and e["review"] == "원문 직접 지지":
                        assert after["states"][e["element_id"]] == "present", case["case_id"]
                        preserved.append([case["case_id"], e["element_id"]])
                for e in new.get("elements", []):
                    if e["state"] != "present":
                        continue
                    for ref in e["evidence_refs"]:
                        cropped = pdf.pages[ref["page_num"] - 1].crop(tuple(ref["bbox"]))
                        chars = "".join(c["text"] for c in cropped.chars)
                        layout = cropped.extract_text(x_tolerance=2, y_tolerance=3) or ""
                        located = norm(ref["quote"]) in norm(chars) or norm(ref["quote"]) in norm(
                            layout
                        )
                        literal_checks.append(
                            dict(
                                case_id=case["case_id"],
                                element_id=e["element_id"],
                                ref=ref,
                                literal_at_native_bbox=located,
                            )
                        )
                rows.append(
                    dict(
                        case_id=case["case_id"],
                        claim_id=case["claim_id"],
                        quote=case["atomic_quote"],
                        source_refs=[asdict(r) for r in claims[case["claim_id"]].source_refs],
                        before=before,
                        after=after,
                        changed_elements=[
                            eid
                            for eid, s in before["states"].items()
                            if after["states"].get(eid) != s
                        ],
                        replay="saved_replicas_reprocessed"
                        if item.get("tag_runs")
                        else "saved_hold_preserved",
                    )
                )
        if name == "naver":
            case = next(c for c in review["cases"] if c["case_id"] == "NAVER-21")
            claim = claims[case["claim_id"]]
            sid = claim.source_refs[0].source_id
            block = next(b for b in graph.blocks if b.source_id == sid)
            path = next(
                p
                for p in (state / "extraction-receipts").glob("*/packet.json")
                if read(p).get("untrusted_document_data", {}).get("source_id") == sid
                and (p.parent / "raw_response.json").exists()
            )
            packet = read(path)
            raw_path = path.parent / "raw_response.json"
            payload = json.loads(read(raw_path)["content"])
            for p in (path, raw_path):
                inputs[str(p)] = sha256(p.read_bytes()).hexdigest()
            settings = read(state / "settings.json")
            flags = {
                k: v for k, v in settings.items() if k.startswith("extraction_") and type(v) is bool
            }
            flags["display_text_profile"] = settings.get("display_text_policy", {}).get("profile")
            with TemporaryDirectory() as temp:
                old = UpstageClaimExtractor(NoTransport(), Path(temp) / "old", **flags)
                new = UpstageClaimExtractor(
                    NoTransport(), Path(temp) / "new", **flags, extraction_k1=True
                )
                assert asdict(old.profile) == snapshot["extraction_profile"]
                assert old.profile.rule_sha256 != new.profile.rule_sha256
                original, _ = old._resolve_payload(
                    payload,
                    block.normalized_text,
                    sid,
                    packet=packet,
                    context_graph=graph,
                )
                changed, diagnostics = new._resolve_payload(
                    payload,
                    block.normalized_text,
                    sid,
                    packet=packet,
                    context_graph=graph,
                )
                receipt = next(r for r in discovery.receipts if r.source_id == sid)
                assert canonical_hash([asdict(s) for s in original]) == canonical_hash(
                    json.loads(receipt.raw_response_json)["spans"]
                )
                assert len(original) == len(changed)
                for b, a in zip(original, changed, strict=True):
                    if a != b:
                        assert b.quote == case["atomic_quote"]
                        assert a.quote == "• 태양광: 2025년 전력 발전량 21.3 MWh"
                        assert block.normalized_text[a.char_start : a.char_end] == a.quote
                        boundaries.append(
                            dict(
                                case_id="NAVER-21",
                                before=asdict(b),
                                after=asdict(a),
                                diagnostics=diagnostics["k1_boundaries"],
                                source_verification=(
                                    "unverified; fresh attestation and tagging required"
                                ),
                                facility_binding="undetermined; no title/value reassignment",
                                copied_old_grade=False,
                            )
                        )
                    else:
                        assert a == b
                assert sum("PUE" in s.quote for s in changed) == 2
                assert any("111.6MWh" in s.quote for s in changed)
    by_case = {r["case_id"]: r for r in rows}
    assert len(rows) == 51 and len(boundaries) == 1
    targets = [f"KIA-{i:02}" for i in (17, 20, 22, 23, 25, 26, 27)]
    for cid in targets:
        r = by_case[cid]["after"]
        assert r["evidence_grade"] is None and r["grade_range"] is None
        assert r["states"]["P1"] == "present" and r["gap_ids"] == ["GAP-001"]
    for cid in ("NAVER-18", "NAVER-19"):
        r = by_case[cid]["after"]
        assert r["states"]["M1"] == "unknown" and r["evidence_grade"] is None
        assert r["reason"] == "K1_PUE_PERFORMANCE_RETAG_REQUIRED" and r["grade_range"] is None
    assert by_case["NAVER-18"]["source_refs"] != by_case["NAVER-19"]["source_refs"]
    assert by_case["KIA-03"]["after"]["states"]["M1"] == "present"
    assert by_case["KIA-03"]["after"]["states"]["M2"] == "unknown"
    assert by_case["KIA-03"]["after"]["evidence_grade"] == "E1"
    false_verified = sum(not c["literal_at_native_bbox"] for c in literal_checks)
    assert false_verified == 0, [c for c in literal_checks if not c["literal_at_native_bbox"]]
    assert all(sha256(Path(p).read_bytes()).hexdigest() == h for p, h in inputs.items())
    record = dict(
        schema="k1-saved-response-replay-v1",
        cases=rows,
        extraction_boundaries=boundaries,
        baseline_policy_sha256=canonical_hash(FINALS_I1_POLICY),
        analysis_policy=K1_POLICY,
        analysis_policy_sha256=canonical_hash(K1_POLICY),
        input_sha256=inputs,
        inputs_unchanged=True,
        baseline_mismatches=[],
        supported_elements_preserved=preserved,
        normal_case_losses=0,
        false_verified=false_verified,
        native_literal_checks=literal_checks,
        changed_grade_cases=[
            r["case_id"]
            for r in rows
            if r["before"]["evidence_grade"] != r["after"]["evidence_grade"]
        ],
        provider_calls=0,
        paid_usd="0",
        production_revisions_written=0,
        seconds=monotonic() - started,
        limitations=[
            "Saved response replay is not fresh inference or human gold.",
            "Changed NAVER-21 quote requires fresh source proof and tagging.",
            "PUE historical management votes require new performance tagging; no P1 minted.",
            "K1 policy is hash-selected; default I1 remains unchanged until adoption.",
        ],
    )
    (args.output / "comparison.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                k: record[k]
                for k in (
                    "analysis_policy_sha256",
                    "changed_grade_cases",
                    "normal_case_losses",
                    "false_verified",
                    "provider_calls",
                    "paid_usd",
                    "seconds",
                )
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
