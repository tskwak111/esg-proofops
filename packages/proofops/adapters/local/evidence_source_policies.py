"""Exact policy dispatch; historical EV1 never gains a different pixel reader."""

from proofops.adapters.local import evidence_source_ocr_v1 as ocr
from proofops.adapters.local import evidence_source_verification_v1 as apple


def evidence_source_reader(policy):
    for reader in (apple, ocr):
        if policy == reader.policy():
            return reader
    raise ValueError("EVIDENCE_SOURCE_POLICY_MISMATCH")
