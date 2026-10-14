"""RG1 restores authorized page OCR, preserving H7 and HX3 historical bytes."""

from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import evidence_source_hx3 as evidence
from proofops.adapters.local import source_hx3
from proofops.adapters.local import upstage_ocr_profile_v14 as normal
from proofops.adapters.local import upstage_ocr_profile_v16 as previous
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.adapters.local.upstage_ocr_page import PageOCRStore
from proofops.domain.provenance import canonical_hash

PROFILE = "upstage-ocr-page-v17"


def claim_source_policy():
    return dict(
        previous.claim_source_policy(),
        profile=PROFILE,
        previous_policy_sha256=canonical_hash(previous.claim_source_policy()),
        collection="authorized-store-normal-pages; H7-bounded-original-local-fallback",
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def native_policy():
    return dict(previous.native_policy(), mode=PROFILE, rg1=claim_source_policy())


def table_policy_sha256():
    return canonical_hash(dict(previous=previous.table_policy_sha256(), rg1=native_policy()))


def table_span_policy():
    return dict(previous.table_span_policy(), profile=PROFILE, rg1=claim_source_policy())


_reader = _exec_private(
    Path(__file__).parent, "upstage_ocr_profile_v15.py", "proofops.adapters.local._rg1_source"
)
_reader.PROFILE = PROFILE
_reader.evidence = evidence
_reader.claim_source_policy = claim_source_policy
_reader.native_policy = native_policy
_reader.table_policy_sha256 = table_policy_sha256
_reader.table_span_policy = table_span_policy


class Reader(_reader.Reader):  # type: ignore[name-defined]
    def __init__(self, store, *, run_id):
        # HostedOCRStore owns money/fencing. ReplayOCRStore and saved collections
        # remain read-only. H7's renderer still bounds oversized original pages.
        normal.Reader.__init__(self, store, run_id=run_id)

    def _modules(self, graph, source, tenant_id, collections=None):
        modules, seen = super()._modules(graph, source, tenant_id, collections)
        for module in modules.values():
            for name in ("_rendered_text", "_rendered_cell"):
                if hasattr(module, name):
                    setattr(module, name, source_hx3.hold_read(getattr(module, name)))
        return modules, seen

    def recompute_claim_receipt(self, receipt, graph, source, refs, *, tenant_id):
        if receipt.get("policy") != claim_source_policy() or receipt.get("run_id") != self.run_id:
            raise ValueError("OCR_POLICY_OR_RUN_MISMATCH")
        # Cold replay validates only the receipt's collected pages. A missing
        # page can use H7's free original raster, but cannot acquire new OCR.
        modules, seen = self._modules(graph, source, tenant_id, receipt.get("page_collections", []))
        original = self._modules
        try:
            self._modules = lambda *a, **k: (modules, seen)
            expected = self.attest_claim_spans(graph, source, tuple(refs), tenant_id=tenant_id)
        finally:
            self._modules = original
        if canonical_hash(receipt) != canonical_hash(expected):
            raise ValueError("OCR_CLAIM_RECEIPT_MISMATCH")
        return expected

    def _finish(self, receipt, seen, *, native=False):
        result = super()._finish(receipt, seen, native=native)
        # Collection receipts retain their budget authority; a read-only replay
        # cannot honestly claim that the original collection was free.
        result.pop("paid_calls", None)
        result["replay_mode"] = "collected-or-original-local-recomputation-rg1-v1"
        result["artifact_sha256"] = canonical_hash(
            {k: v for k, v in result.items() if k != "artifact_sha256"}
        )
        return result


_reader.Reader = Reader


def for_run(run_id):
    return Reader(PageOCRStore.from_env(), run_id=run_id)


_reader.for_run = for_run
_reader._replay.for_run = for_run
attest_claim_spans = _reader.attest_claim_spans
attest_tables = _reader.attest_tables
replay_tables = _reader.replay_tables
replay_claim_spans = _reader.replay_claim_spans
