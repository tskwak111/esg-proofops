"""Compressed offline reads retain logical values and both hash commitments."""

import gzip
import json
from hashlib import sha256

import pytest
from proofops.adapters.parsing.parser_artifacts import (
    iter_parser_artifacts,
    parser_artifact_path,
    read_parser_json,
)


def artifacts(directory, compressed):
    directory.mkdir(parents=True, exist_ok=True)
    values = {
        "graph.json": dict(
            document_version_id="version",
            parse_manifest_id="parse",
            source_sha256="a" * 64,
            blocks=[dict(source_id="source", raw_text="unchanged source")],
        ),
        "candidates.json": [dict(text="unchanged source")],
    }
    manifest = dict(
        tenant_id="tenant",
        parser_profile=dict(output_policy="rb2-output-v1", max_output_bytes=20_000_000),
        artifacts={},
    )
    receipts = {}
    for name, value in values.items():
        raw = json.dumps(value).encode()
        if name in compressed:
            stored_name = "rb2-" + name + ".gz"
            stored = gzip.compress(raw, mtime=0)
            receipts[name] = dict(
                profile="rb2-output-v1", original_bytes=len(raw), sha256=sha256(raw).hexdigest()
            )
        else:
            stored_name, stored = name, raw
        (directory / stored_name).write_bytes(stored)
        manifest["artifacts"][stored_name] = sha256(stored).hexdigest()
    if receipts:
        manifest["rb2_output"] = receipts["candidates.json"]
        if "graph.json" in receipts:
            manifest["rb2_output"]["graph"] = receipts["graph.json"]
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return values, manifest


@pytest.mark.parametrize("compressed", [[], ["candidates.json"], ["candidates.json", "graph.json"]])
def test_logical_and_discovered_paths_keep_every_value_and_stored_hash(tmp_path, compressed):
    values, manifest = artifacts(tmp_path, compressed)
    for name, value in values.items():
        actual = parser_artifact_path(tmp_path / name)
        assert list(iter_parser_artifacts(tmp_path, name)) == [actual]
        assert read_parser_json(tmp_path / name) == read_parser_json(actual) == value
        assert sha256(actual.read_bytes()).hexdigest() == manifest["artifacts"][actual.name]


@pytest.mark.parametrize("failure", ["stored_hash", "expanded_hash", "policy", "size", "symlink"])
def test_compacted_data_fails_closed(tmp_path, failure):
    _, manifest = artifacts(tmp_path, ["candidates.json", "graph.json"])
    actual = parser_artifact_path(tmp_path / "graph.json")
    if failure in ("stored_hash", "expanded_hash"):
        actual.write_bytes(gzip.compress(b"{}", mtime=0))
        if failure == "expanded_hash":
            manifest["artifacts"][actual.name] = sha256(actual.read_bytes()).hexdigest()
    elif failure == "policy":
        manifest["parser_profile"].pop("output_policy")
    elif failure == "size":
        manifest["rb2_output"]["graph"]["original_bytes"] = 20_000_001
    else:
        moved = actual.with_name("moved.gz")
        actual.rename(moved)
        actual.symlink_to(moved)
    with pytest.raises(ValueError):
        read_parser_json(tmp_path / "graph.json", manifest=manifest)


def test_plain_catalog_is_not_misidentified_as_a_parser_artifact(tmp_path):
    path = tmp_path / "candidates.json"
    path.write_text('[{"catalog": true}]')
    assert read_parser_json(path) == [{"catalog": True}]
    path.unlink()
    (tmp_path / "rb2-candidates.json.gz").write_bytes(gzip.compress(b"[]"))
    with pytest.raises(ValueError, match="MANIFEST"):
        read_parser_json(tmp_path / "rb2-candidates.json.gz")


def test_w18_reads_compacted_graph_with_existing_manifest_and_scope_guards(tmp_path):
    from proofops_api.w18_source_view import _graph

    directory = tmp_path / "parser-prepared/tenant/version/parse"
    values, _ = artifacts(directory, ["candidates.json", "graph.json"])
    digest = sha256((directory / "manifest.json").read_bytes()).hexdigest()
    row = dict(tenant_id="tenant", prepared_sha256="a" * 64)
    anchor = ("version", "parse", digest, None)
    assert _graph(tmp_path, row, {}, anchor, False) == {"source": values["graph.json"]["blocks"][0]}
    with pytest.raises(ValueError, match="manifest hash"):
        _graph(tmp_path, row, {}, ("version", "parse", "b" * 64, None), False)
    with pytest.raises(ValueError, match="graph scope"):
        _graph(tmp_path, row | dict(prepared_sha256="c" * 64), {}, anchor, False)
