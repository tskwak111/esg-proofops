"""O1b cache-only replay of the frozen O1 sample; no provider or ledger writes.

Run with --baseline <O1 evidence> --ledger <trusted SQLite> --output <new folder>.
The old evaluator is loaded privately to retain its exact cohort/metric logic.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import upstage_ocr_profile_v2 as profile
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.adapters.local.upstage_ocr_mapping_v2 import MAPPING_POLICY, map_words
from proofops.adapters.local.upstage_ocr_page import PageOCRStore, parse_response, render_page
from proofops.application.ingest.graph_fusion import fuse_candidates
from proofops.domain.provenance import canonical_hash

from evaluation.upstage_ocr_page import stored_inputs, write


class OfflineStore(PageOCRStore):
    def __init__(self, ledger):
        self.ledger = Path(ledger)
        if not self.ledger.is_file():
            raise ValueError("OCR_SHARED_LEDGER_REQUIRED")
        self.transport = self.forbidden

    @staticmethod
    def forbidden(*args, **kwargs):
        raise ValueError("O1B_PAID_CALL_FORBIDDEN")

    fetch = forbidden
    _reserve = forbidden

    def usage(self):
        with sqlite3.connect(self.ledger.resolve().as_uri() + "?mode=ro", uri=True) as db:
            rows = db.execute("SELECT committed,state FROM ocr_calls").fetchall()
        return dict(
            calls=len(rows),
            unsettled_calls=sum(s != "collected" for _, s in rows),
            committed_or_reserved_usd=str(sum((Decimal(c) for c, _ in rows), Decimal(0))),
        )


def attest(reader, graph, source, refs, tenant, collections):
    modules, seen = reader._modules(graph, source, tenant, collections)
    native = reader._finish(
        modules["source_verification"].attest_native_sources(
            graph, source, tenant_id=tenant, geometry_mode="glyph"
        ),
        seen,
        native=True,
    )
    reader.replay_native_sources(native, graph, source, tenant_id=tenant)
    modules, seen = reader._modules(graph, source, tenant, collections)
    claim = reader._finish(
        modules["glyph_alignment_verification"].attest_claim_spans(
            graph, source, refs, tenant_id=tenant
        ),
        seen,
    )
    reader.recompute_claim_receipt(claim, graph, source, refs, tenant_id=tenant)
    return native, claim


def negatives(baseline, output, store):
    from tests.acceptance.test_parsing import candidate

    cases = json.loads((baseline / "negatives-sample.json").read_text())["cases"]
    results = []
    for case in cases:
        source = Path(case["source_path"]).read_bytes()
        image = render_page(source, 1)
        assert image["manifest"] == case["manifest"]
        collection = json.loads(
            (baseline / "negatives" / (case["name"] + "-collection.json")).read_text()
        )
        store.validate(collection, image, tenant_id=case["tenant_id"])
        batch = replace(
            candidate(
                case["name"], [("P", "paragraph", case["expected_raw"], (70, 710, 400, 745), ())]
            ),
            source_sha256=sha256(source).hexdigest(),
        )
        graph = fuse_candidates((batch,), tenant_id=case["tenant_id"])
        reader = profile.Reader(store, run_id="o1b-negative-" + case["name"])
        native, claim = attest(
            reader, graph, source, (graph.blocks[0].source_ref(),), case["tenant_id"], [collection]
        )
        result = dict(
            name=case["name"],
            source_sha256=graph.source_sha256,
            native_status=native["records"][0]["status"],
            native_reason=native["records"][0]["reason"],
            claim_status=claim["records"][0]["status"],
            claim_reason=claim["records"][0]["reason"],
        )
        write(output / "negatives" / (case["name"] + "-native.json"), native)
        write(output / "negatives" / (case["name"] + "-claim.json"), claim)
        results.append(result)
    return results


def geometry_negatives(baseline, store):
    """Synthetic ownership queries over real cached polygons, never new OCR."""
    sample = json.loads((baseline / "sample.json").read_text())
    case = next(p for p in sample["pages"] if p["company"] == "kia" and p["page"] == 2)
    collection = json.loads((baseline / "collections/kia-2.json").read_text())
    image = render_page(Path(case["source_path"]).read_bytes(), case["page"])
    store.validate(collection, image, tenant_id=case["tenant_id"])
    parsed = parse_response(bytes.fromhex(collection["response_hex"]))
    # O1 reviewed columns, in original PDF points. These deliberately malformed
    # queries are negatives, not per-company parameters in the reader policy.
    queries = [
        (
            "neighbor_block_contamination",
            [42, 209, 280, 313],
            [[40, 207, 282, 315]],
            "ocr_block_overlap_ambiguous",
        ),
        ("multi_column_crossing", [42, 209, 800, 462], [], "ocr_column_order_ambiguous"),
    ]
    results = []
    for name, box, peers, reason in queries:
        result = map_words(parsed, image["manifest"], box, competing_boxes=peers)
        results.append(
            dict(
                name=name,
                scope="synthetic_geometry_on_cached_provider_response",
                request_id=collection["request_id"],
                result=result,
                expected_reason=reason,
                passed=result.get("reason") == reason,
                false_verified=result["status"] == "read",
            )
        )
    return results


def classify(baseline, output):
    sample = json.loads((baseline / "sample.json").read_text())
    mismatches, promotions = [], []
    reasons = Counter()
    for company in sorted({p["company"] for p in sample["pages"]}):
        page = next(p for p in sample["pages"] if p["company"] == company)
        _, graph, _, old_native, old_claim = stored_inputs(Path(page["state"]))
        blocks = {b.source_id: b for b in graph.blocks}
        for kind, old in (("native", old_native[1]), ("claim", old_claim[1])):
            new = json.loads(
                (output / "attestations" / (company + "-" + kind + ".json")).read_text()
            )

            def key(r):
                return r["source_id"] if kind == "native" else canonical_hash(r["ref"])

            previous = {key(r): r for r in old["records"]}
            for r in new["records"]:
                sid = r.get("source_id") or r["ref"]["source_id"]
                if blocks[sid].kind != "paragraph":
                    continue
                prior = previous[key(r)]
                rendering = r.get(
                    "rendered", new.get("readings", {}).get(sid, {}).get("rendered", {})
                )
                # Every unresolved verdict and every changed verdict is classified,
                # including holds before rendering (native/quote/geometry guards).
                if r["status"] == "verified" and prior["status"] == "verified":
                    continue
                reason = (
                    rendering.get("reason")
                    if rendering.get("status") == "unresolved"
                    else r.get("reason")
                )
                reason = reason or "verified_exact_source_under_existing_guards"
                reasons[reason] += 1
                entry = dict(
                    company=company,
                    kind=kind,
                    page=blocks[sid].page_num,
                    source_id=sid,
                    bbox=blocks[sid].candidates[blocks[sid].winner].bbox,
                    old_status=prior["status"],
                    new_status=r["status"],
                    classification=reason,
                    native=blocks[sid].candidates[blocks[sid].winner].source.raw_text,
                    rendered=rendering,
                    record=r,
                )
                mismatches.append(entry)
                if prior["status"] != "verified" and r["status"] == "verified":
                    promotions.append(entry)
    write(output / "classified-mismatches.json", mismatches)
    write(output / "promotions.json", promotions)
    return dict(
        mismatch_records=len(mismatches),
        classifications=dict(reasons),
        unclassified_mismatches=sum(not m["classification"] for m in mismatches),
        promotions_pending_image_review=len(promotions),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.resolve() == args.baseline.resolve() or (args.output / "metrics.json").exists():
        raise ValueError("O1B_OUTPUT_MUST_BE_NEW")
    store = OfflineStore(args.ledger)
    before_hash = sha256(args.ledger.read_bytes()).hexdigest()
    before = store.usage()
    evaluator = _exec_private(
        Path(__file__).parent, "upstage_ocr_page.py", "evaluation._o1b_private"
    )
    evaluator.Reader = profile.Reader
    evaluator.PageOCRStore = type("OfflineFactory", (), {"from_env": staticmethod(lambda: store)})
    evaluator.write = lambda path, value: write(
        args.output / path.relative_to(args.baseline), value
    )
    write(
        args.output / "policy.json",
        dict(
            claim=profile.claim_source_policy(),
            native=profile.native_policy(),
            mapping=MAPPING_POLICY,
        ),
    )
    evaluator.evaluate(args.baseline)
    negative_results = negatives(args.baseline, args.output, store)
    write(args.output / "negatives-results.json", negative_results)
    geometry_results = geometry_negatives(args.baseline, store)
    write(args.output / "geometry-negatives.json", geometry_results)
    summary = json.loads((args.output / "metrics.json").read_text())
    summary.update(classify(args.baseline, args.output))
    summary.update(
        paid_calls=store.usage()["calls"] - before["calls"],
        new_cost_usd="0",
        ledger_unchanged=before_hash == sha256(args.ledger.read_bytes()).hexdigest(),
        false_verified=sum(
            r["native_status"] == "verified" or r["claim_status"] == "verified"
            for r in negative_results
        )
        + sum(r["false_verified"] for r in geometry_results),
        additional_geometry_negatives_passed=all(r["passed"] for r in geometry_results),
    )
    assert summary["paid_calls"] == 0 and summary["ledger_unchanged"] and store.usage() == before
    write(args.output / "metrics.json", summary)
    print(json.dumps(summary, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
