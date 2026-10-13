"""EV1 proof over original bytes, with explicit H6 unreadable holds."""

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import pypdfium2 as pdfium
from pdfplumber.utils.exceptions import PdfminerException

from proofops.adapters.local import evidence_source_ocr_v1 as previous
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.adapters.local.upstage_ocr_profile_v14 import PageOCRStore, _page_hold
from proofops.domain.provenance import canonical_hash

PROFILE = "evidence-source-h6-v1"


def policy():
    return dict(
        previous.policy(),
        profile=PROFILE,
        failure="native-EOF-unreadable; page-render-hold",
        wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


_composition = _exec_private(
    Path(__file__).parent, "evidence_source_ocr_v1.py", "proofops.adapters.local._h6_evidence"
)
_composition.policy = policy


class Reader(_composition.Reader):  # type: ignore[name-defined]
    def _evidence_reader(self, graph, source, tenant_id, collections=None):
        reader, seen = super()._evidence_reader(graph, source, tenant_id, collections)
        reader.policy = policy
        reader._rendered_text = _page_hold(reader._rendered_text)
        original = reader.attest_evidence_sources

        def attest(graph, source, *, tenant_id, physical_pages=None):
            try:
                return original(graph, source, tenant_id=tenant_id, physical_pages=physical_pages)
            except PdfminerException:
                # Original EV1 validates graph/source/selection before opening pdfminer.
                pages = tuple(physical_pages or sorted({b.page_num for b in graph.blocks}))
                with pdfium.PdfDocument(source) as document:
                    if pages[-1] > len(document):
                        raise ValueError("EVIDENCE_PAGE_SELECTION_INVALID")
                result = dict(
                    schema="evidence_source_h6_unreadable_v1",
                    policy=policy(),
                    tenant_id=tenant_id,
                    document_version_id=graph.document_version_id,
                    parse_manifest_id=graph.parse_manifest_id,
                    source_sha256=graph.source_sha256,
                    input_graph_sha256=canonical_hash(asdict(graph)),
                    physical_pages=pages,
                    records=[
                        dict(
                            source_id=b.source_id,
                            page=b.page_num,
                            kind=b.kind,
                            status="unresolved",
                            reason="native_text_unreadable",
                        )
                        for b in graph.blocks
                        if b.page_num in pages
                    ],
                    tables=[],
                    semantic_binding="undetermined",
                )
                result["artifact_sha256"] = canonical_hash(result)
                return result

        reader.attest_evidence_sources = attest
        return reader, seen


def attest_evidence_sources(graph, source, *, tenant_id, physical_pages=None, run_id=None):
    return Reader(PageOCRStore.from_env(), run_id=run_id).attest_evidence_sources(
        graph, source, tenant_id=tenant_id, physical_pages=physical_pages
    )


def replay_evidence_sources(receipt, graph, source, *, tenant_id):
    return Reader(PageOCRStore.from_env(), run_id=receipt["run_id"]).replay_evidence_sources(
        receipt, graph, source, tenant_id=tenant_id
    )
