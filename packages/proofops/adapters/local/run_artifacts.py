"""Tenant-scoped verified reads of parser inputs and fence-published rich graphs."""

from __future__ import annotations

import json
from dataclasses import asdict
from hashlib import sha256
from importlib.resources import files
from uuid import UUID, uuid5

from proofops.adapters.parsing.opendataloader import ParseFailure
from proofops.application.ingest.graph_fusion import ParserProfile, SourceArtifact
from proofops.application.ports.jobs import JobMessage
from proofops.domain.provenance import canonical_hash


def load_run_inputs(store, uploads, *, tenant_id: str, run_id: str):
    snapshot = store.snapshot(tenant_id, run_id)
    frozen = {key: value for key, value in snapshot.items() if key != "input_hash"}
    if (snapshot["tenant_id"], snapshot["run_id"]) != (tenant_id, run_id) or (
        canonical_hash(frozen) != snapshot["input_hash"]
    ):
        raise ParseFailure("RUN_INPUT_INTEGRITY_MISMATCH")
    document = snapshot["document"]
    if uploads.version_snapshot(tenant_id, document["version_id"]) != document:
        raise ParseFailure("DOCUMENT_VERSION_MISMATCH")
    content = uploads.read_original(tenant_id, document["version_id"])
    if sha256(content).hexdigest() != document["sha256"]:
        raise ParseFailure("SOURCE_INTEGRITY_MISMATCH")
    source = SourceArtifact(
        tenant_id,
        document["document_id"],
        document["version_id"],
        document["sha256"],
        document["object_version_id"],
        content,
    )
    pages = snapshot["selected_pages"]
    if not pages or any(type(p) is not int or not 1 <= p <= document["page_count"] for p in pages):
        raise ParseFailure("PAGE_SELECTION_INVALID")
    try:
        profile = ParserProfile(
            parse_manifest_id=str(uuid5(UUID(run_id), "parse:" + snapshot["input_hash"])),
            physical_pages=tuple(pages),
            **snapshot["parser_profile"],
        )
    except (ValueError, TypeError, KeyError):
        raise ParseFailure("PARSER_CONFIG_INVALID") from None
    if (
        profile.config_snapshot() != snapshot["parser_profile"]
        or profile.config_hash() != snapshot["parser_profile_hash"]
    ):
        raise ParseFailure("RUN_INPUT_INTEGRITY_MISMATCH")
    return snapshot, source, profile


def checkpoint_note_reviews(envelope):
    """Versioned checkpoint shape; legacy readers must never silently discard notes."""
    schema = envelope.get("schema")
    if any(key.startswith("native_paragraph_") for key in envelope):
        if schema != "local_parser_checkpoint_v4":
            raise ParseFailure("NATIVE_PARAGRAPH_CHECKPOINT_INVALID")
    if schema == "local_parser_checkpoint_v1":
        if {"runtime_note_review_artifacts", "graph_sha256"} & envelope.keys():
            raise ParseFailure("NOTE_REVIEW_CHECKPOINT_INVALID")
        return ()
    if schema not in {
        "local_parser_checkpoint_v2",
        "local_parser_checkpoint_v3",
        "local_parser_checkpoint_v4",
    }:
        raise ParseFailure("PARSER_CHECKPOINT_SCHEMA_UNSUPPORTED")
    artifacts = envelope.get("runtime_note_review_artifacts")
    digest = envelope.get("graph_sha256")
    if schema == "local_parser_checkpoint_v4" and artifacts is None:
        artifacts = []
    if (
        not isinstance(artifacts, list)
        or (
            not artifacts
            and schema not in {"local_parser_checkpoint_v3", "local_parser_checkpoint_v4"}
        )
        or any(not isinstance(item, str) for item in artifacts)
        or len(set(artifacts)) != len(artifacts)
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise ParseFailure("NOTE_REVIEW_CHECKPOINT_INVALID")
    return tuple(artifacts)


def native_paragraph_policy():
    local = files("proofops.adapters.local")
    return dict(
        mode="paragraph_native_v1",
        verifier_sha256=sha256(local.joinpath("source_verification.py").read_bytes()).hexdigest(),
        rendered_reader_sha256=sha256(local.joinpath("native_ocr.swift").read_bytes()).hexdigest(),
        normalization_sha256=sha256(
            files("proofops.application.evidence").joinpath("citations.py").read_bytes()
        ).hexdigest(),
    )


def checkpoint_native_attestation(envelope):
    """Versioned native receipt shape; v1-v3 carry no native attestation."""
    schema = envelope.get("schema")
    if schema != "local_parser_checkpoint_v4":
        if any(key.startswith("native_paragraph_") for key in envelope):
            raise ParseFailure("NATIVE_PARAGRAPH_CHECKPOINT_INVALID")
        return None
    receipt = envelope.get("native_paragraph_attestation")
    policy_digest = envelope.get("native_paragraph_policy_sha256")
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema") != "native_paragraph_attestation_v1"
        or not isinstance(receipt.get("records"), list)
        or not isinstance(receipt.get("artifact_sha256"), str)
        or len(receipt["artifact_sha256"]) != 64
        or any(c not in "0123456789abcdef" for c in receipt["artifact_sha256"])
        or not isinstance(receipt.get("tenant_id"), str)
        or not isinstance(receipt.get("document_version_id"), str)
        or not isinstance(receipt.get("parse_manifest_id"), str)
        or not isinstance(receipt.get("source_sha256"), str)
        or not isinstance(receipt.get("input_graph_sha256"), str)
        or policy_digest != canonical_hash(native_paragraph_policy())
    ):
        raise ParseFailure("NATIVE_PARAGRAPH_CHECKPOINT_INVALID")
    return receipt


