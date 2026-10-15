"""FXG: exact native prose plus authenticated D2 pixel receipts.

The v23 prose wrapper hashes live Apple Vision retry results that it does not
retain. Re-running those reads can invalidate an otherwise identical receipt.
Keep its native visibility/offset proofs; route every remaining span through
D2's existing ledger-authenticated, retained page collections instead.
"""

import io
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from proofops.adapters.local import claim_source_verification_v4 as native
from proofops.adapters.local import upstage_ocr_profile_v21 as previous
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.domain.provenance import canonical_hash

PROFILE = "fxg_claim_source_v1"
PageOCRStore = previous.PageOCRStore
# Parser/evidence/table admission and all historical profiles remain unchanged.
native_policy = previous.native_policy
table_policy_sha256 = previous.table_policy_sha256
table_span_policy = previous.table_span_policy
attest_tables = previous.attest_tables
replay_tables = previous.replay_tables


def prose_policy():
    return dict(
        profile="fxg_native_prose_v1",
        native_policy=native.claim_source_policy(),
        pixel_fallback="d2-authenticated-retained-page-collections",
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def attest_native_prose(graph, source, refs, *, tenant_id):
    native._validate_graph(graph, tenant_id)
    if (
        not isinstance(source, bytes)
        or len(source) > 100 * 1024 * 1024
        or sha256(source).hexdigest() != graph.source_sha256
    ):
        raise ValueError("CLAIM_SOURCE_MISMATCH")
    blocks = {block.source_id: block for block in graph.blocks}
    records, page_cache = [], {}
    with (
        native.pdfplumber.open(io.BytesIO(source)) as document,
        native.pdfium.PdfDocument(source) as pdf,
    ):
        for ref in refs:
            record = dict(ref=asdict(ref), status="unresolved", reason="source_invalid")
            block = blocks.get(ref.source_id)
            if block is not None:
                record.update(
                    native._native_record(document, pdf, graph, block, ref, tenant_id, page_cache)
                )
            records.append(record)
    body = dict(
        schema="fxg_native_prose_receipt_v1",
        policy=prose_policy(),
        tenant_id=tenant_id,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        source_sha256=graph.source_sha256,
        graph_sha256=canonical_hash(asdict(graph)),
        records=records,
    )
    return body | dict(artifact_sha256=canonical_hash(body))


def claim_source_policy():
    return previous.claim_source_policy() | dict(
        profile=PROFILE,
        prose_policy_sha256=canonical_hash(prose_policy()),
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        admission="v4-native-visible-paragraphs; d2-for-all-pixel-and-remaining-spans",
    )


# Reuse the exact composition and full receipt comparison, with private globals.
# No global monkeypatch or modification of the byte-pinned v21 reader is needed.
_reader = _exec_private(
    Path(__file__).parent, "upstage_ocr_profile_v21.py", "proofops.adapters.local._fxg_claim_source"
)
_reader.PROFILE = PROFILE
_reader.prose = SimpleNamespace(attest_claim_spans=attest_native_prose)
_reader.claim_source_policy = claim_source_policy
Reader = _reader.Reader
for_run = _reader.for_run
attest_claim_spans = _reader.attest_claim_spans
replay_claim_spans = _reader.replay_claim_spans
