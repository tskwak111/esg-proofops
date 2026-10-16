"""Opt-in CF4 source proofs with shared read-scoped original inputs."""

from hashlib import sha256
from pathlib import Path
from types import FunctionType, MethodType

from proofops.adapters.local import cf4_claim_source as previous
from proofops.adapters.local import spe_source_execution as execution
from proofops.domain.provenance import canonical_hash

PROFILE = "spe_claim_source_v1"
PageOCRStore = previous.PageOCRStore
native_policy = previous.native_policy
table_policy_sha256 = previous.table_policy_sha256
table_span_policy = previous.table_span_policy
attest_tables = previous.attest_tables
replay_tables = previous.replay_tables


def claim_source_policy():
    return execution.evaluate(previous.claim_source_policy) | dict(
        profile=PROFILE,
        spe_reader_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        spe_execution_sha256=sha256(Path(execution.__file__).read_bytes()).hexdigest(),
        spe_execution="scoped-original-PDF-and-immutable-graph; unchanged-CF4-proofs",
    )


class Reader:
    def __init__(self, *, run_id):
        self.run_id = run_id
        self._previous = None
        self._policy_hash = canonical_hash(claim_source_policy())

    def __getattr__(self, name):
        # Parsing also uses this registered reader for native/table proofs.
        # Preserve that entire CF4 interface and its original execution policy.
        if self._previous is None:
            self._previous = previous.for_run(self.run_id)
        return getattr(self._previous, name)

    def _check(self):
        if canonical_hash(claim_source_policy()) != self._policy_hash:
            raise ValueError("SPE_READER_POLICY_CHANGED")

    def _read(self, method, graph, source, *args, **kwargs):
        self._check()
        try:
            with execution.SourceScope(graph, source) as scope:
                reader = previous.for_run(self.run_id)
                # Only the outer execution policy changes. All nested CF4/S5
                # proof policies, schemas, comparisons and records stay exact.
                for name in ("attest_claim_spans", "recompute_claim_receipt"):
                    original = getattr(type(reader), name)
                    function = FunctionType(
                        original.__code__,
                        original.__globals__ | dict(claim_source_policy=claim_source_policy),
                        original.__name__,
                        original.__defaults__,
                        original.__closure__,
                    )
                    function.__kwdefaults__ = original.__kwdefaults__
                    setattr(reader, name, MethodType(function, reader))
                scope.bind_reader(reader)
                if method == "recompute_claim_receipt":
                    receipt, refs = args
                    return reader.recompute_claim_receipt(receipt, graph, source, refs, **kwargs)
                return reader.attest_claim_spans(graph, source, *args, **kwargs)
        finally:
            self._check()

    def attest_claim_spans(self, graph, source, refs, *, tenant_id, **kwargs):
        return self._read("attest_claim_spans", graph, source, refs, tenant_id=tenant_id, **kwargs)

    def recompute_claim_receipt(self, receipt, graph, source, refs, *, tenant_id):
        return self._read(
            "recompute_claim_receipt", graph, source, receipt, refs, tenant_id=tenant_id
        )


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
