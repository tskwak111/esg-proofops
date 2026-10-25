"""Freeze tag checkpoint contracts before splitting their implementation."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from proofops.adapters.local import tag_store
from proofops.adapters.local.review_store import LocalSQLiteReviewStore
from proofops.application.ports.jobs import JobMessage
from proofops.application.ports.models import ModelBinding
from proofops.application.reviews import ReviewService
from proofops.application.tagging.service import TaggingSettings
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json
from proofops_api.routers.reviews import build_reviews_router

from tests.acceptance.test_preflight import binding
from tests.integration.test_local_tag_runner import TENANT, tag_message, verified_setup
from tests.integration.test_run_lifecycle import client


@pytest.mark.parametrize("facade_first", (False, True), ids=("split-first", "facade-first"))
def test_checkpoint_module_imports_and_reexports(facade_first: bool) -> None:
    modules = ("tag_store", "tag_store_checkpoint")
    if not facade_first:
        modules = tuple(reversed(modules))
    code = "\n".join(f"from proofops.adapters.local import {name}" for name in modules)
    code += "\nfor name in ('tagging_settings', 'tag_pins', 'validate_tag_commit'):\n"
    code += "    assert getattr(tag_store, name) is getattr(tag_store_checkpoint, name)\n"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture
def checkpoint() -> Any:
    extraction = dict.fromkeys(
        (
            "tenant_id",
            "run_id",
            "document_version_id",
            "input_hash",
            "source_sha256",
            "object_version_id",
            "parse_manifest_id",
            "graph_sha256",
            "parse_checkpoint_sha256",
            "manifest_sha256",
            "rule_pack_sha256",
            "model_binding_hash",
            "extraction_profile",
            "extraction_profile_hash",
            "extraction_mode",
        ),
        "fixed",
    )
    extraction.update(discovery={"claims": [{"claim_id": "claim"}]}, coverage={"total": 1})
    raw = canonical_json(extraction).encode()
    digest = sha256(raw).hexdigest()
    snapshot = dict(
        tenant_id=TENANT,
        run_id="00000000-0000-0000-0000-000000000001",
        document={"version_id": "00000000-0000-0000-0000-000000000002"},
        tagging_mode="local_synthetic",
    )
    snapshot["input_hash"] = canonical_hash(snapshot)
    message = JobMessage(
        TENANT,
        snapshot["run_id"],
        snapshot["document"]["version_id"],
        "00000000-0000-0000-0000-000000000003",
        "tag",
        "main",
        snapshot["input_hash"],
    )
    run = dict(extract_job=asdict(replace(message, stage="extract")), claim_snapshot_sha256=digest)
    envelope = tag_store.tag_pins(snapshot, extraction, digest) | dict(
        claims=[dict(claim_id="claim", tag_runs=[], decision=None)],
        coverage=dict(total=1, claims_decided=0, claims_needs_review=1, complete=False),
        stage_status="blocked",
        downstream_status="human_review",
    )
    calls: list[tuple[str, ...]] = []

    def job(db: sqlite3.Connection, msg: JobMessage) -> dict[str, Any]:
        calls.append(("job", msg.tenant_id, msg.run_id, msg.stage))
        return {"artifact_ref": {"key": "extraction", "sha256": digest}}

    def read(db: sqlite3.Connection, *scope: str) -> bytes:
        calls.append(("raw", *scope))
        return raw

    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE run_snapshots (tenant_id TEXT, run_id TEXT, payload TEXT)")
        db.execute(
            "INSERT INTO run_snapshots VALUES (?, ?, ?)",
            (TENANT, snapshot["run_id"], json.dumps(snapshot)),
        )
        yield SimpleNamespace(
            db=db,
            jobs=SimpleNamespace(_job=job, _raw=read),
            run=run,
            message=message,
            envelope=envelope,
            snapshot=snapshot,
            extraction=extraction,
            digest=digest,
            calls=calls,
        )


def _validate(case: Any) -> dict[str, Any]:
    return tag_store.validate_tag_commit(
        case.db, case.jobs, case.run, case.message, case.envelope, None
    )


def test_checkpoint_bytes_hash_and_read_order(checkpoint: Any) -> None:
    before = canonical_json(checkpoint.envelope).encode()
    assert sha256(before).hexdigest() == (
        "e931136eca2fccb99d4840f14dac70c204af03493b775fdc54e535015ccd44d0"
    )
    assert _validate(checkpoint) == dict(
        total=1, claims_decided=0, claims_needs_review=1, complete=False
    )
    assert canonical_json(checkpoint.envelope).encode() == before
    assert checkpoint.calls == [
        ("job", TENANT, checkpoint.message.run_id, "extract"),
        ("raw", TENANT, checkpoint.message.run_id, "artifact", "extraction"),
    ]
    assert tag_store.tag_pins(checkpoint.snapshot, checkpoint.extraction, checkpoint.digest) == {
        **{key: "fixed" for key in checkpoint.extraction if key not in {"coverage", "discovery"}},
        "schema": "local_tag_checkpoint_v1",
        "synthetic": True,
        "claim_snapshot_sha256": checkpoint.digest,
        "tagging_settings": None,
        "tagging_settings_hash": None,
        "tagging_mode": "local_synthetic",
        "validation_profile": "fast_preview",
        "vision_status": "not_run",
    }


@pytest.mark.parametrize("mutation", ("tenant", "input", "pin", "claim", "coverage", "stage"))
def test_commit_error_codes(checkpoint: Any, mutation: str) -> None:
    if mutation == "tenant":
        checkpoint.message = replace(
            checkpoint.message, tenant_id="00000000-0000-0000-0000-000000000004"
        )
    elif mutation == "input":
        checkpoint.message = replace(checkpoint.message, input_hash="a" * 64)
    elif mutation == "pin":
        checkpoint.envelope["source_sha256"] = "tampered"
    elif mutation == "claim":
        checkpoint.envelope["claims"][0]["claim_id"] = "other"
    elif mutation == "coverage":
        checkpoint.envelope["coverage"]["complete"] = True
    else:
        checkpoint.message = replace(checkpoint.message, stage="extract")
    if mutation == "tenant":
        with pytest.raises(KeyError, match="input_hash"):
            _validate(checkpoint)
    else:
        with pytest.raises(ValueError, match="^TAG_CHECKPOINT_INVALID$"):
            _validate(checkpoint)


def test_extraction_hash_error_precedes_pins(
    checkpoint: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(checkpoint.jobs, "_raw", lambda *args: b"tampered")
    with pytest.raises(ValueError, match="^TAG_EXTRACTION_CHECKPOINT_INVALID$"):
        _validate(checkpoint)


def test_original_module_pin_hook(checkpoint: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Any, ...]] = []

    def pins(*args: Any) -> dict[str, Any]:
        calls.append(args)
        return {"hook": "required"}

    monkeypatch.setattr(tag_store, "tag_pins", pins)
    with pytest.raises(ValueError, match="^TAG_CHECKPOINT_INVALID$"):
        _validate(checkpoint)
    assert calls == [(checkpoint.snapshot, checkpoint.extraction, checkpoint.digest)]


def test_original_module_hash_hook(checkpoint: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tag_store, "canonical_hash", lambda value: "hooked")
    with pytest.raises(ValueError, match="^TAG_CHECKPOINT_INVALID$"):
        _validate(checkpoint)


def test_fact_receipt_reader_preserves_none_and_version_error() -> None:
    assert tag_store._fact_assembly_reader(None) is None
    with pytest.raises(ValueError, match="^FACT_ASSEMBLY_VERSION_UNSUPPORTED$"):
        tag_store._fact_assembly_reader({"schema": "unknown"})


@pytest.mark.parametrize("mutation", (None, "hash", "runtime", "binding", "tokens"))
def test_settings_reconstruction_and_errors(mutation: str | None) -> None:
    runtime = binding()
    settings = TaggingSettings(
        ModelBinding(runtime["runtime_binding_id"], "tagger", True),
        runtime["model_id"],
        "local-synthetic-unknown-v1",
        runtime["endpoint_region"],
        "Synthetic only",
        "{}",
        max_tokens=100,
    )
    raw = asdict(settings)
    snapshot = dict(
        tagging_settings=raw,
        tagging_settings_hash=canonical_hash(raw),
        tagging_mode="local_synthetic",
        runtime=runtime,
    )
    if mutation == "hash":
        snapshot["tagging_settings_hash"] = "bad"
    elif mutation == "runtime":
        runtime["status"] = "unapproved"
    elif mutation == "binding":
        raw["binding"]["synthetic"] = False
        snapshot["tagging_settings_hash"] = canonical_hash(raw)
    elif mutation == "tokens":
        raw["max_tokens"] = True
        snapshot["tagging_settings_hash"] = canonical_hash(raw)
    if mutation is None:
        assert tag_store.tagging_settings(snapshot) == settings
    else:
        with pytest.raises(ValueError, match="^TAGGING_PROFILE_MISMATCH$"):
            tag_store.tagging_settings(snapshot)


def test_real_checkpoint_and_review_race_preserve_bytes_and_tenant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, run_id, runner, now, _ = verified_setup(tmp_path, monkeypatch)
    message = tag_message(service, run_id, now[0])
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "needs_review"
    jobs = service.store.jobs
    checkpoint = jobs.read_checkpoint(message)
    assert checkpoint is not None
    digest = sha256(checkpoint).hexdigest()
    assert digest == jobs.get_run(TENANT, run_id)["tag_snapshot_sha256"]
    envelope = runner.tags.load_snapshot(TENANT, run_id)
    assert canonical_json(envelope).encode() == checkpoint
    claim_id = envelope["claims"][0]["claim_id"]
    inputs = runner.tags.load_inputs(TENANT, run_id, claim_id)
    reviews = ReviewService(LocalSQLiteReviewStore(jobs), load_inputs=runner.tags.load_inputs)
    history = reviews.store.history(TENANT, run_id, claim_id)
    with jobs._transaction() as db:
        initial = jobs._raw(db, TENANT, run_id, "tag_revision", f"{claim_id}:0000000001")
    http, auth = client(service)
    http.app.include_router(
        build_reviews_router(
            reviews, auth, allowed_origin="https://testserver", run_store=service.store
        )
    )
    review = http.get(f"/v1/runs/{run_id}/reviews").json()["items"][0]
    body = dict(
        base_tag_revision=1,
        track="performance",
        elements=[asdict(element) for element in inputs.consensus.candidate_elements],
        reason="Preserve unknown elements.",
    )

    def resolve(index: int) -> int:
        with TestClient(http.app, base_url="https://testserver") as competing:
            competing.cookies.update(http.cookies)
            competing.headers.update(http.headers)
            return competing.post(
                f'/v1/reviews/{review["review_id"]}/resolve',
                json=body,
                headers={"If-Match": '"1"', "Idempotency-Key": f"s3-tgs-race-key-{index:04}"},
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(resolve, range(2))) == [200, 412]
    after = reviews.store.history(TENANT, run_id, claim_id)
    assert len(after["tags"]) == 2
    assert after["tags"][0] == history["tags"][0]
    with jobs._transaction() as db:
        assert jobs._raw(db, TENANT, run_id, "tag_revision", f"{claim_id}:0000000001") == initial
    assert jobs.read_checkpoint(message) == checkpoint
    assert jobs.get_run(TENANT, run_id)["tag_snapshot_sha256"] == digest
    assert runner.tags.load_inputs(TENANT, run_id, claim_id).snapshot() == inputs.snapshot()
    with pytest.raises(KeyError):
        runner.tags.load_snapshot(str(uuid4()), run_id)
