"""Offline FXF replay of saved E14 artifacts in the pinned Linux ARM64 image."""

import argparse
import json
import platform
import socket
import sqlite3
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from time import monotonic
from unittest.mock import patch

from proofops.adapters.local import upstage_ocr_profile_fxe as previous
from proofops.adapters.local import upstage_ocr_profile_fxf as current
from proofops.adapters.local.claim_source_verification import discovery_refs
from proofops.adapters.local.upstage_ocr_page import PageOCRStore, reader_policy
from proofops.adapters.local.verified_read_cache import _project_owned_cells
from proofops.domain.provenance import canonical_hash

from evaluation.fxe_source_replay import load_fixture


class SavedStore(PageOCRStore):
    """Read the trusted SQLite snapshot; no reservations, writes or transport."""

    def __init__(self, ledger):
        self.ledger = ledger

    def fetch(self, image, *, tenant_id, run_id, force=False):
        if force:
            raise AssertionError("FXF_FRESH_OCR_FORBIDDEN")
        key = canonical_hash(dict(manifest=image["manifest"], policy=reader_policy()))
        with sqlite3.connect(self.ledger.resolve().as_uri() + "?mode=ro", uri=True) as db:
            row = db.execute(
                "SELECT c.collection FROM ocr_page_cache p JOIN ocr_calls c "
                "ON p.request_id=c.request_id WHERE p.tenant=? AND p.cache_key=? "
                "AND c.state='collected'",
                (tenant_id, key),
            ).fetchone()
        if row is None:
            raise ValueError("OCR_REPLAY_PAGE_MISSING")
        return self.validate(json.loads(row[0]), image, tenant_id=tenant_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--fxe-receipt", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert platform.system() == "Linux" and platform.machine() == "aarch64"
    assert "/work/" in current.__file__
    args.output.mkdir(parents=True, exist_ok=True)

    def write(name, value):
        (args.output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    def deny(*args, **kwargs):
        raise AssertionError("FXF_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    hashes = {
        f.name: sha256(f.read_bytes()).hexdigest() for f in args.input.iterdir() if f.is_file()
    }
    graph, source, discovery, historical = load_fixture(args.input)
    refs = discovery_refs(discovery)
    start = monotonic()
    with patch.object(current.PageOCRStore, "from_env", return_value=SavedStore(args.ledger)):
        baseline = (
            json.loads(args.fxe_receipt.read_bytes())
            if args.fxe_receipt
            else previous.for_run(historical["run_id"]).attest_claim_spans(
                graph, source, refs, tenant_id=graph.tenant_id, previous_receipt=historical
            )
        )
        receipt = current.for_run(historical["run_id"]).attest_claim_spans(
            graph, source, refs, tenant_id=graph.tenant_id, previous_receipt=baseline
        )
        write("receipt.json", receipt)
        print("fresh", Counter(r["status"] for r in receipt["records"]), flush=True)
        cold = current.for_run(historical["run_id"]).recompute_claim_receipt(
            json.loads(json.dumps(receipt)), graph, source, refs, tenant_id=graph.tenant_id
        )
        assert canonical_hash(cold) == canonical_hash(receipt)
    before, _ = _project_owned_cells(
        baseline, graph, discovery, graph.tenant_id, failed_state="candidate"
    )
    after, _ = _project_owned_cells(
        cold, graph, discovery, graph.tenant_id, failed_state="candidate"
    )
    before_ids = {c.claim_id for c in before.claims if c.source_quality == "verified"}
    after_ids = {c.claim_id for c in after.claims if c.source_quality == "verified"}
    assert before_ids <= after_ids
    assert hashes == {
        f.name: sha256(f.read_bytes()).hexdigest() for f in args.input.iterdir() if f.is_file()
    }
    summary = dict(
        platform=platform.platform(),
        architecture=platform.machine(),
        source_sha256=graph.source_sha256,
        claims=len(discovery.claims),
        before_verified=len(before_ids),
        after_verified=len(after_ids),
        lost_verified=0,
        gained_claims=[asdict(c) for c in after.claims if c.claim_id in after_ids - before_ids],
        before_reasons=dict(Counter(r.get("reason") or r["status"] for r in baseline["records"])),
        after_reasons=dict(Counter(r.get("reason") or r["status"] for r in cold["records"])),
        policy=receipt["policy"],
        historical_receipt_recomputed=True,
        cold_replay_equal=True,
        input_hashes=hashes,
        inputs_unchanged=True,
        network="denied",
        paid_replay_calls=0,
        seconds=monotonic() - start,
    )
    write("summary.json", summary)
    print(
        {k: v for k, v in summary.items() if k not in {"gained_claims", "input_hashes", "policy"}},
        flush=True,
    )


if __name__ == "__main__":
    main()
