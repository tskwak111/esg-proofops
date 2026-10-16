import gzip
import json
from dataclasses import replace

import pytest
from proofops.adapters.parsing.opendataloader import ParseFailure
from proofops.application.ingest.graph_fusion import ParserProfile

from tests.acceptance.test_parsing import MANIFEST


def test_only_over_limit_candidates_are_compacted_without_losing_nodes(tmp_path):
    from proofops.adapters.parsing.rb2_output import compact, read_candidates

    payload = json.dumps([{"blocks": [{"text": "source evidence" * 1000}]}]).encode()
    (tmp_path / "candidates.json").write_bytes(payload)
    profile = replace(
        ParserProfile(MANIFEST), output_policy="rb2-output-v1", max_output_bytes=20000
    )
    compact(tmp_path, profile, manifest_bytes=1000)
    assert (tmp_path / "candidates.json").read_bytes() == payload
    (tmp_path / "other.json").write_bytes(b"x" * 10000)
    receipt = compact(tmp_path, profile, manifest_bytes=1000)
    assert not (tmp_path / "candidates.json").exists()
    packed = (tmp_path / "rb2-candidates.json.gz").read_bytes()
    assert receipt["original_bytes"] == len(payload)
    assert read_candidates(packed, profile, receipt) == json.loads(payload)
    assert sum(p.stat().st_size for p in tmp_path.iterdir()) + 1000 <= 20000


def test_decompression_is_bounded_and_integrity_checked():
    from proofops.adapters.parsing.rb2_output import read_candidates

    profile = ParserProfile(MANIFEST, max_output_bytes=1000, output_policy="rb2-output-v1")
    bomb = gzip.compress(b" " * 1000000)
    with pytest.raises((ValueError, ParseFailure)):
        read_candidates(
            bomb,
            profile,
            {"profile": "rb2-output-v1", "original_bytes": 1000000, "sha256": "a" * 64},
        )
    with pytest.raises((ValueError, ParseFailure)):
        read_candidates(
            bomb,
            profile,
            {"profile": "rb2-output-v1", "original_bytes": 2, "sha256": "a" * 64},
        )


def test_real_parser_compaction_survives_cold_replay_and_rejects_tampering(tmp_path):
    from hashlib import sha256
    from uuid import uuid4

    from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
    from proofops.adapters.parsing.rb2_output import ARTIFACT, GRAPH_ARTIFACT, compact

    from tests.acceptance.test_parsing import JAVA
    from tests.integration.test_mixed_parser import document

    source = document()
    parser = OpenDataLoaderParser(tmp_path)
    profile = ParserProfile(
        str(uuid4()), java_executable=JAVA, timeout_seconds=60, output_policy="rb2-output-v1"
    )
    graph = parser.parse(source, profile, tenant_id=source.tenant_id)
    final = tmp_path / source.tenant_id / source.document_version_id / profile.parse_manifest_id
    manifest = json.loads((final / "manifest.json").read_bytes())
    # Exercise the compact representation on a small real parser result without
    # reducing the JVM's unrelated scratch-file hard limit to a few kilobytes.
    receipt = compact(final, profile, manifest_bytes=profile.max_output_bytes)
    manifest["artifacts"].pop("candidates.json")
    manifest["artifacts"][ARTIFACT] = sha256((final / ARTIFACT).read_bytes()).hexdigest()
    assert receipt["graph"]["original_bytes"] > 0
    manifest["artifacts"].pop("graph.json")
    manifest["artifacts"][GRAPH_ARTIFACT] = sha256(
        (final / GRAPH_ARTIFACT).read_bytes()
    ).hexdigest()
    manifest["rb2_output"] = receipt
    (final / "manifest.json").chmod(0o600)
    (final / "manifest.json").write_text(json.dumps(manifest))
    assert manifest["rb2_output"]["original_bytes"] > 0
    assert sum(p.stat().st_size for p in final.iterdir()) <= profile.max_output_bytes
    assert (
        OpenDataLoaderParser(tmp_path).load_verified(source, profile, tenant_id=source.tenant_id)
        == graph
    )
    path = final / "rb2-candidates.json.gz"
    # Even an attacker who updates the outer artifact digest cannot substitute
    # candidate bytes against the exact original-byte commitment.
    path.chmod(0o600)
    path.write_bytes(gzip.compress(b"[]", mtime=0))
    manifest["artifacts"][path.name] = sha256(path.read_bytes()).hexdigest()
    (final / "manifest.json").chmod(0o600)
    (final / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ParseFailure, match="INTEGRITY_MISMATCH"):
        OpenDataLoaderParser(tmp_path).load_verified(source, profile, tenant_id=source.tenant_id)


def test_new_parser_selector_does_not_change_old_invocation_hash():
    original = ParserProfile(MANIFEST)
    assert "output_policy" not in original.invocation_snapshot()
    updated = replace(original, output_policy="rb2-output-v1")
    assert updated.config_hash() != original.config_hash()
    with pytest.raises(ValueError):
        replace(original, output_policy="unregistered")
