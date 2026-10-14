"""I18 adds authorized OCR and collection-only replay to the I17 proof guards."""

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import authorized_ocr_execution as execution
from proofops.adapters.local import evidence_source_i17 as evidence
from proofops.adapters.local import source_hx3
from proofops.adapters.local import upstage_ocr_profile_hx5_v16 as hx5
from proofops.adapters.local import upstage_ocr_profile_v15 as previous
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.adapters.local.upstage_ocr_page import PageOCRStore
from proofops.domain.provenance import canonical_hash

PROFILE = "upstage-ocr-page-v19"


def claim_source_policy():
    return dict(
        hx5.claim_source_policy(),
        profile=PROFILE,
        evidence_policy=evidence.policy(),
        collection_execution=execution.policy(),
        item_holds=source_hx3.policy(),
        complete_fallback="native-and-claim-identity; empty-scope-no-admission",
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def native_policy():
    return dict(previous.native_policy(), mode=PROFILE, i17=claim_source_policy())


def table_policy_sha256():
    return canonical_hash(dict(previous=previous.table_policy_sha256(), i17=native_policy()))


def table_span_policy():
    return dict(previous.table_span_policy(), profile=PROFILE, i17=claim_source_policy())


_complete = _exec_private(
    Path(__file__).parent, "upstage_ocr_profile_v17.py", "proofops.adapters.local._i17_complete"
)
_complete._wrapper.evidence = evidence


class CompleteReader(execution.AuthorizedNormalOCR, _complete.Reader):  # type: ignore[name-defined]
    def _modules(self, graph, source, tenant_id, collections=None):
        modules, seen = super()._modules(graph, source, tenant_id, collections)
        for module in modules.values():
            for name in ("_rendered_text", "_rendered_cell"):
                if hasattr(module, name):
                    setattr(module, name, source_hx3.hold_read(getattr(module, name)))
        return modules, seen


_complete.Reader = CompleteReader


def complete_for_run(run_id):
    return CompleteReader(PageOCRStore.from_env(), run_id=run_id)


_complete.for_run = complete_for_run
_complete._wrapper.for_run = complete_for_run
_complete._wrapper._replay.for_run = complete_for_run
_size = _exec_private(
    Path(__file__).parent, "upstage_ocr_profile_hx5_v16.py", "proofops.adapters.local._i17_size"
)
_size.PROFILE = PROFILE
_size.previous = _complete
_size.claim_source_policy = claim_source_policy
_size.native_policy = native_policy
_size.table_policy_sha256 = table_policy_sha256
_size.table_span_policy = table_span_policy


class Reader(_size.Reader):  # type: ignore[name-defined]
    def replay_native_sources(self, receipt, graph, source, *, tenant_id):
        with execution.retained_collections(self, receipt):
            return super().replay_native_sources(receipt, graph, source, tenant_id=tenant_id)

    def replay_tables(self, receipt, graph, source, *, tenant_id):
        with execution.retained_collections(self, receipt):
            return super().replay_tables(receipt, graph, source, tenant_id=tenant_id)

    def recompute_claim_receipt(self, receipt, graph, source, refs, *, tenant_id):
        with execution.retained_collections(self, receipt):
            return super().recompute_claim_receipt(
                receipt, graph, source, refs, tenant_id=tenant_id
            )

    def attest_table_spans(self, graph, source, refs, *, tenant_id, collections=None):
        refs = tuple(refs)
        if self._large(graph, source, tenant_id):
            base = dict(
                **self._identity(graph),
                schema="table_span_i17_attestation_v1",
                records=[
                    dict(ref=asdict(ref), status="unresolved", reason="SOURCE_PROOF_INPUT_LIMIT")
                    for ref in refs
                ],
            )
        else:
            base = self.previous.attest_table_spans(
                graph, source, refs, tenant_id=tenant_id, collections=collections
            )
        return self._receipt(base, table=True)

    def recompute_table_span_receipt(self, receipt, graph, source, refs, *, tenant_id):
        expected = self.attest_table_spans(
            graph,
            source,
            refs,
            tenant_id=tenant_id,
            collections=receipt.get("base_receipt", {}).get("page_collections", []),
        )
        if canonical_hash(receipt) != canonical_hash(expected):
            raise ValueError("OCR_TABLE_SPAN_RECEIPT_MISMATCH")
        return expected


_size.Reader = Reader
for_run = _size.for_run
attest_claim_spans = _size.attest_claim_spans
attest_tables = _size.attest_tables
replay_tables = _size.replay_tables
_size._replay.for_run = for_run
replay_claim_spans = _size._replay.replay_claim_spans
