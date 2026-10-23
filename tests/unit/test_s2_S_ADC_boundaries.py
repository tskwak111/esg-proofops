"""Freeze reviewed bridge output and rejection contracts before module extraction."""

import json

import pytest
from proofops.adapters.local import reviewed_claim_bridge, reviewed_table
from proofops.domain.provenance import canonical_hash
from test_reviewed_cross_location import _review as cross_review
from test_reviewed_table import _review


def test_reviewed_artifact_bytes_and_hash_are_stable():
    source = b"source bytes"
    artifact = reviewed_table.artifact_from_review(_review(source), source)
    encoded = json.dumps(
        artifact, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    assert len(encoded) == 8472
    assert canonical_hash(artifact) == (
        "a6b313e20203229adc85612b0ca62dc99f50786d6554226b603963be5d62986c"
    )
    assert artifact["eligible_for_admission"] is False


def test_equal_cross_location_values_preserve_population_hold():
    source = b"source bytes"
    evidence = cross_review(source, page=1, layout="a" * 64)
    claim = cross_review(source, page=2, layout="c" * 64)
    result = reviewed_claim_bridge.shared_grid_identity(evidence, claim)
    assert canonical_hash(result) == (
        "8c05f4c7c33d61850a2cca2f1b63bd2002f379fce9570b613d57fffda1203afd"
    )
    assert result["holds"] == ["population_not_established_by_equal_values"]


def test_source_mismatch_is_rejected():
    with pytest.raises(ValueError, match="^reviewed layout source mismatch$"):
        reviewed_table.reviewed_numeric_inputs(_review(b"original"), b"different")


def test_numeric_inputs_keep_native_attestation_patch_path(monkeypatch):
    calls = []

    def attest(review, source, **options):
        calls.append((review, source, options))
        raise ValueError("sentinel")

    monkeypatch.setattr(reviewed_table, "native_attested_layout", attest)
    review = _review(b"original")
    with pytest.raises(ValueError, match="^sentinel$"):
        reviewed_table.reviewed_numeric_inputs(review, b"original", tenant_id="tenant")
    assert calls == [
        (
            review,
            b"original",
            {"tenant_id": "tenant", "verify_context": False, "requested_values": False},
        )
    ]
