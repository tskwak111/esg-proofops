"""Free, read-only receipts for the INT2 ordering diagnosis."""

import json
import sqlite3
from collections import Counter
from hashlib import sha256
from pathlib import Path

ROOT = Path("/path/to/ESG_ProofOps")
OUT = ROOT / "outputs/agent-results/R108-redesign/lab/quality/QI1"


def audit(label):
    state = ROOT / "outputs/agent-results/R108-redesign/lab/integ/INT2/states" / label
    with sqlite3.connect(state.joinpath("state.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        checkpoints = {
            data["schema"]: data
            for (value,) in db.execute(
                "select value from job_records where kind='artifact' "
                "and record_id like '%/checkpoint'"
            )
            if (data := json.loads(value))
        }
    extract = checkpoints["local_extract_checkpoint_v2"]
    final = {r["claim_id"]: r for r in checkpoints["local_tag_checkpoint_v1"]["claims"]}
    rows = []
    for page in extract["page_tag_pipeline"]:
        for record in page["claims"]:
            cid = record["claim_id"]
            catalogs = []
            for run in record["tag_runs"]:
                request_id = run["request"]["request_id"]
                paths = list((state / "tagging-receipts").rglob(request_id + "/request.json"))
                assert len(paths) == 1
                request = json.loads(paths[0].read_text())
                wire = json.loads(request["wire_user_json"])
                catalog = wire.get("evidence_catalog", {})
                catalogs.append(
                    dict(
                        request_id=request_id,
                        request_sha256=sha256(paths[0].read_bytes()).hexdigest(),
                        catalog_size=len(catalog),
                    )
                )
            elements = record["provisional_grade"]["elements"]
            rows.append(
                dict(
                    claim_id=cid,
                    page=page["page"],
                    source_quality_at_tagging=record["source_status"]["status"],
                    source_quality_after_attestation=final[cid]["source_status"]["status"],
                    catalogs=catalogs,
                    all_unknown=bool(elements) and all(e["state"] == "unknown" for e in elements),
                    empty_elements=not elements,
                    tag_runs_reused=record["tag_runs"] == final[cid]["tag_runs"],
                    frozen_packet_reused=record.get("frozen_packet")
                    == final[cid].get("frozen_packet"),
                )
            )
    assert len(rows) == len(final)
    assert all(r["tag_runs_reused"] and r["frozen_packet_reused"] for r in rows)
    return dict(
        label=label,
        rows=rows,
        summary=dict(
            claims=len(rows),
            tagging_source_quality=dict(Counter(r["source_quality_at_tagging"] for r in rows)),
            verified_later=sum(r["source_quality_after_attestation"] == "verified" for r in rows),
            all_unknown=sum(r["all_unknown"] for r in rows),
            empty_elements=sum(r["empty_elements"] for r in rows),
            catalog_sizes=dict(Counter(c["catalog_size"] for r in rows for c in r["catalogs"])),
        ),
    )


if __name__ == "__main__":
    result = [audit(label) for label in ("samsung", "kepco-recovery")]
    (OUT / "int2-ordering-receipt.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps([r["summary"] | {"label": r["label"]} for r in result], indent=2))
