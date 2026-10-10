"""O1c free replay; immutable O1 cohort/collections, v2 comparison and negatives.

All provider operations are forbidden by the reused read-only OfflineStore.
The explicitly synthetic bullet probes reuse source-bound native glyph proofs,
not forged provider collections represented as real OCR acquisitions.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import claim_span_typography as typography
from proofops.adapters.local import upstage_ocr_profile_v3 as profile
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.adapters.local.upstage_ocr_mapping_v2 import MAPPING_POLICY
from proofops.domain.provenance import canonical_hash

from evaluation.upstage_ocr_page import write
from evaluation.upstage_ocr_page_v2 import OfflineStore


def comparison(prior, output):
    changed, probes = [], []
    unexplained, numeric_errors = 0, 0
    for path in sorted((output / "attestations").glob("*-claim.json")):
        old = json.loads((prior / "attestations" / path.name).read_text())
        new = json.loads(path.read_text())
        assert len(old["records"]) == len(new["records"])
        for i, (a, b) in enumerate(zip(old["records"], new["records"], strict=True)):
            assert a["ref"] == b["ref"]
            sid = b["ref"]["source_id"]
            reading = new["readings"].get(sid, {})
            if a["status"] != b["status"]:
                proof = new["glyph_alignments"].get(str(i), {})
                explained = (
                    a["status"] == "unresolved"
                    and b["status"] == "verified"
                    and proof.get("reason")
                    == "existing_typography_and_glyph_proven_artificial_space"
                    and bool(proof.get("boundaries"))
                    and bool(proof.get("typography_substitutions"))
                    and proof.get("native_side_folded") is False
                    and proof.get("rendered_read_sha256") == canonical_hash(reading.get("rendered"))
                )
                # Full codepoint parity under exactly the five pinned entries:
                # stronger than checking only the digits extracted by a regex.
                native = " ".join(w["text"] for w in reading.get("words", []))
                actual = reading.get("rendered", {}).get("text", "")
                parity = typography._rendered_folded(native).replace(
                    " ", ""
                ) == typography._rendered_folded(actual).replace(" ", "")
                unexplained += not explained
                numeric_errors += b["status"] == "verified" and not parity
                changed.append(
                    dict(
                        company=path.stem.removesuffix("-claim"),
                        index=i,
                        ref=b["ref"],
                        previous_status=a["status"],
                        new_status=b["status"],
                        explained=explained,
                        numeric_unit_sign_codepoints_preserved=parity,
                        proof=proof,
                        native=native,
                        rendered=actual,
                    )
                )
            # Deliberately corrupt every individual bullet position in each
            # eligible cached read. The result is diagnostic, never persisted
            # as an acquired/validated provider collection or source receipt.
            if reading.get("reason") != "rendered_quote_unresolved":
                continue
            text = reading.get("rendered", {}).get("text", "")
            for offset, char in enumerate(text):
                if char not in {"•", "·", "●"}:
                    continue
                for forged in ("x", "1", "0", "-", "*", "▪"):
                    probe = deepcopy(reading)
                    probe["rendered"]["text"] = text[:offset] + forged + text[offset + 1 :]
                    result = profile.align_reading(
                        native=" ".join(w["text"] for w in reading.get("words", [])),
                        quote=b["ref"]["quote"],
                        reading=probe,
                        page_num=b["ref"]["page_num"],
                        bbox=b["ref"]["bbox"],
                        source_sha256=new["source_sha256"],
                    )
                    probes.append(
                        dict(
                            company=path.stem.removesuffix("-claim"),
                            record_index=i,
                            source_id=sid,
                            rendered_offset=offset,
                            original_char=char,
                            forged_char=forged,
                            result=result,
                            scope="synthetic_rendered_forgery_on_cached_native_proof",
                            false_verified=result["status"] == "verified",
                        )
                    )
    write(output / "v2-changes.json", changed)
    write(output / "bullet-negatives.json", probes)
    return dict(
        v2_changed_records=len(changed),
        unexplained_promotions=unexplained,
        numeric_or_unit_error_promotions=numeric_errors,
        bullet_negative_count=len(probes),
        bullet_false_verified=sum(p["false_verified"] for p in probes),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--prior", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if (
        args.output.resolve() in {args.baseline.resolve(), args.prior.resolve()}
        or (args.output / "metrics.json").exists()
    ):
        raise ValueError("O1C_OUTPUT_MUST_BE_NEW")
    store = OfflineStore(args.ledger)
    before_hash, before = sha256(args.ledger.read_bytes()).hexdigest(), store.usage()
    evaluator = _exec_private(
        Path(__file__).parent, "upstage_ocr_page.py", "evaluation._o1c_private"
    )
    evaluator.Reader = profile.Reader
    evaluator.PageOCRStore = type("OfflineFactory", (), {"from_env": staticmethod(lambda: store)})
    evaluator.write = lambda path, value: write(
        args.output / path.relative_to(args.baseline), value
    )
    reused = _exec_private(
        Path(__file__).parent, "upstage_ocr_page_v2.py", "evaluation._o1c_v2_private"
    )
    reused.profile = profile
    write(
        args.output / "policy.json",
        dict(
            claim=profile.claim_source_policy(),
            native=profile.native_policy(),
            mapping=MAPPING_POLICY,
            normalization=profile.normalization_policy(),
        ),
    )
    evaluator.evaluate(args.baseline)
    negatives = reused.negatives(args.baseline, args.output, store)
    geometry = reused.geometry_negatives(args.baseline, store)
    write(args.output / "negatives-results.json", negatives)
    write(args.output / "geometry-negatives.json", geometry)
    summary = json.loads((args.output / "metrics.json").read_text())
    summary.update(reused.classify(args.baseline, args.output))
    summary.update(comparison(args.prior, args.output))
    summary.update(
        paid_calls=store.usage()["calls"] - before["calls"],
        new_cost_usd="0",
        ledger_unchanged=before_hash == sha256(args.ledger.read_bytes()).hexdigest(),
        false_verified=sum(
            r["native_status"] == "verified" or r["claim_status"] == "verified" for r in negatives
        )
        + sum(r["false_verified"] for r in geometry)
        + summary["bullet_false_verified"],
        additional_geometry_negatives_passed=all(r["passed"] for r in geometry),
    )
    assert summary["paid_calls"] == 0 and summary["ledger_unchanged"] and store.usage() == before
    summary["gate_components"] = dict(
        verified_retention_at_least_95=summary["claim_verified_retention"] >= 0.95,
        false_verified_zero=summary["false_verified"] == 0,
        unexplained_promotions_zero=summary["unexplained_promotions"] == 0,
        numeric_or_unit_promotions_zero=summary["numeric_or_unit_error_promotions"] == 0,
    )
    summary["gate"] = (
        "PASS_CACHE_METRICS_PENDING_IMAGE_REVIEW"
        if all(summary["gate_components"].values())
        else "FAIL_HOLD_LIVE_ROLLOUT"
    )
    summary["additional_negative_scope"] = (
        "6 original provider-collected synthetic PDFs, 2 cached geometry queries, "
        "synthetic bullet forgeries on source-bound cached glyph readings"
    )
    write(args.output / "metrics.json", summary)
    print(json.dumps(summary, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
