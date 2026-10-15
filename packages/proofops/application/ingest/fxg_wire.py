"""Opt-in FXG extraction wire contract; historical profiles remain frozen."""

from contextlib import contextmanager
from contextvars import ContextVar

POLICY = dict(
    profile="fxg_source_block_split_v1",
    budget="actual-provider-request-body; unchanged-provider-limit",
    partition="ordered-candidate-halves-then-context-block-halves; no-text-cuts",
    identity="original-selectors-offsets-coordinates-context-indexes-parent-indexes",
    validation="chunk-local-selector-membership; exact-source-spans; repeated-selector-unanimity",
    replay="exact-plan-request-raw-response-result; no-repeat-dispatch",
    dispatch="per-child-lease-authorization-and-frozen-call-cap; provider-money-ledger",
    max_parts=64,
)

_GUARD = ContextVar("fxg_dispatch_guard", default=None)


@contextmanager
def dispatch_scope(guard):
    token = _GUARD.set(guard)
    try:
        yield
    finally:
        _GUARD.reset(token)


def before_dispatch():
    guard = _GUARD.get()
    if guard is not None:
        guard()
