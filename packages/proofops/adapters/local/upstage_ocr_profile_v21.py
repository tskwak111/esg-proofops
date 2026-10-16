"""V23 composes FXA render-conditioned prose with the D2 page-local OCR reader."""

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import claim_source_verification as strict
from proofops.adapters.local import claim_source_verification_v4 as prose
from proofops.adapters.local import upstage_ocr_profile_d2_v21 as previous
from proofops.domain.provenance import canonical_hash

PROFILE = "upstage-ocr-page-v21"
# Preserve the historical/hosted store injection surface. D2 wraps this store
# through its own PageOCRStore.from_env before reading.
PageOCRStore = previous.BasePageOCRStore
# Native, evidence and table paths use the complete D2 reader.
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
        prose_policy_sha256=canonical_hash(prose.claim_source_policy()),
        evidence_policy=previous.claim_source_policy()["evidence_policy"],
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        admission="v4-verified-paragraphs; d2-for-remaining-spans",
    )


class Reader:
    def __init__(self, *, run_id):
        self.previous = previous.for_run(run_id)
        self.run_id = run_id

    def __getattr__(self, name):
        return getattr(self.previous, name)

    def attest_claim_spans(
        self, graph, source, refs, *, tenant_id, run_id=None, previous_receipt=None
    ):
        refs = tuple(refs)
        blocks = {b.source_id: b for b in graph.blocks}
        large = self.previous._large(graph, source, tenant_id)
        paragraphs = tuple(r for r in refs if not large and blocks[r.source_id].kind == "paragraph")
        prose_receipt = prose.attest_claim_spans(graph, source, paragraphs, tenant_id=tenant_id)
        accepted = {
            canonical_hash(r["ref"]) for r in prose_receipt["records"] if r["status"] == "verified"
        }
        rest = tuple(r for r in refs if canonical_hash(asdict(r)) not in accepted)
        body = dict(
            schema="claim_source_i20_attestation_v1",
            policy=claim_source_policy(),
            tenant_id=tenant_id,
            run_id=self.run_id,
            source_sha256=graph.source_sha256,
            document_version_id=graph.document_version_id,
            parse_manifest_id=graph.parse_manifest_id,
            input_graph_sha256=canonical_hash(asdict(graph)),
            graph_sha256=canonical_hash(asdict(graph)),
            prose_receipt=prose_receipt,
            previous_receipt=(
                self.previous.attest_claim_spans(graph, source, rest, tenant_id=tenant_id)
                if previous_receipt is None
                else self.previous.recompute_claim_receipt(
                    previous_receipt, graph, source, rest, tenant_id=tenant_id
                )
            ),
        )
        body["pb1_cell_proofs"] = body["previous_receipt"]["pb1_cell_proofs"]
        records = {
            canonical_hash(record["ref"]): record for record in body["previous_receipt"]["records"]
        }
        records.update(
            {
                canonical_hash(record["ref"]): record
                for record in prose_receipt["records"]
                if record["status"] == "verified"
            }
        )
        # Fresh-proof cache keys bind the caller's complete ordered ref list.
        body["records"] = [records[canonical_hash(asdict(ref))] for ref in refs]
        return body | dict(artifact_sha256=canonical_hash(body))

    def recompute_claim_receipt(self, receipt, graph, source, refs, *, tenant_id):
        # Retain authenticated page collections for cold replay; acquisition is
        # never needed for prose; D2 retains page-local acquisition failures.
        expected = self.attest_claim_spans(
            graph,
            source,
            refs,
            tenant_id=tenant_id,
            previous_receipt=receipt["previous_receipt"],
        )
        if canonical_hash(receipt) != canonical_hash(expected):
            raise ValueError("I20_CLAIM_RECEIPT_MISMATCH")
        return expected


def for_run(run_id):
    return Reader(run_id=run_id)


def attest_claim_spans(graph, source, refs, *, tenant_id, run_id=None):
    return for_run(run_id).attest_claim_spans(graph, source, refs, tenant_id=tenant_id)


def replay_claim_spans(receipt, graph, source, discovery, *, tenant_id):
    expected = for_run(receipt["run_id"]).recompute_claim_receipt(
        receipt, graph, source, strict.discovery_refs(discovery), tenant_id=tenant_id
    )
    from proofops.adapters.local.verified_read_cache import _project_owned_cells

    return _project_owned_cells(expected, graph, discovery, tenant_id, failed_state="candidate")
