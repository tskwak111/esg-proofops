"""Tag checkpoint validation/replay; initial revisions belong to LocalSQLiteReviewStore.

No parallel revision tables. Checkpoints use the existing immutable artifact
pointer and retain the extraction checkpoint digest and frozen run inputs.
"""

from __future__ import annotations

import json as json
from collections.abc import Callable
from dataclasses import asdict
from hashlib import sha256 as sha256
from typing import TYPE_CHECKING

from proofops.adapters.cache.aws import CacheNamespace, CacheRequest
from proofops.adapters.local.claim_source_policies import PAGE_OCR_PROFILES
from proofops.adapters.local.claim_store import LocalClaimStore
from proofops.adapters.local.tag_store_checkpoint import tag_pins as tag_pins
from proofops.adapters.local.tag_store_checkpoint import tagging_settings as tagging_settings
from proofops.adapters.local.tag_store_checkpoint import validate_tag_commit as validate_tag_commit
from proofops.application.budget import TokenUsage
from proofops.application.evidence.binding import ClaimContext
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.ports.jobs import JobMessage as JobMessage
from proofops.application.ports.models import ModelBinding as ModelBinding
from proofops.application.preflight import (
    relation_settings_contract_valid as relation_settings_contract_valid,
)
from proofops.application.reviews import ReviewInputs
from proofops.application.tagging.consensus import ConsensusResult, form_consensus
from proofops.application.tagging.consensus import reviewable_decision as _reviewable_decision
from proofops.application.tagging.report_level_link import (
    replay_report_level_link as _replay_report_level_link,
)
from proofops.application.tagging.report_level_link import strict_fallback as _strict_fallback
from proofops.application.tagging.service import TaggingSettings as TaggingSettings
from proofops.application.tagging.service import TagRun
from proofops.domain.provenance import canonical_hash as canonical_hash
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.rules.engine import ConfirmedTags, RuleContext, evaluate
from proofops.domain.values import SourceRef, llm_tags_from_dict

if TYPE_CHECKING:
    from types import ModuleType
    from typing import Any

    from proofops.adapters.local.run_store import LocalSQLiteRunStore
    from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
    from proofops.application.claims import Claim, ClaimDiscovery
    from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
    from proofops.application.tagging.fact_assembly_c2 import FactAssemblyReceiptV1
    from proofops.application.uploads import UploadService


reviewable_decision = _reviewable_decision

replay_report_level_link: Callable[..., ConsensusResult] = _replay_report_level_link
strict_fallback: Callable[..., ConfirmedTags | None] = _strict_fallback

# Added to TagRun on 2026-09-27. Only absent/null is equivalent, only in
# tag_runs during read comparison; persisted inputs and their hashes stay intact.
TAG_RUN_READ_COMPAT_NULL_FIELDS = frozenset({"diagnostic_detail"})


def _tag_replay_hash(snapshot: dict[str, Any]) -> str:
    comparable = snapshot | {
        "tag_runs": [
            {field: None for field in TAG_RUN_READ_COMPAT_NULL_FIELDS} | entry
            for entry in snapshot["tag_runs"]
        ]
    }
    return canonical_hash(comparable)


