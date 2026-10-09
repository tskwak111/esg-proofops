"""One authorized recovery of INT1's receipted async job; no billable dispatch."""

import json
import sqlite3
from decimal import Decimal
from pathlib import Path

from proofops.adapters.local.upstage_parse import UpstageParseProbe
from proofops.domain.provenance import canonical_hash

from scripts.finals_demo import FinalsBudget

ROOT = Path("/Users/ss020/Dev/ESG_ProofOps")
OUT = ROOT / "outputs/agent-results/R108-redesign/lab/integ/INT2"
REQUEST = "ecd3ba44-ee9b-4614-b31a-7ed6f29559df"
PROVIDER = "e2bbed91-05fc-40b6-bbc7-6139f0d8d1ac"


def main():
    body = json.loads((OUT / "enhanced-request-reconstruction.json").read_text())
    batches = json.loads((OUT / "recovered-enhanced-batches.json").read_text())
    status = json.loads((OUT / (PROVIDER + "-status.json")).read_text())
    listing = json.loads((OUT / "provider-request-list.json").read_text())
    matches = [
        r
        for r in listing["requests"]
        if "2026-10-09T15:46:09" <= r["requested_at"] <= "2026-10-09T15:46:11Z"
    ]
    assert [r["id"] for r in matches] == [PROVIDER]
    assert status["id"] == PROVIDER and status["status"] == "completed"
    assert status["total_pages"] == status["completed_pages"] == body["pages"] == 3
    assert body["mode"] == "enhanced"
    assert len(batches) == 1 and batches[0]["model"] == "document-parse-260128"
    assert batches[0]["usage"] == {"pages": 3, "enhanced": [1, 2, 3]}
    signature = canonical_hash(body)
    assert signature == "d021f80ea1f2694fb43b9796ce6fe063959426203da09ff0fc036c79be9cdf5e"
    ledger = ROOT / ".local/upstage/budget.sqlite3"
    with sqlite3.connect(ledger) as db:
        old = db.execute(
            "SELECT signature,committed,receipt FROM probe_calls WHERE request_id=?", (REQUEST,)
        ).fetchone()
    assert old[0] == signature
    receipt = dict(
        model=body["model"],
        provider_model=status["model"],
        pages=3,
        mode="enhanced",
        usage=batches[0]["usage"],
        cost_with_vat_reserve_usd=".099",
        request_sha256=signature,
        response_sha256=canonical_hash(batches),
        provider_request_id=PROVIDER,
        settlement_origin="recovered_provider_result",
        recovery_evidence="INT2 request reconstruction, unique timed job and raw batches",
    )
    audit = dict(
        request_id=REQUEST,
        provider_request_id=PROVIDER,
        old_reservation_usd="1.00",
        recovered_settled_usd=".099",
        released_difference_usd=".901",
        mapping_evidence="exact original 11/18/21 PDF request signature; unique job "
        "accepted within INT1 call interval; completed enhanced usage3",
        historical_error="POST accepted; immediate poll failed before job completion. "
        "Exact original HTTP/status code unavailable (INT1 did not archive it).",
        prior_logs_immutable=True,
        common_guard_uncertain_bound_retained_usd=".099",
    )
    (OUT / "ledger-reconciliation.json").write_text(json.dumps(audit, indent=2) + "\n")
    if old[2] is None:
        assert Decimal(old[1]) == 1
        archive = ledger.parent / "parse-responses" / (canonical_hash(REQUEST) + "-async.json")
        with archive.open("x") as stream:
            json.dump(batches, stream, ensure_ascii=False)
        archive.chmod(0o400)
        UpstageParseProbe("reconciliation-no-network", ledger)._settle(REQUEST, ".099", receipt)
    else:
        assert Decimal(old[1]) == Decimal(".099") and json.loads(old[2]) == receipt
    budget = FinalsBudget(
        ROOT / "outputs/agent-results/R108-redesign/lab/sprint3/E2E/r108-spend.json",
        {"upstage": ledger},
        OUT / "reconciliation-events.jsonl",
        task="integ-INT1",
    )
    with budget.transaction() as (data, entry):
        corrections = entry.setdefault("reconciliations", [])
        if not any(c["request_id"] == REQUEST for c in corrections):
            entry["delta_usd"] = str(Decimal(entry["delta_usd"]) - Decimal(".901"))
            data["cumulative_usd"] = str(Decimal(data["cumulative_usd"]) - Decimal(".901"))
            corrections.append(audit)
    print(json.dumps(audit))


if __name__ == "__main__":
    main()
