"""Bounded C4 local lifecycle on the existing immutable SQLite revision store."""

import json
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local.c4_selected_sources import replay as replay_source
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
from proofops.application.tagging.fact_assembly_c4 import (
    POLICY,
    POLICY_HASH,
    PROFILE,
    confirmation_display,
    publication_values,
)
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.rules.engine import RuleContext
from proofops.domain.values import SourceRef


class LocalC4Publication:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_symlink() or any(
            (self.path / name).is_symlink()
            for name in ("state.sqlite3", "original.pdf", "c4-evidence.json", "pilot.json")
        ):
            raise ValueError("C4_UNSAFE_ARTIFACT_PATH")
        self.runs = LocalSQLiteRunStore(self.path / "state.sqlite3")
        self.store = LocalSQLiteReviewStore(self.runs.jobs)
        self.service = ReviewService(self.store, load_inputs=self.load_inputs)

    def initialize(self, case, receipt, *, source, parser_artifact):
        claim, graph = case["context"].claim, case["graph"]
        base = fuse_candidates(
            candidates_from_snapshot(parser_artifact["candidates"]), tenant_id=claim.tenant_id
        )
        base = replace(base, issues=tuple(QualityIssue(**i) for i in parser_artifact["issues"]))
        admitted = replay_source(case["source_receipt"], base, source, tenant_id=claim.tenant_id)
        if canonical_hash(asdict(admitted)) != canonical_hash(asdict(graph)):
            raise ValueError("C4_SOURCE_ADMISSION_REPLAY_MISMATCH")
        consensus, decision = publication_values(
            receipt.to_dict(), rulepack=case["rulepack"], tag_revision=1
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
            fact_assembly_profile=PROFILE,
            fact_assembly_receipt=receipt,
        )
        inputs.validate()
        if sha256(source).hexdigest() != graph.source_sha256:
            raise ValueError("C4_SOURCE_HASH_MISMATCH")
        evidence = dict(parser_artifact=parser_artifact, source_receipt=case["source_receipt"])
        snapshot = dict(
            tenant_id=claim.tenant_id,
            run_id=run_id,
            document=dict(version_id=claim.document_version_id, sha256=graph.source_sha256),
            rulepack=asdict(case["rulepack"]),
            analysis_profile_policy=POLICY,
            analysis_profile_policy_sha256=POLICY_HASH,
            c4_evidence_sha256=canonical_hash(evidence),
        )
        snapshot["input_hash"] = canonical_hash(snapshot)
        for name, content in (
            ("original.pdf", source),
            ("c4-evidence.json", json.dumps(evidence, ensure_ascii=False).encode()),
            (
                "pilot.json",
                json.dumps(
                    dict(
                        tenant_id=claim.tenant_id,
                        run_id=run_id,
                        claim_id=claim.claim_id,
                        publication_profile=PROFILE,
                        document_version_id=claim.document_version_id,
                        selected_pages=sorted({r.page_num for r in claim.source_refs}),
                    ),
                    sort_keys=True,
                ).encode(),
            ),
            ("outcome.json", b'{"status":"completed","reason":null}'),
        ):
            target = self.path / name
            if target.exists():
                if target.read_bytes() != content:
                    raise ValueError("C4_IMMUTABLE_ARTIFACT_CONFLICT")
            else:
                target.write_bytes(content)
        with self.runs.jobs._transaction() as db:
            prior = db.execute(
                "SELECT payload FROM run_snapshots WHERE tenant_id=? AND run_id=?",
                (claim.tenant_id, run_id),
            ).fetchone()
            if prior and canonical_hash(json.loads(prior[0])) != canonical_hash(snapshot):
                raise ValueError("C4_RUN_SNAPSHOT_CONFLICT")
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
        if (self.path / "original.pdf").is_symlink() or (
            self.path / "c4-evidence.json"
        ).is_symlink():
            raise ValueError("C4_UNSAFE_ARTIFACT_PATH")
        if (
            frozen.get("analysis_profile_policy") != POLICY
            or frozen.get("analysis_profile_policy_sha256") != POLICY_HASH
            or frozen.get("input_hash")
            != canonical_hash({k: v for k, v in frozen.items() if k != "input_hash"})
        ):
            raise ValueError("C4_FROZEN_POLICY_MISMATCH")
        history = self.store.history(tenant, run, claim_id)
        raw = history["tags"][0]["inputs"]
        evidence = json.loads((self.path / "c4-evidence.json").read_text())
        if canonical_hash(evidence) != frozen["c4_evidence_sha256"]:
            raise ValueError("C4_EVIDENCE_HASH_MISMATCH")
        d = evidence["parser_artifact"]
        graph = fuse_candidates(candidates_from_snapshot(d["candidates"]), tenant_id=tenant)
        graph = replace(graph, issues=tuple(QualityIssue(**i) for i in d["issues"]))
        graph = replay_source(
            evidence["source_receipt"],
            graph,
            (self.path / "original.pdf").read_bytes(),
            tenant_id=tenant,
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
            raise ValueError("C4_SCOPE_MISMATCH")
        packet = freeze_packet({k: v for k, v in raw["packet"].items() if k != "packet_sha256"})
        original = freeze_packet(
            {k: v for k, v in raw["original_packet"].items() if k != "packet_sha256"}
        )
        pack = RulePackSnapshot(**frozen["rulepack"])
        receipt = _fact_assembly_reader(raw["fact_assembly_receipt"])
        consensus, decision = publication_values(
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
            fact_assembly_profile=PROFILE,
            fact_assembly_receipt=receipt,
        )
        inputs.validate()
        if canonical_hash(inputs.snapshot()) != canonical_hash(raw):
            raise ValueError("C4_STORED_INPUT_REPLAY_MISMATCH")
        return inputs

    def result(self, tenant, run, claim_id):
        inputs = self.load_inputs(tenant, run, claim_id)
        history = self.store.history(tenant, run, claim_id)
        tag, record = history["tags"][-1], history["decisions"][-1]
        decision = record["api"] | dict(excluded_elements=record["decision"]["excluded_elements"])
        auto = tag["origin"] == "consensus"
        claim = inputs.context.claim
        return dict(
            schema="r108-hosted-result-v1",
            page_map=sorted({r.page_num for r in claim.source_refs}),
            hold_reasons=[],
            pipeline=dict(status="completed"),
            reviews=[self.store.get(tenant, self.service._review(inputs)["review_id"])],
            claims=[
                claim.to_summary()
                | dict(
                    page_num=1,
                    original_page_num=claim.source_refs[0].page_num,
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
                    # Frozen C3-web discriminator for direct-certification UI.
                    # The policy hash and receipt identify the C4 implementation.
                    confirmation_source="auto_direct_certification_c3_v1"
                    if auto
                    else "human_review",
                    confirmation_policy_sha256=POLICY_HASH,
                    confirmation_display=confirmation_display(
                        inputs.fact_assembly_receipt.to_dict()
                    )
                    if auto
                    else "사람 태깅 검토 후 Python 재판정",
                    confirmation_basis=confirmation_display(
                        inputs.fact_assembly_receipt.to_dict()
                    ).split(" — ", 1)[1]
                    if auto
                    else None,
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
