"""Authorized collection for new proofs; saved collections only during cold replay."""

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import upstage_ocr_profile_v14 as normal


def policy():
    return dict(
        profile="authorized-normal-collected-replay-v1",
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


class AuthorizedNormalOCR:
    def __init__(self, store, *, run_id):
        normal.Reader.__init__(self, store, run_id=run_id)

    def _modules(self, graph, source, tenant_id, collections=None):
        if collections is None:
            collections = getattr(self, "_saved_collections", None)
        return super()._modules(graph, source, tenant_id, collections)

    def _finish(self, receipt, seen, *, native=False):
        from proofops.domain.provenance import canonical_hash

        result = super()._finish(receipt, seen, native=native)
        result.pop("paid_calls", None)
        result["replay_mode"] = "authorized-collected-or-original-local-v1"
        result["artifact_sha256"] = canonical_hash(
            {k: v for k, v in result.items() if k != "artifact_sha256"}
        )
        return result


@contextmanager
def retained_collections(reader, receipt):
    """Bind only this reader instance; never mutate shared reader globals."""
    while hasattr(reader, "previous"):
        reader = reader.previous
    while "base_receipt" in receipt:
        receipt = receipt["base_receipt"]
    previous = getattr(reader, "_saved_collections", None)
    reader._saved_collections = receipt.get("page_collections", [])
    try:
        yield
    finally:
        reader._saved_collections = previous
