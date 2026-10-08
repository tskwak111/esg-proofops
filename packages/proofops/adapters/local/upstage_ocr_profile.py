"""Opt-in page OCR composition over unchanged native/claim verifier bytes.

Private module namespaces follow frozen_native_replay's existing isolation
pattern. No shared module or frozen byte is modified; legacy policy hashes hold.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.adapters.local.upstage_ocr_page import (
    PROFILE,
    PageOCRStore,
    map_words,
    parse_response,
    reader_policy,
    render_page,
)
from proofops.application.evidence import span_citations
from proofops.application.ingest.gri import _validate_graph
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef


def claim_source_policy():
    from proofops.adapters.local import glyph_alignment_verification as apple

    return dict(
        schema="claim_span_typography_policy_v1",
        profile=PROFILE,
        base=apple.claim_source_policy(),
        reader=reader_policy(),
        wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def native_policy():
    from proofops.adapters.local.run_artifacts import native_paragraph_policy

    return dict(
        mode=PROFILE,
        base=native_paragraph_policy(),
        reader=reader_policy(),
        wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


class Reader:
    def __init__(self, store: PageOCRStore, *, run_id: str):
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("OCR_RUN_REQUIRED")
        self.store, self.run_id = store, run_id

    def _modules(self, graph, source, tenant_id, collections=None):
        _validate_graph(graph, tenant_id)
        if not isinstance(source, bytes) or sha256(source).hexdigest() != graph.source_sha256:
            raise ValueError("OCR_SOURCE_MISMATCH")
        seen = {}
        offline = collections is not None
        saved = {c["manifest"]["physical_page"]: c for c in (collections or [])}
        if len(saved) != len(collections or []):
            raise ValueError("OCR_DUPLICATE_COLLECTION")

        def read(page, box, **kwargs):
            num = page.page_number
            if num not in seen:
                image = render_page(source, num)
                if (
                    abs(page.width - image["manifest"]["width_pt"]) > 0.001
                    or abs(page.height - image["manifest"]["height_pt"]) > 0.001
                ):
                    raise ValueError("OCR_PAGE_COORDINATE_MISMATCH")
                if offline:
                    if num not in saved:
                        raise ValueError("OCR_REPLAY_PAGE_MISSING")
                    collection = self.store.validate(saved[num], image, tenant_id=tenant_id)
                else:
                    collection = self.store.fetch(image, tenant_id=tenant_id, run_id=self.run_id)
                seen[num] = collection
            collection = seen[num]
            manifest = collection["manifest"]
            boxes = set()
            for b in graph.blocks:
                if (
                    b.page_num != num
                    or b.kind not in {"paragraph", "table_cell"}
                    or b.winner is None
                ):
                    continue
                other = b.candidates[b.winner].bbox
                if other:
                    boxes.add(tuple(other))
            owners = [
                b
                for b in boxes
                if (
                    b[0] <= box[0] + 0.001
                    and b[1] <= box[1] + 0.001
                    and b[2] >= box[2] - 0.001
                    and b[3] >= box[3] - 0.001
                )
            ]
            owner = tuple(box) if tuple(box) in boxes else (owners[0] if len(owners) == 1 else None)
            if owner is None and len(owners) > 1:
                return dict(status="unresolved", reason="ocr_block_owner_ambiguous")
            peers = [b for b in boxes if b != owner]
            result = map_words(
                parse_response(bytes.fromhex(collection["response_hex"])),
                manifest,
                box,
                competing_boxes=peers,
            )
            return dict(
                **result,
                reader=PROFILE,
                image_sha256=manifest["png_sha256"],
                page_request_id=collection["request_id"],
                physical_page=num,
                source_sha256=manifest["source_sha256"],
                box=list(box),
                response_sha256=collection["response_sha256"],
                mapping_sha256=reader_policy()["mapping_sha256"],
            )

        folder = Path(__file__).parent
        modules = {
            name: _exec_private(
                folder, name + ".py", "proofops.adapters.local._ocr_private." + name
            )
            for name in (
                "source_verification",
                "selected_cell_table_verification",
                "claim_source_verification_v1",
                "claim_source_verification_v2",
                "claim_source_verification",
                "claim_span_render_resolution",
                "claim_span_bullet_alignment",
                "claim_span_typography",
                "glyph_alignment_verification",
                "table_span_source_verification",
            )
        }
        sv = modules["source_verification"]
        cell = modules["selected_cell_table_verification"]
        sv._rendered_text = read
        cell._rendered_cell = read
        for name in (
            "claim_source_verification_v1",
            "claim_source_verification_v2",
            "claim_source_verification",
        ):
            modules[name]._rendered_text = read
        strict = modules["claim_source_verification"]
        table_span = modules["table_span_source_verification"]
        table_span._rendered_text = read
        table_span.claim_verifier = strict
        render = modules["claim_span_render_resolution"]
        render.base = strict
        render.cell_reader = cell
        bullet = modules["claim_span_bullet_alignment"]
        bullet.baseline = render
        bullet.source_verification = sv
        typography = modules["claim_span_typography"]
        typography.baseline = bullet
        typography.base = strict
        glyph = modules["glyph_alignment_verification"]
        glyph.baseline = typography
        glyph.strict = strict
        return modules, seen

    def _finish(self, receipt, seen, *, native=False):
        receipt.update(
            rendered_reader_profile=PROFILE,
            run_id=self.run_id,
            page_collections=[seen[p] for p in sorted(seen)],
            replay_mode="offline_collected_response_recomputation_v1",
        )
        if native:
            receipt["reader_policy"] = native_policy()
            receipt["rendered_reader_sha256"] = reader_policy()["reader_sha256"]
        else:
            receipt["policy"] = claim_source_policy()
        receipt["artifact_sha256"] = canonical_hash(
            {k: v for k, v in receipt.items() if k != "artifact_sha256"}
        )
        return receipt

    def attest_claim_spans(self, graph, source, refs, *, tenant_id):
        modules, seen = self._modules(graph, source, tenant_id)
        result = modules["glyph_alignment_verification"].attest_claim_spans(
            graph, source, tuple(refs), tenant_id=tenant_id
        )
        return self._finish(result, seen)

    def attest_native_sources(self, graph, source, *, tenant_id, geometry_mode="glyph"):
        modules, seen = self._modules(graph, source, tenant_id)
        receipt = modules["source_verification"].attest_native_sources(
            graph, source, tenant_id=tenant_id, geometry_mode=geometry_mode
        )
        return self._finish(receipt, seen, native=True)

    def recompute_claim_receipt(self, receipt, graph, source, refs, *, tenant_id):
        if receipt.get("policy") != claim_source_policy() or receipt.get("run_id") != self.run_id:
            raise ValueError("OCR_POLICY_OR_RUN_MISMATCH")
        modules, seen = self._modules(graph, source, tenant_id, receipt.get("page_collections", []))
        expected = self._finish(
            modules["glyph_alignment_verification"].attest_claim_spans(
                graph, source, tuple(refs), tenant_id=tenant_id
            ),
            seen,
        )
        if canonical_hash(receipt) != canonical_hash(expected):
            raise ValueError("OCR_CLAIM_RECEIPT_MISMATCH")
        return expected

    def replay_native_sources(self, receipt, graph, source, *, tenant_id):
        if receipt.get("reader_policy") != native_policy() or receipt.get("run_id") != self.run_id:
            raise ValueError("OCR_POLICY_OR_RUN_MISMATCH")
        modules, seen = self._modules(graph, source, tenant_id, receipt.get("page_collections", []))
        mode = receipt.get("geometry_mode", "font")
        expected = self._finish(
            modules["source_verification"].attest_native_sources(
                graph, source, tenant_id=tenant_id, geometry_mode=mode
            ),
            seen,
            native=True,
        )
        if canonical_hash(receipt) != canonical_hash(expected):
            raise ValueError("OCR_NATIVE_RECEIPT_MISMATCH")
        verified = {r["source_id"] for r in expected["records"] if r["status"] == "verified"}
        return replace(
            graph,
            blocks=tuple(
                replace(b, quality="verified") if b.source_id in verified else b
                for b in graph.blocks
            ),
        )

    def attest_tables(self, graph, source, *, tenant_id):
        modules, seen = self._modules(graph, source, tenant_id)
        receipt = modules["selected_cell_table_verification"].attest_tables(
            graph, source, tenant_id=tenant_id
        )
        receipt["policy_sha256"] = table_policy_sha256()
        return self._finish(receipt, seen, native=True)

    def attest_table_spans(self, graph, source, refs, *, tenant_id, collections=None):
        modules, seen = self._modules(graph, source, tenant_id, collections)
        receipt = modules["table_span_source_verification"].attest_table_spans(
            graph, source, tuple(refs), tenant_id=tenant_id
        )
        self._finish(receipt, seen)
        receipt["policy"] = table_span_policy()
        receipt["artifact_sha256"] = canonical_hash(
            {k: v for k, v in receipt.items() if k != "artifact_sha256"}
        )
        return receipt

    def recompute_table_span_receipt(self, receipt, graph, source, refs, *, tenant_id):
        if receipt.get("run_id") != self.run_id or receipt.get("policy") != table_span_policy():
            raise ValueError("OCR_POLICY_OR_RUN_MISMATCH")
        expected = self.attest_table_spans(
            graph,
            source,
            refs,
            tenant_id=tenant_id,
            collections=receipt.get("page_collections", []),
        )
        if canonical_hash(expected) != canonical_hash(receipt):
            raise ValueError("OCR_TABLE_SPAN_RECEIPT_MISMATCH")
        return expected

    def replay_tables(self, receipt, graph, source, *, tenant_id):
        if receipt.get("run_id") != self.run_id or receipt.get("reader_policy") != native_policy():
            raise ValueError("OCR_POLICY_OR_RUN_MISMATCH")
        modules, seen = self._modules(graph, source, tenant_id, receipt.get("page_collections", []))
        baseline = modules["selected_cell_table_verification"].attest_tables(
            graph, source, tenant_id=tenant_id
        )
        expected = deepcopy(baseline)
        expected["policy_sha256"] = table_policy_sha256()
        self._finish(expected, seen, native=True)
        if canonical_hash(expected) != canonical_hash(receipt):
            raise ValueError("OCR_TABLE_RECEIPT_MISMATCH")
        return modules["selected_cell_table_verification"].replay_tables(
            baseline, graph, source, tenant_id=tenant_id
        )


def for_run(run_id):
    return Reader(PageOCRStore.from_env(), run_id=run_id)


def table_policy_sha256():
    from proofops.adapters.local.selected_cell_table_verification import policy_sha256

    return canonical_hash(dict(reader=native_policy(), selected_cell_policy=policy_sha256()))


def table_span_policy():
    from proofops.adapters.local import table_span_source_verification as base

    return dict(
        profile=PROFILE,
        base=base.table_span_policy(),
        line_base=base.line_span_policy(),
        reader=reader_policy(),
        wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def attest_tables(graph, source, *, tenant_id, run_id=None):
    if run_id is None:
        raise ValueError("OCR_RUN_REQUIRED")
    return for_run(run_id).attest_tables(graph, source, tenant_id=tenant_id)


def replay_tables(receipt, graph, source, *, tenant_id):
    return for_run(receipt["run_id"]).replay_tables(receipt, graph, source, tenant_id=tenant_id)


def attest_claim_spans(graph, source, refs, *, tenant_id, run_id=None):
    if run_id is None:
        raise ValueError("OCR_RUN_REQUIRED")
    return for_run(run_id).attest_claim_spans(graph, source, refs, tenant_id=tenant_id)


def replay_claim_spans(receipt, graph, source, discovery, *, tenant_id):
    from proofops.adapters.local.claim_source_verification import discovery_refs

    reader = for_run(receipt["run_id"])
    expected = reader.recompute_claim_receipt(
        receipt, graph, source, discovery_refs(discovery), tenant_id=tenant_id
    )
    newly = tuple(
        replace(SourceRef(**r["ref"]), verification_state="verified")
        for r in expected["records"]
        if r["status"] == "verified"
    )
    existing = tuple(getattr(graph, "verified_spans", ()) or ())
    seen = {(r.source_id, r.char_start, r.char_end) for r in existing}
    scoped = span_citations.span_verified_graph(
        graph,
        existing + tuple(r for r in newly if (r.source_id, r.char_start, r.char_end) not in seen),
        expected["artifact_sha256"],
    )
    claims = []
    for claim in discovery.claims:
        if claim.source_quality != "unverified":
            claims.append(claim)
            continue
        checked = tuple(
            span_citations.verify_source_ref(r, scoped, tenant_id=tenant_id)
            for r in claim.source_refs
        )
        claims.append(
            replace(claim, source_quality="verified", source_refs=checked)
            if checked and all(r.verification_state == "verified" for r in checked)
            else claim
        )
    return replace(discovery, claims=tuple(claims)), scoped
