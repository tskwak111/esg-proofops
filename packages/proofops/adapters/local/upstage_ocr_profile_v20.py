"""P3 makes failed acquisition use the same original-byte proof as cold replay.

Only availability errors from acquisition select the existing local raster
proof. Collection validation, source/tenant identity and whole-receipt hash
checks remain unchanged. V19 and its dependencies retain their exact bytes.
"""

from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import upstage_ocr_profile_v19 as previous
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.domain.provenance import canonical_hash

PROFILE = "upstage-ocr-page-v20"
PageOCRStore = previous.PageOCRStore


def claim_source_policy():
    return dict(
        previous.claim_source_policy(),
        profile=PROFILE,
        previous_reader_sha256=sha256(Path(previous.__file__).read_bytes()).hexdigest(),
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        acquisition_failure="failed-or-pending-reservation-original-local-proof-v1",
    )


def native_policy():
    return dict(previous.previous.native_policy(), mode=PROFILE, i17=claim_source_policy())


def table_policy_sha256():
    return canonical_hash(
        dict(previous=previous.previous.table_policy_sha256(), i17=native_policy())
    )


def table_span_policy():
    return dict(previous.previous.table_span_policy(), profile=PROFILE, i17=claim_source_policy())


class _AvailableStore:
    """An instance-local acquisition adapter; validate delegates without catches."""

    def __init__(self, store):
        self.store = store

    def __getattr__(self, name):
        return getattr(self.store, name)

    def fetch(self, *args, **kwargs):
        try:
            return self.store.fetch(*args, **kwargs)
        except ValueError as error:
            if str(error) == "OCR_PENDING_OR_FAILED" or str(error).startswith(
                "OCR_COLLECTION_FAILED_RESERVATION_RETAINED:"
            ):
                # The reservation remains in the store. The existing bounded
                # reader recomputes a local proof when no collection is present.
                raise ValueError("OCR_REPLAY_PAGE_MISSING") from None
            raise


_reader = _exec_private(
    Path(__file__).parent, "upstage_ocr_profile_v19.py", "proofops.adapters.local._p3_v19"
)


class CompleteReader(_reader.CompleteReader):  # type: ignore[name-defined]
    def __init__(self, store, *, run_id):
        super().__init__(_AvailableStore(store), run_id=run_id)


_reader.CompleteReader = CompleteReader
_reader._complete.Reader = CompleteReader
for _name in (
    "PROFILE",
    "claim_source_policy",
    "native_policy",
    "table_policy_sha256",
    "table_span_policy",
):
    setattr(_reader._size, _name, globals()[_name])

Reader = _reader.Reader
for_run = _reader.for_run
attest_claim_spans = _reader.attest_claim_spans
attest_tables = _reader.attest_tables
replay_tables = _reader.replay_tables
replay_claim_spans = _reader.replay_claim_spans
