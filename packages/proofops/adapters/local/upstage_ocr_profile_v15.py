"""Opt-in H7 original-byte source proofs; H6 and every historical replay stay pinned."""

import json
import os
import sqlite3
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import evidence_source_h7 as evidence
from proofops.adapters.local import source_h7
from proofops.adapters.local import upstage_ocr_profile_v14 as previous
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.adapters.local.upstage_ocr_page import PageOCRStore
from proofops.adapters.local.upstage_ocr_page import reader_policy as collection_policy
from proofops.application.evidence.span_citations import span_verified_graph, verify_source_ref
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef

PROFILE = "upstage-ocr-page-v15"


def claim_source_policy():
    return dict(
        schema="claim_span_typography_policy_v1",
        profile=PROFILE,
        previous_policy_sha256=canonical_hash(previous.claim_source_policy()),
        evidence_policy=evidence.policy(),
        original_reader=source_h7.policy(),
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        admission="exact-whole-prose-proof-and-validated-ref-subset; no-semantic-approval",
    )


def native_policy():
    return dict(previous.native_policy(), mode=PROFILE, h7=claim_source_policy())


def table_policy_sha256():
    return canonical_hash(dict(previous=previous.table_policy_sha256(), h7=native_policy()))


def table_span_policy():
    return dict(previous.table_span_policy(), profile=PROFILE, h7=claim_source_policy())


class Reader(previous.Reader):
    def __init__(self, store, *, run_id):
        # Existing trusted collections can preserve normal-source admission;
        # opening a ledger never creates one or reserves a new provider call.
        super().__init__(_LocalOnlyStore(getattr(store, "ledger", None)), run_id=run_id)

    def _modules(self, graph, source, tenant_id, collections=None):
        modules, seen = super()._modules(graph, source, tenant_id, collections)
        raster = source_h7.RasterReader(source)

        def bounded(read):
            def checked(page, box, **kwargs):
                if source_h7.render_scale(page.width, page.height) < 3:
                    return raster.read(page, box, **kwargs)
                try:
                    return read(page, box, **kwargs)
                except ValueError as error:
                    if str(error) not in {"OCR_COLLECTION_UNTRUSTED", "OCR_REPLAY_PAGE_MISSING"}:
                        raise
                    return raster.read(page, box, **kwargs)

            return checked

        # Normal collected responses retain their original mapping. Missing
        # responses and oversized pages use free local pixels, never a purchase.
        for module in modules.values():
            for name in ("_rendered_text", "_rendered_cell"):
                if hasattr(module, name):
                    setattr(module, name, bounded(getattr(module, name)))
        return modules, seen

    def _finish(self, receipt, seen, *, native=False):
        result = super()._finish(receipt, seen, native=native)
        result.update(rendered_reader_profile=PROFILE, paid_calls=0)
        result["replay_mode"] = "original-byte-local-raster-recomputation-h7-v1"
        if native:
            result["rendered_reader_sha256"] = source_h7.policy()["verifier_sha256"]
        result["reader_policy" if native else "policy"] = (
            native_policy() if native else claim_source_policy()
        )
        result["artifact_sha256"] = canonical_hash(
            {k: v for k, v in result.items() if k != "artifact_sha256"}
        )
        return result

    def attest_claim_spans(self, graph, source, refs, *, tenant_id):
        refs = tuple(refs)
        result = super().attest_claim_spans(graph, source, refs, tenant_id=tenant_id)
        eligible = [i for i, r in enumerate(result["records"]) if r["status"] == "unresolved"]
        if eligible:
            proof = evidence.attest_evidence_sources(
                graph,
                source,
                tenant_id=tenant_id,
                physical_pages=tuple(sorted({refs[i].page_num for i in eligible})),
                run_id=self.run_id,
            )
            records = {
                r["source_id"]: r
                for r in proof["records"]
                if r["kind"] == "paragraph" and r["status"] == "verified"
            }
            scoped = span_verified_graph(
                graph,
                tuple(
                    replace(SourceRef(**r["ref"]), verification_state="verified")
                    for r in records.values()
                ),
                proof["artifact_sha256"],
            )
            for i in eligible:
                ref = refs[i]
                record = records.get(ref.source_id)
                if record is None:
                    continue
                checked = verify_source_ref(ref, scoped, tenant_id=tenant_id)
                whole = record["ref"]
                if (
                    checked.verification_state == "verified"
                    and whole["char_start"] <= ref.char_start < ref.char_end <= whole["char_end"]
                ):
                    result["records"][i].update(
                        status="verified", reason=None, h7_proof=record["proof"]
                    )
            result["h7_evidence_attestation"] = proof
        return self._finish(
            result,
            {c["manifest"]["physical_page"]: c for c in result.get("page_collections", [])},
            native=False,
        )

    def recompute_claim_receipt(self, receipt, graph, source, refs, *, tenant_id):
        if receipt.get("policy") != claim_source_policy() or receipt.get("run_id") != self.run_id:
            raise ValueError("OCR_POLICY_OR_RUN_MISMATCH")
        expected = self.attest_claim_spans(graph, source, tuple(refs), tenant_id=tenant_id)
        if canonical_hash(receipt) != canonical_hash(expected):
            raise ValueError("OCR_CLAIM_RECEIPT_MISMATCH")
        return expected

    def _native_receipt(
        self, graph, source, *, tenant_id, geometry_mode="glyph", collections=None, tables=False
    ):
        result = super()._native_receipt(
            graph,
            source,
            tenant_id=tenant_id,
            geometry_mode=geometry_mode,
            collections=collections,
            tables=tables,
        )
        if not tables:
            proof = evidence.attest_evidence_sources(
                graph, source, tenant_id=tenant_id, run_id=self.run_id
            )
            admitted = {
                r["source_id"]: r
                for r in proof["records"]
                if r["kind"] == "paragraph" and r["status"] == "verified"
            }
            for record in result["records"]:
                if record["source_id"] in admitted and record["status"] != "verified":
                    record.update(
                        status="verified",
                        reason=None,
                        h7_proof=admitted[record["source_id"]]["proof"],
                    )
            result["h7_evidence_attestation"] = proof
        else:
            result["policy_sha256"] = table_policy_sha256()
        return self._finish(
            result,
            {c["manifest"]["physical_page"]: c for c in result.get("page_collections", [])},
            native=True,
        )

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
        admitted = {r["source_id"] for r in expected["records"] if r["status"] == "verified"}
        return replace(
            graph,
            blocks=tuple(
                replace(b, quality="verified") if b.source_id in admitted else b
                for b in graph.blocks
            ),
        )

    def attest_table_spans(self, graph, source, refs, *, tenant_id, collections=None):
        result = super().attest_table_spans(
            graph, source, refs, tenant_id=tenant_id, collections=collections
        )
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


