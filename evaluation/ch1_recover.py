"""CH1 opt-in chart recovery CLI, using an existing trusted OCR ledger read-only.

python -m evaluation.ch1_recover --print-policy
python -m evaluation.ch1_recover --source selected.pdf --request scope-layouts.json \
  --ledger budget.sqlite3 --policy-sha256 HASH --output new-receipt.json

For a newly authorized collection, callers inject the existing bounded
PageOCRStore into ch1_charts.extract. This CLI never dispatches paid calls.
"""

import argparse
import json
import sqlite3
from pathlib import Path

from proofops.adapters.local.ch1_charts import extract, policy, replay
from proofops.adapters.local.upstage_ocr_page import PageOCRStore, reader_policy
from proofops.domain.provenance import canonical_hash


class ReadOnlyOCRStore(PageOCRStore):
    def __init__(self, ledger):
        self.ledger = Path(ledger)
        if not self.ledger.is_file():
            raise ValueError("OCR_SHARED_LEDGER_REQUIRED")

    def fetch(self, image, *, tenant_id, run_id):
        key = canonical_hash(dict(manifest=image["manifest"], policy=reader_policy()))
        with sqlite3.connect(self.ledger.resolve().as_uri() + "?mode=ro", uri=True) as db:
            row = db.execute(
                "SELECT collection FROM ocr_calls WHERE tenant=? AND cache_key=? "
                "AND state='collected' ORDER BY request_id LIMIT 1",
                (tenant_id, key),
            ).fetchone()
        if row is None:
            raise ValueError("OCR_REPLAY_PAGE_MISSING")
        return self.validate(json.loads(row[0]), image, tenant_id=tenant_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-policy", action="store_true")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--policy-sha256")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args()
    if args.print_policy:
        print(json.dumps(dict(policy=policy(), sha256=canonical_hash(policy())), indent=2))
        return
    if not all((args.source, args.request, args.ledger, args.output, args.policy_sha256)):
        parser.error("source, request, ledger, policy-sha256 and output are required")
    request = json.loads(args.request.read_text())
    store = ReadOnlyOCRStore(args.ledger)
    source = args.source.read_bytes()
    if args.replay:
        if args.policy_sha256 != canonical_hash(policy()):
            raise ValueError("CH1_POLICY_PIN_MISMATCH")
        receipt = json.loads(args.replay.read_text())
        # Recreate proposals as well as label proofs from the saved OCR bytes.
        result = extract(
            source,
            request["scope"],
            request["layouts"],
            store=store,
            policy_sha256=args.policy_sha256,
            saved_pages=receipt["page_reads"],
        )
        replay(receipt, source, result["request"], store=store)
    else:
        result = extract(
            source,
            request["scope"],
            request["layouts"],
            store=store,
            policy_sha256=args.policy_sha256,
        )
    # Existing revisions must never be overwritten, including during replay.
    with args.output.open("x") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.write("\n")
    points = [p for r in result["regions"] for p in r["observations"]]
    print(
        json.dumps(
            dict(
                artifact_sha256=result["artifact_sha256"],
                observations=len(points),
                labels_verified=sum(p["status"] == "verified" for p in points),
                scoring_eligible=0,
                real_provider_calls=0,
            )
        )
    )


if __name__ == "__main__":
    main()