def validate_automatic_note_reviews(graph, artifacts, policy, *, selected_pages=None):
    if (
        not isinstance(policy, dict)
        or set(policy) != {"mode", "model", "extractor_sha256", "batch_sha256"}
        or policy["mode"] not in {"automatic_v1", "automatic_pages_v2"}
    ):
        raise ParseFailure("NOTE_REVIEW_POLICY_MISMATCH")
    tables = {b.source_id for b in graph.blocks if b.kind == "table"}
    pages = {b.page_num for b in graph.blocks if b.kind == "table"}
    if policy["mode"] == "automatic_pages_v2":
        if (
            not selected_pages
            or any(type(p) is not int or p < 1 for p in selected_pages)
            or len(set(selected_pages)) != len(selected_pages)
            or not pages <= set(selected_pages)
        ):
            raise ParseFailure("NOTE_REVIEW_PAGE_COVERAGE_MISMATCH")
        pages = set(selected_pages)
    covered = set()
    covered_pages = set()
    for artifact in artifacts:
        raw = json.loads(artifact)
        page = raw["packet"]["untrusted_document_data"]["page"]
        if type(page) is not int or page not in pages or page in covered_pages:
            raise ParseFailure("NOTE_REVIEW_PAGE_COVERAGE_MISMATCH")
        covered_pages.add(page)
        covered.update(raw["packet"]["table_ids"])
        for request in raw["extracted"].get("requests", []):
            if (
                request.get("model") != policy["model"]
                or request.get("helper_sha256") != policy["extractor_sha256"]
            ):
                raise ParseFailure("NOTE_REVIEW_POLICY_MISMATCH")
    if covered != tables or covered_pages != pages or len(artifacts) != len(pages):
        raise ParseFailure("NOTE_REVIEW_TABLE_COVERAGE_MISMATCH")


def load_run_graph(store, uploads, parser, *, tenant_id: str, run_id: str):
    return load_run_evidence(store, uploads, parser, tenant_id=tenant_id, run_id=run_id)["graph"]


