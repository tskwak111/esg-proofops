"""Read-only SC1 admission audit of preserved R17/E14 inputs, plus text guard probes.

Aggregate exports cannot reconstruct missing minority votes or current inventory
responses. Report blocked admission explicitly; never manufacture those inputs.
"""

import argparse
import json
import math
import time
from collections import Counter
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from proofops.application.ingest.graph_fusion import fuse_candidates
from proofops.application.tagging.analysis_scope import InventoryIndex, confirmation_policy
from proofops.application.tagging.element_inventory import (
    POLICY,
    build_inventory,
    selection_from_snapshot,
)
from proofops.domain.provenance import canonical_hash
from pypdf import PdfReader


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def source_audit(root):
    lab = root / "outputs/agent-results/R108-redesign/lab"
    path = lab / "review/R17/audit.json"
    audit = json.loads(path.read_text())
    reports = []
    for report in audit["reports"]:
        result_path = root / report["result_path"]
        source = Path(report["source_pdf"])
        if sha256(result_path.read_bytes()).hexdigest() != report["result_sha256"]:
            raise ValueError("R17 result source changed")
        if sha256(source.read_bytes()).hexdigest() != report["source_sha256"]:
            raise ValueError("R17 PDF source changed")
        result = json.loads(result_path.read_text())
        claims = [r for r in report["rows"] if r["record_type"] == "claim"]
        start = time.monotonic()
        reader = PdfReader(source)
        selected = result["page_map"]
        pages = []
        for page in selected:
            text = reader.pages[page - 1].extract_text() or ""
            pages.append(
                dict(
                    physical_page=page,
                    text_utf8_bytes=len(text.encode()),
                    minimum_chunks=max(
                        1, math.ceil(len(text.encode()) / POLICY["max_chunk_utf8_bytes"])
                    ),
                )
            )
        planning_seconds = time.monotonic() - start
        variants = []
        for threshold in (3, 2, 1):
            counts = Counter()
            candidate_claims, disagreement_claims = set(), set()
            for row in claims:
                for e in row["elements"]:
                    if e["server_state"] != "present" or e.get("votes", 0) < threshold:
                        continue
                    refs = e.get("evidence_refs", [])
                    if refs and all(r.get("verification_state") == "verified" for r in refs):
                        counts["source_verified_present_slots"] += 1
                        if e["element_id"] in {"P1", "M1", "G1", "G2"}:
                            candidate_claims.add(row["claim_id"])
                        if e.get("gold_state") != "present" or e.get("evidence_support") not in {
                            "exact",
                            "partial",
                        }:
                            counts["source_disagreement_slots"] += 1
                            disagreement_claims.add(row["claim_id"])
            variants.append(
                dict(
                    required_present_votes=threshold,
                    policy_sha256=canonical_hash(confirmation_policy(threshold)),
                    sample_claims=len(claims),
                    confirmed_grades=0,
                    over_confirmations=0,
                    admission_blocked=len(claims),
                    threshold_effect_identifiable=False,
                    reasons=[
                        "NO_SAME_RUN_VERIFIED_INVENTORY",
                        "NO_RAW_THREE_REPLICA_RECEIPTS",
                        "NO_VERIFIED_CLAIM_ATTRIBUTE_KEYS",
                    ],
                    aggregate_present_slots_diagnostic=dict(counts),
                    aggregate_lower_fact_candidate_claims=len(candidate_claims),
                    source_disagreement_claims=sorted(disagreement_claims),
                    caveat=(
                        "Diagnostics are not confirmed grades; "
                        "missing minority votes cannot be assumed unknown."
                    ),
                )
            )
        chunks = sum(p["minimum_chunks"] for p in pages)
        reports.append(
            dict(
                case=report["case"],
                run_id=report["run_id"],
                result_sha256=report["result_sha256"],
                source_sha256=report["source_sha256"],
                selected_pages=selected,
                document_total_pages=len(reader.pages),
                sample_claim_ids=[r["claim_id"] for r in claims],
                pages=pages,
                variants=variants,
                cost_latency=dict(
                    source_text_plan_seconds=planning_seconds,
                    actual_model_calls=0,
                    actual_api_cost_usd=0,
                    minimum_inventory_calls=3 * chunks,
                    repeated_scope_calls_for_sample=3 * chunks * len(claims),
                    repeated_scope_calls_for_population=3 * chunks * len(result["claims"]),
                    amortization_factor_for_sample=len(claims),
                    formula=(
                        "3*chunks once versus 3*chunks*claims; "
                        "native text lower bound, not production token billing"
                    ),
                    provider_latency_seconds=None,
                ),
            )
        )
    return dict(
        schema="sc1-r17-admission-audit-v1",
        audit_sha256=sha256(path.read_bytes()).hexdigest(),
        method=(
            "preserved aggregate exports and original selected-page text; "
            "no invented replica votes"
        ),
        no_accuracy_claim=True,
        reports=reports,
    )


