"""Local-synthetic atomic rescores using the existing jobs/audit database.

Additive schema v1: two immutable job-record kinds and version marker. Old
readers ignore them; rollback disables rescore routes/writers and retains every
artifact and decision revision. Initialization is idempotent, never destructive.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from proofops.adapters.local.audit_store import append_audit_transaction, read_audit_head
from proofops.adapters.local.rulepack_store import RulePackNotFound
from proofops.application.rescores import RescoreRejected
from proofops.domain.audit import ChangeSet
from proofops.domain.provenance import canonical_hash

if TYPE_CHECKING:
    import sqlite3
    from typing import Any

    from proofops.adapters.local.run_store import LocalSQLiteRunStore
    from proofops.application.authorization import AuthContext


class LocalSQLiteRescoreStore:
    kind = "local-synthetic-only"

    def __init__(self, run_store: LocalSQLiteRunStore) -> None:
        self.runs, self.jobs = run_store, run_store.jobs
        with self.jobs._transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS rescore_schema (version INTEGER PRIMARY KEY)")
            versions = db.execute("SELECT version FROM rescore_schema").fetchall()
            if versions and versions != [(1,)]:
                raise RescoreRejected("UNSUPPORTED_RESCORE_SCHEMA")
            db.execute("INSERT OR IGNORE INTO rescore_schema VALUES (1)")
            kinds = "'rescore_artifact','rescore_idempotency','decision_revision'"
            for action in ("UPDATE", "DELETE"):
                db.execute(f"""CREATE TRIGGER IF NOT EXISTS rescore_immutable_{action.lower()}
                    BEFORE {action} ON job_records WHEN OLD.kind IN ({kinds})
                    BEGIN SELECT RAISE(ABORT,'rescore artifact is immutable'); END""")
            db.execute(f"""CREATE TRIGGER IF NOT EXISTS rescore_immutable_insert
                BEFORE INSERT ON job_records WHEN NEW.kind IN ({kinds}) AND EXISTS (
                SELECT 1 FROM job_records WHERE tenant_id=NEW.tenant_id AND run_id=NEW.run_id
                AND kind=NEW.kind AND record_id=NEW.record_id)
                BEGIN SELECT RAISE(ABORT,'rescore artifact already exists'); END""")

    def _run(self, db: sqlite3.Connection, tenant: str, run_id: str) -> dict[str, Any]:
        try:
            return self.jobs._get(db, tenant, run_id, "run", "META")
        except KeyError:
            raise RescoreRejected("RESOURCE_NOT_FOUND", 404) from None

    def _replay(
        self, db: sqlite3.Connection, tenant: str, key: str, request_hash: str
    ) -> dict[str, Any] | None:
        row = db.execute(
            """SELECT value FROM job_records WHERE tenant_id=?
            AND kind='rescore_idempotency' AND record_id=?""",
            (tenant, key),
        ).fetchone()
        if row is None:
            return None
        saved = json.loads(row[0])
        if saved["request_hash"] != request_hash:
            raise RescoreRejected("IDEMPOTENCY_CONFLICT")
        return_value: dict[str, Any] | None = saved["response"]
        return return_value

    def _target(
        self, db: sqlite3.Connection, tenant: str, mode: str, pack_id: str
    ) -> dict[str, Any]:
        try:
            pack = self.runs.rulepacks.active_snapshot_transaction(db, tenant, mode, pack_id)
        except RulePackNotFound:
            raise RescoreRejected("RESOURCE_NOT_FOUND", 404) from None
        if pack.status != "active":
            raise RescoreRejected("RULE_PACK_NOT_ACTIVE")
        return asdict(pack)

    def _claims(self, db: sqlite3.Connection, tenant: str, run: str) -> dict[str, Any]:
        rows = db.execute(
            """SELECT record_id,value FROM job_records
            WHERE tenant_id=? AND run_id=? AND kind='claim_head' ORDER BY record_id""",
            (tenant, run),
        ).fetchall()
        claims = {}
        for claim_id, raw in rows:
            head = json.loads(raw)
            try:
                tag = self.jobs._get(
                    db, tenant, run, "tag_revision", f'{claim_id}:{head["tag_revision"]:010}'
                )
                decision = (
                    self.jobs._get(
                        db,
                        tenant,
                        run,
                        "decision_revision",
                        f'{claim_id}:{head["decision_revision"]:010}',
                    )
                    if head["decision_revision"]
                    else None
                )
            except KeyError:
                raise RescoreRejected("RETAG_REQUIRED") from None
            claims[claim_id] = dict(head=head, tag=tag, decision=decision)
        if not claims:
            raise RescoreRejected("RETAG_REQUIRED")
        return claims

    def capture(
        self, actor: AuthContext, run_id: str, body: dict[str, Any], key: str, expected: int | None
    ) -> dict[str, Any]:
        tenant = actor.tenant_id
        replay_key = canonical_hash([actor.user_sub, "rescore", key])
        request_hash = canonical_hash([run_id, body, expected])
        with self.jobs._transaction() as db:
            run = self._run(db, tenant, run_id)
            replay = self._replay(db, tenant, replay_key, request_hash)
            if replay is not None:
                return {"response": replay}
            if expected is not None and run["revision"] != expected:
                raise RescoreRejected("STALE_RUN_REVISION", 412)
            if run["status"] not in {"partial", "completed"}:
                raise RescoreRejected("RUN_NOT_RESCOREABLE")
            snapshot = self.runs._snapshot(db, tenant, run_id)
            return dict(
                run=run,
                run_snapshot=snapshot,
                claims=self._claims(db, tenant, run_id),
                target_pack=self._target(
                    db, tenant, snapshot["rulepack"]["mode"], body["rule_pack_id"]
                ),
                replay_key=replay_key,
                request_hash=request_hash,
            )

    def commit(
        self,
        actor: AuthContext,
        run_id: str,
        body: dict[str, Any],
        captured: dict[str, Any],
        prepared: dict[str, Any],
    ) -> dict[str, Any]:
        tenant = actor.tenant_id
        with self.jobs._transaction() as db:
            run = self._run(db, tenant, run_id)
            replay = self._replay(db, tenant, captured["replay_key"], captured["request_hash"])
            if replay is not None:
                return replay
            if run != captured["run"] or self._claims(db, tenant, run_id) != captured["claims"]:
                raise RescoreRejected("STALE_RUN_REVISION", 412)
            if (
                self._target(db, tenant, captured["target_pack"]["mode"], body["rule_pack_id"])
                != captured["target_pack"]
            ):
                raise RescoreRejected("RULE_PACK_CHANGED", 412)
            if prepared.keys() != captured["claims"].keys():
                raise RescoreRejected("INCOMPLETE_RESCORE")
            rescore_id = str(uuid4())
            response = dict(
                job_id=str(uuid4()),
                resource_id=rescore_id,
                status="ready",
                status_url=f"/v1/runs/{run_id}/rescores/{rescore_id}",
            )
            now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            for claim_id, decision in prepared.items():
                head = captured["claims"][claim_id]["head"]
                if decision["decision_revision"] != head["decision_revision"] + 1:
                    raise RescoreRejected("STALE_DECISION_REVISION", 412)
                self.jobs._put(
                    db,
                    tenant,
                    run_id,
                    "decision_revision",
                    f'{claim_id}:{decision["decision_revision"]:010}',
                    decision,
                    immutable=True,
                )
                self.jobs._put(
                    db,
                    tenant,
                    run_id,
                    "claim_head",
                    claim_id,
                    head | {"decision_revision": decision["decision_revision"]},
                )
            artifact = dict(
                response=response,
                tenant_id=tenant,
                run_id=run_id,
                target_pack=captured["target_pack"],
                original_run_snapshot_sha256=canonical_hash(captured["run_snapshot"]),
                previous_run_revision=run["revision"],
                previous_heads={
                    claim: value["head"] for claim, value in captured["claims"].items()
                },
                decisions=prepared,
                actor_sub=actor.user_sub,
                reason=body["reason"],
                created_at=now,
                execution_profile=self.kind,
            )
            self.jobs._put(
                db, tenant, run_id, "rescore_artifact", rescore_id, artifact, immutable=True
            )
            self.jobs._bump_run(db, run, refresh_claim_counts=True)
            append_audit_transaction(
                connection=db,
                change=ChangeSet(
                    tenant,
                    run_id,
                    actor.user_sub,
                    "run_rescored",
                    rescore_id,
                    canonical_hash(captured["claims"]),
                    canonical_hash(artifact),
                    run["revision"],
                    body["reason"],
                ),
                expected_head=read_audit_head(db, tenant, run_id),
                event_id=str(uuid4()),
                timestamp=now,
            )
            self.jobs._put(
                db,
                tenant,
                run_id,
                "rescore_idempotency",
                captured["replay_key"],
                dict(request_hash=captured["request_hash"], response=response),
                immutable=True,
            )
            return response

    def get(self, tenant_id: str, run_id: str, rescore_id: str) -> dict[str, Any]:
        with self.jobs._transaction() as db:
            self._run(db, tenant_id, run_id)
            try:
                return_value: dict[str, Any] = self.jobs._get(
                    db, tenant_id, run_id, "rescore_artifact", rescore_id
                )["response"]
                return return_value
            except KeyError:
                raise RescoreRejected("RESOURCE_NOT_FOUND", 404) from None
