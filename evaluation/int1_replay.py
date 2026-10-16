"""Network-free range projection over existing MP1/PT1 immutable results."""

import json
import os
from collections import Counter
from hashlib import sha256
from pathlib import Path

ROOT = Path("/path/to/ESG_ProofOps")
OUT = ROOT / "outputs/agent-results/R108-redesign/lab/integ/INT1"


def main():
    import socket

    from proofops.adapters.local.run_store import LocalSQLiteRunStore
    from proofops.adapters.local.tag_store import LocalTagStore
    from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
    from proofops.application.registry import Registry
    from proofops.application.tagging.unattended import ensure_range
    from proofops.application.uploads import UploadService
    from proofops.domain.rulepacks import RulePackSnapshot

    def deny(*args, **kwargs):
        raise AssertionError("INT1_REPLAY_NETWORK_FORBIDDEN")

    socket.socket.connect = deny
    os.environ["PROOFOPS_RECEIPT_READ_PROFILE"] = "receipt-env-drift-v1"
    summaries = []
    for task, company in [
        ("parse/MP1", "samsung"),
        ("parse/MP1", "kepco"),
        ("pipeline/PT1", "skino"),
        ("pipeline/PT1", "steel"),
    ]:
        state = ROOT / f"outputs/agent-results/R108-redesign/lab/{task}/states/{company}"
        pilot = json.loads((state / "pilot.json").read_text())
        database = state / "state.sqlite3"
        original = sha256(database.read_bytes()).hexdigest()
        registry = Registry.sqlite(database)
        uploads = UploadService(database, state / "objects", registry)
        store = LocalSQLiteRunStore(database)
        snapshot = store.snapshot(pilot["tenant_id"], pilot["run_id"])
        tags = LocalTagStore(store, uploads, OpenDataLoaderParser(state / "parser-prepared"))
        envelope = tags.load_snapshot(pilot["tenant_id"], pilot["run_id"])
        pack = RulePackSnapshot(**snapshot["rulepack"])
        results = []
        before = Counter()
        for item in envelope["claims"]:
            result = item["provisional_grade"]
            before["numeric" if result.get("evidence_grade") else "none"] += 1
            after = ensure_range(result, pack)
            assert item["decision"] is None and item["review_inputs"] is None
            results.append(
                dict(
                    claim_id=item["claim_id"],
                    source_status=item["source_status"],
                    provisional_grade=after,
                    reason=item.get("reason"),
                )
            )
        uploads.close()
        registry.close()
        assert sha256(database.read_bytes()).hexdigest() == original, "immutable state changed"
        summary = dict(
            task=task,
            company=company,
            claims=len(results),
            before=dict(before),
            after=dict(Counter(r["provisional_grade"]["display_type"] for r in results)),
            source_confirmation_required=sum(
                r["source_status"]["status"] != "verified" for r in results
            ),
            input_database_sha256=original,
            confirmed_revisions=0,
            paid_calls=0,
            scope="existing result display projection; not new inference or speed evidence",
        )
        (OUT / f"{company}-free-projections.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n"
        )
        summaries.append(summary)
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    (OUT / "replay-summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