def counterexample_audit(root):
    """Force three omission replies on the actual saved adverse text: cues must hold."""
    from tests.unit.test_c4_assembly import prepared

    lab = root / "outputs/agent-results/R108-redesign/lab/review"
    r10 = json.loads((lab / "R10/counterexamples.json").read_text())
    r11 = json.loads((lab / "R11/counterexamples.json").read_text())
    inputs, _ = prepared()
    original = inputs["graph"]
    batch = original.candidates[0]
    template = batch.blocks[0]
    cases = []
    for group, rows in (("R10", r10["cases"]), ("R11", r11["new_cases"])):
        for row in rows:
            if group == "R10":
                texts = [(1, row["main"])]
                if row.get("extra"):
                    texts.append((1, row["extra"]))
            else:
                texts = [
                    (b["source"]["physical_page"], b["source"]["raw_text"])
                    for b in row["graph"]["candidates"][0]["blocks"]
                ]
            blocks = tuple(
                replace(
                    template,
                    source=replace(
                        template.source,
                        source_native_id=str(i),
                        raw_text=text,
                        char_end=len(text),
                        physical_page=page,
                        native_bbox=(10, 10 + i * 40, 500, 40 + i * 40),
                    ),
                )
                for i, (page, text) in enumerate(texts)
            )
            graph = fuse_candidates((replace(batch, blocks=blocks),), tenant_id=batch.tenant_id)
            graph = replace(
                graph, blocks=tuple(replace(b, quality="verified") for b in graph.blocks)
            )
            count = max(p for p, _ in texts)
            scope = selection_from_snapshot(
                dict(
                    document=dict(
                        version_id=graph.document_version_id,
                        sha256=graph.source_sha256,
                        page_count=count,
                    ),
                    selected_pages=list(range(1, count + 1)),
                ),
                graph,
                batch.parser_run_id,
            )

            def omission_reply(request):
                return {
                    **{
                        k: request[k]
                        for k in (
                            "request_id",
                            "request_signature",
                            "packet_sha256",
                            "replicate_id",
                            "model_sha256",
                            "prompt_sha256",
                        )
                    },
                    "provider_response_id": "sim-" + request["request_id"],
                    "synthetic": True,
                    "status": "succeeded",
                    "raw_response_json": json.dumps(
                        dict(
                            complete=True,
                            records=[],
                            packet_sha256=request["packet_sha256"],
                            replicate_id=request["replicate_id"],
                        )
                    ),
                }

            inventory = build_inventory(graph, scope, model_sha256="a" * 64, invoke=omission_reply)
            index = InventoryIndex(inventory, graph)
            variants = []
            for n in (3, 2, 1):
                states = {
                    eid: index.state(eid, ("당사", "환경경영시스템", "국내 전 사업장", "2025"), n)[
                        0
                    ]
                    for eid in ("M2", "M3")
                }
                # Both higher elements must be absent to certify the seeded M1 floor.
                possible = all(s == "absent_in_scope" for s in states.values())
                variants.append(
                    dict(
                        required_present_votes=n,
                        confirmed_grades=int(possible),
                        over_confirmations=int(possible),
                        upper_element_states=states,
                    )
                )
            if any(v["confirmed_grades"] for v in variants):
                raise AssertionError("Adverse certification text bypassed inventory recall guard")
            cases.append(
                dict(
                    review=group,
                    case_id=row["case_id"],
                    variants=variants,
                    method=(
                        "three synthetic omission replies over retained source text; "
                        "no live model/publication"
                    ),
                    inventory_sha256=inventory["inventory_sha256"],
                )
            )
    return dict(schema="sc1-counterexample-inventory-guard-v1", cases=cases)


