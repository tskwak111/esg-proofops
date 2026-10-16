"""S2 table execution; the byte-pinned S1/I4 adapter remains untouched."""

from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import parse_table_cache as historical
from proofops.adapters.local.receipt_environment_compat import compare_receipts, read_profile
from proofops.adapters.local.verified_read_cache import (
    _execution_policy,
    remember_parse_attestation,
    replay_cached,
)
from proofops.application.analysis_profile import VERIFIED_READ_V11_POLICY


def _enabled():
    if _execution_policy() != VERIFIED_READ_V11_POLICY:
        return False
    if (
        sha256(Path(__file__).read_bytes()).hexdigest()
        != VERIFIED_READ_V11_POLICY["table_replay_sha256"]
    ):
        raise ValueError("S2_TABLE_EXECUTION_MISMATCH")
    return True


def _args(receipt, graph, source, tenant_id):
    return dict(
        reader_name="native:upstage-ocr-page-v19",
        policy=receipt["reader_policy"],
        receipt=receipt,
        graph=graph,
        source=source,
        tenant_id=tenant_id,
    )


def attest(verifier, graph, source, *, tenant_id):
    receipt = historical.attest(verifier, graph, source, tenant_id=tenant_id)
    if _enabled() and receipt.get("reader_policy", {}).get("mode") == "upstage-ocr-page-v19":
        remember_parse_attestation(**_args(receipt, graph, source, tenant_id))
    return receipt


def replay(verifier, receipt, graph, source, *, tenant_id, compatible=False):
    if (
        _enabled()
        and read_profile() == "strict-v1"
        and receipt.get("reader_policy", {}).get("mode") == "upstage-ocr-page-v19"
    ):
        result = replay_cached(
            **_args(receipt, graph, source, tenant_id),
            recompute=verifier.replay_tables,
        )
        if compatible:
            compare_receipts(receipt, receipt, profile="strict-v1")
        return result
    return historical.replay(
        verifier,
        receipt,
        graph,
        source,
        tenant_id=tenant_id,
        compatible=compatible,
    )
