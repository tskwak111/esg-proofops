"""Export payload-size contract: shared original input packets and compressed bundles.

Covers the observed blocker where a published tag whose input packet is stored twice in
one revision record doubled the captured bytes and tripped EXPORT_SIZE_LIMIT before any
format was rendered. The 32 MiB caps are unchanged and are never patched away here.
"""

import json
from hashlib import sha256
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest
from proofops.application.exports import (
    MAX_EXPORT_BYTES,
    REVISION_RECORDS_V1,
    REVISION_RECORDS_V2,
    SHARED_ORIGINAL_INPUTS,
    decode_revision_record,
    encode_revision_record,
)
from proofops.domain.rulepacks import canonical_json

from tests.acceptance.test_exports import archive, create, exports
from tests.integration.test_revision_coverage import resolve


def test_identical_original_packet_is_stored_once_and_restores_exact_bytes():
    inputs = {"claim": {"claim_id": "c"}, "payload": ["x" * 64, {"n": 1}]}
    tag = {"tag_revision": 1, "inputs": json.loads(canonical_json(inputs))}
    record = encode_revision_record(tag, None, inputs)
    assert record["original_inputs_ref"] == SHARED_ORIGINAL_INPUTS
    assert "original_inputs" not in record
    assert len(canonical_json(record).encode()) < len(
        canonical_json(dict(tag=tag, decision=None, original_inputs=inputs)).encode()
    )
    restored = decode_revision_record(record, encoding=REVISION_RECORDS_V2)
    assert canonical_json(restored["original_inputs"]) == canonical_json(inputs)
    assert canonical_json(restored["tag"]) == canonical_json(tag)
    assert canonical_json(restored) == canonical_json(
        dict(tag=tag, decision=None, original_inputs=inputs)
    )


def test_unequal_packets_are_both_preserved_verbatim():
    inputs = {"claim": {"claim_id": "c"}, "payload": [1, 2, 3]}
    tag = {"tag_revision": 2, "inputs": {"claim": {"claim_id": "c"}, "payload": [1, 2, 4]}}
    record = encode_revision_record(tag, None, inputs)
    assert "original_inputs_ref" not in record
    assert canonical_json(record["original_inputs"]) == canonical_json(inputs)
    assert canonical_json(record["tag"]["inputs"]) == canonical_json(tag["inputs"])
    assert decode_revision_record(record, encoding=REVISION_RECORDS_V2) == record


def test_reviewed_tag_without_embedded_inputs_stays_inline_under_v2():
    inputs = {"claim": {"claim_id": "c"}}
    record = encode_revision_record({"tag_revision": 3}, None, inputs)
    assert record["original_inputs"] == inputs and "original_inputs_ref" not in record
    assert decode_revision_record(record, encoding=REVISION_RECORDS_V2) == record
    assert decode_revision_record(record, encoding=REVISION_RECORDS_V1) == record


def test_version_dispatch_defaults_to_legacy_and_refuses_mismatched_records():
    legacy = dict(tag={"inputs": {"a": 1}}, decision=None, original_inputs={"a": 2})
    assert decode_revision_record(legacy) == legacy
    assert REVISION_RECORDS_V1 != REVISION_RECORDS_V2
    shared = dict(
        tag={"inputs": {"a": 1}}, decision=None, original_inputs_ref=SHARED_ORIGINAL_INPUTS
    )
    # A v1 manifest can never carry a reference record, so the default encoding refuses it.
    with pytest.raises(ValueError):
        decode_revision_record(shared)
    with pytest.raises(ValueError):
        decode_revision_record(shared, encoding="shared_original_inputs_v3")
    with pytest.raises(ValueError):
        decode_revision_record(legacy, encoding="shared_original_inputs_v3")
    assert decode_revision_record(shared, encoding=REVISION_RECORDS_V2)["original_inputs"] == {
        "a": 1
    }


def test_malformed_records_raise_instead_of_losing_the_packet():
    ref = SHARED_ORIGINAL_INPUTS
    for broken in (
        dict(tag={}, decision=None),
        dict(tag={"inputs": {}}, decision=None, original_inputs_ref="tag"),
        dict(tag={"inputs": {}}, decision=None, original_inputs={}, original_inputs_ref=ref),
        dict(tag={}, decision=None, original_inputs_ref=ref),
        dict(tag={"inputs": None}, decision=None, original_inputs_ref=ref),
        dict(tag={"inputs": "not a packet"}, decision=None, original_inputs_ref=ref),
        dict(tag={"inputs": []}, decision=None, original_inputs_ref=ref),
        dict(tag=None, decision=None, original_inputs_ref=ref),
        dict(tag={"inputs": {}}, decision=None, original_inputs_ref=None),
    ):
        with pytest.raises(ValueError):
            decode_revision_record(broken, encoding=REVISION_RECORDS_V2)
    with pytest.raises(ValueError):
        decode_revision_record(["not", "an", "object"], encoding=REVISION_RECORDS_V2)


def test_http_bundle_is_deflated_and_declares_the_shared_packet_encoding(tmp_path, monkeypatch):
    ws = exports(tmp_path, monkeypatch)
    resolve(ws)
    result = create(ws).json()
    bundle, ticket, content = archive(ws, result)
    assert set(bundle.namelist()) == {"manifest.json", "report.json", "report.csv", "report.html"}
    assert {info.compress_type for info in bundle.infolist()} == {ZIP_DEFLATED}
    assert len(content) <= MAX_EXPORT_BYTES
    assert sha256(content).hexdigest() == ticket["sha256"]
    manifest = json.loads(bundle.read("manifest.json"))
    encoding = manifest["revision_records_encoding"]
    assert encoding == REVISION_RECORDS_V2
    records = manifest["revision_records"]
    assert records
    for record in records.values():
        restored = decode_revision_record(record, encoding=encoding)
        assert canonical_json(restored["original_inputs"]) == canonical_json(
            record["tag"]["inputs"]
        )


def test_stored_and_deflated_bundles_round_trip_the_same_member_bytes():
    from io import BytesIO

    payload = canonical_json({"x": ["y" * 512] * 32}).encode()
    archives = {}
    for compression in (ZIP_STORED, ZIP_DEFLATED):
        stream = BytesIO()
        with ZipFile(stream, "w", compression=compression) as bundle:
            info = ZipInfo("manifest.json")
            info.compress_type = compression
            bundle.writestr(info, payload)
        archives[compression] = stream.getvalue()
    assert len(archives[ZIP_DEFLATED]) < len(archives[ZIP_STORED])
    for raw in archives.values():
        with ZipFile(BytesIO(raw)) as bundle:
            assert bundle.read("manifest.json") == payload
