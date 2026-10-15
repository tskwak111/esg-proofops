"""Bounded C3 local lifecycle on the existing immutable SQLite revision store."""

import json
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local.c3_source import replay as replay_source
from proofops.adapters.local.review_store import LocalSQLiteReviewStore
from proofops.adapters.local.run_store import LocalSQLiteRunStore
from proofops.adapters.local.tag_store import _fact_assembly_reader
from proofops.application.claims import Claim, ExtractionProfile, ExtractionReceipt
from proofops.application.evidence.binding import ClaimContext
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.exports import encode_revision_record
from proofops.application.ingest.graph_fusion import (
    QualityIssue,
    candidates_from_snapshot,
    fuse_candidates,
)
from proofops.application.reviews import ReviewInputs, ReviewService
from proofops.application.tagging.fact_assembly_c3 import PROFILE
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.rules.engine import RuleContext
from proofops.domain.values import SourceRef


def _profile_module(profile, *, pinned_hash=None):
    if profile == PROFILE:
        from proofops.application.tagging import fact_assembly_c3 as module

        return module
    from proofops.application.tagging.fact_assembly_c3_v2 import PROFILE as C3_V2_PROFILE

    if profile == C3_V2_PROFILE:
        from proofops.application.tagging import fact_assembly_c3_v2 as module

        if pinned_hash == module.legacy.POLICY_HASH:
            return module.legacy
        return module
    raise ValueError("C3_PUBLICATION_PROFILE_UNKNOWN")