class _LocalOnlyStore(PageOCRStore):
    def __init__(self, ledger=None):
        root = Path(__file__).resolve().parents[4]
        self.ledger = Path(
            ledger
            or os.environ.get("UPSTAGE_OCR_LEDGER", str(root / ".local/upstage/budget.sqlite3"))
        )

    def fetch(self, image, *, tenant_id, run_id, force=False):
        if force:
            raise ValueError("OCR_COLLECTION_UNTRUSTED")
        key = canonical_hash(dict(manifest=image["manifest"], policy=collection_policy()))
        try:
            with sqlite3.connect(self.ledger.resolve().as_uri() + "?mode=ro", uri=True) as db:
                row = db.execute(
                    "SELECT c.collection FROM ocr_page_cache p JOIN ocr_calls c "
                    "ON p.request_id=c.request_id WHERE p.tenant=? AND p.cache_key=? "
                    "AND c.state='collected'",
                    (tenant_id, key),
                ).fetchone()
        except sqlite3.Error:
            raise ValueError("OCR_COLLECTION_UNTRUSTED") from None
        if row is None:
            raise ValueError("OCR_COLLECTION_UNTRUSTED")
        return self.validate(json.loads(row[0]), image, tenant_id=tenant_id)


def for_run(run_id):
    return Reader(_LocalOnlyStore(), run_id=run_id)


def attest_claim_spans(graph, source, refs, *, tenant_id, run_id=None):
    return for_run(run_id).attest_claim_spans(graph, source, refs, tenant_id=tenant_id)


def attest_tables(graph, source, *, tenant_id, run_id=None):
    return for_run(run_id).attest_tables(graph, source, tenant_id=tenant_id)


def replay_tables(receipt, graph, source, *, tenant_id):
    return for_run(receipt["run_id"]).replay_tables(receipt, graph, source, tenant_id=tenant_id)


_replay = _exec_private(
    Path(__file__).parent, "upstage_ocr_profile_v11.py", "proofops.adapters.local._h7_claim_replay"
)
_replay.for_run = for_run
replay_claim_spans = _replay.replay_claim_spans
