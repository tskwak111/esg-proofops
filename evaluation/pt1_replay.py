"""PT1 read-only replay of stored six-company E2E8 receipts; network forbidden."""

import json
import socket
import sqlite3
from collections import Counter
from hashlib import sha256
from pathlib import Path
from time import monotonic

from proofops.adapters.cache.aws import CacheNamespace, CacheRequest
from proofops.application.budget import TokenUsage
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.tagging.service import TagRun
from proofops.application.tagging.unattended import empty_provisional, provisional_result
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.rules.engine import RuleContext
from proofops.domain.values import llm_tags_from_dict

from evaluation.sv1_source_audit import BASE

OUT = Path("/Users/ss020/Dev/ESG_ProofOps/outputs/agent-results/R108-redesign/lab/pipeline/PT1")


def decode_runs(entries):
    return tuple(
        TagRun(
            **(
                e
                | dict(
                    request=CacheRequest(
                        **(
                            e["request"]
                            | dict(namespace=CacheNamespace(**e["request"]["namespace"]))
                        )
                    ),
                    usage=TokenUsage(**e["usage"]) if e["usage"] else None,
                    guarded=llm_tags_from_dict(e["guarded"]) if e["guarded"] else None,
                    errors=tuple(e["errors"]),
                    source_scopes=tuple(map(tuple, e["source_scopes"])),
                    binding_hashes=tuple(map(tuple, e["binding_hashes"])),
                )
            )
        )
        for e in entries
    )


def saved(path):
    funnel = json.loads((path / "funnel.json").read_text())
    pin = funnel["checkpoint_pins"]["tag"]
    with sqlite3.connect((path / "state.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        blob = db.execute(
            "select value from job_records where kind='artifact' and run_id=? and record_id=?",
            (funnel["run_id"], pin["record_id"]),
        ).fetchone()[0]
        assert sha256(blob).hexdigest() == pin["sha256"]
        snapshot = json.loads(
            db.execute(
                "select payload from run_snapshots where run_id=?", (funnel["run_id"],)
            ).fetchone()[0]
        )
    return funnel, json.loads(blob), snapshot


def replay(name, path):
    began = monotonic()
    before = sha256((path / "state.sqlite3").read_bytes()).hexdigest()
    funnel, envelope, snapshot = saved(path)
    rows = []
    for item in envelope["claims"]:
        inputs = item.get("review_inputs")
        if item["tag_runs"] and inputs:
            data = {k: v for k, v in inputs["packet"].items() if k != "packet_sha256"}
            packet = freeze_packet(data)
            assert packet.packet_sha256 == inputs["packet_sha256"]
            assert inputs["rulepack"] == snapshot["rulepack"]
            runs = decode_runs(item["tag_runs"])
            context = RuleContext(**inputs["rule_context"])
            result = provisional_result(
                runs, packet, RulePackSnapshot(**snapshot["rulepack"]), context
            )
        else:
            result = empty_provisional(item.get("reason"))
        rows.append(
            dict(
                claim_id=item["claim_id"],
                source_verified=next(
                    c["source_verification"]["status"] == "verified"
                    for c in funnel["claims"]
                    if c["claim_id"] == item["claim_id"]
                ),
                elements_replayed=bool(item["tag_runs"]),
                provisional_grade=result,
                prior_stop=item.get("reason"),
            )
        )
    assert sha256((path / "state.sqlite3").read_bytes()).hexdigest() == before
    record = dict(
        company=name,
        claims=len(rows),
        tagged_before=sum(r["elements_replayed"] for r in rows),
        source_unverified=sum(not r["source_verified"] for r in rows),
        potential_added_targets=sum(not r["elements_replayed"] for r in rows),
        grades=dict(
            Counter(r["provisional_grade"].get("evidence_grade") or "unavailable" for r in rows)
        ),
        majority_elements=sum(
            e["votes"] == 2 for r in rows for e in r["provisional_grade"]["elements"]
        ),
        seconds=monotonic() - began,
        state_sha256=before,
        tag_checkpoint_sha256=funnel["checkpoint_pins"]["tag"]["sha256"],
        claims_projection=rows,
    )
    (OUT / "replay" / f"{name}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    )
    print(name, record["grades"], round(record["seconds"], 3), flush=True)
    return {k: v for k, v in record.items() if k != "claims_projection"}


def deny(*args, **kwargs):
    raise RuntimeError("PT1_REPLAY_NETWORK_FORBIDDEN")


def main():
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    (OUT / "replay").mkdir(exist_ok=True)
    rows = [
        replay(name, Path(path))
        for name, path in json.loads((BASE / "state-map.json").read_text()).items()
        if name.startswith("control-")
    ]
    (OUT / "replay-summary.json").write_text(
        json.dumps(
            dict(
                companies=rows,
                model_calls=0,
                network="denied",
                scope=(
                    "Existing validated replicas only; stopped claims have no new paid tags; "
                    "downstream effect remains not_run."
                ),
                grade_computation=(
                    "same pure engine; unknown preserved; " "lower bounds explicitly provisional"
                ),
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
