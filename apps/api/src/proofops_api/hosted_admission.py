"""Hosted admission; every operation uses the facade's shared transaction context."""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from proofops.application.authorization import AuthContext

from proofops_api.hosted_contracts import (
    CONTROL_MESSAGES,
    RUN_LEASE_SECONDS,
    HostedError,
    HostedRow,
    day,
    digest,
    micros,
)

if TYPE_CHECKING:
    from proofops_api.hosted_store import HostedStore


def _scope(
    store: HostedStore, db: sqlite3.Connection, tenant: str, document: str
) -> dict[str, Any]:
    doc = store._document(db, tenant, document)
    if time.time() >= doc["expires"]:
        raise HostedError("SOURCE_EXPIRED")
    paths = sorted(store.document_dir(tenant, document).glob("scope-*.json"))
    if not paths:
        raise HostedError("SCOPE_PLAN_REQUIRED")
    scope: dict[str, Any] = json.loads(paths[-1].read_text())
    from proofops_api.hosted_scope import scope_selection

    if scope["plan"]["source_sha256"] != doc["sha256"]:
        raise HostedError("SOURCE_HASH_MISMATCH")
    if scope["plan"]["status"] != "failed" or scope["selection"] is not None:
        try:
            selection = scope_selection(
                scope["plan"],
                doc["sha256"],
                doc["page_count"],
                reporting_scope=scope.get("reporting_scope"),
                manual_override=scope["plan"]["status"] == "failed",
                manual_selection=(scope["selection"] or {}).get("manual_selection", False),
            )
        except (ValueError, KeyError, TypeError):
            raise HostedError("SCOPE_INTEGRITY_INVALID") from None
        if selection != scope["selection"]:
            raise HostedError("SCOPE_INTEGRITY_INVALID")
    return scope


def get_scope(store: HostedStore, tenant: str, document: str) -> dict[str, Any]:
    with store.transaction(readonly=True) as db:
        return store._scope(db, tenant, document)


def generate_scope(store: HostedStore, auth: AuthContext, document: str) -> dict[str, Any]:
    if not auth.has_capability("editor"):
        raise HostedError("FORBIDDEN", 403)
    with store.transaction() as db:
        doc = dict(store._document(db, auth.tenant_id, document))
        path = store.document_dir(auth.tenant_id, document)
        if list(path.glob("scope-*.json")):
            return store._scope(db, auth.tenant_id, document)
        if time.time() >= doc["expires"]:
            raise HostedError("SOURCE_EXPIRED")
    # Share the cross-process upload slot with validation on the 4GiB host.
    with (store.settings.root / "upload.lock").open("a+b") as lease:
        os.fchmod(lease.fileno(), 0o600)
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise HostedError("UPLOAD_BUSY", 429) from None
        with TemporaryDirectory(prefix="proofops-scope-") as scratch:
            output = Path(scratch) / "plan.json"
            try:
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "proofops_api.hosted_scope",
                        str(store.analysis_source(path, doc)),
                        str(output),
                        doc["sha256"],
                        auth.tenant_id,
                    ],
                    timeout=90,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                plan = json.loads(output.read_text())
            except (subprocess.SubprocessError, OSError, ValueError):
                from evaluation.hosted_scope_plan import failed_plan

                # External API is untyped and outside this work package.
                plan = failed_plan(doc["sha256"], doc["page_count"], "SCOPE_INSPECTION_FAILED")  # type: ignore[no-untyped-call]
    from proofops.domain.provenance import canonical_hash

    from evaluation.reporting_period import (
        detect_reporting_period,
        resolve_reporting_scope,
        validate_detection,
    )
    from proofops_api.hosted_scope import scope_selection

    if "reporting_period_detection" not in plan:
        # External API is untyped and outside this work package.
        plan["reporting_period_detection"] = detect_reporting_period(  # type: ignore[no-untyped-call]
            {}, doc["page_count"], doc["sha256"]
        )

    detection = plan["reporting_period_detection"]
    # External API is untyped and outside this work package.
    validate_detection(detection, doc["sha256"])  # type: ignore[no-untyped-call]
    for item in detection["candidates"] + detection["exceptions"]:
        item["source_ref"].update(
            tenant_id=auth.tenant_id, document_id=document, document_version_id=document
        )
    plan["plan_sha256"] = canonical_hash({k: v for k, v in plan.items() if k != "plan_sha256"})
    defaults = None
    if store.settings.live_config is not None:
        try:
            defaults = json.loads(store.settings.live_config.read_text())
        except (OSError, ValueError):
            pass  # No invented default when operator configuration is unavailable.
    # External API is untyped and outside this work package.
    period = resolve_reporting_scope(plan["reporting_period_detection"], defaults)  # type: ignore[no-untyped-call]
    selection = (
        None
        if plan["status"] == "failed"
        else scope_selection(plan, doc["sha256"], doc["page_count"], reporting_scope=period)
    )
    with store.transaction() as db:
        current = store._document(db, auth.tenant_id, document)
        if time.time() >= current["expires"]:
            raise HostedError("SOURCE_EXPIRED")
        if plan["source_sha256"] != current["sha256"]:
            raise HostedError("SOURCE_HASH_MISMATCH")
        if list(path.glob("scope-*.json")):
            return store._scope(db, auth.tenant_id, document)
        scope = dict(revision=1, plan=plan, selection=selection, reporting_scope=period)
        store._write(path / "scope-000001.json", json.dumps(scope).encode())
        return scope


