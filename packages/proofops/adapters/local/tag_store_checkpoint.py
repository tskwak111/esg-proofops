"""Frozen tagging settings, checkpoint pins and transactional commit validation.

Resolve shared hooks through tag_store at call time to preserve its patch surface
without a runtime import cycle when this module is imported first.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3
    from typing import Any

    from proofops.adapters.local.job_store import LocalSQLiteJobStore
    from proofops.application.ports.jobs import JobMessage
    from proofops.application.tagging.service import TaggingSettings


def tagging_settings(
    snapshot: dict[str, Any], *, preliminary: bool = False, relation: bool = False
) -> TaggingSettings:
    from proofops.adapters.local import tag_store as _tag_store

    if preliminary and relation:
        raise ValueError("TAGGING_PROFILE_MISMATCH")
    from proofops.application.tagging.decisions import (
        validate_decision_snapshot as _validate_decision_snapshot,
    )

    validate_decision_snapshot: Callable[..., None] = _validate_decision_snapshot

    validate_decision_snapshot(snapshot)
    prefix = "relation" if relation else "preliminary" if preliminary else "tagging"
    if prefix + "_settings" not in snapshot:
        raise ValueError("TAGGING_PROFILE_MISMATCH")
    raw = snapshot[prefix + "_settings"]
    settings = _tag_store.TaggingSettings(
        **(raw | {"binding": _tag_store.ModelBinding(**raw["binding"])})
    )
    if snapshot.get("tagging_mode") == "upstage_local":
        from proofops.application.registry import artifact_sha256

        runtime = snapshot[prefix + "_runtime"]
        if (
            _tag_store.canonical_hash(raw) != snapshot[prefix + "_settings_hash"]
            or artifact_sha256(runtime) != snapshot[prefix + "_runtime_artifact_hash"]
            or settings.binding.synthetic is not False
            or settings.binding.binding_id != runtime["runtime_binding_id"]
            or settings.binding.role != "tagger"
            or settings.model_id != runtime["model_id"]
            or runtime.get("tagging_settings_sha256") != _tag_store.canonical_hash(raw)
            or runtime.get("input_reservation_policy_sha256")
            != snapshot["input_reservation_policy_hash"]
            or _tag_store.canonical_hash(snapshot["input_reservation_policy"])
            != snapshot["input_reservation_policy_hash"]
        ):
            raise ValueError("TAGGING_PROFILE_MISMATCH")
        if relation and not _tag_store.relation_settings_contract_valid(settings):
            raise ValueError("TAGGING_PROFILE_MISMATCH")
        return settings
    if preliminary or relation:
        raise ValueError("PRELIMINARY_PROFILE_UNSUPPORTED")
    runtime = snapshot["runtime"]
    if (
        _tag_store.canonical_hash(raw) != snapshot["tagging_settings_hash"]
        or snapshot["tagging_mode"] != "local_synthetic"
        or not settings.binding.synthetic
        or settings.binding.binding_id != runtime["runtime_binding_id"]
        or settings.binding.role != runtime["role"]
        or (settings.model_id, settings.region) != (runtime["model_id"], runtime["endpoint_region"])
        or runtime["status"] != "approved"
        or type(settings.max_tokens) is not int
        or not 1 <= settings.max_tokens <= runtime["max_output_tokens"]
    ):
        raise ValueError("TAGGING_PROFILE_MISMATCH")
    return settings


def tag_pins(
    snapshot: dict[str, Any], extraction: dict[str, Any], extraction_hash: str
) -> dict[str, Any]:
    from proofops.adapters.local import tag_store as _tag_store
    from proofops.application.evidence.relation_attribution import (
        snapshot_policy as _snapshot_policy,
    )

    snapshot_policy = _snapshot_policy

    attribution = snapshot_policy(snapshot)
    pins = dict(
        schema="local_tag_checkpoint_v1",
        synthetic=snapshot.get("tagging_mode") != "upstage_local",
        **{
            key: extraction[key]
            for key in (
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
            )
        },
        claim_snapshot_sha256=extraction_hash,
        tagging_settings=snapshot.get("tagging_settings"),
        tagging_settings_hash=snapshot.get("tagging_settings_hash"),
        tagging_mode=snapshot.get("tagging_mode"),
        validation_profile="fast_preview",
        vision_status="not_run",
    )
    if attribution is not None:
        pins.update(
            relation_attribution_policy=attribution,
            relation_attribution_policy_sha256=_tag_store.canonical_hash(attribution),
        )
    if snapshot.get("tagging_mode") == "upstage_local":
        pins.update(
            **{
                key: snapshot[key]
                for key in (
                    "preliminary_settings",
                    "preliminary_settings_hash",
                    "preliminary_runtime",
                    "preliminary_runtime_artifact_hash",
                    "tagging_runtime",
                    "tagging_runtime_artifact_hash",
                    "input_reservation_policy",
                    "input_reservation_policy_hash",
                    "rulepack_use",
                )
            }
        )
        relation_keys = (
            "relation_settings",
            "relation_settings_hash",
            "relation_runtime",
            "relation_runtime_artifact_hash",
        )
        if any(key in snapshot for key in relation_keys):
            if not all(key in snapshot for key in relation_keys):
                raise ValueError("TAG_CHECKPOINT_PIN_MISMATCH")
            pins.update({key: snapshot[key] for key in relation_keys})
    elif any(
        key in snapshot
        for key in (
            "relation_settings",
            "relation_settings_hash",
            "relation_runtime",
            "relation_runtime_artifact_hash",
        )
    ):
        raise ValueError("TAG_CHECKPOINT_PIN_MISMATCH")
    from proofops.application.tagging.decisions import (
        validate_decision_snapshot as _validate_decision_snapshot,
    )

    validate_decision_snapshot: Callable[..., None] = _validate_decision_snapshot

    validate_decision_snapshot(snapshot)
    if "decision_settings" in snapshot:
        pins.update(
            {
                key: snapshot[key]
                for key in (
                    "decision_settings",
                    "decision_settings_hash",
                    "decision_runtimes",
                    "decision_runtime_hashes",
                )
            }
        )
    if "pipeline_profile" in snapshot:
        pins["pipeline_profile"] = snapshot["pipeline_profile"]
        if snapshot["pipeline_profile"] in ("finals-unattended-v1", "finals-unattended-v2"):
            from proofops.application.analysis_profile import policy_for as _policy_for

            policy_for: Callable[..., dict[str, Any]] = _policy_for

            policy = policy_for(
                snapshot["pipeline_profile"],
                pinned_hash=snapshot.get("analysis_profile_policy_sha256"),
            )
            policy_hash = _tag_store.canonical_hash(policy)

            if (
                snapshot.get("analysis_profile_policy") != policy
                or snapshot.get("analysis_profile_policy_sha256") != policy_hash
            ):
                raise ValueError("ANALYSIS_PROFILE_PIN_MISMATCH")
            pins["analysis_profile_policy_sha256"] = policy_hash
    if "fact_assembly_profile" in snapshot:
        pins["fact_assembly_profile"] = snapshot["fact_assembly_profile"]
    if "report_level_link" in snapshot:
        pins["report_level_link"] = snapshot["report_level_link"]
    return pins


def validate_tag_commit(
    db: sqlite3.Connection,
    jobs: LocalSQLiteJobStore,
    run: dict[str, Any],
    message: JobMessage,
    envelope: dict[str, Any],
    next_job: JobMessage | None,
) -> dict[str, Any]:
    from proofops.adapters.local import tag_store as _tag_store

    row = db.execute(
        "SELECT payload FROM run_snapshots WHERE tenant_id=? AND run_id=?",
        (message.tenant_id, message.run_id),
    ).fetchone()
    snapshot = _tag_store.json.loads(row[0]) if row else {}
    extraction_job = jobs._job(db, _tag_store.JobMessage(**run["extract_job"]))
    ref = extraction_job["artifact_ref"]
    raw = jobs._raw(db, message.tenant_id, message.run_id, "artifact", ref["key"])
    if raw is None or _tag_store.sha256(raw).hexdigest() != ref["sha256"]:
        raise ValueError("TAG_EXTRACTION_CHECKPOINT_INVALID")
    extraction = _tag_store.json.loads(raw)
    expected = _tag_store.tag_pins(snapshot, extraction, ref["sha256"])
    claims = envelope["claims"]
    unattended = snapshot.get("pipeline_profile") in (
        "unattended-v1",
        "finals-unattended-v1",
        "finals-unattended-v2",
    )
    original_ids = [c["claim_id"] for c in extraction["discovery"]["claims"]]
    decided = sum(
        item["decision"] is not None and item["decision"]["decision_status"] == "decided"
        for item in claims
    )
    coverage = dict(
        extraction["coverage"],
        claims_decided=decided,
        claims_needs_review=len(claims) - decided,
        complete=False,
    )
    if (
        message.stage != "tag"
        or next_job is not None
        or message.input_hash != snapshot["input_hash"]
        or _tag_store.canonical_hash({k: v for k, v in snapshot.items() if k != "input_hash"})
        != message.input_hash
        or (message.tenant_id, message.run_id, message.document_version_id)
        != (snapshot["tenant_id"], snapshot["run_id"], snapshot["document"]["version_id"])
        or run["claim_snapshot_sha256"] != ref["sha256"]
        or any(envelope.get(k) != v for k, v in expected.items())
        or [item["claim_id"] for item in claims] != original_ids
        or envelope["coverage"] != coverage
        or envelope["stage_status"] not in {"blocked", "needs_review", "completed"}
        or envelope["downstream_status"] != "human_review"
        or (
            not unattended
            and any(item["tag_runs"] and item.get("review_inputs") is None for item in claims)
        )
        or any(not item["tag_runs"] and item["decision"] is not None for item in claims)
    ):
        raise ValueError("TAG_CHECKPOINT_INVALID")
    # Only the caller holding this same transaction's fence can publish revisions.
    for item in claims:
        if unattended:
            if (
                item.get("decision") is not None
                or item.get("review_inputs") is not None
                or item.get("provisional_grade", {}).get("decision_status") != "provisional"
                or item.get("source_status", {}).get("status") not in {"verified", "unverified"}
            ):
                raise ValueError("UNATTENDED_CHECKPOINT_INVALID")
            continue
        if item["tag_runs"]:
            review = item["review_inputs"]
            if (
                review["tag_runs"] != item["tag_runs"]
                or review["decision"] != item["decision"]
                or review["claim"]["claim_id"] != item["claim_id"]
            ):
                raise ValueError("TAG_REVIEW_INPUT_MISMATCH")
    return coverage
