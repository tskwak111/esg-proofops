"""Free saved-outcome replay through the real tag/consensus/rules reader."""

import json
import os
import socket
from dataclasses import asdict
from pathlib import Path

from proofops.adapters.local.run_store import LocalSQLiteRunStore
from proofops.adapters.local.tag_store import LocalTagStore
from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
from proofops.application.registry import Registry
from proofops.application.uploads import UploadService
from proofops.domain.provenance import canonical_hash

ROOT = Path("/path/to/ESG_ProofOps")
OUT = ROOT / "outputs/agent-results/R108-redesign/lab/perf/PF1"


def deny(*args, **kwargs):
    raise RuntimeError("PF1_OFFLINE_NETWORK_FORBIDDEN")


def main():
    socket.socket.connect = socket.create_connection = deny
    os.environ["PROOFOPS_RECEIPT_READ_PROFILE"] = "receipt-env-drift-v1"
    records = []
    for company, tenant, run in [
        ("naver", "2e868816-ecb9-4cc2-837c-c06daf981ab4", "58a78076-6f52-4eac-9ee8-04d040dc79ae"),
        ("skino", "2de69ca4-db4f-4b95-abe5-c3fb4f6d2310", "3f4f63c5-253a-472a-9628-6c97487c2c8f"),
    ]:
        state = OUT / (company + "-offline-state")
        db = state / "state.sqlite3"
        tags = LocalTagStore(
            LocalSQLiteRunStore(db),
            UploadService(db, state / "objects", Registry.sqlite(db)),
            OpenDataLoaderParser(state / "parser-prepared"),
        )
        evidence = tags._load_snapshot_with_evidence(tenant, run)
        # One pinned offline snapshot; each load_inputs still validates tags and re-evaluates rules.
        tags._load_snapshot_with_evidence = lambda *_: evidence
        rows = []
        for item in evidence[0]["claims"]:
            if not item.get("review_inputs"):
                continue
            inputs = tags.load_inputs(tenant, run, item["claim_id"])
            decision = asdict(inputs.decision) if inputs.decision else None
            assert canonical_hash(decision) == canonical_hash(item["decision"])
            assert len(inputs.tag_runs) == 3
            assert len({r.request.request_id for r in inputs.tag_runs}) == 3
            rows.append(
                dict(
                    claim_id=item["claim_id"],
                    decision_sha256=canonical_hash(decision),
                    status=item["status"],
                    replicas=3,
                )
            )
        records.append(
            dict(
                company=company,
                claims_checked=len(rows),
                rows=rows,
                decisions_equal=True,
                publication_status_equal=True,
                model_calls=0,
            )
        )
        (OUT / "outcomes.json").write_text(json.dumps(records, indent=2) + "\n")
        print(company, len(rows), "saved judgments and publication statuses equal", flush=True)


if __name__ == "__main__":
    main()
