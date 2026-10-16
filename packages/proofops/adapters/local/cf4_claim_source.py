"""Opt-in CF4 region corroboration after the unchanged v27/S5 reader."""

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import cf4_source_region as region
from proofops.adapters.local import s5_claim_source as previous
from proofops.domain.provenance import canonical_hash

PROFILE = "cf4_claim_source_v1"
PageOCRStore = previous.PageOCRStore
native_policy = previous.native_policy
table_policy_sha256 = previous.table_policy_sha256
table_span_policy = previous.table_span_policy
attest_tables = previous.attest_tables
replay_tables = previous.replay_tables


def claim_source_policy():
    return dict(
        schema="claim_source_policy_v2",
        profile=PROFILE,
        previous_policy_sha256=canonical_hash(previous.claim_source_policy()),
        region_policy_sha256=canonical_hash(region.policy()),
        evidence_policy=previous.claim_source_policy()["evidence_policy"],
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        admission="S5-retained; failed-paragraph-native-glyph-plus-trusted-region-OCR",
    )


class Reader:
    def __init__(self, *, run_id):
        self.previous = previous.for_run(run_id)
        self.run_id = run_id

    def __getattr__(self, name):
        return getattr(self.previous, name)

    def attest_claim_spans(
        self,
        graph,
        source,
        refs,
        *,
        tenant_id,
        previous_receipt=None,
        recovery_receipt=None,
        replaying=False,
    ):
        refs = tuple(refs)
        baseline = (
            self.previous.attest_claim_spans(graph, source, refs, tenant_id=tenant_id)
            if previous_receipt is None
            else self.previous.recompute_claim_receipt(
                previous_receipt, graph, source, refs, tenant_id=tenant_id
            )
        )
        unresolved = {
            canonical_hash(r["ref"]) for r in baseline["records"] if r["status"] != "verified"
        }
        blocks = {b.source_id: b for b in graph.blocks}
        eligible = tuple(
            r
            for r in refs
            if canonical_hash(asdict(r)) in unresolved
            and r.source_id in blocks
            and blocks[r.source_id].kind == "paragraph"
        )
        recovery = (
            region.attest_regions(
                graph,
                source,
                eligible,
                tenant_id=tenant_id,
                run_id=self.run_id,
                store=PageOCRStore.from_env(),
                saved_regions=(recovery_receipt or {}).get("region_reads", [])
                if replaying
                else None,
            )
            if eligible
            else None
        )
        recovered = (
            {canonical_hash(r["ref"]): r for r in recovery["records"] if r["status"] == "verified"}
            if recovery
            else {}
        )
        body = dict(
            schema="cf4_claim_source_composition_v1",
            policy=claim_source_policy(),
            tenant_id=tenant_id,
            run_id=self.run_id,
            source_sha256=graph.source_sha256,
            document_version_id=graph.document_version_id,
            parse_manifest_id=graph.parse_manifest_id,
            input_graph_sha256=canonical_hash(asdict(graph)),
            graph_sha256=canonical_hash(asdict(graph)),
            previous_receipt=baseline,
            recovery_receipt=recovery,
            pb1_cell_proofs=baseline["pb1_cell_proofs"],
            records=[recovered.get(canonical_hash(r["ref"]), r) for r in baseline["records"]],
        )
        return body | dict(artifact_sha256=canonical_hash(body))

    def recompute_claim_receipt(self, receipt, graph, source, refs, *, tenant_id):
        if receipt.get("policy") != claim_source_policy() or receipt.get("run_id") != self.run_id:
            raise ValueError("OCR_POLICY_OR_RUN_MISMATCH")
        if not isinstance(receipt.get("previous_receipt"), dict) or (
            receipt.get("recovery_receipt") is not None
            and not isinstance(receipt["recovery_receipt"], dict)
        ):
            raise ValueError("CF4_CLAIM_RECEIPT_MISMATCH")
        expected = self.attest_claim_spans(
            graph,
            source,
            refs,
            tenant_id=tenant_id,
            previous_receipt=receipt["previous_receipt"],
            recovery_receipt=receipt["recovery_receipt"],
            replaying=True,
        )
        if canonical_hash(receipt) != canonical_hash(expected):
            raise ValueError("CF4_CLAIM_RECEIPT_MISMATCH")
        return expected


def for_run(run_id):
    return Reader(run_id=run_id)


def attest_claim_spans(graph, source, refs, *, tenant_id, run_id=None):
    return for_run(run_id).attest_claim_spans(graph, source, refs, tenant_id=tenant_id)


def replay_claim_spans(receipt, graph, source, discovery, *, tenant_id):
    from proofops.adapters.local.claim_source_verification import discovery_refs
    from proofops.adapters.local.verified_read_cache import _project_owned_cells

    checked = for_run(receipt["run_id"]).recompute_claim_receipt(
        receipt, graph, source, discovery_refs(discovery), tenant_id=tenant_id
    )
    return _project_owned_cells(checked, graph, discovery, tenant_id, failed_state="candidate")
