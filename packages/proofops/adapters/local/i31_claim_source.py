"""Verify selected tables' literal header rows using the unchanged native reader.

I31 composes the frozen TB1 proof contract over SPE execution.
CF4 claim proofs remain intact. Additional header spans have independent native
cell/row ownership proofs and are re-read on cold replay; no whole-table promotion.
"""

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import spe_claim_source as previous
from proofops.adapters.local import upstage_ocr_profile_v10 as native
from proofops.application.tagging import tb1_table_bundles as bundles
from proofops.domain.provenance import canonical_hash

PROFILE = "i31_claim_source_v1"
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
        native_policy_sha256=canonical_hash(native.claim_source_policy()),
        evidence_policy=previous.claim_source_policy()["evidence_policy"],
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        bundle_selector_sha256=sha256(Path(bundles.__file__).read_bytes()).hexdigest(),
        admission="unchanged-SPE-CF4; selected-numeric-table-header-native-cell-proof-only",
    )


def attest_headers(graph, source, refs, *, tenant_id):
    selected = bundles.header_refs(graph, refs)
    return native.cell_proof(graph, source, selected, tenant_id=tenant_id) if selected else []


class Reader:
    def __init__(self, *, run_id):
        self.previous = previous.for_run(run_id)
        self.run_id = run_id

    def __getattr__(self, name):
        return getattr(self.previous, name)

    def attest_claim_spans(self, graph, source, refs, *, tenant_id, previous_receipt=None):
        refs = tuple(refs)
        baseline = (
            self.previous.attest_claim_spans(graph, source, refs, tenant_id=tenant_id)
            if previous_receipt is None
            else self.previous.recompute_claim_receipt(
                previous_receipt, graph, source, refs, tenant_id=tenant_id
            )
        )
        headers = attest_headers(graph, source, refs, tenant_id=tenant_id)
        body = dict(
            schema="tb1_claim_source_composition_v1",
            policy=claim_source_policy(),
            tenant_id=tenant_id,
            run_id=self.run_id,
            source_sha256=graph.source_sha256,
            document_version_id=graph.document_version_id,
            parse_manifest_id=graph.parse_manifest_id,
            input_graph_sha256=canonical_hash(asdict(graph)),
            graph_sha256=canonical_hash(asdict(graph)),
            previous_receipt=baseline,
            tb1_header_proofs=headers,
            pb1_cell_proofs=[*baseline["pb1_cell_proofs"], *headers],
            records=[
                *baseline["records"],
                *[{k: p[k] for k in ("ref", "status", "reason")} for p in headers],
            ],
        )
        return body | dict(artifact_sha256=canonical_hash(body))

    def recompute_claim_receipt(self, receipt, graph, source, refs, *, tenant_id):
        if receipt.get("policy") != claim_source_policy() or receipt.get("run_id") != self.run_id:
            raise ValueError("TB1_SOURCE_POLICY_OR_RUN_MISMATCH")
        expected = self.attest_claim_spans(
            graph,
            source,
            refs,
            tenant_id=tenant_id,
            previous_receipt=receipt["previous_receipt"],
        )
        if canonical_hash(receipt) != canonical_hash(expected):
            raise ValueError("TB1_SOURCE_RECEIPT_MISMATCH")
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
