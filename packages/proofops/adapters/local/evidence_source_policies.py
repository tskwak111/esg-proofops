"""Exact policy dispatch; historical EV1 never gains a different pixel reader."""

from proofops.adapters.local import evidence_source_ocr_v1 as ocr
from proofops.adapters.local import evidence_source_verification_v1 as apple


def evidence_source_reader(policy):
    from proofops.adapters.local import evidence_source_i17

    if policy == evidence_source_i17.policy():
        return evidence_source_i17

    from proofops.adapters.local import (
        evidence_source_h6,
        evidence_source_h7,
        evidence_source_hx3,
        evidence_source_hx4,
    )

    if policy == evidence_source_hx3.policy():
        return evidence_source_hx3
    if policy == evidence_source_hx4.policy():
        return evidence_source_hx4
    from proofops.adapters.local import evidence_source_hx5

    if policy == evidence_source_hx5.policy():
        return evidence_source_hx5

    if policy == evidence_source_h7.policy():
        return evidence_source_h7
    if policy == evidence_source_h6.policy():
        return evidence_source_h6
    for reader in (apple, ocr):
        if policy == reader.policy():
            return reader
    raise ValueError("EVIDENCE_SOURCE_POLICY_MISMATCH")
