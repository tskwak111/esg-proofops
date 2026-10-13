"""H7 literal admission with item-local read boundaries, under a new exact policy."""

from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import evidence_source_h7 as previous
from proofops.adapters.local import source_hx3
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.domain.provenance import canonical_hash

PROFILE = "evidence-source-hx3-v1"
SCHEMA = "evidence_source_hx3_attestation_v1"


def policy():
    return dict(
        previous.policy(),
        profile=PROFILE,
        previous_policy_sha256=canonical_hash(previous.policy()),
        item_holds=source_hx3.policy(),
        wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


_reader = _exec_private(
    Path(__file__).parent, "evidence_source_h7.py", "proofops.adapters.local._hx3_evidence"
)
_reader.policy = policy
_reader.SCHEMA = SCHEMA


def _guarded_module(*args, **kwargs):
    module = _exec_private(*args, **kwargs)
    module._literal = source_hx3.hold_read(module._literal)
    return module


_reader._exec_private = _guarded_module
attest_evidence_sources = _reader.attest_evidence_sources
replay_evidence_sources = _reader.replay_evidence_sources
