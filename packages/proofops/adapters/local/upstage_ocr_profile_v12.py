"""H1 heading spans use the unchanged native/glyph/visible-text proof.

Parser kind is not source truth. This changes heading eligibility only; no
paragraph/table guard, quote, canonical source ID or evidence binding changes.
"""

import io
import re
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium

from proofops.adapters.local import upstage_ocr_profile_v11 as previous
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.domain.provenance import canonical_hash

PROFILE = "upstage-ocr-page-v12"
PageOCRStore = previous.PageOCRStore
native_policy = previous.native_policy
table_policy_sha256 = previous.table_policy_sha256
table_span_policy = previous.table_span_policy
attest_tables = previous.attest_tables
replay_tables = previous.replay_tables


def claim_source_policy():
    return dict(
        schema="claim_span_typography_policy_v1",
        profile=PROFILE,
        previous_policy_sha256=canonical_hash(previous.claim_source_policy()),
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        eligible="heading/source_invalid-or-complete-single-cell-prose; exact-source-reference",
        admission="unchanged-v3-native-glyph-quantity-annotation-and-page-OCR-proof",
    )


class Reader(previous.Reader):
    def _claim_receipt(self, modules, graph, source, refs, *, tenant_id):
        baseline = super()._claim_receipt(modules, graph, source, refs, tenant_id=tenant_id)
        blocks = {b.source_id: b for b in graph.blocks}
        records = deepcopy(baseline["records"])
        literal = _exec_private(
            Path(__file__).parent,
            "claim_source_verification_v3.py",
            "proofops.adapters.local._h1_heading",
        )
        literal.strict = modules["claim_source_verification"]
        literal._rendered_text = literal.strict._rendered_text
        page_cache, render_cache, proofs = {}, {}, []
        with pdfplumber.open(io.BytesIO(source)) as document, pdfium.PdfDocument(source) as native:
            for index, ref in enumerate(refs):
                block, record = blocks.get(ref.source_id), records[index]
                if (
                    block is None
                    or block.kind not in {"heading", "table_cell"}
                    or block.winner is None
                    or block.quality not in {"verified", "unverified"}
                    or record.get("reason") != "source_invalid"
                ):
                    continue
                if block.kind == "table_cell":
                    c = block.candidates[block.winner]
                    # A bare value still needs its row/year proof. This extension
                    # proves only a complete literal statement in ONE stored cell.
                    if (
                        c.row_number is None
                        or c.column_number is None
                        or not c.table_native_id
                        or "\t" in ref.quote
                        or len(ref.quote) < 20
                        or not re.search(r"다[.!?。]?\s*$", ref.quote)
                    ):
                        continue
                checked = replace(
                    graph,
                    blocks=tuple(
                        replace(b, quality="verified") if b == block else b for b in graph.blocks
                    ),
                )
                if (
                    verify_source_ref(ref, checked, tenant_id=tenant_id).verification_state
                    != "verified"
                ):
                    continue
                proof = literal._recover(
                    document, native, block, ref, page_cache, render_cache, graph.source_sha256
                )
                record.update(proof)
                proofs.append(dict(ref=asdict(ref), kind=block.kind, **proof))
        result = dict(baseline, records=records, heading_proofs=proofs)
        result.pop("artifact_sha256", None)
        result["artifact_sha256"] = canonical_hash(result)
        return result

    def attest_claim_spans(self, graph, source, refs, *, tenant_id):
        result = super().attest_claim_spans(graph, source, tuple(refs), tenant_id=tenant_id)
        proofs = result["baseline_receipt"].get("heading_proofs", [])
        # The older row verifier intentionally rejects standalone cells. Only
        # its precise narrative-cell failure is eligible; corrupt grids, native
        # ownership conflicts, numbers and unresolved visibility remain held.
        for proof in proofs:
            if proof["kind"] != "table_cell" or proof["status"] != "verified":
                continue
            for record in result["records"]:
                if record["ref"] == proof["ref"] and record["reason"] == "pb1_value_requires_row":
                    record.update(status="verified", reason=None, h1_literal_proof=proof)
                    for cell in result["pb1_cell_proofs"]:
                        if cell["ref"] == proof["ref"]:
                            cell.update(
                                status="verified",
                                reason=None,
                                cell_proofs=[
                                    dict(
                                        source_ref=proof["ref"],
                                        native_bbox=proof["normalization"]["bbox"],
                                        attribution="literal-source-only-no-row-year-evidence",
                                    )
                                ],
                            )
        result.update(schema="claim_source_h1_extension_v1", policy=claim_source_policy())
        result.pop("artifact_sha256", None)
        result["artifact_sha256"] = canonical_hash(result)
        return result

    def recompute_claim_receipt(self, receipt, graph, source, refs, *, tenant_id):
        if receipt.get("policy") != claim_source_policy() or receipt.get("run_id") != self.run_id:
            raise ValueError("OCR_POLICY_OR_RUN_MISMATCH")
        expected = self.attest_claim_spans(graph, source, refs, tenant_id=tenant_id)
        if canonical_hash(receipt) != canonical_hash(expected):
            raise ValueError("OCR_CLAIM_RECEIPT_MISMATCH")
        return expected


def for_run(run_id):
    return Reader(PageOCRStore.from_env(), run_id=run_id)


def attest_claim_spans(graph, source, refs, *, tenant_id, run_id=None):
    if run_id is None:
        raise ValueError("OCR_RUN_REQUIRED")
    return for_run(run_id).attest_claim_spans(graph, source, refs, tenant_id=tenant_id)


_replay = _exec_private(
    Path(__file__).parent, "upstage_ocr_profile_v11.py", "proofops.adapters.local._h1_replay"
)
_replay.for_run = for_run
replay_claim_spans = _replay.replay_claim_spans
