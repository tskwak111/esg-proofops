"""Offline what-if comparison, NEVER a source-verification or text-repair policy.

Usage: uv run python evidence/probe-ocr-punctuation.py STATE_DIRECTORY [...]
Only saved, committed parse receipts are inspected; no OCR/model calls or writes.
"""

import json
import re
import sqlite3
import sys
from collections import Counter
from hashlib import sha256
from pathlib import Path

from proofops.application.evidence.citations import _normalized
from proofops.domain.provenance import canonical_hash


def hypothetical(text):
    text = text.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'}))
    return _normalized(re.sub(r"(?<=[가-힣])[·•](?=[가-힣])", "·", text))


def probe(state):
    database = (Path(state) / "state.sqlite3").resolve()
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        runs = db.execute(
            "SELECT tenant_id,run_id,value FROM job_records WHERE kind='run' AND record_id='META'"
        ).fetchall()
        assert len(runs) == 1
        tenant, run, metadata = runs[0]
        job_id = json.loads(metadata)["parse_job"]["job_id"]

        def row(kind, identifier):
            return db.execute(
                "SELECT value FROM job_records WHERE tenant_id=? AND run_id=? "
                "AND kind=? AND record_id=?",
                (tenant, run, kind, identifier),
            ).fetchone()[0]

        ref = json.loads(row("job", job_id))["artifact_ref"]
        raw = row("artifact", ref["key"])
        assert sha256(raw).hexdigest() == ref["sha256"] and len(raw) == ref["byte_size"]
        receipt = json.loads(raw)["native_paragraph_attestation"]
    assert (
        canonical_hash({k: v for k, v in receipt.items() if k != "artifact_sha256"})
        == receipt["artifact_sha256"]
    )
    counts = Counter()
    changed = []
    for record in receipt["records"]:
        counts["records"] += 1
        counts["original_" + record["status"]] += 1
        rendered = record.get("rendered", {})
        if rendered.get("status") != "read":
            continue
        counts["readable_rendered"] += 1
        native = " ".join(word["text"] for word in record["words"])
        ocr = rendered["text"]
        if _normalized(native) != _normalized(ocr) and hypothetical(native) == hypothetical(ocr):
            counts["hypothetical_matches"] += 1
            changed.append(
                dict(
                    source_id=record["source_id"],
                    original_reason=record["reason"],
                    native=native,
                    ocr=ocr,
                )
            )
    return dict(
        run_id=run,
        source_sha256=receipt["source_sha256"],
        checkpoint_sha256=ref["sha256"],
        receipt_sha256=receipt["artifact_sha256"],
        counts=dict(counts),
        hypothetical_changes=changed,
    )


if __name__ == "__main__":
    assert hypothetical("‘계획’ 분석·검토") == hypothetical("'계획' 분석•검토")
    for left, right in [
        ("1.5", "15"),
        ("-5%", "5%"),
        ("2025", "2026"),
        ("미달성", "달성"),
        ("a·b", "a•b"),
        ("3′", "3'"),
    ]:
        assert hypothetical(left) != hypothetical(right)
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    print(
        json.dumps(
            dict(
                schema="ocr_punctuation_what_if_v1",
                source_quality_changed=False,
                additional_model_calls=0,
                limitations=[
                    "Counterfactual comparison of retained receipts only; not an approved "
                    "normalization policy, PDF replay, semantic gold or proof of visibility."
                ],
                runs=[probe(p) for p in sys.argv[1:]],
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
