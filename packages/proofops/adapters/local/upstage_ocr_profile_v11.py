"""K3 literal column recovery. Older readers and all prose gates stay unchanged.

Only one parser cell may use this fallback. Physical column rules and independently
read column headings locate the owner; a unique native literal proves the quote.
No row concatenation, status reordering, character repair or semantic binding.
"""

import io
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

import pdfplumber

from proofops.adapters.local import upstage_ocr_profile_v6 as v6
from proofops.adapters.local import upstage_ocr_profile_v8 as table_base
from proofops.adapters.local import upstage_ocr_profile_v10 as previous
from proofops.adapters.parsing.gemini_vision import compact
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef

PROFILE = "upstage-ocr-page-v11"
PageOCRStore = v6.PageOCRStore
native_policy = v6.native_policy
table_policy_sha256 = v6.table_policy_sha256
table_span_policy = v6.table_span_policy
attest_tables = v6.attest_tables
replay_tables = v6.replay_tables


def reader_policy():
    return dict(
        previous.reader_policy(),
        profile=PROFILE,
        recovery="one-cell-native-column-k3-v1",
        previous_policy_sha256=canonical_hash(previous.claim_source_policy()),
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def claim_source_policy():
    return dict(
        schema="claim_span_typography_policy_v1",
        profile=PROFILE,
        base_prose_policy_sha256=canonical_hash(v6.claim_source_policy()),
        reader=reader_policy(),
        wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def _column_owners(page, graph, table):
    grid = previous._grid(graph, table)
    heads = sorted((c, b) for (r, c), b in grid.items() if r == 0)
    if len(heads) < 2 or [c for c, _ in heads] != list(range(len(heads))):
        raise ValueError("column_headers_unresolved")
    if any(b.candidates[b.winner].column_span != 1 for _, b in heads):
        raise ValueError("column_headers_unresolved")
    box = table.bbox
    if box is None:
        raise ValueError("source_invalid")
    xs = sorted(
        {
            round(e["x0"], 3)
            for e in page.edges
            if abs(e["x0"] - e["x1"]) < 0.05
            and e["bottom"] - e["top"] >= 0.8 * (box[3] - box[1])
            and box[1] - 2 <= e["top"] < e["bottom"] <= box[3] + 2
            and box[0] + 2 < e["x0"] < box[2] - 2
        }
    )
    if len(xs) != len(heads) - 1:
        raise ValueError("native_columns_unresolved")
    xs = [box[0], *xs, box[2]]
    owners, proofs = {}, []
    for col, head in heads:
        owner = (xs[col], box[1], xs[col + 1], box[3])
        native = previous._literal(page, owner, head.raw_text)
        if head.bbox is not None and not previous._within(native, head.bbox, 0.5):
            raise ValueError("header_native_owner_unresolved")
        owners[col] = owner
        proofs.append(
            dict(
                column=col,
                quote=head.raw_text,
                native_bbox=native,
                source_ref=asdict(head.source_ref()),
            )
        )
    if max(p["native_bbox"][1] for p in proofs) >= min(p["native_bbox"][3] for p in proofs):
        raise ValueError("header_native_row_unresolved")
    return owners, proofs


def _column_literal(page, owner, quote):
    # This fallback only recovers a single bullet, never joined declarations.
    if not quote.lstrip().startswith("•") or quote.count("•") != 1:
        raise ValueError("column_recovery_requires_one_bullet")
    matched = previous._literal(page, owner, quote)
    chars = [
        c
        for c in page.chars
        if previous._within((c["x0"], c["top"], c["x1"], c["bottom"]), matched)
    ]
    if compact("".join(c["text"] for c in chars)) != compact(quote):
        raise ValueError("cell_native_order_unresolved")
    for left, right in zip(chars, chars[1:]):
        height = max(left["bottom"] - left["top"], right["bottom"] - right["top"])
        if min(left["bottom"], right["bottom"]) > max(left["top"], right["top"]):
            if right["x0"] < left["x0"] - 0.5 or right["x0"] - left["x1"] > 2 * height:
                raise ValueError("cell_native_order_unresolved")
        elif right["top"] < left["top"] - 0.5 or right["top"] - left["bottom"] > 2 * height:
            raise ValueError("cell_native_order_unresolved")
    return matched


def cell_proof(graph, source, refs, *, tenant_id):
    refs = tuple(refs)
    records = previous.cell_proof(graph, source, refs, tenant_id=tenant_id)
    if sha256(source).hexdigest() != graph.source_sha256:
        return records
    blocks = {b.source_id: b for b in graph.blocks}
    with pdfplumber.open(io.BytesIO(source)) as document:
        owners = {}
        for ref, record in zip(refs, records, strict=True):
            if record["reason"] not in {"cell_native_literal_unresolved", "cell_source_unresolved"}:
                continue
            try:
                table, parts = table_base._segments(graph, blocks[ref.source_id], ref, tenant_id)
                if len(parts) != 1:  # An entire numeric row keeps the PA9 row proof.
                    raise ValueError("column_recovery_requires_one_cell")
                cell, cell_ref = parts[0]
                page = document.pages[ref.page_num - 1]
                if page.rotation or tuple(page.cropbox[:2]) != (0, 0):
                    raise ValueError("geometry_unsupported")
                if table.source_id not in owners:
                    owners[table.source_id] = _column_owners(page, graph, table)
                regions, headers = owners[table.source_id]
                candidate = cell.candidates[cell.winner]
                owner = regions[candidate.column_number]
                if candidate.has_invalid_geometry:
                    raise ValueError("source_invalid")
                matched = _column_literal(page, owner, cell_ref.quote)
                if matched[1] <= max(h["native_bbox"][3] for h in headers):
                    raise ValueError("cell_native_order_unresolved")
                if cell.bbox is not None and not previous._within(matched, cell.bbox, 0.5):
                    raise ValueError("cell_source_unresolved")
                record.update(
                    status="verified",
                    reason=None,
                    table_id=table.source_id,
                    ownership="native-column-k3-v1",
                    column_headers=headers,
                    cell_proofs=[
                        dict(
                            source_ref=asdict(cell_ref),
                            native_bbox=matched,
                            owner_bbox=owner,
                            row=candidate.row_number,
                            column=candidate.column_number,
                            recovered_selection=cell.bbox is None,
                        )
                    ],
                )
            except (ValueError, KeyError) as error:
                record["k3_recovery_reason"] = str(error)
    return records


def _extend(baseline, graph, source, refs, *, tenant_id):
    receipt = previous._extend(baseline, graph, source, refs, tenant_id=tenant_id)
    blocks = {b.source_id: b for b in graph.blocks}
    indices = [i for i, r in enumerate(refs) if blocks[r.source_id].kind in {"table", "table_cell"}]
    proofs = (
        cell_proof(graph, source, [refs[i] for i in indices], tenant_id=tenant_id)
        if indices
        else []
    )
    for index, proof in zip(indices, proofs, strict=True):
        receipt["records"][index].update(status=proof["status"], reason=proof["reason"])
    receipt.update(
        schema="claim_source_k3_extension_v1", policy=claim_source_policy(), pb1_cell_proofs=proofs
    )
    receipt.pop("artifact_sha256", None)
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
                        replace(r, verification_state="candidate")
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
