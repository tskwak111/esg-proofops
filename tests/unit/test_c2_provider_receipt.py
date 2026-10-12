import json
import sqlite3

import pytest
from proofops.domain.provenance import canonical_hash

from evaluation.c2_pilot import verify_provider_receipt


def test_saved_raw_response_edit_or_made_up_provider_identity_is_rejected(tmp_path):
    ledger = tmp_path / "provider.sqlite3"
    original = dict(
        request_id="original-provider-call",
        provider_request_id="actual-origin",
        content='{"track":"management"}',
        schema_valid=True,
    )
    raw = dict(
        id=original["provider_request_id"],
        choices=[dict(message=dict(content=original["content"]))],
    )
    original["response_sha256"] = canonical_hash(raw)
    folder = ledger.with_name(ledger.name + ".responses")
    folder.mkdir()
    (folder / "origin.json").write_text(json.dumps(dict(provider_response=raw)))
    with sqlite3.connect(ledger) as db:
        db.execute("CREATE TABLE probe_calls (request_id TEXT, receipt TEXT)")
        db.execute(
            "INSERT INTO probe_calls VALUES (?,?)",
            (
                original["request_id"],
                json.dumps({k: v for k, v in original.items() if k != "content"}),
            ),
        )
    verify_provider_receipt(original, ledger)
    for changed in [
        original | dict(content='{"track":"performance"}'),
        original | dict(request_id="invented-call"),
    ]:
        with pytest.raises(ValueError, match="ORIGIN_MISMATCH"):
            verify_provider_receipt(changed, ledger)