def edit_scope(
    store: HostedStore,
    auth: AuthContext,
    document: str,
    claims: list[int],
    evidence: list[int],
    if_match: str | None,
    *,
    manual_selection: bool = False,
    reporting_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not auth.has_capability("editor"):
        raise HostedError("FORBIDDEN", 403)
    with store.transaction() as db:
        scope = store._scope(db, auth.tenant_id, document)
        if if_match is None:
            raise HostedError("IF_MATCH_REQUIRED", 428)
        if if_match != f'"{scope["revision"]}"':
            raise HostedError("SCOPE_CONFLICT", 412)
        doc = store._document(db, auth.tenant_id, document)
        plan = scope["plan"] | dict(selected_claim_pages=claims, selected_evidence_pages=evidence)
        from evaluation.reporting_period import validate_period
        from proofops_api.hosted_scope import scope_selection

        period = scope.get("reporting_scope")
        if reporting_scope is not None:
            try:
                # External API is untyped and outside this work package.
                value = validate_period(reporting_scope)  # type: ignore[no-untyped-call]
            except ValueError:
                raise HostedError("REPORTING_SCOPE_INVALID", 422) from None
            period = (period or {}) | value | dict(origin="manual", warning=None)
        try:
            selection = scope_selection(
                plan,
                doc["sha256"],
                doc["page_count"],
                reporting_scope=period,
                manual_override=plan["status"] == "failed",
                manual_selection=manual_selection,
            )
        except (ValueError, KeyError, TypeError):
            raise HostedError("PAGE_SELECTION_INVALID", 422) from None
        revision = scope["revision"] + 1
        updated = dict(revision=revision, plan=plan, selection=selection)
        if period is not None:
            updated["reporting_scope"] = period
        store._write(
            store.document_dir(auth.tenant_id, document) / f"scope-{revision:06}.json",
            json.dumps(updated).encode(),
        )
        return updated


def run_options(store: HostedStore, job: HostedRow) -> dict[str, Any]:
    path = (
        store.document_dir(job["tenant_id"], job["document_id"]) / f'{job["run_id"]}.options.json'
    )
    if not path.is_file():
        return {}  # Previous <=2-page runs retain their frozen profile.
    options: dict[str, Any] = json.loads(path.read_text())
    from proofops.domain.provenance import canonical_hash

    expected = options.pop("sha256")
    if canonical_hash(options) != expected or options["pages"] != json.loads(job["pages"]):
        raise HostedError("SCOPE_INTEGRITY_INVALID")
    return options


def create_run(
    store: HostedStore,
    auth: Any,
    document: str,
    pages: list[int] | None,
    key: str,
    *,
    now: float,
    auto_scope: bool = False,
    scope_selection_sha256: str | None = None,
    pipeline_profile: str = "unattended-v1",
    force_fresh: bool = False,
) -> dict[str, Any]:
    if not auth.has_capability("editor"):
        raise HostedError("FORBIDDEN", 403)
    if force_fresh and not auth.has_capability("admin"):
        raise HostedError("FORBIDDEN", 403)
    if not store.settings.accept_runs or store.settings.backend != "r108":
        raise HostedError("ANALYSIS_DISABLED", 503)
    with store.transaction() as db:
        doc = store._document(db, auth.tenant_id, document)
        store._require_document_owner(db, auth, document)
        if now >= doc["expires"]:
            raise HostedError("SOURCE_EXPIRED", 409)
        options = None
        if auto_scope and pages is None:
            scope = store._scope(db, auth.tenant_id, document)
            if scope["selection"] is None:
                raise HostedError("SCOPE_PLAN_FAILED", 422)
            selection = scope["selection"]
            if scope_selection_sha256 and scope_selection_sha256 != selection["selection_sha256"]:
                raise HostedError("SCOPE_CONFLICT", 412)
            if "reporting_scope" in selection:
                from evaluation.reporting_period import validate_period

                try:
                    # External API is untyped and outside this work package.
                    validate_period(selection["reporting_scope"])  # type: ignore[no-untyped-call]
                except ValueError:
                    raise HostedError("REPORTING_SCOPE_REQUIRED", 422) from None
            selected = selection["pages"]
            options = selection | dict(
                pipeline_profile=pipeline_profile,
                source_sha256=doc["sha256"],
                scope_policy_sha256=scope["plan"]["policy_sha256"],
            )
        else:
            selected = list(range(1, min(2, doc["page_count"]) + 1)) if pages is None else pages
            if auto_scope:
                options = dict(
                    pages=selected,
                    claim_pages=selected,
                    pipeline_profile=pipeline_profile,
                    source_sha256=doc["sha256"],
                    declared_subset=True,
                )
        if (
            not isinstance(selected, list)
            or not 1 <= len(selected) <= (30 if options else 2)
            or any(type(page) is not int or not 1 <= page <= doc["page_count"] for page in selected)
            or len(set(selected)) != len(selected)
        ):
            raise HostedError("PAGE_SELECTION_INVALID", 422)
        from proofops_api.hosted_analysis import FINALS_PROFILES

        if pipeline_profile not in {"unattended-v1", "strict-v1", *FINALS_PROFILES}:
            raise HostedError("PIPELINE_PROFILE_INVALID", 422)
        if pipeline_profile in FINALS_PROFILES:
            from proofops.application.analysis_profile import publication_policy_for
            from proofops.domain.provenance import canonical_hash

            if options is None:
                options = dict(pages=selected, claim_pages=selected, source_sha256=doc["sha256"])
            if len(options["claim_pages"]) > 10:
                raise HostedError("PAGE_SELECTION_INVALID", 422)
            operator_pin = None
            config = {}
            if store.settings.live_config is not None:
                config = json.loads(store.settings.live_config.read_text())
                operator_pin = config.get("analysis_policy_sha256")
            options.update(
                pipeline_profile=pipeline_profile,
                analysis_profile=pipeline_profile,
                analysis_profile_sha256=canonical_hash(
                    # External API is untyped and outside this work package.
                    publication_policy_for(pipeline_profile, pinned_hash=operator_pin)  # type: ignore[no-untyped-call]
                ),
            )
            from proofops_api.hosted_analysis import operator_profiles

            # External API is untyped and outside this work package.
            execution = publication_policy_for(pipeline_profile, pinned_hash=operator_pin)  # type: ignore[no-untyped-call]
            if execution.get("provider_scheduler"):
                profiles = operator_profiles(config | dict(analysis_profile=pipeline_profile))
                frozen = {k: profiles[k] for k in ("llm_max_workers", "llm_requests_per_second")}
                options.update(
                    provider_execution=frozen, provider_execution_sha256=canonical_hash(frozen)
                )
            if store.settings.rc1_reuse_enabled and "reporting_scope" not in options:
                from evaluation.reporting_period import validate_period

                try:
                    # External API is untyped and outside this work package.
                    options["reporting_scope"] = validate_period(config)  # type: ignore[no-untyped-call]
                except ValueError:
                    pass  # Unknown period cannot match a reusable publication.
        body_hash = digest(json.dumps([document, selected, options]))
        if force_fresh:
            body_hash = digest(body_hash + ":force_fresh")
        replay = store._replay(db, auth, "run", key, body_hash)
        if replay:
            return store._project_run(store._run(db, auth.tenant_id, replay), db)
        if store._maintenance(db):
            raise HostedError("MAINTENANCE", 503)
        if not (store.document_dir(auth.tenant_id, document) / "original.pdf").is_file():
            raise HostedError("SOURCE_UNAVAILABLE")
        if store.settings.rc1_reuse_enabled:
            from proofops_api.hosted_reuse import try_reuse

            store.analysis_source(store.document_dir(auth.tenant_id, document), dict(doc))
            if not force_fresh:
                reused = try_reuse(
                    store, db, auth, doc, options, key=key, body_hash=body_hash, now=now
                )
                if reused is not None:
                    return reused
        store.guest.check_fresh_run(db, auth, now)
        user = store.user_hash(auth.user_sub)
        # Per-user slot pressure queues work; admission still reserves the
        # complete envelope and checks the global queue, count and USD caps.
        if db.execute("SELECT count(*) FROM runs WHERE status='queued'").fetchone()[0] >= 8:
            raise HostedError("QUEUE_FULL", 429)
        today = day(now)
        for subject, maximum in (
            (user, store.settings.user_daily_runs),
            (None, store.settings.daily_runs),
        ):
            query = "SELECT count(*) FROM deletion.spend WHERE day=?"
            params: tuple[str, ...] = (today,)
            if subject is not None:
                query += " AND user_hash=?"
                params += (subject,)
            if db.execute(query, params).fetchone()[0] >= maximum:
                raise HostedError("DAILY_RUN_LIMIT", 429)
        bound = micros(store.settings.run_usd)
        for field, value, cap in (
            ("day", today, store.settings.day_usd),
            ("event_id", store.settings.event_id, store.settings.event_usd),
        ):
            total = db.execute(
                f"SELECT coalesce(sum(amount),0) FROM deletion.spend WHERE {field}=?", (value,)
            ).fetchone()[0]
            if field == "event_id":
                archived = db.execute(
                    "SELECT amount FROM deletion.event_totals WHERE event_id=?", (value,)
                ).fetchone()
                total += archived[0] if archived else 0
            if total + bound > micros(cap):
                raise HostedError("BUDGET_EXCEEDED", 429)
        run = str(uuid4())
        if options:
            from proofops.domain.provenance import canonical_hash

            options["sha256"] = canonical_hash(options)
            store._write(
                store.document_dir(auth.tenant_id, document) / f"{run}.options.json",
                json.dumps(options).encode(),
            )
        db.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,'queued',?,?,?,?,0,0,NULL,NULL)",
            (
                auth.tenant_id,
                run,
                document,
                user,
                json.dumps(selected),
                now,
                today,
                store.settings.event_id,
                bound,
            ),
        )
        db.execute(
            "INSERT INTO deletion.spend VALUES (?,?,?,?,?,?,'reserved')",
            (run, user, today, store.settings.event_id, bound, now),
        )
        db.execute(
            "INSERT INTO deletion.source_retention VALUES (?,?,?,?,?)",
            (auth.tenant_id, run, document, doc["expires"], now),
        )
        store._remember(db, auth, "run", key, body_hash, run, document, now)
        return store._project_run(store._run(db, auth.tenant_id, run), db)


