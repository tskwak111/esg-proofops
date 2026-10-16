"""S1: reuse only a whole, freshly executed table proof in one parse delivery.

The cache holds no persisted approvals. Cold/mismatched/transient reads execute
the historical verifier. A warm read runs its byte-pinned projection tail with
the exact base receipt, retaining unattested cells, issues and all provenance.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from types import FunctionType

from proofops.adapters.local import selected_cell_table_verification as selected
from proofops.adapters.local import upstage_ocr_profile as composition
from proofops.adapters.local import upstage_ocr_profile_v6 as v6
from proofops.adapters.local.local_raster_reader import runtime_policy
from proofops.adapters.local.receipt_environment_compat import (
    compare_receipts,
    read_profile,
    replay_receipt,
)
from proofops.adapters.local.verified_read_cache import _transient
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json

_scope: ContextVar[tuple | None] = ContextVar("s1_fresh_table_proof", default=None)
MAX_BYTES = 32 * 1024 * 1024

# The projection is the unchanged tail in these original reader bytes.
SELECTED_SHA256 = "045f4dca825e35a29f12307e234c30be546d53c5a18fc916e8c98c852a1389db"
COMPOSITION_SHA256 = "8d4b5caddb377ca1e9dc10998588449b85415aff6e4910372774d355db643102"


@contextmanager
def scope(tenant, run):
    token = _scope.set((tenant, run, {}))
    try:
        yield
    finally:
        _scope.reset(token)


def _key(receipt, graph, source, tenant_id):
    bound = _scope.get()
    if bound is None or read_profile() != "strict-v1" or _transient(receipt):
        return None
    if (
        bound[:2] != (tenant_id, receipt.get("run_id"))
        or receipt.get("reader_policy") != v6.native_policy()
        or receipt.get("policy_sha256") != v6.table_policy_sha256()
        or sha256(Path(selected.__file__).read_bytes()).hexdigest() != SELECTED_SHA256
        or sha256(Path(composition.__file__).read_bytes()).hexdigest() != COMPOSITION_SHA256
        or not isinstance(source, bytes)
        or sha256(source).hexdigest() != graph.source_sha256
        or receipt.get("tenant_id") != tenant_id
        or graph.tenant_id != tenant_id
        or receipt.get("source_sha256") != graph.source_sha256
        or receipt.get("input_graph_sha256") != canonical_hash(asdict(graph))
    ):
        return None
    return canonical_hash(
        dict(
            tenant=tenant_id,
            run=bound[1],
            receipt=receipt,
            graph=asdict(graph),
            source_sha256=graph.source_sha256,
            runtime=runtime_policy(),
            read_profile=read_profile(),
        )
    )


def attest(verifier, graph, source, *, tenant_id):
    receipt = verifier.attest_tables(graph, source, tenant_id=tenant_id)
    key = _key(receipt, graph, source, tenant_id)
    if key is not None:
        encoded = canonical_json(receipt).encode()
        if len(encoded) <= MAX_BYTES:
            # One delivery owns one table census; never accumulate report-sized data.
            entries = _scope.get()[2]
            entries.clear()
            entries[key] = encoded
    return receipt


def replay(verifier, receipt, graph, source, *, tenant_id, compatible=False):
    key = _key(receipt, graph, source, tenant_id)
    bound = _scope.get()
    if key is None or bound[2].get(key) != canonical_json(receipt).encode():
        if compatible:
            return replay_receipt(
                verifier.replay_tables, receipt, graph, source, tenant_id=tenant_id
            )
        return verifier.replay_tables(receipt, graph, source, tenant_id=tenant_id)
    # _finish() overwrote only the selected policy/outer fields. Restore the
    # original base preimage, then run selected.replay_tables' own projection.
    outer = {
        "rendered_reader_profile",
        "run_id",
        "page_collections",
        "replay_mode",
        "reader_policy",
        "rendered_reader_sha256",
        "artifact_sha256",
    }
    baseline = {k: v for k, v in receipt.items() if k not in outer}
    baseline["policy_sha256"] = selected.policy_sha256()
    baseline["artifact_sha256"] = canonical_hash(baseline)
    original = selected.replay_tables
    project = FunctionType(
        original.__code__,
        original.__globals__ | dict(attest_tables=lambda *a, **k: baseline),
        original.__name__,
        original.__defaults__,
        original.__closure__,
    )
    project.__kwdefaults__ = original.__kwdefaults__
    result = project(baseline, graph, source, tenant_id=tenant_id)
    if compatible:
        compare_receipts(receipt, receipt, profile="strict-v1")
    return result


@contextmanager
def for_snapshot(snapshot, tenant, run):
    from proofops.application.analysis_profile import S1_POLICY

    pin = snapshot.get("analysis_profile_policy_sha256")
    if pin == canonical_hash(S1_POLICY):
        if (
            snapshot.get("analysis_profile_policy") != S1_POLICY
            or S1_POLICY["parse_replay_cache"]["implementation_sha256"]
            != sha256(Path(__file__).read_bytes()).hexdigest()
        ):
            raise ValueError("S1_PARSE_POLICY_MISMATCH")
        with scope(tenant, run):
            yield
    else:
        yield
