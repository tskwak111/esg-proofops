"""Current C3 spans use the main pipeline's FXA + D2 source reader.

The original bytes are checked again under the current run and exact parser
refs. A selected-page pipeline receipt is not transferable to the original PDF.
Historical C2 receipts retain their original verifier and policy bytes.
"""

from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import c2_selected_sources as legacy
from proofops.adapters.local import upstage_ocr_profile_v21 as current
from proofops.application.evidence.span_citations import span_verified_graph
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef

SCHEMA = "c3_current_source_receipt_v1"


def policy():
    return dict(
        profile="c3-current-claim-source-v1",
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        claim_source_policy=current.claim_source_policy(),
        admission="current-run-exact-spans; FXA-visibility-and-D2-pixels; no-parent-promotion",
    )


def attest(graph, source, refs, *, tenant_id, run_id):
    receipt = current.for_run(run_id).attest_claim_spans(
        graph, source, tuple(refs), tenant_id=tenant_id
    )
    body = dict(
        schema=SCHEMA,
        policy=policy(),
        run_id=run_id,
        claim_source_receipt=receipt,
    )
    return body | dict(artifact_sha256=canonical_hash(body))


def replay(receipt, graph, source, *, tenant_id, run_id):
    if receipt.get("schema") == "c2_selected_source_receipt_v1":
        return legacy.replay(receipt, graph, source, tenant_id=tenant_id)
    if (
        receipt.get("schema") != SCHEMA
        or receipt.get("policy") != policy()
        or receipt.get("run_id") != run_id
        or receipt.get("artifact_sha256")
        != canonical_hash({k: v for k, v in receipt.items() if k != "artifact_sha256"})
    ):
        raise ValueError("C3_SOURCE_POLICY_OR_RUN_MISMATCH")
    saved = receipt["claim_source_receipt"]
    if (
        saved.get("policy") != current.claim_source_policy()
        or saved.get("run_id") != run_id
        or saved.get("tenant_id") != tenant_id
        or saved.get("document_version_id") != graph.document_version_id
        or saved.get("parse_manifest_id") != graph.parse_manifest_id
        or saved.get("source_sha256") != graph.source_sha256
        or saved.get("input_graph_sha256") != canonical_hash(asdict(graph))
    ):
        raise ValueError("C3_SOURCE_IDENTITY_MISMATCH")
    refs = tuple(SourceRef(**r["ref"]) for r in saved["records"])
    expected = current.for_run(run_id).recompute_claim_receipt(
        saved, graph, source, refs, tenant_id=tenant_id
    )
    verified = tuple(
        replace(SourceRef(**r["ref"]), verification_state="verified")
        for r in expected["records"]
        if r["status"] == "verified"
    )
    return span_verified_graph(graph, verified, receipt["artifact_sha256"])