def _maintenance(db: sqlite3.Connection) -> bool:
    return bool(db.execute("SELECT draining FROM admission_control WHERE id=1").fetchone()[0])


def _control_state(store: HostedStore, db: sqlite3.Connection) -> dict[str, Any]:
    maintenance = store._maintenance(db)
    counts = db.execute(
        "SELECT coalesce(sum(status='running'),0),coalesce(sum(status='queued'),0) FROM runs"
    ).fetchone()
    return dict(
        maintenance=maintenance,
        message=CONTROL_MESSAGES["MAINTENANCE"] if maintenance else None,
        running=counts[0],
        queued=counts[1],
    )


def drain(store: HostedStore, *, now: float) -> dict[str, Any]:
    with store.transaction() as db:
        db.execute("UPDATE admission_control SET draining=1,updated=? WHERE id=1", (now,))
        return store._control_state(db)


def resume(store: HostedStore, *, now: float) -> dict[str, Any]:
    with store.transaction() as db:
        db.execute("UPDATE admission_control SET draining=0,updated=? WHERE id=1", (now,))
        return store._control_state(db)


def control_state(store: HostedStore, *, now: float) -> dict[str, Any]:
    with store.transaction() as db:
        store._expire_running(db, now)
        return store._control_state(db)


def _expire_running(store: HostedStore, db: sqlite3.Connection, now: float) -> None:
    expired = db.execute(
        "SELECT run_id FROM runs WHERE (status='running' AND lease_until<=?) "
        "OR (status='accounting_pending' AND error_code='LEASE_EXPIRED')",
        (now,),
    ).fetchall()
    for row in expired:
        # Broker inserts a cost reservation before transport. No rows in
        # the surviving independent ledger proves no provider was sent.
        no_dispatch = db.execute(
            "SELECT 1 FROM deletion.spend WHERE run_id=? AND NOT EXISTS "
            "(SELECT 1 FROM deletion.costs WHERE run_id=?)",
            (row[0], row[0]),
        ).fetchone()
        if no_dispatch:
            db.execute(
                "UPDATE runs SET status='failed',fence=fence+1,lease_until=0,"
                "error_code='LEASE_EXPIRED_NO_DISPATCH' WHERE run_id=?",
                (row[0],),
            )
            store._settle_envelope(db, row[0])
            continue
        db.execute(
            "UPDATE runs SET "
            "status='accounting_pending',fence=fence+1,error_code='LEASE_EXPIRED' WHERE "
            "run_id=?",
            (row[0],),
        )
        db.execute(
            "UPDATE deletion.spend SET status='accounting_pending' WHERE run_id=?",
            (row[0],),
        )


