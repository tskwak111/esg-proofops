"""K7 structural-grid observed headers, preserving every historical source reader."""

import io
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import pdfplumber

from proofops.adapters.local import upstage_ocr_profile_v10 as native
from proofops.adapters.local import upstage_ocr_profile_v12 as previous
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.adapters.local.local_raster_reader import interactive_catalog_requires_review
from proofops.application.ingest.k6_coverage import observations_for
from proofops.application.ingest.w9_tables import graph_cells, grid
from proofops.domain.provenance import canonical_hash

PROFILE = "upstage-ocr-page-v13"
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
        recovery="explicit-origin-grid-k6-observed-row-and-all-year-headers",
        admission="exact-native-cell-literal-location-row-column-and-visibility; no-repair",
    )


def cell_proof(graph, source, refs, *, tenant_id):
    from proofops.adapters.local import upstage_ocr_profile_v8 as structure
    from proofops.adapters.local import upstage_ocr_profile_v11 as baseline

    refs = tuple(refs)
    if tenant_id != graph.tenant_id or sha256(source).hexdigest() != graph.source_sha256:
        return [dict(ref=asdict(r), status="unresolved", reason="source_invalid") for r in refs]
    records = baseline.cell_proof(graph, source, refs, tenant_id=tenant_id)
    if interactive_catalog_requires_review(source):
        return records
    blocks = {b.source_id: b for b in graph.blocks}
    with pdfplumber.open(io.BytesIO(source)) as document:
        for ref, record in zip(refs, records, strict=True):
            if record["status"] == "verified":
                continue
            try:
                table = blocks[ref.source_id]
                if table.kind != "table" or not structure.tables.tables._checked_ref(
                    graph, ref, table, tenant_id
                ):
                    raise ValueError("source_invalid")
                observation = next(
                    (
                        o
                        for o in observations_for(table, graph)
                        if (o["start"], o["end"]) == (ref.char_start, ref.char_end)
                    ),
                    None,
                )
                if observation is None:
                    raise ValueError("observed_row_unresolved")
                cells = native._grid(graph, table)
                rows = grid(table.normalized_text, graph_cells(table, graph))
                row = rows[observation["row"]]
                selected = [
                    (e["cell"]["row"], e["column"])
                    for e in row["entries"]
                    if e["cell"] and e["text"]
                ]
                heads = [observation["year_header"]]
                for comparison in observation["comparisons"]:
                    matches = [
                        e
                        for r in rows[: observation["row"]]
                        for e in r["entries"]
                        if e["column"] == comparison["column"]
                        and e["cell"]
                        and e["text"].strip().startswith(comparison["year"])
                    ]
                    if len(matches) != 1:
                        raise ValueError("observed_year_header_unresolved")
                    heads.append(dict(row=matches[0]["cell"]["row"], column=comparison["column"]))
                selected += [(h["row"], h["column"]) for h in heads]
                page = document.pages[ref.page_num - 1]
                if page.rotation or tuple(page.cropbox[:2]) != (0, 0):
                    raise ValueError("geometry_unsupported")
                # Independently painted header cells prove physical columns even
                # when a glyph-tight parser box clips their outer table rules.
                column_owners = {}
                for key, header in sorted(cells.items()):
                    if key[0] != observation["year_header"]["row"]:
                        continue
                    rectangles = []
                    for rect in page.rects:
                        box = tuple(rect[k] for k in ("x0", "top", "x1", "bottom"))
                        if header.bbox is None or not native._within(header.bbox, box):
                            continue
                        try:
                            native._literal(page, box, header.raw_text, whole=True)
                        except ValueError:
                            continue
                        rectangles.append(box)
                    if len(set(rectangles)) != 1:
                        raise ValueError("header_native_owner_unresolved")
                    column_owners[key[1]] = rectangles[0]
                owners = list(column_owners.values())
                if any(
                    a[2] > b[0] + 0.01 or abs(a[1] - b[1]) > 0.01 or abs(a[3] - b[3]) > 0.01
                    for a, b in zip(owners, owners[1:])
                ):
                    raise ValueError("header_native_order_unresolved")
                proofs = []
                for key in selected:
                    cell = cells[key]
                    cell_ref = cell.source_ref()
                    if cell.bbox is None or not structure.tables.tables._checked_ref(
                        graph, cell_ref, cell, tenant_id
                    ):
                        raise ValueError("cell_source_unresolved")
                    matched = native._literal(page, cell.bbox, cell_ref.quote, whole=True)
                    owner = column_owners[key[1]]
                    if not owner[0] <= matched[0] < matched[2] <= owner[2]:
                        raise ValueError("header_native_column_unresolved")
                    proofs.append(
                        dict(
                            source_ref=asdict(cell_ref),
                            native_bbox=matched,
                            row=key[0],
                            column=key[1],
                            recovered_selection=False,
                            column_owner_bbox=owner,
                        )
                    )
                row_proofs = [p for p in proofs if p["row"] == observation["row"]]
                if max(p["native_bbox"][1] for p in row_proofs) >= min(
                    p["native_bbox"][3] for p in row_proofs
                ):
                    raise ValueError("cell_native_order_unresolved")
                if any(
                    a["column"] >= b["column"] or a["native_bbox"][2] > b["native_bbox"][0]
                    for a, b in zip(row_proofs, row_proofs[1:])
                ):
                    raise ValueError("cell_native_order_unresolved")
                header_proofs = [p for p in proofs if p["row"] != observation["row"]]
                if any(
                    p["native_bbox"][3] >= min(r["native_bbox"][1] for r in row_proofs)
                    for p in header_proofs
                ):
                    raise ValueError("header_native_row_unresolved")
                record.update(
                    status="verified",
                    reason=None,
                    cell_proofs=proofs,
                    ownership="explicit-native-observed-grid-k7-v1",
                )
            except (ValueError, KeyError, IndexError) as error:
                record["k7_recovery_reason"] = str(error)
    return records


class Reader(previous.Reader):
    def attest_claim_spans(self, graph, source, refs, *, tenant_id):
        refs = tuple(refs)
        result = super().attest_claim_spans(graph, source, refs, tenant_id=tenant_id)
        blocks = {b.source_id: b for b in graph.blocks}
        selected = [i for i, r in enumerate(refs) if blocks[r.source_id].kind == "table"]
        proofs = cell_proof(graph, source, [refs[i] for i in selected], tenant_id=tenant_id)
        for index, proof in zip(selected, proofs, strict=True):
            result["records"][index].update(status=proof["status"], reason=proof["reason"])
            for old in result["pb1_cell_proofs"]:
                if old["ref"] == proof["ref"]:
                    old.update(proof)
        result.update(schema="claim_source_k7_extension_v1", policy=claim_source_policy())
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
    Path(__file__).parent, "upstage_ocr_profile_v11.py", "proofops.adapters.local._k7_replay"
)
_replay.for_run = for_run
replay_claim_spans = _replay.replay_claim_spans
