"""I24 composition: stable FXG receipts followed by exact FXE and FXF recovery.

Private module globals reuse the shipped full-receipt comparisons without
mutating any historical reader or widening source admission.
"""

from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import fxg_claim_source as baseline
from proofops.adapters.local.frozen_native_replay import _exec_private

PROFILE = "i24_claim_source_v1"
PageOCRStore = baseline.PageOCRStore
native_policy = baseline.native_policy
table_policy_sha256 = baseline.table_policy_sha256
table_span_policy = baseline.table_span_policy
attest_tables = baseline.attest_tables
replay_tables = baseline.replay_tables

_local = Path(__file__).parent
_fxe = _exec_private(_local, "upstage_ocr_profile_fxe.py", "proofops.adapters.local._i24_fxe")
_fxe.previous = baseline
_fxe.PROFILE = "i24_fxe_claim_source_v1"
_fxf = _exec_private(_local, "upstage_ocr_profile_fxf.py", "proofops.adapters.local._i24_fxf")
_fxf.previous = _fxe
_fxf.PROFILE = PROFILE
_composed_policy = _fxf.claim_source_policy


def claim_source_policy():
    return _composed_policy() | dict(
        integration_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        admission="FXG-retained; FXE-original-region; FXF-bounded-page-pixels",
    )


_fxf.claim_source_policy = claim_source_policy
Reader = _fxf.Reader
for_run = _fxf.for_run
attest_claim_spans = _fxf.attest_claim_spans
replay_claim_spans = _fxf.replay_claim_spans
