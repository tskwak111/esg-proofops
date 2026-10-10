"""Offline regression against retained, integrity-checked model annotations.

This is explicitly a re-evaluation, not a new extraction or an expert gold test.
Never changes the original run or makes a paid API call.
"""

import argparse
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from proofops.adapters.parsing.openai_vision import OpenAIVisionProbe

from evaluation import local_analysis_pipeline as pipeline
from evaluation import report_decisions as rd


def recheck(run_id, pdf):
    if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
        raise ValueError("INVALID_RUN")
    if (
        sha256(pdf).hexdigest() != pipeline.SOURCE_HASH
        or not (pipeline.ROOT / pipeline.SNAPSHOT / "manifest.json").is_file()
    ):
        raise ValueError("RECHECK_VERIFIED_SNAPSHOT_REQUIRED")
    folder = pipeline.ROOT / ".local/web-analysis" / run_id
    old = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    records = json.loads((folder / "tagging-records.json").read_text(encoding="utf-8"))
    source, parsed, batches, audit_records, _ = pipeline.load_source(pdf, old["pages"])
    blocks = pipeline.catalog(batches, list(map(int, parsed)))
    by_key = {b["key"]: b for b in blocks}
    audit = {r["key"]: r["reason"] for r in audit_records}
    pack = rd.load_pack(source.tenant_id)
    if old["runtime"]["source_sha256"] != source.sha256 or not pack:
        raise ValueError("RECHECK_SOURCE_OR_POLICY_MISMATCH")
    claims = deepcopy(old["claims"])
    for i, claim in enumerate(claims):
        replicas = records[i // 6]
        for replica in replicas:
            OpenAIVisionProbe.validate_result(replica)
        origin = by_key[claim["parser_source"]["key"]]
        old_index = claim["block"]
        claim.update(
            block=origin["index"],
            tagging_complete=len(replicas) == 3,
            replicate_hashes=[rd.digest(r) for r in replicas],
            model=old["runtime"]["model"],
            parser_source=origin,
            evidence_packet_sha256=rd.digest(records[i // 6]),
        )
        claim["crosscheck"] = pipeline.verify(claim["quote"], origin, parsed, batches, audit)
        claim["source_verified"] = claim["crosscheck"]["native_verified"]
        for element in claim["elements"]:
            citation = element.get("citation")
            if not citation:
                continue
            # The old merged candidate must really occur in at least two saved passes.
            votes = 0
            for replica in replicas:
                annotations = [c for c in replica["document"]["claims"] if c["index"] == i]
                if len(annotations) == 1 and any(
                    e["name"] == element["name"]
                    and e["block"] == citation["block"]
                    and e["quote"] == citation["quote"]
                    for e in annotations[0]["elements"]
                ):
                    votes += 1
            if votes < 2:
                element.update(citation=None, source_verified=False)
                continue
            target = by_key[citation["source_key"]]
            element["citation"] = rd.literal_citation(
                dict(block=target["index"], quote=citation["quote"]), blocks
            )
            element["crosscheck"] = pipeline.verify(
                citation["quote"], target, parsed, batches, audit
            )
            element["source_verified"] = element["crosscheck"]["native_verified"]
        rd.decide(claim, source, blocks, pack)
        claim["recheck_original_block"] = old_index
    return dict(
        mode="offline_saved_annotations_recheck",
        original_run=run_id,
        source_sha256=source.sha256,
        expert_gold=False,
        new_api_calls=0,
        claims=claims,
        summary=dict(
            claims=len(claims),
            confirmed_elements=sum(e["state"] == "present" for c in claims for e in c["elements"]),
            grades=sum(bool(c["decision"].get("evidence_grade")) for c in claims),
            ranges=sum(bool(c["decision"].get("grade_range")) for c in claims),
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--run", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pdf = args.pdf.read_bytes()
    results = [recheck(run, pdf) for run in args.run]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps([r["summary"] | {"run": r["original_run"]} for r in results]))


if __name__ == "__main__":
    main()
