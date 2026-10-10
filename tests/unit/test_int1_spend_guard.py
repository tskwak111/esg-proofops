from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest


def test_atomic_parser_plus_llm_caps_and_uncertain_charges(tmp_path):
    from proofops.adapters.local.spend_guard import SpendGuard
    from proofops.application.budget import BudgetExceeded

    guard = SpendGuard(tmp_path / "event.sqlite", event_id="finals")
    guard.configure_run("a", day="2026-10-10", run_limit="1", group_id="INT1", group_limit="1.2")
    guard.configure_run("b", day="2026-10-10", run_limit="1", group_id="INT1", group_limit="1.2")
    guard.reserve("a", "parser", "parse", ".6")
    guard.settle("parse", ".6")
    guard.reserve("a", "openai", "model", ".3")
    with pytest.raises(BudgetExceeded):
        guard.reserve("a", "openai", "overflow", ".11")
    guard.configure_run("c", day="2026-10-10", run_limit="1", group_id="INT1", group_limit="1.2")
    with pytest.raises(BudgetExceeded):
        guard.reserve("c", "parser", "group-overflow", ".31")
    guard.settle("model", None)
    assert Decimal(guard.summary()["exposure_usd"]) == Decimal(".9")
    with pytest.raises(ValueError, match="UNCERTAIN"):
        guard.reserve("a", "openai", "model", ".3")


def test_cross_connection_reservations_do_not_overspend(tmp_path):
    from proofops.adapters.local.spend_guard import SpendGuard
    from proofops.application.budget import BudgetExceeded

    path = tmp_path / "event.sqlite"
    guard = SpendGuard(path, event_id="event", daily_limit="7", event_limit="7")
    for i in range(10):
        guard.configure_run(str(i), day="2026-10-10")

    def call(i):
        try:
            SpendGuard(path, event_id="event").reserve(str(i), "parser", str(i), "1")
            return True
        except BudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=10) as pool:
        assert sum(pool.map(call, range(10))) == 7
    assert guard.summary()["exposure_usd"] == "7"