def claim(store: HostedStore, *, now: float) -> dict[str, Any] | None:
    with store.transaction() as db:
        store._expire_running(db, now)
        if store._maintenance(db):
            return None
        # Only an active fenced worker occupies the slot. Pending accounting
        # remains charged to its envelope/day/event; it cannot dispatch again.
        if db.execute("SELECT count(*) FROM runs WHERE status='running'").fetchone()[0] >= (
            store.settings.max_active_runs
        ):
            return None
        row = db.execute(
            "SELECT q.* FROM runs q WHERE q.status='queued' AND NOT EXISTS "
            "(SELECT 1 FROM runs r WHERE r.status='running' AND "
            "r.tenant_id=q.tenant_id AND r.document_id=q.document_id) "
            "AND (SELECT count(*) FROM runs u WHERE u.user_hash=q.user_hash "
            "AND u.status='running')<? ORDER BY q.created,q.run_id LIMIT 1",
            (store.settings.user_active_runs,),
        ).fetchone()
        if row is None:
            return None
        store._document(db, row["tenant_id"], row["document_id"])
        db.execute(
            "UPDATE runs SET status='running',fence=fence+1,lease_until=? WHERE run_id=?",
            (now + RUN_LEASE_SECONDS, row["run_id"]),
        )
        return dict(db.execute("SELECT * FROM runs WHERE run_id=?", (row["run_id"],)).fetchone())