class LocalC3Publication:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_symlink() or any(
            (self.path / name).is_symlink()
            for name in ("state.sqlite3", "original.pdf", "c3-evidence.json", "pilot.json")
        ):
            raise ValueError("C3_UNSAFE_ARTIFACT_PATH")
        self.runs = LocalSQLiteRunStore(self.path / "state.sqlite3")
        self.store = LocalSQLiteReviewStore(self.runs.jobs)
        self.service = ReviewService(self.store, load_inputs=self.load_inputs)

    def initialize(self, case, receipt, *, source, parser_artifact, profile=None):
        claim, graph = case["context"].claim, case["graph"]
        receipt_data = receipt.to_dict()
        profile = profile or receipt_data.get("policy", {}).get("profile", PROFILE)
        module = _profile_module(profile)
        if receipt_data.get("policy_sha256") != module.POLICY_HASH:
            raise ValueError("C3_CURRENT_POLICY_REQUIRED")
        consensus, decision = module.publication_values(
            receipt_data, rulepack=case["rulepack"], tag_revision=1
        )
        run_id = case["packet"].to_dict()["run_id"]
        inputs = ReviewInputs(
            run_id,
            case["context"],
            graph,
            case["rulepack"],
            RuleContext(
                claim.tenant_id,
                claim.document_version_id,
                claim.claim_id,
                case["packet"].packet_sha256,
            ),
            case["packet"],
            case["original_packet"],
            (),
            consensus,
            {},
            decision=decision,
            fact_assembly_profile=profile,
            fact_assembly_receipt=receipt,
        )
        inputs.validate()
        if sha256(source).hexdigest() != graph.source_sha256:
            raise ValueError("C3_SOURCE_HASH_MISMATCH")
        evidence = dict(parser_artifact=parser_artifact, source_receipt=case["source_receipt"])
        snapshot = dict(
            tenant_id=claim.tenant_id,
            run_id=run_id,
            document=dict(version_id=claim.document_version_id, sha256=graph.source_sha256),
            rulepack=asdict(case["rulepack"]),
            analysis_profile_policy=module.POLICY,
            analysis_profile_policy_sha256=module.POLICY_HASH,
            c3_evidence_sha256=canonical_hash(evidence),
        )
        snapshot["input_hash"] = canonical_hash(snapshot)
        for name, content in (
            ("original.pdf", source),
            ("c3-evidence.json", json.dumps(evidence, ensure_ascii=False).encode()),
        ):
            target = self.path / name
            if target.exists():
                if target.read_bytes() != content:
                    raise ValueError("C3_IMMUTABLE_ARTIFACT_CONFLICT")
            else:
                target.write_bytes(content)
        with self.runs.jobs._transaction() as db:
            prior = db.execute(
                "SELECT payload FROM run_snapshots WHERE tenant_id=? AND run_id=?",
                (claim.tenant_id, run_id),
            ).fetchone()
            if prior and canonical_hash(json.loads(prior[0])) != canonical_hash(snapshot):
                raise ValueError("C3_RUN_SNAPSHOT_CONFLICT")
            if not prior:
                db.execute(
                    "INSERT INTO run_snapshots VALUES (?, ?, ?)",
                    (claim.tenant_id, run_id, json.dumps(snapshot)),
                )
        try:
            self.runs.jobs.get_run(claim.tenant_id, run_id)
        except KeyError:
            self.runs.jobs.create_run(claim.tenant_id, run_id, claim.document_version_id)
        return self.service.publish(inputs)

    def load_inputs(self, tenant, run, claim_id):
        frozen = self.runs.snapshot(tenant, run)
        profile = frozen.get("analysis_profile_policy", {}).get("profile")
        module = _profile_module(profile, pinned_hash=frozen.get("analysis_profile_policy_sha256"))
        policy = module.publication_policy_for(
            profile, pinned_hash=frozen.get("analysis_profile_policy_sha256")
        )
        if (self.path / "original.pdf").is_symlink() or (
            self.path / "c3-evidence.json"
        ).is_symlink():
            raise ValueError("C3_UNSAFE_ARTIFACT_PATH")
        if (
            frozen.get("analysis_profile_policy") != policy
            or frozen.get("analysis_profile_policy_sha256") != module.POLICY_HASH
            or frozen.get("input_hash")
            != canonical_hash({k: v for k, v in frozen.items() if k != "input_hash"})
        ):
            raise ValueError("C3_FROZEN_POLICY_MISMATCH")
        history = self.store.history(tenant, run, claim_id)
        raw = history["tags"][0]["inputs"]
        evidence = json.loads((self.path / "c3-evidence.json").read_text())
        if canonical_hash(evidence) != frozen["c3_evidence_sha256"]:
            raise ValueError("C3_EVIDENCE_HASH_MISMATCH")
        d = evidence["parser_artifact"]
        graph = fuse_candidates(candidates_from_snapshot(d["candidates"]), tenant_id=tenant)
        graph = replace(graph, issues=tuple(QualityIssue(**i) for i in d["issues"]))
        graph = replay_source(
            evidence["source_receipt"],
            graph,
            (self.path / "original.pdf").read_bytes(),
            tenant_id=tenant,
            run_id=run,
        )
        value = raw["claim"]
        extraction = value["receipt"]
        claim = Claim(
            **(
                value
                | dict(
                    source_refs=tuple(SourceRef(**r) for r in value["source_refs"]),
                    topic_ids=tuple(value["topic_ids"]),
                    receipt=ExtractionReceipt(
                        **(extraction | dict(profile=ExtractionProfile(**extraction["profile"])))
                    ),
                )
            )
        )
        if (
            claim.tenant_id != tenant
            or claim.claim_id != claim_id
            or raw["run_id"] != run
            or frozen["document"]
            != dict(version_id=graph.document_version_id, sha256=graph.source_sha256)
        ):
            raise ValueError("C3_SCOPE_MISMATCH")
        packet = freeze_packet({k: v for k, v in raw["packet"].items() if k != "packet_sha256"})
        original = freeze_packet(
            {k: v for k, v in raw["original_packet"].items() if k != "packet_sha256"}
        )
        pack = RulePackSnapshot(**frozen["rulepack"])
        receipt = _fact_assembly_reader(raw["fact_assembly_receipt"])
        consensus, decision = module.publication_values(
            receipt.to_dict(), rulepack=pack, tag_revision=raw["tag_revision"]
        )
        inputs = ReviewInputs(
            run,
            ClaimContext(claim, {}),
            graph,
            pack,
            RuleContext(**raw["rule_context"]),
            packet,
            original,
            (),
            consensus,
            {},
            tag_revision=raw["tag_revision"],
            decision=decision,
            fact_assembly_profile=profile,
            fact_assembly_receipt=receipt,
        )
        inputs.validate()
        if canonical_hash(inputs.snapshot()) != canonical_hash(raw):
            raise ValueError("C3_STORED_INPUT_REPLAY_MISMATCH")
        return inputs

    def result(self, tenant, run, claim_id):
        inputs = self.load_inputs(tenant, run, claim_id)
        history = self.store.history(tenant, run, claim_id)
        tag, record = history["tags"][-1], history["decisions"][-1]
        decision = record["api"] | dict(excluded_elements=record["decision"]["excluded_elements"])
        auto = tag["origin"] == "consensus"
        claim = inputs.context.claim
        module = _profile_module(
            inputs.fact_assembly_profile,
            pinned_hash=inputs.fact_assembly_receipt.to_dict()["policy_sha256"],
        )
        version = "c3_v1" if inputs.fact_assembly_profile == PROFILE else "c3_v2"
        return dict(
            schema="r108-hosted-result-v1",
            page_map=[36],
            hold_reasons=[],
            pipeline=dict(status="completed"),
            reviews=[self.store.get(tenant, self.service._review(inputs)["review_id"])],
            claims=[
                claim.to_summary()
                | dict(
                    page_num=1,
                    original_page_num=36,
                    track="management",
                    decision=decision,
                    source_refs=[asdict(r) for r in claim.source_refs],
                    source_quality=claim.source_quality,
                    source_ref_page_space="original",
                    elements=tag["elements"],
                    revision=tag["tag_revision"],
                    hold_reason=None,
                    possible_grade_range=decision.get("grade_range"),
                    confirmed_grade=decision.get("evidence_grade"),
                    confirmed_label=decision.get("label"),
                    confirmation_source=f"auto_direct_certification_{version}"
                    if auto
                    else "human_review",
                    confirmation_policy_sha256=module.POLICY_HASH,
                    confirmation_display=module.DISPLAY
                    if auto
                    else "사람 태깅 검토 후 Python 재판정",
                    confirmation_basis=module.DISPLAY.split(" — ", 1)[1] if auto else None,
                    missing_evidence=[],
                )
            ],
        )

    def export(self, tenant, run, claim_id):
        inputs = self.load_inputs(tenant, run, claim_id)
        history = self.store.history(tenant, run, claim_id)
        return encode_revision_record(
            history["tags"][-1], history["decisions"][-1], inputs.snapshot()
        )
