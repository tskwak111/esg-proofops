"""Replay-only CFA/I20 readers from before the FXA visibility gate.

Recompute under the exact old bytes without changing current module globals.
Complete policy equality still authenticates all transitive dependencies.
"""

from hashlib import sha256
from pathlib import Path

from proofops.adapters.local.frozen_native_replay import _exec_private

_ROOT = Path(__file__).with_name("_frozen_verifiers")
_PINNED = {
    "claim_source_v4_pre_visibility.py": (
        "a9dd38b09b16e7e30c42789e637b887a7e8aef30c4ba26a4cd4d821473f9d855"
    ),
    "upstage_ocr_v21_pre_visibility.py": (
        "e365f48e672edf2353185a5756a95ab98b5ddd0636496ce78b5a8114190218db"
    ),
}


def historical_prose_reader(*, page_ocr=False):
    for name, digest in _PINNED.items():
        path = _ROOT / name
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("CLAIM_SOURCE_POLICY_UNKNOWN")
    prose = _exec_private(
        _ROOT, "claim_source_v4_pre_visibility.py", "proofops.adapters.local._fxa_old_prose"
    )
    if not page_ocr:
        return prose
    reader = _exec_private(
        _ROOT, "upstage_ocr_v21_pre_visibility.py", "proofops.adapters.local._fxa_old_i20"
    )
    reader.prose = prose
    return reader


def historical_pre_d2_reader():
    """Replay the exact FXA/I22 wrapper without changing current reader globals."""
    name = "upstage_ocr_v21_pre_d2.py"
    path = _ROOT / name
    if (
        sha256(path.read_bytes()).hexdigest()
        != "e365f48e672edf2353185a5756a95ab98b5ddd0636496ce78b5a8114190218db"
    ):
        raise ValueError("CLAIM_SOURCE_POLICY_UNKNOWN")
    return _exec_private(_ROOT, name, "proofops.adapters.local._i23_old_i22")