def _fenced(
    store: HostedStore, db: sqlite3.Connection, job: dict[str, Any], now: float
) -> sqlite3.Row:
    row = store._run(db, job["tenant_id"], job["run_id"])
    if row["status"] != "running" or row["fence"] != job["fence"] or row["lease_until"] <= now:
        raise HostedError("LEASE_LOST")
    return row


def renew_lease(store: HostedStore, job: dict[str, Any], *, now: float) -> None:
    started = time.monotonic()
    # Like the inner job heartbeat, only renewal gets a longer BUSY budget.
    # Acquisition/COMMIT may retry; the fenced body is never replayed.
    with store.transaction(lock_wait_seconds=30, operation="renew_lease") as db:
        current = now + time.monotonic() - started
        row = store._fenced(db, job, current)
        lease_until = max(row["lease_until"], current + RUN_LEASE_SECONDS)
        db.execute(
            "UPDATE runs SET lease_until=? WHERE run_id=?",
            (lease_until, job["run_id"]),
        )
    job["lease_until"] = lease_until


def cancel(store: HostedStore, auth: Any, run: str, *, now: float) -> dict[str, Any]:
    with store.transaction() as db:
        row = store._run(db, auth.tenant_id, run)
        if row["user_hash"] != store.user_hash(auth.user_sub) and not auth.has_capability("admin"):
            raise HostedError("FORBIDDEN", 403)
        db.execute(
            "UPDATE runs SET status='cancelled',fence=fence+1,lease_until=0 WHERE run_id=?",
            (run,),
        )
        store._settle_envelope(db, run)
        store.guest.audit(db, auth, "cancel", run, now)
        return store._project_run(store._run(db, auth.tenant_id, run), db)
