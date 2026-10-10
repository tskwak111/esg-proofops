"""FX5: mismatch-only Upstage fallback over unchanged v4 literal/layout guards.

The independent SV1 glyph inventory avoids pdfminer/PDFium origin disagreement.
It still requires the original native quote, tight glyph containment, unchanged
quantity spacing, quote-local visibility and the collected raster OCR. No origin
tolerance is widened. A prose-layout veto prevents borrowing other rows/columns.
"""

import io
from contextlib import nullcontext
from hashlib import sha256
from pathlib import Path

import pdfplumber

from proofops.adapters.local import claim_source_verification_v3 as literal
from proofops.adapters.local import evidence_source_verification_v1 as evidence
from proofops.adapters.local import upstage_ocr_profile as v1
from proofops.adapters.local import upstage_ocr_profile_v3 as v3
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.adapters.local.local_raster_reader import (
    LocalRasterReader,
    interactive_catalog_requires_review,
    runtime_policy,
)
from proofops.domain.provenance import canonical_hash

PROFILE = "upstage-ocr-page-v5"
map_words = v3.map_words
PageOCRStore = v1.PageOCRStore


def reader_policy():
    return dict(
        v3.reader_policy(),
        profile=PROFILE,
        local_raster=runtime_policy(),
        fallback=dict(
            reader=v3.PROFILE,
            reason="rendered_quote_unresolved",
            max_claim_pages=10,
            evidence_pages=False,
        ),
    )


