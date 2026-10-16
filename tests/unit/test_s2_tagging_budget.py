from threading import Lock
from types import SimpleNamespace

import pytest
from proofops.application.budget import BudgetExceeded
from proofops_worker.live_tagging import LiveTaggingRuntime


def test_claim_volume_covers_e1_without_changing_dollar_cap():
    from proofops.application.tagging.s2_budget import POLICY, call_allowance

    assert call_allowance(103) == call_allowance(110) == 2000
    assert call_allowance(10) == 270
    assert call_allowance(0) == 0
    assert POLICY["run_usd"] == "1.0"


def test_priority_dispatch_preserves_each_claim_and_source_order_ties():
    from proofops.application.tagging.s2_budget import priority

    def claim(identifier, quote, quality="verified"):
        return SimpleNamespace(
            claim_id=identifier,
            quote=quote,
            source_quality=quality,
            source_refs=[SimpleNamespace(page_num=1, source_id="s", char_start=0)],
        )

    claims = [
        claim("a", "환경 활동"),
        claim("b", "배출량 100톤"),
        claim("c", "2030 목표", "unverified"),
    ]
    assert [c.claim_id for c in sorted(claims, key=priority)] == ["b", "a", "c"]
    assert [c.claim_id for c in claims] == ["a", "b", "c"]


def test_allowance_never_bypasses_existing_budget_failure():
    live = object.__new__(LiveTaggingRuntime)
    live._account_lock = Lock()
    live.s2_call_allowance = 27
    live.s2_reserved_calls = set()

    def deny(*args, **kwargs):
        raise BudgetExceeded("BUDGET_EXHAUSTED: existing immutable limit")

    live.runner = SimpleNamespace(store=SimpleNamespace(usage=SimpleNamespace(reserve_budget=deny)))
    with pytest.raises(BudgetExceeded, match="existing immutable"):
        live.reserve_tag_call(SimpleNamespace(request_id="one", attempt=1))
    assert not live.s2_reserved_calls


def test_concurrent_allowance_is_atomic_and_keeps_existing_reservations():
    from concurrent.futures import ThreadPoolExecutor

    live = object.__new__(LiveTaggingRuntime)
    live._account_lock = Lock()
    live.s2_call_allowance = 2
    live.s2_reserved_calls = set()
    calls = []
    live.runner = SimpleNamespace(
        store=SimpleNamespace(
            usage=SimpleNamespace(
                reserve_budget=lambda call, **kw: calls.append(call.request_id) or True,
            )
        )
    )

    def attempt(index):
        try:
            return live.reserve_tag_call(SimpleNamespace(request_id=str(index), attempt=1))
        except BudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert sum(results) == len(calls) == len(live.s2_reserved_calls) == 2