def _stored_context_reader(
    store: LocalSQLiteRunStore,
    claim: Claim,
    run_id: str,
    refs: tuple[SourceRef, ...],
    run_policy: dict[str, Any] | None,
    replay_receipt: dict[str, Any] | None,
    *,
    published_tag: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    """Resolve only the explicitly requested, already-published receipt."""
    jobs = getattr(store, "jobs", None)
    if jobs is None or not hasattr(jobs, "_transaction"):
        raise ValueError("CONTEXT_SOURCE_REPLAY_MISMATCH")
    if published_tag is None:
        try:
            with jobs._transaction() as db:
                head = jobs._get(db, claim.tenant_id, run_id, "claim_head", claim.claim_id)
                tag = jobs._get(
                    db,
                    claim.tenant_id,
                    run_id,
                    "tag_revision",
                    f'{claim.claim_id}:{head["tag_revision"]:010}',
                )
        except KeyError:
            raise ValueError("CONTEXT_SOURCE_REPLAY_MISMATCH") from None
    else:
        tag = published_tag
        if not isinstance(tag, dict):
            raise ValueError("CONTEXT_SOURCE_REPLAY_MISMATCH")
        tag_claim = tag.get("confirmed_tags") or (tag.get("inputs") or {}).get("claim") or {}
        if tag_claim.get("claim_id") != claim.claim_id:
            raise ValueError("CONTEXT_SOURCE_REPLAY_MISMATCH")

    ref_hash = canonical_hash([dict(asdict(ref), verification_state="candidate") for ref in refs])
    for prior in reversed(tag.get("report_level_review", ())):
        prior_refs = prior.get("refs")
        if (
            not isinstance(prior_refs, list)
            or canonical_hash([dict(ref, verification_state="candidate") for ref in prior_refs])
            != ref_hash
            or prior.get("source_receipt") != replay_receipt
        ):
            continue
        receipt = prior.get("source_receipt")
        if not isinstance(receipt, dict) or receipt.get("artifact_sha256") != canonical_hash(
            {key: value for key, value in receipt.items() if key != "artifact_sha256"}
        ):
            raise ValueError("CONTEXT_SOURCE_REPLAY_MISMATCH")
        paragraph = (
            receipt
            if isinstance(receipt.get("policy"), dict)
            else (receipt.get("receipts") or {}).get("paragraph")
        )
        if paragraph is None and receipt.get("schema") == "context_source_attestation_v1":
            if run_policy and run_policy.get("profile") in PAGE_OCR_PROFILES:
                from proofops.adapters.local.claim_source_policies import (
                    claim_source_reader as _claim_source_reader,
                )

                claim_source_reader: Callable[..., ModuleType] = _claim_source_reader

                table_span_policy = claim_source_reader(run_policy).table_span_policy

                table = (receipt.get("receipts") or {}).get("table")
                if (
                    isinstance(table, dict)
                    and table.get("run_id") == run_id
                    and table.get("policy") == table_span_policy()
                    and receipt.get("policy_hashes", {}).get("table")
                    == canonical_hash(table_span_policy())
                ):
                    return receipt, run_policy, None
                raise ValueError("CONTEXT_SOURCE_REPLAY_MISMATCH")
            from proofops.adapters.local.claim_source_verification import claim_source_policy

            policy = claim_source_policy()
            if receipt.get("policy_hashes", {}).get("paragraph") == canonical_hash(policy):
                return receipt, policy, None
            raise ValueError("CONTEXT_SOURCE_REPLAY_MISMATCH")
        if not isinstance(paragraph, dict) or not isinstance(paragraph.get("policy"), dict):
            raise ValueError("CONTEXT_SOURCE_REPLAY_MISMATCH")
        if paragraph.get("artifact_sha256") != canonical_hash(
            {key: value for key, value in paragraph.items() if key != "artifact_sha256"}
        ):
            raise ValueError("CONTEXT_SOURCE_REPLAY_MISMATCH")
        policy = paragraph["policy"]
        from proofops.adapters.local.claim_source_verification import claim_source_policy

        if policy != run_policy and policy != claim_source_policy():
            raise ValueError("CONTEXT_SOURCE_REPLAY_MISMATCH")
        recorded_hash = paragraph.get("reader_policy_sha256")
        if recorded_hash is not None and recorded_hash != canonical_hash(policy):
            raise ValueError("CONTEXT_SOURCE_REPLAY_MISMATCH")
        if paragraph is receipt and policy != claim_source_policy() and recorded_hash is None:
            raise ValueError("CONTEXT_SOURCE_REPLAY_MISMATCH")
        if receipt.get("schema") == "context_source_attestation_v1" and receipt.get(
            "policy_hashes", {}
        ).get("paragraph") != canonical_hash(policy):
            raise ValueError("CONTEXT_SOURCE_REPLAY_MISMATCH")
        return receipt, policy, recorded_hash
    raise ValueError("CONTEXT_SOURCE_REPLAY_MISMATCH")


class LocalTagStore:
    def __init__(
        self, store: LocalSQLiteRunStore, uploads: UploadService, parser: OpenDataLoaderParser
    ) -> None:
        self.store, self.uploads, self.parser = store, uploads, parser
        self.claims = LocalClaimStore(store, uploads, parser)

    def verify_context_sources(
        self,
        inputs: ReviewInputs,
        refs: tuple[SourceRef, ...],
        *,
        replay_receipt: dict[str, Any] | None = None,
        pinned_run_snapshot: dict[str, Any] | None = None,
        published_tag: dict[str, Any] | None = None,
    ) -> tuple[CanonicalDocumentGraph, dict[str, Any]]:
        """Publish under current policy, or replay an explicitly stored receipt.

        Historical readers are selected only after storage and ref binding have
        been checked. Frozen inputs and the saved receipt identity stay intact.
        """
        from dataclasses import replace

        from proofops.adapters.local.claim_source_policies import attest_claims as _attest_claims

        attest_claims: Callable[..., dict[str, Any]] = _attest_claims
        from proofops.adapters.local.claim_source_verification import claim_source_policy
        from proofops.adapters.local.table_span_source_verification import (
            attest_table_spans as default_attest_table_spans,
        )
        from proofops.adapters.local.table_span_source_verification import (
            table_span_policy,
        )
        from proofops.application.evidence.span_citations import (
            span_verified_graph,
            verify_source_ref,
        )

        attest_table_spans: Callable[..., dict[str, Any]] = default_attest_table_spans
        claim, graph = inputs.context.claim, inputs.original
        if not 1 <= len(refs) <= 6:
            raise ValueError("CONTEXT_SOURCE_LIMIT")
        reader = None
        reader_policy = None
        stored_receipt = None
        stored_reader_policy_hash = None
        run_id = getattr(inputs, "run_id", None)
        if run_id is not None:
            if self.store is None:
                raise ValueError("CONTEXT_SOURCE_REJECTED")
            snapshot = (
                pinned_run_snapshot
                if pinned_run_snapshot is not None
                else self.store.snapshot(claim.tenant_id, run_id)
            )
            if snapshot is None:
                raise ValueError("CONTEXT_SOURCE_REJECTED")
            if pinned_run_snapshot is not None and (
                snapshot.get("tenant_id") != claim.tenant_id
                or snapshot.get("run_id") != run_id
                or snapshot.get("document", {}).get("version_id") != graph.document_version_id
            ):
                raise ValueError("CONTEXT_SOURCE_REJECTED")
            reader_policy = snapshot.get("claim_source_policy")
            if replay_receipt is not None:
                stored_receipt, reader_policy, stored_reader_policy_hash = _stored_context_reader(
                    self.store,
                    claim,
                    run_id,
                    refs,
                    reader_policy,
                    replay_receipt,
                    published_tag=published_tag,
                )
            if reader_policy is not None:
                from proofops.adapters.local.claim_source_policies import (
                    claim_source_reader as _claim_source_reader,
                )
                from proofops.adapters.local.claim_source_policies import (
                    publication_reader as _publication_reader,
                )

                claim_source_reader: Callable[..., ModuleType] = _claim_source_reader
                publication_reader: Callable[..., ModuleType] = _publication_reader

                reader = (
                    claim_source_reader(reader_policy)
                    if stored_receipt is not None
                    else publication_reader(reader_policy)
                )
        elif replay_receipt is not None:
            raise ValueError("CONTEXT_SOURCE_REPLAY_MISMATCH")
        if reader is None:
            from proofops.adapters.local import claim_source_verification

            reader = claim_source_verification
        source = self.uploads.read_original(claim.tenant_id, claim.document_version_id)
        if sha256(source).hexdigest() != graph.source_sha256:
            raise ValueError("CONTEXT_SOURCE_MISMATCH")

        def attest_paragraphs(selected: tuple[SourceRef, ...]) -> dict[str, Any]:
            if reader_policy and reader_policy.get("profile") in PAGE_OCR_PROFILES:
                for_run = reader.for_run

                if stored_receipt is not None:
                    saved = (stored_receipt.get("receipts") or {}).get("paragraph", stored_receipt)
                    saved = {k: v for k, v in saved.items() if k != "reader_policy_sha256"}
                    saved["artifact_sha256"] = canonical_hash(
                        {k: v for k, v in saved.items() if k != "artifact_sha256"}
                    )
                    return_value: dict[str, Any] = for_run(run_id).recompute_claim_receipt(
                        saved, graph, source, selected, tenant_id=claim.tenant_id
                    )
                    return return_value
            return attest_claims(
                reader=reader,
                graph=graph,
                source=source,
                refs=selected,
                tenant_id=claim.tenant_id,
                cache=False,
                run_id=run_id,
            )

        kinds = {block.source_id: block.kind for block in graph.blocks}
        if any(
            kinds.get(ref.source_id) not in {"paragraph", "table_cell", "table_row"} for ref in refs
        ):
            raise ValueError("CONTEXT_SOURCE_REJECTED")
        unresolved = tuple(
            r
            for r in refs
            if verify_source_ref(r, graph, tenant_id=claim.tenant_id).verification_state
            != "verified"
        )
        paragraphs = tuple(ref for ref in unresolved if kinds[ref.source_id] == "paragraph")
        tables = tuple(ref for ref in unresolved if kinds[ref.source_id] != "paragraph")
        if reader_policy and reader_policy.get("profile") in PAGE_OCR_PROFILES:
            page_reader = reader.for_run(run_id)
            table_span_policy = reader.table_span_policy
            if stored_receipt is not None:
                saved_table = (stored_receipt.get("receipts") or {}).get("table")

                def attest_saved_table_spans(
                    graph: CanonicalDocumentGraph,
                    source: bytes,
                    selected: tuple[SourceRef, ...],
                    *,
                    tenant_id: str,
                ) -> dict[str, Any]:
                    return_value: dict[str, Any] = page_reader.recompute_table_span_receipt(
                        saved_table, graph, source, selected, tenant_id=tenant_id
                    )
                    return return_value

                attest_table_spans = attest_saved_table_spans
            else:
                attest_table_spans = page_reader.attest_table_spans
        receipt: dict[str, Any]
        if tables:
            paragraph_receipt = attest_paragraphs(paragraphs) if paragraphs else None
            table_receipt = attest_table_spans(graph, source, tables, tenant_id=claim.tenant_id)
            if (
                (paragraph_receipt and len(paragraph_receipt["records"]) != len(paragraphs))
                or len(table_receipt["records"]) != len(tables)
                or any(
                    record["status"] != "verified"
                    for item in (paragraph_receipt, table_receipt)
                    if item
                    for record in item["records"]
                )
            ):
                raise ValueError("CONTEXT_SOURCE_REJECTED")
            receipts = {"paragraph": paragraph_receipt, "table": table_receipt}
            records = {
                kind: iter(item["records"] if item else ()) for kind, item in receipts.items()
            }
            ordered = [
                next(records["paragraph" if kinds[ref.source_id] == "paragraph" else "table"])
                for ref in unresolved
            ]
            receipt = dict(
                schema="context_source_attestation_v1",
                tenant_id=claim.tenant_id,
                document_version_id=graph.document_version_id,
                parse_manifest_id=graph.parse_manifest_id,
                source_sha256=graph.source_sha256,
                policy_hashes={
                    "paragraph": canonical_hash(
                        reader_policy
                        if paragraphs and reader_policy is not None
                        else claim_source_policy()
                    ),
                    "table": canonical_hash(table_span_policy()),
                },
                receipts=receipts,
                records=ordered,
            )
            receipt["artifact_sha256"] = canonical_hash(receipt)
        else:
            # Keep R38 paragraph-only receipts byte-for-byte compatible on replay.
            receipt = attest_paragraphs(unresolved)
            if reader_policy is not None and reader_policy != claim_source_policy():
                if stored_receipt is None or stored_reader_policy_hash is not None:
                    receipt["reader_policy_sha256"] = canonical_hash(reader_policy)
                    receipt["artifact_sha256"] = canonical_hash(
                        {key: value for key, value in receipt.items() if key != "artifact_sha256"}
                    )
        if len(receipt["records"]) != len(unresolved) or any(
            record["status"] != "verified" for record in receipt["records"]
        ):
            raise ValueError("CONTEXT_SOURCE_REJECTED")
        if stored_receipt is not None:
            from proofops.adapters.local.receipt_environment_compat import (
                compare_receipts as _compare_receipts,
            )
            from proofops.adapters.local.receipt_environment_compat import (
                read_profile as _read_profile,
            )

            compare_receipts: Callable[..., dict[str, Any]] = _compare_receipts
            read_profile: Callable[..., str] = _read_profile

            try:
                compare_receipts(stored_receipt, receipt, profile=read_profile())
            except ValueError:
                raise ValueError("CONTEXT_SOURCE_REPLAY_MISMATCH") from None
            # Historical supplemental span identity is part of the frozen tag.
            receipt = stored_receipt
        scoped = span_verified_graph(
            graph,
            (
                *getattr(graph, "verified_spans", ()),
                *(replace(r, verification_state="verified") for r in unresolved),
            ),
            canonical_hash(
                dict(
                    prior=getattr(graph, "span_receipt_sha256", ""),
                    supplemental=receipt["artifact_sha256"],
                )
            ),
        )
        return scoped, receipt

    def _facility_evidence(
        self,
        evidence: tuple[dict[str, Any], ClaimDiscovery, CanonicalDocumentGraph],
        snapshot: dict[str, Any],
        tenant_id: str,
    ) -> tuple[dict[str, Any], ClaimDiscovery, CanonicalDocumentGraph]:
        extraction, discovery, graph = evidence
        policy = snapshot.get("analysis_profile_policy", {})
        if policy.get("facility_tagging_candidates") is not None:
            from proofops.adapters.local.k6_facilities import facility_graph as _facility_graph

            facility_graph: Callable[..., tuple[CanonicalDocumentGraph, dict[str, Any]]] = (
                _facility_graph
            )

            graph, _ = facility_graph(
                graph,
                self.uploads.read_original(tenant_id, graph.document_version_id),
                discovery.claims,
                tenant_id=tenant_id,
                policy=policy,
            )
        if policy.get("local_implementation_binding_policy"):
            from proofops.adapters.local.k9_scope_sources import scope_graph as _scope_graph

            scope_graph: Callable[..., tuple[CanonicalDocumentGraph, dict[str, Any]]] = _scope_graph

            graph, _ = scope_graph(
                graph,
                self.uploads.read_original(tenant_id, graph.document_version_id),
                discovery.claims,
                tenant_id=tenant_id,
                run_id=snapshot["run_id"],
                policy=policy,
            )
        return extraction, discovery, graph

    def _load_snapshot_with_evidence(
        self, tenant_id: str, run_id: str
    ) -> tuple[dict[str, Any], tuple[dict[str, Any], ClaimDiscovery, CanonicalDocumentGraph]]:
        # Share the evidence replay used to verify the tag checkpoint pins.
        run = self.store.jobs.get_run(tenant_id, run_id)
        message = JobMessage(**run["tag_job"])
        payload = self.store.jobs.read_checkpoint(message)
        if payload is None or sha256(payload).hexdigest() != run["tag_snapshot_sha256"]:
            raise ValueError("TAG_CHECKPOINT_HASH_MISMATCH")
        envelope = json.loads(payload)
        evidence = self.claims.load_evidence(tenant_id, run_id)
        extraction = evidence[0]
        snapshot = self.store.snapshot(tenant_id, run_id)
        evidence = self._facility_evidence(evidence, snapshot, tenant_id)
        expected = tag_pins(snapshot, extraction, run["claim_snapshot_sha256"])
        if any(envelope.get(k) != v for k, v in expected.items()):
            raise ValueError("TAG_CHECKPOINT_PIN_MISMATCH")
        sc1_policy = snapshot.get("analysis_profile_policy", {}).get("sc1_scope_confirmation")
        if sc1_policy is not None:
            from proofops.application.tagging.analysis_scope import (
                InventoryIndex as _InventoryIndex,
            )
            from proofops.application.tagging.analysis_scope import (
                analyze_record as _analyze_record,
            )

            InventoryIndex: Callable[..., _InventoryIndex] = _InventoryIndex
            analyze_record: Callable[..., dict[str, Any]] = _analyze_record
            from proofops.application.tagging.v1_activity_links import (
                policy_from_profile as _policy_from_profile,
            )

            policy_from_profile: Callable[..., dict[str, Any] | None] = _policy_from_profile

            inventory = envelope.get("sc1_inventory")
            index = InventoryIndex(inventory, evidence[2]) if inventory is not None else None
            if index is not None:
                from proofops.application.tagging.element_inventory import (
                    selection_from_snapshot as _selection_from_snapshot,
                )

                selection_from_snapshot: Callable[..., dict[str, Any]] = _selection_from_snapshot

                if index.inventory["selection"] != selection_from_snapshot(
                    snapshot, evidence[2], run_id
                ):
                    raise ValueError("SC1_INVENTORY_SELECTION_MISMATCH")
            claims = {c.claim_id: c for c in evidence[1].claims}
            pack = RulePackSnapshot(**snapshot["rulepack"])
            for item in envelope["claims"]:
                receipt = item.get("sc1_scope_receipt")
                if receipt is not None:
                    if index is None:
                        raise ValueError("SC1_INVENTORY_MISSING")
                    replayed = analyze_record(
                        item,
                        claims[item["claim_id"]],
                        evidence[2],
                        pack,
                        index,
                        required_present_votes=sc1_policy["agreement"]["required_present_votes"],
                        local_synthetic=envelope["synthetic"],
                        grade_agreement_policy=snapshot.get("analysis_profile_policy", {}).get(
                            "grade_required_agreement_policy"
                        ),
                        v1_activity_policy=policy_from_profile(
                            snapshot.get("analysis_profile_policy", {})
                        ),
                    )
                    if canonical_hash(replayed) != canonical_hash(receipt) or any(
                        item.get(k) != receipt[k] for k in ("sc1_confirmation", "sc1_elements")
                    ):
                        raise ValueError("SC1_SCOPE_RECEIPT_MISMATCH")
                elif item.get("sc1_confirmation") is not None:
                    raise ValueError("SC1_CONFIRMATION_WITHOUT_RECEIPT")
        elif "sc1_inventory" in envelope or any(
            item.get("sc1_confirmation") for item in envelope["claims"]
        ):
            raise ValueError("SC1_UNPINNED_CONFIRMATION")
        cf6_policy = snapshot.get("analysis_profile_policy", {}).get("cf6_confirmation")
        for item in envelope["claims"]:
            receipt = item.get("cf6_receipt")
            if receipt is not None:
                if cf6_policy is None:
                    raise ValueError("CF6_UNPINNED_CONFIRMATION")
                from proofops.application.tagging.cf6_confirmation import (
                    analyze_record as _analyze_cf6,
                )

                analyze_cf6: Callable[..., dict[str, Any]] = _analyze_cf6

                claim = next(c for c in evidence[1].claims if c.claim_id == item["claim_id"])
                replayed = analyze_cf6(
                    item,
                    claim,
                    evidence[2],
                    RulePackSnapshot(**snapshot["rulepack"]),
                    snapshot["analysis_profile_policy"],
                )
                if (
                    canonical_hash(replayed) != canonical_hash(receipt)
                    or item.get("cf6_confirmation") != replayed["cf6_confirmation"]
                ):
                    raise ValueError("CF6_RECEIPT_MISMATCH")
            elif item.get("cf6_confirmation") is not None:
                raise ValueError("CF6_CONFIRMATION_WITHOUT_RECEIPT")
        return envelope, evidence

    def load_snapshot(self, tenant_id: str, run_id: str) -> dict[str, Any]:
        return self._load_snapshot_with_evidence(tenant_id, run_id)[0]

    def load_inputs(self, tenant_id: str, run_id: str, claim_id: str) -> ReviewInputs:
        run = self.store.jobs.get_run(tenant_id, run_id)
        envelope = None
        if "tag_job" in run:
            envelope, evidence = self._load_snapshot_with_evidence(tenant_id, run_id)
            item = next((item for item in envelope["claims"] if item["claim_id"] == claim_id), None)
            if item is None or item.get("review_inputs") is None:
                raise KeyError("tagged claim not published")
            raw = item["review_inputs"]
        else:
            evidence = self.claims.load_evidence(tenant_id, run_id)
            _, discovery, graph = evidence
            claim = next((c for c in discovery.claims if c.claim_id == claim_id), None)
            if claim is None:
                raise KeyError("tagged claim not published")
            try:
                with self.store.jobs._transaction() as db:
                    head = self.store.jobs._get(db, tenant_id, run_id, "claim_head", claim_id)
                    published = self.store.jobs._get(
                        db,
                        tenant_id,
                        run_id,
                        "tag_revision",
                        f"{claim_id}:{1:010}",
                    )
            except KeyError:
                raise KeyError("tagged claim not published") from None
            raw = published.get("inputs")
            snapshot = self.store.snapshot(tenant_id, run_id)
            evidence = self._facility_evidence(evidence, snapshot, tenant_id)
            graph = evidence[2]
            # Keep snapshot-policy validation from the checkpoint path. Its
            # extraction graph pin is distinct from the attested graph below.
            tag_pins(snapshot, evidence[0], run["claim_snapshot_sha256"])
            if (
                published.get("origin") != "consensus"
                or published.get("tag_revision") != 1
                or head.get("tag_revision", 0) < 1
                or not isinstance(raw, dict)
                or canonical_hash(raw.get("claim")) != canonical_hash(asdict(claim))
                or raw.get("run_id") != run_id
                # Extraction pins precede source attestation. Partial publications
                # bind to the same verified graph used by normal checkpoint replay.
                or raw.get("original", {}).get("graph_sha256") != canonical_hash(asdict(graph))
                or canonical_hash(raw.get("rulepack")) != canonical_hash(snapshot["rulepack"])
            ):
                raise ValueError("TAG_REPLAY_MISMATCH")
        _, discovery, graph = evidence
        claim = next(c for c in discovery.claims if c.claim_id == claim_id)
        snapshot = self.store.snapshot(tenant_id, run_id)
        rulepack = RulePackSnapshot(**snapshot["rulepack"])
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
            profile=raw.get("fact_assembly", {}).get("profile", "strict-v1"),
        )
        link_config = snapshot.get("report_level_link")
        if raw.get("report_level_link") != link_config:
            raise ValueError("TAG_REPLAY_MISMATCH")
        link_receipts = tuple(raw.get("report_level_review", ()))
        if link_config is not None:
            consensus = replay_report_level_link(
                consensus,
                config=link_config,
                context=context,
                graph=graph,
                receipts=link_receipts,
                fallback_tags=strict_fallback(
                    tuple(runs),
                    packet,
                    rulepack,
                    tenant_id,
                    raw["tag_revision"],
                    raw.get("fact_assembly", {}).get("profile", "strict-v1"),
                ),
            )
        elif link_receipts:
            raise ValueError("TAG_REPLAY_MISMATCH")
        rule_context = RuleContext(**raw["rule_context"])
        decision = (
            evaluate(consensus.confirmed_tags, rule_context, rulepack)
            if consensus.confirmed_tags
            and snapshot.get("rulepack_use") != "candidate_tagging_reference_only"
            else None
        )
        decision, _ = reviewable_decision(
            decision,
            raw.get("fact_assembly", {}).get("profile", "strict-v1"),
            consensus.review_status,
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
            raw.get("fact_assembly", {}).get("profile", "strict-v1"),
            link_config,
            link_receipts,
            _fact_assembly_reader(raw.get("fact_assembly_receipt")),
        )
        inputs.validate()
        if _tag_replay_hash(inputs.snapshot()) != _tag_replay_hash(raw):
            raise ValueError("TAG_REPLAY_MISMATCH")
        for receipt in link_receipts:
            refs = tuple(SourceRef(**ref) for ref in receipt["refs"])
            # raw came from the hash/pin-checked checkpoint or initial immutable
            # revision above, and its complete replay has now been validated.
            # Bind to that publication rather than a potentially newer tag head.
            _, replayed = self.verify_context_sources(
                inputs,
                refs,
                replay_receipt=receipt["source_receipt"],
                pinned_run_snapshot=snapshot,
                published_tag=dict(inputs=raw, report_level_review=link_receipts),
            )
            if canonical_hash(replayed) != canonical_hash(receipt["source_receipt"]):
                raise ValueError("REPORT_LEVEL_LINK_REPLAY_MISMATCH")
        return inputs


def _fact_assembly_reader(raw: dict[str, Any] | None) -> FactAssemblyReceiptV1 | None:
    """Opaque versioned artifact; replay remains ReviewInputs' responsibility."""
    if raw is None:
        return None
    from proofops.application.tagging.fact_assembly_c2 import SCHEMA, FactAssemblyReceiptV1

    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        raise ValueError("FACT_ASSEMBLY_VERSION_UNSUPPORTED")
    content = {k: v for k, v in raw.items() if k != "receipt_sha256"}
    return FactAssemblyReceiptV1(
        json.dumps(content, ensure_ascii=False, sort_keys=True), raw["receipt_sha256"]
    )
