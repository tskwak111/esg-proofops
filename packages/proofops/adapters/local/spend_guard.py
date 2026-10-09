"""Shared atomic USD guard for parser AND model calls, across processes.

Opaque SQLite sidecar: no existing provider/run schema is migrated. Uncertain
calls retain their full bound indefinitely. Duplicate dispatch is forbidden.
"""

import sqlite3
import time
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from proofops.application.budget import BudgetConflict, BudgetExceeded


def amount(value):
    number = Decimal(value)
    if not number.is_finite() or number < 0:
        raise ValueError("INVALID_SPEND_AMOUNT")
    return number


class SpendGuard:
    def __init__(self, path, *, event_id, daily_limit="7", event_limit="7"):
        self.path, self.event_id = Path(path), event_id
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.transaction() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, daily TEXT, cap TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, event TEXT, "
                "day TEXT, cap TEXT, "
                "group_id TEXT, group_cap TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS charges (id TEXT PRIMARY KEY, run TEXT, provider TEXT, "
                "bound TEXT, exposure TEXT, state TEXT)"
            )
            pin = (event_id, str(amount(daily_limit)), str(amount(event_limit)))
            old = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
            if old and old != pin:
                raise BudgetConflict("SPEND_POLICY_CHANGED")
            db.execute("INSERT OR IGNORE INTO events VALUES (?,?,?)", pin)
        self.path.chmod(0o600)

    @contextmanager
    def transaction(self):
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    def configure_run(self, run_id, *, day, run_limit="1", group_id=None, group_limit=None):
        pin = (
            run_id,
            self.event_id,
            day,
            str(amount(run_limit)),
            group_id,
            str(amount(group_limit)) if group_limit is not None else None,
        )
        if not day or not run_id or not 0 < amount(run_limit) <= 1:
            raise ValueError("INVALID_SPEND_RUN")
        if (group_id is None) != (group_limit is None):
            raise ValueError("INVALID_SPEND_GROUP")
        with self.transaction() as db:
            old = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if old and old != pin:
                raise BudgetConflict("SPEND_RUN_CHANGED")
            if (
                group_id is not None
                and db.execute(
                    "SELECT 1 FROM runs WHERE event=? AND group_id=? AND group_cap != ?",
                    (self.event_id, group_id, pin[-1]),
                ).fetchone()
            ):
                raise BudgetConflict("SPEND_GROUP_CHANGED")
            db.execute("INSERT OR IGNORE INTO runs VALUES (?,?,?,?,?,?)", pin)

    def reserve(self, run_id, provider, request_id, bound):
        bound = amount(bound)
        if bound <= 0:
            raise ValueError("INVALID_SPEND_BOUND")
        with self.transaction() as db:
            old = db.execute(
                "SELECT run,provider,bound,state FROM charges WHERE id=?", (request_id,)
            ).fetchone()
            if old:
                if old[:3] != (run_id, provider, str(bound)):
                    raise BudgetConflict("SPEND_REQUEST_CHANGED")
                raise ValueError("SPEND_DUPLICATE_OR_UNCERTAIN_DISPATCH")
            run = db.execute(
                "SELECT * FROM runs WHERE id=? AND event=?", (run_id, self.event_id)
            ).fetchone()
            if run is None:
                raise ValueError("SPEND_RUN_NOT_CONFIGURED")
            daily, event = db.execute(
                "SELECT daily,cap FROM events WHERE id=?", (self.event_id,)
            ).fetchone()
            rows = db.execute(
                "SELECT c.exposure,r.id,r.day,r.group_id FROM charges c "
                "JOIN runs r ON c.run=r.id WHERE r.event=?",
                (self.event_id,),
            ).fetchall()

            def total(index=None, value=None):
                return sum(
                    (amount(row[0]) for row in rows if index is None or row[index] == value),
                    Decimal(0),
                )

            if (
                total() + bound > amount(event)
                or total(2, run[2]) + bound > amount(daily)
                or total(1, run_id) + bound > amount(run[3])
                or (run[4] is not None and total(3, run[4]) + bound > amount(run[5]))
            ):
                raise BudgetExceeded("BUDGET_EXHAUSTED")
            db.execute(
                "INSERT INTO charges VALUES (?,?,?,?,?,?)",
                (request_id, run_id, provider, str(bound), str(bound), "reserved"),
            )

    def settle(self, request_id, charged):
        with self.transaction() as db:
            row = db.execute(
                "SELECT bound,exposure,state FROM charges WHERE id=?", (request_id,)
            ).fetchone()
            if row is None:
                raise BudgetConflict("SPEND_RESERVATION_MISSING")
            exposure = row[0] if charged is None else str(amount(charged))
            state = "uncertain" if charged is None else "settled"
            if amount(exposure) > amount(row[0]):
                raise BudgetConflict("SPEND_BOUND_EXCEEDED")
            if row[2] != "reserved" and row[1:] != (exposure, state):
                raise BudgetConflict("SPEND_SETTLEMENT_CHANGED")
            db.execute(
                "UPDATE charges SET exposure=?,state=? WHERE id=?", (exposure, state, request_id)
            )

    def summary(self):
        with self.transaction() as db:
            rows = db.execute(
                "SELECT c.* FROM charges c " "JOIN runs r ON c.run=r.id WHERE r.event=?",
                (self.event_id,),
            ).fetchall()
        return dict(
            event_id=self.event_id,
            exposure_usd=str(sum((amount(r[4]) for r in rows), Decimal(0))),
            settled_usd=str(sum((amount(r[4]) for r in rows if r[5] == "settled"), Decimal(0))),
            uncertain=sum(r[5] == "uncertain" for r in rows),
            reserved=sum(r[5] == "reserved" for r in rows),
            calls=len(rows),
        )

    def guarded(self, original, *, run_id, provider, bound, slots=None):
        def call(probe, *args, **kwargs):
            from contextlib import nullcontext

            with slots if slots is not None else nullcontext():
                request_id = provider + ":" + kwargs["request_id"]
                reservation = amount(bound(args, kwargs))
                # Wait only for active reservations to settle; uncertainty never expires.
                deadline = time.monotonic() + 120
                while True:
                    try:
                        self.reserve(run_id, provider, request_id, reservation)
                        break
                    except BudgetExceeded:
                        if not self.summary()["reserved"] or time.monotonic() >= deadline:
                            raise
                        time.sleep(0.05)
                try:
                    return original(probe, *args, **kwargs)
                finally:
                    with sqlite3.connect(probe.ledger) as db:
                        row = db.execute(
                            "SELECT committed,receipt FROM probe_calls WHERE request_id=?",
                            (kwargs["request_id"],),
                        ).fetchone()
                    self.settle(
                        request_id, row[0] if row and row[1] is not None else None if row else "0"
                    )

        return call
