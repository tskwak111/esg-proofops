"""Hosted-size intake with explicit holds beyond the historical proof-reader cap.

V15 and its byte-pinned proof readers remain unchanged. A larger original can
be parsed for review, but this profile grants no source verification for it.
"""

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import upstage_ocr_profile_v15 as previous
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.application.ingest.gri import _validate_graph
from proofops.application.input_failures import HOSTED_MAX_UPLOAD_BYTES
from proofops.domain.provenance import canonical_hash

PROFILE = "upstage-ocr-page-v16"
LEGACY_PROOF_BYTES = 100 * 1024 * 1024


def claim_source_policy():
    return dict(
        schema="claim_span_typography_policy_v1",
        profile=PROFILE,
        previous_policy_sha256=canonical_hash(previous.claim_source_policy()),
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        max_input_bytes=HOSTED_MAX_UPLOAD_BYTES,
        max_verified_input_bytes=LEGACY_PROOF_BYTES,
        admission="v15-proof-unchanged; larger-originals-unresolved-without-proof-credit",
    )


def native_policy():
    return dict(previous.native_policy(), mode=PROFILE, hx5=claim_source_policy())


def table_policy_sha256():
    return canonical_hash(dict(previous=previous.table_policy_sha256(), hx5=native_policy()))


def table_span_policy():
    return dict(previous.table_span_policy(), profile=PROFILE, hx5=claim_source_policy())


class Reader:
    def __init__(self, *, run_id):
        self.run_id = run_id
        self.previous = previous.for_run(run_id)

    def _large(self, graph, source, tenant_id):
        _validate_graph(graph, tenant_id)
        if (
            tenant_id != graph.tenant_id
            or not isinstance(source, bytes)
            or not 0 < len(source) <= HOSTED_MAX_UPLOAD_BYTES
            or sha256(source).hexdigest() != graph.source_sha256
        ):
            raise ValueError("CLAIM_SOURCE_MISMATCH")
        return len(source) > LEGACY_PROOF_BYTES

    def _receipt(self, base, *, native=False, table=False):
        receipt = dict(
            base,
            base_receipt=base,
            rendered_reader_profile=PROFILE,
            run_id=self.run_id,
        )
        receipt["reader_policy" if native else "policy"] = (
            native_policy() if native else table_span_policy() if table else claim_source_policy()
        )
        if native and table:
            receipt["policy_sha256"] = table_policy_sha256()
        receipt["artifact_sha256"] = canonical_hash(
            {k: v for k, v in receipt.items() if k != "artifact_sha256"}
        )
        return receipt

    def _identity(self, graph):
        return dict(
            tenant_id=graph.tenant_id,
            document_version_id=graph.document_version_id,
            parse_manifest_id=graph.parse_manifest_id,
            source_sha256=graph.source_sha256,
            input_graph_sha256=canonical_hash(asdict(graph)),
            graph_sha256=canonical_hash(asdict(graph)),
        )

    def attest_native_sources(self, graph, source, *, tenant_id, geometry_mode="glyph"):
        if geometry_mode not in {"glyph", "font"}:
            raise ValueError("unsupported native geometry mode")
        large = self._large(graph, source, tenant_id)
        base = (
            dict(
                **self._identity(graph),
                schema="native_paragraph_attestation_v2",
                geometry_mode=geometry_mode,
                records=[
                    dict(
                        source_id=b.source_id,
                        status="unresolved",
                        reason="SOURCE_PROOF_INPUT_LIMIT",
                    )
                    for b in graph.blocks
                ],
            )
            if large
            else self.previous.attest_native_sources(
                graph, source, tenant_id=tenant_id, geometry_mode=geometry_mode
            )
        )
        return self._receipt(base, native=True)

    def replay_native_sources(self, receipt, graph, source, *, tenant_id):
        expected = self.attest_native_sources(
            graph, source, tenant_id=tenant_id, geometry_mode=receipt.get("geometry_mode", "glyph")
        )
        if canonical_hash(receipt) != canonical_hash(expected):
            raise ValueError("OCR_NATIVE_RECEIPT_MISMATCH")
        if self._large(graph, source, tenant_id):
            return graph
        return self.previous.replay_native_sources(
            receipt["base_receipt"], graph, source, tenant_id=tenant_id
        )

    def attest_claim_spans(self, graph, source, refs, *, tenant_id):
        refs = tuple(refs)
        large = self._large(graph, source, tenant_id)
        base = (
            dict(
                **self._identity(graph),
                schema="claim_source_hx5_attestation_v1",
                pb1_cell_proofs=[],
                records=[
                    dict(ref=asdict(r), status="unresolved", reason="SOURCE_PROOF_INPUT_LIMIT")
                    for r in refs
                ],
            )
            if large
            else self.previous.attest_claim_spans(graph, source, refs, tenant_id=tenant_id)
        )
        return self._receipt(base)

    def recompute_claim_receipt(self, receipt, graph, source, refs, *, tenant_id):
        expected = self.attest_claim_spans(graph, source, refs, tenant_id=tenant_id)
        if canonical_hash(receipt) != canonical_hash(expected):
            raise ValueError("OCR_CLAIM_RECEIPT_MISMATCH")
        return expected

    def attest_tables(self, graph, source, *, tenant_id):
        if self._large(graph, source, tenant_id):
            base = dict(
                **self._identity(graph),
                schema="table_source_hx5_attestation_v1",
                records=[
                    dict(
                        source_id=b.source_id,
                        status="unresolved",
                        reason="SOURCE_PROOF_INPUT_LIMIT",
                    )
                    for b in graph.blocks
                    if b.kind == "table"
                ],
            )
        else:
            base = self.previous.attest_tables(graph, source, tenant_id=tenant_id)
        return self._receipt(base, native=True, table=True)

    def replay_tables(self, receipt, graph, source, *, tenant_id):
        expected = self.attest_tables(graph, source, tenant_id=tenant_id)
        if canonical_hash(receipt) != canonical_hash(expected):
            raise ValueError("OCR_TABLE_RECEIPT_MISMATCH")
        if self._large(graph, source, tenant_id):
            return graph
        return self.previous.replay_tables(
            receipt["base_receipt"], graph, source, tenant_id=tenant_id
        )


def for_run(run_id):
    return Reader(run_id=run_id)


def attest_claim_spans(graph, source, refs, *, tenant_id, run_id=None):
    return for_run(run_id).attest_claim_spans(graph, source, refs, tenant_id=tenant_id)


def attest_tables(graph, source, *, tenant_id, run_id=None):
    return for_run(run_id).attest_tables(graph, source, tenant_id=tenant_id)


def replay_tables(receipt, graph, source, *, tenant_id):
    return for_run(receipt["run_id"]).replay_tables(receipt, graph, source, tenant_id=tenant_id)


_replay = _exec_private(
    Path(__file__).parent, "upstage_ocr_profile_v11.py", "proofops.adapters.local._hx5_claim_replay"
)
_replay.for_run = for_run
replay_claim_spans = _replay.replay_claim_spans
