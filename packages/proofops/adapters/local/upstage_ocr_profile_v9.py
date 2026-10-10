"""PB4 table ownership extension; prose/native replay calls the exact v6 reader."""

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import upstage_ocr_profile_v6 as v6
from proofops.adapters.local import upstage_ocr_profile_v8 as table_base
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef

PROFILE = "upstage-ocr-page-v9"
PageOCRStore = v6.PageOCRStore
native_policy = v6.native_policy
table_policy_sha256 = v6.table_policy_sha256
table_span_policy = v6.table_span_policy
attest_tables = v6.attest_tables
replay_tables = v6.replay_tables


def reader_policy():
    return dict(
        v6.reader_policy(),
        profile=PROFILE,
        prose_reader_policy_sha256=canonical_hash(v6.reader_policy()),
        table_reader_policy_sha256=canonical_hash(table_base.reader_policy()),
        table_reader_sha256=sha256(Path(table_base.__file__).read_bytes()).hexdigest(),
        native_row_ownership="all-selected-cells-pb4-v1",
    )


def claim_source_policy():
    return dict(
        schema="claim_span_typography_policy_v1",
        profile=PROFILE,
        base_prose_policy_sha256=canonical_hash(v6.claim_source_policy()),
        reader=reader_policy(),
        wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def cell_proof(graph, source, refs, *, tenant_id):
    """A parser row must also be one native row, in the declared column order."""
    refs = tuple(refs)
    records = table_base.cell_proof(graph, source, refs, tenant_id=tenant_id)
    blocks = {b.source_id: b for b in graph.blocks}
    for ref, record in zip(refs, records, strict=True):
        if record["status"] != "verified":
            continue
        _table, parts = table_base._segments(graph, blocks[ref.source_id], ref, tenant_id)
        # An explicitly attested year header is contextual evidence above the
        # selected row. It is not an extra cell of the contiguous row quote.
        row = parts[0][0].candidates[parts[0][0].winner].row_number
        selected = [p for p in record["cell_proofs"] if p["row"] == row]
        if selected and max(p["native_bbox"][1] for p in selected) >= min(
            p["native_bbox"][3] for p in selected
        ):
            record.update(status="unresolved", reason="cell_native_order_unresolved")
            record.pop("cell_proofs", None)
            continue
        for previous, current in zip(selected, selected[1:]):
            left, right = previous["native_bbox"], current["native_bbox"]
            if (
                previous["column"] >= current["column"]
                or left[2] > right[0]
                or max(left[1], right[1]) >= min(left[3], right[3])
            ):
                record.update(status="unresolved", reason="cell_native_order_unresolved")
                record.pop("cell_proofs", None)
                break
    return records


def _extend(baseline, graph, source, refs, *, tenant_id):
    blocks = {b.source_id: b for b in graph.blocks}
    indices = [i for i, r in enumerate(refs) if blocks[r.source_id].kind in {"table", "table_cell"}]
    proofs = (
        cell_proof(graph, source, [refs[i] for i in indices], tenant_id=tenant_id)
        if indices
        else []
    )
    records = deepcopy(baseline["records"])
    for index, proof in zip(indices, proofs, strict=True):
        records[index].update(status=proof["status"], reason=proof["reason"])
    receipt = dict(
        schema="claim_source_pb4_extension_v1",
        policy=claim_source_policy(),
        baseline_receipt=baseline,
        records=records,
        pb1_cell_proofs=proofs,
        **{
            k: baseline[k]
            for k in (
                "tenant_id",
                "document_version_id",
                "parse_manifest_id",
                "run_id",
                "source_sha256",
                "graph_sha256",
            )
        },
    )
    receipt["artifact_sha256"] = canonical_hash(receipt)
    return receipt


class Reader(v6.Reader):
    def attest_claim_spans(self, graph, source, refs, *, tenant_id):
        refs = tuple(refs)
        baseline = super().attest_claim_spans(graph, source, refs, tenant_id=tenant_id)
        return _extend(baseline, graph, source, refs, tenant_id=tenant_id)

    def recompute_claim_receipt(self, receipt, graph, source, refs, *, tenant_id):
        if receipt.get("policy") != claim_source_policy() or receipt.get("run_id") != self.run_id:
            raise ValueError("OCR_POLICY_OR_RUN_MISMATCH")
        baseline = super().recompute_claim_receipt(
            receipt["baseline_receipt"], graph, source, tuple(refs), tenant_id=tenant_id
        )
        expected = _extend(baseline, graph, source, tuple(refs), tenant_id=tenant_id)
        if canonical_hash(receipt) != canonical_hash(expected):
            raise ValueError("OCR_CLAIM_RECEIPT_MISMATCH")
        return expected


def for_run(run_id):
    return Reader(PageOCRStore.from_env(), run_id=run_id)


def attest_claim_spans(graph, source, refs, *, tenant_id, run_id=None):
    if run_id is None:
        raise ValueError("OCR_RUN_REQUIRED")
    return for_run(run_id).attest_claim_spans(graph, source, refs, tenant_id=tenant_id)


def replay_claim_spans(receipt, graph, source, discovery, *, tenant_id):
    from proofops.adapters.local.claim_source_verification import discovery_refs
    from proofops.application.evidence.span_citations import span_verified_graph, verify_source_ref

    refs = discovery_refs(discovery)
    checked = for_run(receipt["run_id"]).recompute_claim_receipt(
        receipt, graph, source, refs, tenant_id=tenant_id
    )
    approved = {
        (r["ref"]["source_id"], r["ref"]["char_start"], r["ref"]["char_end"])
        for r in checked["records"]
        if r["status"] == "verified"
    }
    newly = tuple(
        replace(SourceRef(**r["ref"]), verification_state="verified")
        for r in checked["records"]
        if r["status"] == "verified"
    )
    cells = tuple(
        replace(SourceRef(**c["source_ref"]), verification_state="verified")
        for p in checked["pb1_cell_proofs"]
        if p["status"] == "verified"
        for c in p["cell_proofs"]
        if not c.get("recovered_selection")
    )
    existing = tuple(getattr(graph, "verified_spans", ()))
    seen = {(r.source_id, r.char_start, r.char_end) for r in existing}
    scoped = span_verified_graph(
        graph,
        existing
        + tuple(r for r in (*newly, *cells) if (r.source_id, r.char_start, r.char_end) not in seen),
        checked["artifact_sha256"],
    )
    blocks = {b.source_id: b for b in graph.blocks}
    claims = []
    for claim in discovery.claims:
        table_claim = any(
            blocks[r.source_id].kind in {"table", "table_cell"} for r in claim.source_refs
        )
        if table_claim and not all(
            (r.source_id, r.char_start, r.char_end) in approved for r in claim.source_refs
        ):
            # A whole-table flag or an inherited span cannot override this
            # reader's failed native ownership proof for the selected row.
            claims.append(
                replace(
                    claim,
                    source_quality="unverified"
                    if claim.source_quality == "verified"
                    else claim.source_quality,
                    source_refs=tuple(
                        replace(r, verification_state="unverified")
                        if r.verification_state == "verified"
                        else r
                        for r in claim.source_refs
                    ),
                )
            )
            continue
        if claim.source_quality != "unverified":
            claims.append(claim)
            continue
        sources = tuple(
            verify_source_ref(r, scoped, tenant_id=tenant_id) for r in claim.source_refs
        )
        claims.append(
            replace(claim, source_quality="verified", source_refs=sources)
            if sources and all(r.verification_state == "verified" for r in sources)
            else claim
        )
    return replace(discovery, claims=tuple(claims)), scoped
