"""Operator CLI for the separate hosted volume. Never prints credentials except a new invite."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import time
from contextlib import ExitStack
from pathlib import Path

from proofops_api.hosted_store import HostedError, HostedSettings, HostedStore, digest, micros, usd


def reconcile(store, receipt, evidence: Path, *, apply=False):
    """Operator-attested export matching; no provider query or automatic guessed cost."""
    if (
        not isinstance(receipt, dict)
        or not receipt.get("operator")
        or not 5 <= len(receipt.get("reason", "")) <= 1000
        or digest(evidence.read_bytes()) != receipt.get("provider_evidence_sha256")
    ):
        raise ValueError("RECONCILIATION_EVIDENCE_REQUIRED")
    calls = receipt.get("calls", [])
    if not calls or len({c["call_id"] for c in calls}) != len(calls):
        raise ValueError("RECONCILIATION_CALLS_INVALID")
    with ExitStack() as stack, store.transaction() as db:
        run = db.execute("SELECT * FROM runs WHERE run_id=?", (receipt["run_id"],)).fetchone()
        if run is None or run["status"] not in {"accounting_pending", "failed", "cancelled"}:
            raise HostedError("RECONCILIATION_RUN_UNAVAILABLE")
        directory = store.document_dir(run["tenant_id"], run["document_id"])
        store._document(db, run["tenant_id"], run["document_id"])
        lock = stack.enter_context((directory / "analysis.lock").open("a+b"))
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        recorded = db.execute(
            "SELECT * FROM deletion.costs WHERE run_id=?",
            (receipt["run_id"],),
        ).fetchall()
        if {c["call_id"] for c in calls} != {r["call_id"] for r in recorded}:
            raise ValueError("RECONCILIATION_CALL_SET_MISMATCH")
        matched = {c["call_id"]: c for c in calls}
        amounts = []
        for row in recorded:
            call = matched[row["call_id"]]
            if any(call.get(k) != row[k] for k in ("request_id", "provider", "input_sha256")):
                raise ValueError("RECONCILIATION_IDENTITY_MISMATCH")
            amount = micros(call["actual_usd"])
            if amount > row["bound"]:
                raise ValueError("RECONCILIATION_BOUND_EXCEEDED")
            if row["status"] == "settled":
                if amount != row["actual"]:
                    raise ValueError("RECONCILIATION_SETTLED_COST_MISMATCH")
            else:
                amounts.append((amount, receipt["run_id"], row["call_id"]))
        if apply:
            # Preserve operator audit before freeing any reservation. A failed
            # transaction can leave an audit file, but never an unrecorded release.
            audit = json.dumps(receipt, sort_keys=True).encode()
            audit_dir = directory / "receipt"
            audit_dir.mkdir(mode=0o700, exist_ok=True)
            audit_path = audit_dir / f"settlement-{digest(audit)}.json"
            if audit_path.exists() and audit_path.read_bytes() != audit:
                raise ValueError("RECONCILIATION_AUDIT_CONFLICT")
            if not audit_path.exists():
                store._write(audit_path, audit)
                audit_path.chmod(0o400)
            db.executemany(
                "UPDATE deletion.costs SET actual=?,status='settled' "
                "WHERE run_id=? AND call_id=?",
                amounts,
            )
            store._settle_envelope(db, receipt["run_id"])
            db.execute(
                "UPDATE runs SET status='failed',fence=fence+1,lease_until=0,"
                "error_code='ACCOUNTING_RECONCILED' WHERE run_id=? AND status='accounting_pending'",
                (receipt["run_id"],),
            )
    return dict(
        applied=apply,
        calls=len(recorded),
        actual_usd=usd(sum(micros(c["actual_usd"]) for c in calls)),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    invite = sub.add_parser("invite")
    invite.add_argument("--tenant", required=True)
    invite.add_argument("--user", required=True)
    invite.add_argument("--role", choices=("viewer", "editor", "reviewer", "admin"), required=True)
    worker = sub.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    sub.add_parser("maintain")
    settlement = sub.add_parser("reconcile")
    settlement.add_argument("--receipt", type=Path, required=True)
    settlement.add_argument("--evidence", type=Path, required=True)
    settlement.add_argument("--apply", action="store_true")
    for command in ("backup", "restore"):
        item = sub.add_parser(command)
        item.add_argument("--path", type=Path, required=True)
    args = parser.parse_args()
    store = HostedStore(HostedSettings.from_env(os.environ))
    if args.command == "invite":
        print(store.invite(args.tenant, args.user, args.role, now=time.time()))
    elif args.command == "maintain":
        store.maintain(now=time.time())
    elif args.command == "reconcile":
        print(
            json.dumps(
                reconcile(
                    store, json.loads(args.receipt.read_text()), args.evidence, apply=args.apply
                )
            )
        )
    elif args.command == "backup":
        store.backup(args.path, now=time.time())
    elif args.command == "restore":
        store.restore(args.path, now=time.time())
    elif args.command == "worker":
        while True:
            store.maintain(now=time.time())
            store.tick(now=time.time())
            if args.once:
                break
            time.sleep(1)


if __name__ == "__main__":
    main()
