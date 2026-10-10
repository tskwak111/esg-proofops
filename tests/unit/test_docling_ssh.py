import gzip
import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
from proofops.adapters.parsing import docling_ssh
from proofops.adapters.parsing.docling_document import convert_pages
from proofops.adapters.parsing.docling_gpu_child import page_document
from proofops.adapters.parsing.opendataloader import ParseFailure
from proofops.domain.provenance import canonical_hash

from tests.unit.test_docling_parser import fixture


@pytest.mark.parametrize("target", ["-x", "user@host;command", "user@host/path", "user@$(cmd)"])
def test_ssh_target_cannot_inject_commands(target):
    _, profile, _, _, _ = fixture()
    with pytest.raises(ValueError):
        replace(profile, docling_ssh_target=target)


def test_cpu_hash_is_unchanged_and_gpu_hash_is_distinct():
    _, profile, _, _, _ = fixture()
    assert "docling_ssh_target" not in profile.invocation_snapshot()
    assert (
        replace(profile, docling_ssh_target="parser@gpu.example.internal").config_hash()
        != profile.config_hash()
    )


def test_picture_children_are_not_dropped_by_page_projection():
    raw = dict(
        pages={"1": {"size": {}}},
        texts=[
            dict(
                text="native picture text", parent={"$ref": "#/pictures/0"}, prov=[dict(page_no=1)]
            )
        ],
        pictures=[],
        tables=[],
    )
    assert page_document(raw, 1)["texts"] == raw["texts"]


def test_gpu_options_cannot_masquerade_as_cpu():
    source, profile, pages, _, _ = fixture()
    pages["1"]["options"] = dict(pages["1"]["options"], device="cuda", num_threads=16)
    with pytest.raises(ParseFailure, match="CONFIG_MISMATCH"):
        convert_pages(pages, source, profile)
    assert convert_pages(pages, source, replace(profile, docling_ssh_target="user5@host"))


def test_receipt_cache_rejects_tamper_without_connecting(tmp_path, monkeypatch):
    source, profile, pages, _, _ = fixture()
    profile = replace(profile, docling_ssh_target="user5@host")
    worker_hash = sha256(
        Path(docling_ssh.__file__).with_name("docling_gpu_child.py").read_bytes()
    ).hexdigest()
    identity = dict(
        source=source.sha256,
        pages=[1],
        worker_sha256=worker_hash,
        target=profile.docling_ssh_target,
        runtime="a100-mig-40gb-v2",
    )
    directory = tmp_path / "docling-gpu-cache" / source.tenant_id
    directory.mkdir(parents=True)
    cache = directory / (canonical_hash(identity) + ".json.gz")
    envelope = dict(
        source_sha256=source.sha256,
        worker_sha256=worker_hash,
        pages=pages,
        docling_version="2.137.0",
    )
    envelope["payload_sha256"] = canonical_hash(envelope)
    cache.write_bytes(gzip.compress(json.dumps(envelope).encode()))
    monkeypatch.setattr(docling_ssh, "_run", lambda *a, **k: pytest.fail("unexpected network"))
    assert docling_ssh.fetch_pages(source, profile, (1,), tmp_path)["pages"] == pages
    envelope["pages"]["1"]["chars"] = []
    cache.write_bytes(gzip.compress(json.dumps(envelope).encode()))
    with pytest.raises(ParseFailure, match="CACHE_INTEGRITY"):
        docling_ssh.fetch_pages(source, profile, (1,), tmp_path)


def test_decompression_is_bounded(tmp_path, monkeypatch):
    source, profile, _, _, _ = fixture()
    profile = replace(profile, docling_ssh_target="user5@host", max_output_bytes=100)
    worker_hash = sha256(
        Path(docling_ssh.__file__).with_name("docling_gpu_child.py").read_bytes()
    ).hexdigest()
    identity = dict(
        source=source.sha256,
        pages=[1],
        worker_sha256=worker_hash,
        target=profile.docling_ssh_target,
        runtime="a100-mig-40gb-v2",
    )
    directory = tmp_path / "docling-gpu-cache" / source.tenant_id
    directory.mkdir(parents=True)
    (directory / (canonical_hash(identity) + ".json.gz")).write_bytes(gzip.compress(b"x" * 10000))
    with pytest.raises(ParseFailure, match="OUTPUT_LIMIT"):
        docling_ssh.fetch_pages(source, profile, (1,), tmp_path)
