"""HX4 claim fallback provenance; v16 and all earlier source receipts stay pinned."""

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import evidence_source_hx4 as evidence
from proofops.adapters.local import upstage_ocr_profile_v15 as previous
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.domain.provenance import canonical_hash

PROFILE = "upstage-ocr-page-v17"


def claim_source_policy():
    return dict(
        previous.claim_source_policy(),
        profile=PROFILE,
        evidence_policy=evidence.policy(),
        previous_policy_sha256=canonical_hash(previous.claim_source_policy()),
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        failure="complete-native-and-claim-unreadable-receipts; empty-graph-no-admission",
    )


def native_policy():
    return dict(previous.native_policy(), mode=PROFILE, hx4=claim_source_policy())


def table_policy_sha256():
    return canonical_hash(dict(previous=previous.table_policy_sha256(), hx4=native_policy()))


def table_span_policy():
    return dict(previous.table_span_policy(), profile=PROFILE, hx4=claim_source_policy())


_wrapper = _exec_private(
    Path(__file__).parent, "upstage_ocr_profile_v15.py", "proofops.adapters.local._hx4_source_v17"
)
_wrapper.PROFILE, _wrapper.evidence = PROFILE, evidence
_wrapper.claim_source_policy, _wrapper.native_policy = claim_source_policy, native_policy
_wrapper.table_policy_sha256, _wrapper.table_span_policy = table_policy_sha256, table_span_policy


class Reader(_wrapper.Reader):
    def attest_claim_spans(self, graph, source, refs, *, tenant_id):
        result = super().attest_claim_spans(graph, source, tuple(refs), tenant_id=tenant_id)
        if result.get("schema") == "claim_source_h6_unreadable_v1":
            result.update(
                tenant_id=tenant_id,
                document_version_id=graph.document_version_id,
                parse_manifest_id=graph.parse_manifest_id,
                source_sha256=graph.source_sha256,
                graph_sha256=canonical_hash(asdict(graph)),
            )
            result["artifact_sha256"] = canonical_hash(
                {k: v for k, v in result.items() if k != "artifact_sha256"}
            )
        return result

    def _native_receipt(self, graph, source, *, tenant_id, **kwargs):
        result = super()._native_receipt(graph, source, tenant_id=tenant_id, **kwargs)
        if not kwargs.get("tables") and result.get("schema") == "source_h6_unreadable_v1":
            # H6's fallback omitted identity and used a schema that native
            # checkpoints correctly refuse. Complete the new receipt, retaining
            # unresolved records and only H7's independently proved promotions.
            result.update(
                schema="native_paragraph_attestation_v2",
                native_text_status="unreadable",
                tenant_id=tenant_id,
                document_version_id=graph.document_version_id,
                parse_manifest_id=graph.parse_manifest_id,
                source_sha256=graph.source_sha256,
                input_graph_sha256=canonical_hash(asdict(graph)),
            )
            result["artifact_sha256"] = canonical_hash(
                {k: v for k, v in result.items() if k != "artifact_sha256"}
            )
        return result


def for_run(run_id):
    return Reader(previous._LocalOnlyStore(), run_id=run_id)


_wrapper.for_run = for_run


def attest_claim_spans(graph, source, refs, *, tenant_id, run_id=None):
    return for_run(run_id).attest_claim_spans(graph, source, refs, tenant_id=tenant_id)


def attest_tables(graph, source, *, tenant_id, run_id=None):
    return for_run(run_id).attest_tables(graph, source, tenant_id=tenant_id)


def replay_tables(receipt, graph, source, *, tenant_id):
    return for_run(receipt["run_id"]).replay_tables(receipt, graph, source, tenant_id=tenant_id)


_wrapper._replay.for_run = for_run
replay_claim_spans = _wrapper._replay.replay_claim_spans
