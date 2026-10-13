"""H6 page-local render holds; unchanged K7 proof and historical reader bytes."""

from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

from pdfplumber.utils.exceptions import PdfminerException

from proofops.adapters.local import upstage_ocr_profile_v13 as previous
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.domain.provenance import canonical_hash

PROFILE = "upstage-ocr-page-v14"
PageOCRStore = previous.PageOCRStore


def claim_source_policy():
    return dict(
        schema="claim_span_typography_policy_v1",
        profile=PROFILE,
        previous_policy_sha256=canonical_hash(previous.claim_source_policy()),
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        failure="oversized-page-unresolved; native-EOF-unreadable; original-source-only",
    )


def native_policy():
    return dict(previous.native_policy(), mode=PROFILE, h6=claim_source_policy())


def table_policy_sha256():
    return canonical_hash(dict(previous=previous.table_policy_sha256(), h6=native_policy()))


def table_span_policy():
    return dict(previous.table_span_policy(), profile=PROFILE, h6=claim_source_policy())


def _page_hold(read):
    def checked(*args, **kwargs):
        try:
            return read(*args, **kwargs)
        except ValueError as error:
            if str(error) != "OCR_RENDER_LIMIT":
                raise
            return dict(status="unresolved", reason="render_limit")

    return checked


class Reader(previous.Reader):
    def _modules(self, graph, source, tenant_id, collections=None):
        modules, seen = super()._modules(graph, source, tenant_id, collections)
        for module in modules.values():
            for name in ("_rendered_text", "_rendered_cell"):
                if hasattr(module, name):
                    setattr(module, name, _page_hold(getattr(module, name)))
        return modules, seen

    def _finish(self, receipt, seen, *, native=False):
        result = super()._finish(receipt, seen, native=native)
        result.update(rendered_reader_profile=PROFILE)
        if native:
            result["reader_policy"] = native_policy()
        else:
            result["policy"] = claim_source_policy()
        result["artifact_sha256"] = canonical_hash(
            {k: v for k, v in result.items() if k != "artifact_sha256"}
        )
        return result

    def attest_claim_spans(self, graph, source, refs, *, tenant_id):
        refs = tuple(refs)
        modules, seen = self._modules(graph, source, tenant_id)
        original = self._modules
        try:
            self._modules = lambda *a, **k: (modules, seen)
            result = super().attest_claim_spans(graph, source, refs, tenant_id=tenant_id)
        except PdfminerException:
            result = dict(
                schema="claim_source_h6_unreadable_v1",
                records=[
                    dict(ref=asdict(r), status="unresolved", reason="native_text_unreadable")
                    for r in refs
                ],
                pb1_cell_proofs=[],
            )
        finally:
            self._modules = original
        return self._finish(result, seen)

    def recompute_claim_receipt(self, receipt, graph, source, refs, *, tenant_id):
        if receipt.get("policy") != claim_source_policy() or receipt.get("run_id") != self.run_id:
            raise ValueError("OCR_POLICY_OR_RUN_MISMATCH")
        # Rebind the store to offline validation. Missing collections cannot buy OCR.
        modules, seen = self._modules(graph, source, tenant_id, receipt.get("page_collections", []))
        try:
            # K7's extension is applied by its attest method, so replay that method
            # with an instance-local offline module binding as well.
            original = self._modules
            try:
                self._modules = lambda *a, **k: (modules, seen)
                result = previous.Reader.attest_claim_spans(
                    self, graph, source, tuple(refs), tenant_id=tenant_id
                )
            finally:
                self._modules = original
        except PdfminerException:
            result = dict(
                schema="claim_source_h6_unreadable_v1",
                records=[
                    dict(ref=asdict(r), status="unresolved", reason="native_text_unreadable")
                    for r in refs
                ],
                pb1_cell_proofs=[],
            )
        expected = self._finish(result, seen)
        if canonical_hash(receipt) != canonical_hash(expected):
            raise ValueError("OCR_CLAIM_RECEIPT_MISMATCH")
        return expected

    def _native_receipt(
        self, graph, source, *, tenant_id, geometry_mode="glyph", collections=None, tables=False
    ):
        modules, seen = self._modules(graph, source, tenant_id, collections)
        try:
            if tables:
                result = modules["selected_cell_table_verification"].attest_tables(
                    graph, source, tenant_id=tenant_id
                )
            else:
                result = modules["source_verification"].attest_native_sources(
                    graph, source, tenant_id=tenant_id, geometry_mode=geometry_mode
                )
        except PdfminerException:
            result = dict(
                schema="source_h6_unreadable_v1",
                records=[
                    dict(
                        source_id=b.source_id, status="unresolved", reason="native_text_unreadable"
                    )
                    for b in graph.blocks
                ],
            )
        if tables:
            result["policy_sha256"] = table_policy_sha256()
        else:
            result["geometry_mode"] = geometry_mode
        return self._finish(result, seen, native=True)

    def attest_native_sources(self, graph, source, *, tenant_id, geometry_mode="glyph"):
        return self._native_receipt(graph, source, tenant_id=tenant_id, geometry_mode=geometry_mode)

    def attest_tables(self, graph, source, *, tenant_id):
        return self._native_receipt(graph, source, tenant_id=tenant_id, tables=True)

    def _replay_native(self, receipt, graph, source, *, tenant_id, tables=False):
        if receipt.get("reader_policy") != native_policy() or receipt.get("run_id") != self.run_id:
            raise ValueError("OCR_POLICY_OR_RUN_MISMATCH")
        expected = self._native_receipt(
            graph,
            source,
            tenant_id=tenant_id,
            tables=tables,
            geometry_mode=receipt.get("geometry_mode", "glyph"),
            collections=receipt.get("page_collections", []),
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

    def replay_native_sources(self, receipt, graph, source, *, tenant_id):
        return self._replay_native(receipt, graph, source, tenant_id=tenant_id)

    def replay_tables(self, receipt, graph, source, *, tenant_id):
        return self._replay_native(receipt, graph, source, tenant_id=tenant_id, tables=True)

    def attest_table_spans(self, graph, source, refs, *, tenant_id, collections=None):
        modules, seen = self._modules(graph, source, tenant_id, collections)
        try:
            result = modules["table_span_source_verification"].attest_table_spans(
                graph, source, tuple(refs), tenant_id=tenant_id
            )
        except PdfminerException:
            result = dict(
                schema="table_span_h6_unreadable_v1",
                records=[
                    dict(ref=asdict(r), status="unresolved", reason="native_text_unreadable")
                    for r in refs
                ],
            )
        result = self._finish(result, seen)
        result["policy"] = table_span_policy()
        result["artifact_sha256"] = canonical_hash(
            {k: v for k, v in result.items() if k != "artifact_sha256"}
        )
        return result

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
        if canonical_hash(receipt) != canonical_hash(expected):
            raise ValueError("OCR_TABLE_SPAN_RECEIPT_MISMATCH")
        return expected


def for_run(run_id):
    return Reader(PageOCRStore.from_env(), run_id=run_id)


def attest_claim_spans(graph, source, refs, *, tenant_id, run_id=None):
    return for_run(run_id).attest_claim_spans(graph, source, refs, tenant_id=tenant_id)


def attest_tables(graph, source, *, tenant_id, run_id=None):
    return for_run(run_id).attest_tables(graph, source, tenant_id=tenant_id)


def replay_tables(receipt, graph, source, *, tenant_id):
    return for_run(receipt["run_id"]).replay_tables(receipt, graph, source, tenant_id=tenant_id)


_replay = _exec_private(
    Path(__file__).parent, "upstage_ocr_profile_v11.py", "proofops.adapters.local._h6_claim_replay"
)
_replay.for_run = for_run
replay_claim_spans = _replay.replay_claim_spans
