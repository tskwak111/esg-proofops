"""OS-bound OCR receipts must fail closed even when text and pixels agree.

Real PDF/native parsing with explicitly mocked OCR metadata; the actual R105
archive reproduction is recorded separately in the Sprint 2 T2 lab.
"""

from dataclasses import asdict

import pytest
from proofops.adapters.local import merged_table_verification as verifier
from proofops.domain.provenance import canonical_hash

from tests.integration.test_merged_table_verification import TENANT, fixture, ocr


def test_archive_reverify_rejects_os_only_drift(monkeypatch):
    source, graph = fixture()
    original = canonical_hash(asdict(graph))
    reader_os = "Version 27.0 (Build 26A428)"

    def rendered(page, box, **kwargs):
        return {**ocr(page, box, **kwargs), "os": reader_os}

    monkeypatch.setattr(verifier, "_rendered_text", rendered)
    verifier._attest_json.cache_clear()
    try:
        saved = verifier.attest_tables(graph, source, tenant_id=TENANT)
        assert saved["records"][0]["status"] == "verified"
        checked = verifier.replay_tables(saved, graph, source, tenant_id=TENANT)
        assert any(block.quality == "verified" for block in checked.blocks)

        reader_os = "Version 27.0.1 (Build 26A434)"
        # A new replay process cannot reuse the prior process's in-memory OCR.
        verifier._attest_json.cache_clear()
        current = verifier.attest_tables(graph, source, tenant_id=TENANT)
        assert current["policy_sha256"] == saved["policy_sha256"]
        for old_record, new_record in zip(saved["records"], current["records"], strict=True):
            for old, new in zip(old_record["cells"], new_record["cells"], strict=True):
                assert old["rendered"]["text"] == new["rendered"]["text"]
                assert old["rendered"]["image_sha256"] == new["rendered"]["image_sha256"]
                assert old["rendered"]["os"] != new["rendered"]["os"]
        with pytest.raises(ValueError, match="^table attestation mismatch$"):
            verifier.replay_tables(saved, graph, source, tenant_id=TENANT)
        assert canonical_hash(asdict(graph)) == original
    finally:
        verifier._attest_json.cache_clear()
