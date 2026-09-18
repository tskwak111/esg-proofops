"""Tag checkpoint validation/replay; initial revisions belong to LocalSQLiteReviewStore.

No parallel revision tables. Checkpoints use the existing immutable artifact
pointer and retain the extraction checkpoint digest and frozen run inputs.
"""

import json
from dataclasses import asdict
from hashlib import sha256

from proofops.adapters.cache.aws import CacheNamespace, CacheRequest
from proofops.adapters.local.claim_store import LocalClaimStore
from proofops.adapters.local.run_artifacts import load_run_graph
from proofops.application.budget import TokenUsage
from proofops.application.evidence.binding import ClaimContext
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.ports.jobs import JobMessage
from proofops.application.ports.models import ModelBinding
from proofops.application.reviews import ReviewInputs
from proofops.application.tagging.consensus import form_consensus
from proofops.application.tagging.service import TaggingSettings, TagRun
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.rules.engine import RuleContext, evaluate
from proofops.domain.values import SourceRef, llm_tags_from_dict


def tagging_settings(snapshot):
    raw = snapshot["tagging_settings"]
    settings = TaggingSettings(**(raw | {"binding": ModelBinding(**raw["binding"])}))
    runtime = snapshot["runtime"]
    if (
        canonical_hash(asdict(settings)) != snapshot["tagging_settings_hash"]
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


def tag_pins(snapshot, extraction, extraction_hash):
    return dict(
        schema="local_tag_checkpoint_v1",
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


def validate_tag_commit(db, jobs, run, message, envelope, next_job):
    row = db.execute(
        "SELECT payload FROM run_snapshots WHERE tenant_id=? AND run_id=?",
        (message.tenant_id, message.run_id),
    ).fetchone()
    snapshot = json.loads(row[0]) if row else {}
    extraction_job = jobs._job(db, JobMessage(**run["extract_job"]))
    ref = extraction_job["artifact_ref"]
    raw = jobs._raw(db, message.tenant_id, message.run_id, "artifact", ref["key"])
    if raw is None or sha256(raw).hexdigest() != ref["sha256"]:
        raise ValueError("TAG_EXTRACTION_CHECKPOINT_INVALID")
    extraction = json.loads(raw)
    expected = tag_pins(snapshot, extraction, ref["sha256"])
    claims = envelope["claims"]
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
        or canonical_hash({k: v for k, v in snapshot.items() if k != "input_hash"})
        != message.input_hash
        or (message.tenant_id, message.run_id, message.document_version_id)
        != (snapshot["tenant_id"], snapshot["run_id"], snapshot["document"]["version_id"])
        or run["claim_snapshot_sha256"] != ref["sha256"]
        or any(envelope.get(k) != v for k, v in expected.items())
        or [item["claim_id"] for item in claims] != original_ids
        or envelope["coverage"] != coverage
        or envelope["stage_status"] not in {"blocked", "needs_review", "completed"}
        or envelope["downstream_status"] != "human_review"
        or any(item["tag_runs"] and item.get("review_inputs") is None for item in claims)
        or any(not item["tag_runs"] and item["decision"] is not None for item in claims)
    ):
        raise ValueError("TAG_CHECKPOINT_INVALID")
    # Only the caller holding this same transaction's fence can publish revisions.
    for item in claims:
        if item["tag_runs"]:
            review = item["review_inputs"]
            if (
                review["tag_runs"] != item["tag_runs"]
                or review["decision"] != item["decision"]
                or review["claim"]["claim_id"] != item["claim_id"]
            ):
                raise ValueError("TAG_REVIEW_INPUT_MISMATCH")
    return coverage


class LocalTagStore:
    def __init__(self, store, uploads, parser):
        self.store, self.uploads, self.parser = store, uploads, parser
        self.claims = LocalClaimStore(store, uploads, parser)

    def load_snapshot(self, tenant_id, run_id):
        run = self.store.jobs.get_run(tenant_id, run_id)
        message = JobMessage(**run["tag_job"])
        payload = self.store.jobs.read_checkpoint(message)
        if payload is None or sha256(payload).hexdigest() != run["tag_snapshot_sha256"]:
            raise ValueError("TAG_CHECKPOINT_HASH_MISMATCH")
        envelope = json.loads(payload)
        extraction = self.claims.load_snapshot(tenant_id, run_id)
        snapshot = self.store.snapshot(tenant_id, run_id)
        expected = tag_pins(snapshot, extraction, run["claim_snapshot_sha256"])
        if any(envelope.get(k) != v for k, v in expected.items()):
            raise ValueError("TAG_CHECKPOINT_PIN_MISMATCH")
        return envelope

    def load_inputs(self, tenant_id, run_id, claim_id):
        envelope = self.load_snapshot(tenant_id, run_id)
        item = next((item for item in envelope["claims"] if item["claim_id"] == claim_id), None)
        if item is None or item.get("review_inputs") is None:
            raise KeyError("tagged claim not published")
        raw = item["review_inputs"]
        claim = self.claims.get(tenant_id, run_id, claim_id)
        graph = load_run_graph(
            self.store, self.uploads, self.parser, tenant_id=tenant_id, run_id=run_id
        )
        rulepack = RulePackSnapshot(**self.store.snapshot(tenant_id, run_id)["rulepack"])
        packet = freeze_packet({k: v for k, v in raw["packet"].items() if k != "packet_sha256"})
        original_packet = freeze_packet(
            {k: v for k, v in raw["original_packet"].items() if k != "packet_sha256"}
        )
        context = ClaimContext(
            claim, {k: SourceRef(**v) if v else None for k, v in raw["dimensions"].items()}
        )
        runs = []
        for entry in raw["tag_runs"]:
            request = entry["request"]
            runs.append(
                TagRun(
                    **(
                        entry
                        | dict(
                            request=CacheRequest(
                                **(request | {"namespace": CacheNamespace(**request["namespace"])})
                            ),
                            usage=TokenUsage(**entry["usage"]) if entry["usage"] else None,
                            guarded=llm_tags_from_dict(entry["guarded"])
                            if entry["guarded"]
                            else None,
                            errors=tuple(entry["errors"]),
                            source_scopes=tuple(tuple(v) for v in entry["source_scopes"]),
                            binding_hashes=tuple(tuple(v) for v in entry["binding_hashes"]),
                        )
                    )
                )
            )
        consensus = form_consensus(
            tuple(runs),
            packet=packet,
            rulepack=rulepack,
            tenant_id=tenant_id,
            tag_revision=raw["tag_revision"],
        )
        rule_context = RuleContext(**raw["rule_context"])
        decision = (
            evaluate(consensus.confirmed_tags, rule_context, rulepack)
            if consensus.confirmed_tags
            else None
        )
        inputs = ReviewInputs(
            run_id,
            context,
            graph,
            rulepack,
            rule_context,
            packet,
            original_packet,
            tuple(runs),
            consensus,
            {
                sid: {k: SourceRef(**v) if v else None for k, v in values.items()}
                for sid, values in raw["relation_tags"].items()
            },
            raw["tag_revision"],
            decision,
        )
        inputs.validate()
        if canonical_hash(inputs.snapshot()) != canonical_hash(raw):
            raise ValueError("TAG_REPLAY_MISMATCH")
        return inputs
