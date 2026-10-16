"""Opt-in FXH execution with non-redundant policy evaluation.

All original proof methods and nested receipt comparisons execute unchanged.
Only this reader's private globals hold policy snapshots, checked against live
code/tool identities at both read boundaries. Historical modules stay untouched.
"""

from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import MethodType, SimpleNamespace

from proofops.adapters.local import fxh_claim_source as previous
from proofops.adapters.local import rb3_policy_evaluation as policies
from proofops.adapters.local.worker_resources import shared_ocr_pool
from proofops.domain.provenance import canonical_hash

PROFILE = "rb3_claim_source_v1"
PageOCRStore = previous.PageOCRStore
native_policy = previous.native_policy
table_policy_sha256 = previous.table_policy_sha256
table_span_policy = previous.table_span_policy
attest_tables = previous.attest_tables
replay_tables = previous.replay_tables


def claim_source_policy():
    return policies.evaluate(previous.claim_source_policy) | dict(
        profile=PROFILE,
        rb3_execution_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        rb3_policy_evaluation_sha256=sha256(Path(policies.__file__).read_bytes()).hexdigest(),
        rb3_execution="private-policy-DAG-snapshots; live-identity-checks-at-both-boundaries",
    )


def _snapshot(function):
    value = policies.evaluate(function)
    return lambda: deepcopy(value)


_execution = SimpleNamespace(
    _POLICIES=previous.execution._POLICIES,
    _snapshot=_snapshot,
    _bind=previous._clone(previous.execution._bind, _snapshot=_snapshot),
)
_initialize = previous._clone(
    previous.Reader.__init__, claim_source_policy=claim_source_policy, execution=_execution
)


class Reader(previous.Reader):
    def __init__(self, *, run_id):
        self._policy_hash = canonical_hash(claim_source_policy())
        _initialize(self, run_id=run_id)
        # FXF -> FXE -> FXG wrappers; the core already has private execution
        # bindings. Snapshot each wrapper's own policy, preserving nested hashes.
        instance = self.reader
        for _ in range(3):
            for name in ("attest_claim_spans", "recompute_claim_receipt"):
                original = getattr(instance, name).__func__
                policy = original.__globals__["claim_source_policy"]
                function = previous._clone(original, claim_source_policy=_snapshot(policy))
                setattr(instance, name, MethodType(function, instance))
            instance = instance.previous
        if canonical_hash(claim_source_policy()) != self._policy_hash:
            raise ValueError("RB3_READER_POLICY_CHANGED")

    @contextmanager
    def _scope(self, tenant_id):
        policy = claim_source_policy()
        if canonical_hash(policy) != self._policy_hash:
            raise ValueError("RB3_READER_POLICY_CHANGED")
        with previous.raster.scope(tenant_id, self.run_id, policy):
            token = previous.raster._pool.set(shared_ocr_pool())
            try:
                yield
            finally:
                previous.raster._pool.reset(token)
                if canonical_hash(claim_source_policy()) != self._policy_hash:
                    raise ValueError("RB3_READER_POLICY_CHANGED")


def for_run(run_id):
    return Reader(run_id=run_id)


def attest_claim_spans(graph, source, refs, *, tenant_id, run_id=None):
    return for_run(run_id).attest_claim_spans(graph, source, refs, tenant_id=tenant_id)


def replay_claim_spans(receipt, graph, source, discovery, *, tenant_id):
    from proofops.adapters.local.claim_source_verification import discovery_refs
    from proofops.adapters.local.verified_read_cache import _project_owned_cells

    checked = for_run(receipt["run_id"]).recompute_claim_receipt(
        receipt, graph, source, discovery_refs(discovery), tenant_id=tenant_id
    )
    return _project_owned_cells(checked, graph, discovery, tenant_id, failed_state="candidate")
