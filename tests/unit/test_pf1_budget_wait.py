"""A full reservation window waits; spent budget and uncertain dispatch never retry."""

from contextlib import contextmanager

import pytest

from evaluation.pf1_live import wait_for_budget_slot


class Budget:
    def __init__(self, pending):
        self.pending = pending

    @contextmanager
    def transaction(self):
        yield {}, {"reserved_usd": self.pending}


def test_wait_only_for_never_dispatched_reservation(monkeypatch):
    attempts = []

    def call():
        attempts.append(1)
        if len(attempts) == 1:
            raise ValueError("R108_FINALS_BUDGET_EXHAUSTED")
        return "dispatched once"

    monkeypatch.setattr("evaluation.pf1_live.time.sleep", lambda _: None)
    assert wait_for_budget_slot(call, Budget("0.02")) == "dispatched once"


@pytest.mark.parametrize(
    "code,pending",
    [
        ("OPENAI_REQUEST_FAILED", "0.02"),
        ("R108_FINALS_BUDGET_EXHAUSTED", "0"),
    ],
)
def test_uncertain_dispatch_or_exhausted_budget_is_not_retried(code, pending):
    attempts = []

    def call():
        attempts.append(1)
        raise ValueError(code)

    with pytest.raises(ValueError, match=code):
        wait_for_budget_slot(call, Budget(pending))
    assert len(attempts) == 1