def claim_source_policy():
    return dict(
        schema="claim_span_typography_policy_v1",
        profile=PROFILE,
        base=v3.claim_source_policy(),
        literal_policy=literal.claim_source_policy(),
        layout_policy=evidence.policy(),
        reader=reader_policy(),
        wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def native_policy():
    return dict(
        v3.native_policy(),
        mode=PROFILE,
        reader=reader_policy(),
        wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def table_policy_sha256():
    from proofops.adapters.local.selected_cell_table_verification import policy_sha256

    return canonical_hash(dict(reader=native_policy(), selected_cell_policy=policy_sha256()))


def table_span_policy():
    return dict(v3.table_span_policy(), profile=PROFILE, reader=reader_policy())


_composition = _exec_private(
    Path(__file__).parent,
    "upstage_ocr_profile.py",
    "proofops.adapters.local._ocr_v5_private.composition",
)
for _name in (
    "PROFILE",
    "map_words",
    "reader_policy",
    "claim_source_policy",
    "native_policy",
    "table_policy_sha256",
    "table_span_policy",
):
    setattr(_composition, _name, globals()[_name])


class Reader(_composition.Reader):  # type: ignore[name-defined]
    def _modules(self, graph, source, tenant_id, collections=None):
        modules, seen = super()._modules(graph, source, tenant_id, collections)
        modules["glyph_alignment_verification"].align_reading = v3.align_reading
        if interactive_catalog_requires_review(source):
            for module in modules.values():
                for name in ("_rendered_text", "_rendered_cell"):
                    if hasattr(module, name):
                        setattr(
                            module,
                            name,
                            lambda *a, **k: {
                                "status": "unresolved",
                                "reason": "interactive_visibility_requires_review",
                            },
                        )
        return modules, seen

    def _claim_receipt(self, modules, graph, source, refs, *, tenant_id):
        base = modules["glyph_alignment_verification"].attest_claim_spans(
            graph, source, refs, tenant_id=tenant_id
        )
        sv1 = _exec_private(
            Path(__file__).parent,
            "claim_source_verification_v3.py",
            "proofops.adapters.local._ocr_v5_private.literal",
        )
        sv1.strict = modules["claim_source_verification"]
        raster = LocalRasterReader(source)
        sv1._rendered_text = (
            raster.read if raster.policy["status"] == "ready" else sv1.strict._rendered_text
        )
        sv1.claim_source_policy = claim_source_policy
        # Eligibility for an independent proof, never an approval by reason code.
        sv1._ELIGIBLE = sv1._ELIGIBLE | {"glyph_geometry_unresolved"}
        receipt = sv1._extend_receipt(base, graph, source, refs, tenant_id=tenant_id)
        # Only rendered literal mismatches qualify. Reuse the v3 page reader,
        # but re-run SV1's identical native/glyph/quantity/visibility proof.
        # The store caches successful AND failed page reservations, so neither
        # repeated claims nor failed transport can buy the page twice.
        eligible = [
            r
            for r in receipt["records"]
            if r["status"] != "verified" and r["reason"] == "rendered_quote_unresolved"
        ]
        pages = {r["ref"]["page_num"] for r in eligible}
        if raster.policy["status"] == "ready" and len(pages) <= 10 and eligible:
            fallback = _exec_private(
                Path(__file__).parent,
                "claim_source_verification_v3.py",
                "proofops.adapters.local._ocr_v5_private.fallback_literal",
            )
            fallback.strict = sv1.strict
            fallback._ELIGIBLE = {"rendered_quote_unresolved"}
            fallback.claim_source_policy = claim_source_policy
            paid_read = modules["claim_source_verification"]._rendered_text

            def read(page, box, **kwargs):
                try:
                    scope = getattr(self.store, "claim_fallback_scope", None)
                    with scope(page.page_number) if scope else nullcontext():
                        return dict(paid_read(page, box, **kwargs), reader=v3.PROFILE)
                except ValueError:
                    # Failed/pending/missing saved responses stay unresolved.
                    return dict(status="unresolved", reason="fallback_reader_unavailable")

            fallback._rendered_text = read
            retry = fallback._extend_receipt(receipt, graph, source, refs, tenant_id=tenant_id)
            for before, after in zip(receipt["records"], retry["records"], strict=True):
                if (
                    before["status"] != "verified"
                    and before["reason"] == "rendered_quote_unresolved"
                ):
                    after["fallback_from_reason"] = before["reason"]
                    after["fallback_reader"] = v3.PROFILE
                    if after["status"] == "verified":
                        after["verification_reader"] = v3.PROFILE
            receipt = retry
        for record in receipt["records"]:
            if record["status"] == "verified" and "verification_reader" not in record:
                attempts = record.get("normalization", {}).get("rendered_attempts", [])
                record["verification_reader"] = (
                    "local-raster-ocr-v1"
                    if attempts and raster.policy["status"] == "ready"
                    else v3.PROFILE
                )
        with pdfplumber.open(io.BytesIO(source)) as document:
            unreadable_form = interactive_catalog_requires_review(source)
            for old, record in zip(base["records"], receipt["records"], strict=True):
                if unreadable_form:
                    record.update(
                        status="unresolved", reason="interactive_visibility_requires_review"
                    )
                    continue
                if old["status"] == "verified" or record["status"] != "verified":
                    continue
                proof = record["normalization"]
                reason = evidence._prose_layout(
                    document.pages[proof["physical_page"] - 1], proof["bbox"], proof["glyphs"]
                )
                if reason:
                    record.update(status="unresolved", reason=reason)
                    record.pop("verification_reader", None)
        return receipt

    def attest_claim_spans(self, graph, source, refs, *, tenant_id):
        modules, seen = self._modules(graph, source, tenant_id)
        return self._finish(
            self._claim_receipt(modules, graph, source, tuple(refs), tenant_id=tenant_id), seen
        )

    def recompute_claim_receipt(self, receipt, graph, source, refs, *, tenant_id):
        if receipt.get("policy") != claim_source_policy() or receipt.get("run_id") != self.run_id:
            raise ValueError("OCR_POLICY_OR_RUN_MISMATCH")
        modules, seen = self._modules(graph, source, tenant_id, receipt.get("page_collections", []))
        expected = self._finish(
            self._claim_receipt(modules, graph, source, tuple(refs), tenant_id=tenant_id), seen
        )
        if canonical_hash(receipt) != canonical_hash(expected):
            raise ValueError("OCR_CLAIM_RECEIPT_MISMATCH")
        return expected


_composition.Reader = Reader
for_run = _composition.for_run
replay_claim_spans = _composition.replay_claim_spans
attest_claim_spans = _composition.attest_claim_spans
attest_tables = _composition.attest_tables
replay_tables = _composition.replay_tables