def r16_probes():
    """R16 classes replayed against SC1: saved reply, source, partial and conflict."""
    from copy import deepcopy
    from tempfile import TemporaryDirectory

    from proofops.application.tagging.element_inventory import assemble_inventory, plan_inventory

    from tests.integration.test_sc1_scope import analyze, case

    cases = []
    with TemporaryDirectory(prefix="sc1-r16-") as directory:
        inputs, base_runs, baseline = case(Path(directory))
        for name in (
            "third_replica_unavailable",
            "unverified_present",
            "binding_disagreement",
            "unanimous_conflict",
            "saved_old_response",
            "wrong_wire_request",
            "wrong_document_version",
            "unreadable_page",
        ):
            runs, inv = list(base_runs), deepcopy(baseline)
            if name == "third_replica_unavailable":
                runs[2] = replace(
                    runs[2], guarded=None, status="model_failed", errors=("MODEL_UNAVAILABLE",)
                )
            elif name == "unverified_present":
                runs = [
                    replace(
                        r,
                        guarded=replace(
                            r.guarded,
                            elements=tuple(
                                replace(
                                    e,
                                    evidence_refs=tuple(
                                        replace(ref, verification_state="candidate")
                                        for ref in e.evidence_refs
                                    ),
                                )
                                for e in r.guarded.elements
                            ),
                        ),
                    )
                    for r in runs
                ]
            elif name == "binding_disagreement":
                runs[2] = replace(
                    runs[2],
                    binding_hashes=tuple((eid, "b" * 64) for eid, _ in runs[2].binding_hashes),
                )
            elif name == "unanimous_conflict":
                runs = [
                    replace(
                        r,
                        guarded=replace(
                            r.guarded,
                            elements=tuple(
                                replace(
                                    e, state="conflict", evidence_refs=(), normalized_value=None
                                )
                                if e.element_id == "P1"
                                else e
                                for e in r.guarded.elements
                            ),
                        ),
                    )
                    for r in runs
                ]
            elif name == "wrong_document_version":
                inv["selection"]["document_version_id"] = "00000000-0000-0000-0000-000000000099"
            else:
                responses = inv["raw_responses"]
                for reply in responses.values():
                    if name == "saved_old_response":
                        reply.update(
                            synthetic=False,
                            saved_response_origin=dict(replay=True, fresh_model_call=False),
                        )
                    elif name == "wrong_wire_request":
                        reply["request_signature"] = "b" * 64
                    else:
                        reply["status"] = "failed"
                inv = assemble_inventory(
                    plan_inventory(inputs["original"], inv["selection"]),
                    responses,
                    graph=inputs["original"],
                    model_sha256=inv["model_sha256"],
                )
            variants = []
            for threshold in (3, 2, 1):
                try:
                    result = analyze(inputs, tuple(runs), inv, threshold)
                    confirmed = bool(result["sc1_confirmation"])
                    reasons = result["reasons"]
                except ValueError as exc:
                    confirmed, reasons = False, [str(exc)]
                assert not confirmed, name
                variants.append(
                    dict(
                        required_present_votes=threshold,
                        confirmed_grades=0,
                        over_confirmations=0,
                        reasons=reasons,
                    )
                )
            cases.append(dict(case_id=name, variants=variants))
    return dict(
        schema="sc1-r16-boundary-probes-v1",
        cases=cases,
        method=(
            "SC1 regression classes from R16; synthetic sources/replies, "
            "not a rerun of the old deployed code"
        ),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    _write(args.output / "r17-threshold-comparison.json", source_audit(args.source_root))
    _write(args.output / "r10-r11-counterexamples.json", counterexample_audit(args.source_root))
    _write(args.output / "r16-counterexamples.json", r16_probes())


if __name__ == "__main__":
    main()
