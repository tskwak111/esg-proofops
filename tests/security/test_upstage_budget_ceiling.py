"""Budget authorization cannot mint more than the user's cumulative USD20."""

import sqlite3

import pytest
from proofops.adapters.local.upstage import UpstageProbe


def test_repeated_extension_cannot_mint_another_allowance(tmp_path):
    probe = UpstageProbe("offline-key", tmp_path / "budget.sqlite3")
    probe.authorize_additional_budget("10.00", reason="user approved additional USD10")
    with pytest.raises(ValueError):
        probe.authorize_additional_budget("10.00", reason="replayed authorization")
    assert probe.summary()["authorized_limit_usd"] == "20.00"


@pytest.mark.parametrize("amount", ["NaN", "-10.00", "10.01", "Infinity"])
def test_reservation_revalidates_durable_authorization(tmp_path, amount):
    path = tmp_path / "budget.sqlite3"
    probe = UpstageProbe("offline-key", path)
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO probe_extensions(additional_usd,reason,authorized_at) VALUES (?,?,?)",
            (amount, "tampered", "2026-09-18T00:00:00Z"),
        )
    with pytest.raises(ValueError, match="BUDGET_POLICY_MISMATCH"):
        probe._reserve("no-network", {})
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM probe_calls").fetchone()[0] == 0


def test_reservation_revalidates_base_policy_after_construction(tmp_path):
    path = tmp_path / "budget.sqlite3"
    probe = UpstageProbe("offline-key", path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE probe_policy SET body='{}' WHERE id=1")
    with pytest.raises(ValueError, match="BUDGET_POLICY_MISMATCH"):
        probe._reserve("no-network", {})
