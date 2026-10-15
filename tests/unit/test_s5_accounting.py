"""Deferring repeated reporting reads never defers durable per-call settlement."""

import json
import sqlite3
from threading import Lock
from types import SimpleNamespace

import pytest
from proofops.adapters.local.upstage import request_usage
from proofops_worker.live_tagging import LiveTaggingRuntime
from proofops_worker.tag_runner import LocalTagRunner


def runtime(tmp_path):
    live = object.__new__(LiveTaggingRuntime)
    live.ledger = tmp_path / "ledger.sqlite3"
    live._account_lock = Lock()
    live._s5_defer_accounting = True
    live.previously_accounted = {"prior"}
    live.request_ids = set()
    live.usage = dict(sc1_inventory_plan=dict(planned_calls=3))
    with sqlite3.connect(live.ledger) as db:
        db.execute("CREATE TABLE probe_calls(request_id TEXT, committed TEXT, receipt TEXT)")
        db.executemany(
            "INSERT INTO probe_calls VALUES (?,?,?)",
            [
                ("done", ".001", json.dumps(dict(input_tokens=10, output_tokens=20))),
                ("uncertain", ".011", None),
                ("prior", ".001", json.dumps(dict(input_tokens=99, output_tokens=99))),
            ],
        )
    return live


@pytest.mark.parametrize("failed", [False, True])
def test_final_reporting_matches_live_ledger_even_when_tagging_aborts(tmp_path, failed):
    live = runtime(tmp_path)

    def execute(*args, accounting_flushers, **kwargs):
        accounting_flushers.append(live.flush_accounting)
        for request in ["done", "uncertain", "done", "prior", "never_reserved"]:
            live.account(request)
        # Reporting reads are deferred, never the money ledger's actual amounts.
        assert "model_calls" not in live.usage
        if failed:
            raise ValueError("LEASE_LOST")
        return b"unchanged-tag-result"

    runner = SimpleNamespace(_execute_tag=execute)
    if failed:
        with pytest.raises(ValueError, match="LEASE_LOST"):
            LocalTagRunner._execute(runner)
    else:
        assert LocalTagRunner._execute(runner) == b"unchanged-tag-result"
    ids = ["done", "never_reserved", "uncertain"]
    assert live.usage == request_usage(live.ledger, ids) | dict(
        sc1_inventory_plan=dict(planned_calls=3), tag_request_ids=ids
    )
    assert live.usage["unsettled_calls"] == 1
    assert live.usage["cost_with_vat_reserve_usd"] == "unknown"


def test_final_snapshot_rechecks_changed_or_corrupt_settlement(tmp_path):
    live = runtime(tmp_path)
    live.account("done")
    live.account("uncertain")
    with sqlite3.connect(live.ledger) as db:
        db.execute(
            "UPDATE probe_calls SET receipt=? WHERE request_id='uncertain'",
            (json.dumps(dict(input_tokens=5, output_tokens=6)),),
        )
    live.flush_accounting()
    assert live.usage["unsettled_calls"] == 0
    with sqlite3.connect(live.ledger) as db:
        db.execute("UPDATE probe_calls SET receipt='not-json' WHERE request_id='done'")
    with pytest.raises(ValueError, match="ACCOUNTING_UNAVAILABLE"):
        live.flush_accounting()