def load_run_evidence(store, uploads, parser, *, tenant_id: str, run_id: str):
    """Only committed pointers publish evidence; private prepared files are insufficient."""
    snapshot, source, profile = load_run_inputs(store, uploads, tenant_id=tenant_id, run_id=run_id)
    run = store.jobs.get_run(tenant_id, run_id)
    if "parse_job" not in run:
        raise ParseFailure("PARSE_NOT_PUBLISHED")
    message = JobMessage(**run["parse_job"])
    if (
        message.tenant_id,
        message.run_id,
        message.document_version_id,
        message.stage,
        message.input_hash,
    ) != (tenant_id, run_id, source.document_version_id, "parse", snapshot["input_hash"]):
        raise ParseFailure("RUN_INPUT_INTEGRITY_MISMATCH")
    payload = store.jobs.read_checkpoint(message)
    if payload is None:
        raise ParseFailure("PARSE_NOT_PUBLISHED")
    envelope = json.loads(payload)
    note_reviews = checkpoint_note_reviews(envelope)
    native_receipt = checkpoint_native_attestation(envelope)
    policy = store.jobs.parser_note_policy(message)
    native_policy = store.jobs.parser_native_policy(message)
    if native_policy is not None:
        if (
            envelope.get("schema") != "local_parser_checkpoint_v4"
            or envelope.get("native_paragraph_policy_sha256") != canonical_hash(native_policy)
            or native_receipt is None
        ):
            raise ParseFailure("NATIVE_PARAGRAPH_POLICY_MISMATCH")
    elif envelope.get("schema") == "local_parser_checkpoint_v4" or (native_receipt is not None):
        raise ParseFailure("NATIVE_PARAGRAPH_POLICY_MISMATCH")
    if policy is not None:
        if envelope.get("schema") not in {
            "local_parser_checkpoint_v3",
            "local_parser_checkpoint_v4",
        } or envelope.get("note_review_policy_sha256") != canonical_hash(policy):
            raise ParseFailure("NOTE_REVIEW_POLICY_MISMATCH")
    elif (
        envelope.get("schema") == "local_parser_checkpoint_v3"
        or "note_review_policy_sha256" in envelope
    ):
        raise ParseFailure("NOTE_REVIEW_POLICY_MISMATCH")
    pinned = store.jobs.parser_note_reviews(message)
    if ((note_reviews or policy is not None) and pinned is None) or (
        pinned is not None and note_reviews != pinned
    ):
        raise ParseFailure("NOTE_REVIEW_CHECKPOINT_INPUT_MISMATCH")
    if (
        envelope["tenant_id"],
        envelope["run_id"],
        envelope["document_version_id"],
        envelope["input_hash"],
        envelope["parse_manifest_id"],
        envelope["source_sha256"],
        envelope["object_version_id"],
    ) != (
        tenant_id,
        run_id,
        source.document_version_id,
        snapshot["input_hash"],
        profile.parse_manifest_id,
        source.sha256,
        source.object_version_id,
    ):
        raise ParseFailure("RUN_INPUT_INTEGRITY_MISMATCH")
    graph = parser.load_verified(
        source, profile, tenant_id=tenant_id, manifest_sha256=envelope["manifest_sha256"]
    )
    base_graph = graph
    if note_reviews:
        from proofops.adapters.local.table_notes import replay_note_reviews

        try:
            graph = replay_note_reviews(note_reviews, graph, source.content, tenant_id=tenant_id)
        except (ValueError, TypeError, KeyError):
            raise ParseFailure("NOTE_REVIEW_REPLAY_INVALID") from None
    if native_receipt is not None:
        from proofops.adapters.local.source_verification import replay_native_sources

        try:
            graph = replay_native_sources(
                native_receipt, graph, source.content, tenant_id=tenant_id
            )
        except (ValueError, TypeError, KeyError):
            raise ParseFailure("NATIVE_PARAGRAPH_REPLAY_INVALID") from None
    if note_reviews or policy is not None or native_receipt is not None:
        if canonical_hash(asdict(graph)) != envelope["graph_sha256"]:
            raise ParseFailure("NOTE_REVIEW_GRAPH_MISMATCH")
    if policy is not None:
        validate_automatic_note_reviews(
            graph, note_reviews, policy, selected_pages=profile.physical_pages
        )
    return dict(
        graph=graph,
        base_graph=base_graph,
        source=source,
        note_reviews=note_reviews,
        native_attestation=native_receipt,
        input_hash=snapshot["input_hash"],
        parse_checkpoint_sha256=sha256(payload).hexdigest(),
    )
