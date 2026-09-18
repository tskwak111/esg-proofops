import shutil
import sys
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256

import pytest
from proofops.application.ingest.graph_fusion import fuse_candidates

from tests.acceptance.test_parsing import FOREIGN, TENANT, candidate, pdf


@pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("swift") is None,
    reason="Positive rendered OCR requires macOS Swift + Apple Vision",
)
def test_native_attestation_replays_source_and_never_promotes_table_relationships():
    from proofops.adapters.local.source_verification import (
        attest_native_sources,
        replay_native_sources,
    )
    from proofops.application.evidence.citations import verify_source_ref

    source = pdf()
    batch = replace(
        candidate(
            "fixture",
            [
                ("good", "paragraph", "Page 1 emissions 1234 tCO2e", (70, 710, 300, 740), ()),
                ("wrong", "paragraph", "Page 1 emissions 1235 tCO2e", (70, 650, 300, 680), ()),
                ("cell", "table_cell", "1234", (400, 710, 440, 740), ()),
            ],
        ),
        source_sha256=sha256(source).hexdigest(),
    )
    graph = fuse_candidates((batch,), tenant_id=TENANT)
    receipt = attest_native_sources(graph, source, tenant_id=TENANT)
    verified = replay_native_sources(receipt, graph, source, tenant_id=TENANT)
    by_id = {b.candidates[0].source.source_native_id: b for b in verified.blocks}
    assert by_id["good"].quality == "verified"
    assert (
        verify_source_ref(by_id["good"].source_ref(), verified, tenant_id=TENANT).verification_state
        == "verified"
    )
    assert by_id["wrong"].quality == by_id["cell"].quality == "unverified"
    assert all(b.quality == "unverified" for b in graph.blocks)
    forged = deepcopy(receipt)
    forged["records"][0]["status"] = "made_up"
    with pytest.raises(ValueError):
        replay_native_sources(forged, graph, source, tenant_id=TENANT)
    with pytest.raises(ValueError):
        replay_native_sources(receipt, graph, source + b"changed", tenant_id=TENANT)
    with pytest.raises(ValueError):
        replay_native_sources(receipt, graph, source, tenant_id=FOREIGN)


@pytest.mark.parametrize("operation", [b"BT 3 Tr", b"BT"])
def test_hidden_or_overpainted_native_text_is_not_verified(operation):
    from io import BytesIO

    from proofops.adapters.local.source_verification import attest_native_sources
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject

    writer = PdfWriter(clone_from=PdfReader(BytesIO(pdf())))
    page = writer.pages[0]
    stream = DecodedStreamObject()
    content = page.get_contents().get_data().replace(b"BT", operation)
    if operation == b"BT":
        content += b" 1 1 1 rg 0 0 600 800 re f"
    stream.set_data(content)
    page[NameObject("/Contents")] = writer._add_object(stream)
    out = BytesIO()
    writer.write(out)
    source = out.getvalue()
    batch = replace(
        candidate(
            "hidden",
            [
                ("P", "paragraph", "Page 1 emissions 1234 tCO2e", (70, 710, 300, 740), ()),
            ],
        ),
        source_sha256=sha256(source).hexdigest(),
    )
    graph = fuse_candidates((batch,), tenant_id=TENANT)
    assert (
        attest_native_sources(graph, source, tenant_id=TENANT)["records"][0]["status"]
        == "unresolved"
    )


@pytest.mark.parametrize("catalog_key", ["/AcroForm", "/OCProperties"])
def test_interactive_visibility_is_unresolved(catalog_key):
    from io import BytesIO

    from proofops.adapters.local.source_verification import attest_native_sources
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DictionaryObject, NameObject

    writer = PdfWriter(clone_from=PdfReader(BytesIO(pdf())))
    writer._root_object[NameObject(catalog_key)] = DictionaryObject()
    out = BytesIO()
    writer.write(out)
    source = out.getvalue()
    batch = replace(
        candidate(
            "interactive",
            [("P", "paragraph", "Page 1 emissions 1234 tCO2e", (70, 710, 300, 740), ())],
        ),
        source_sha256=sha256(source).hexdigest(),
    )
    receipt = attest_native_sources(
        fuse_candidates((batch,), tenant_id=TENANT), source, tenant_id=TENANT
    )
    assert receipt["records"][0]["reason"] == "interactive_visibility_requires_review"
    assert receipt["records"][0]["status"] == "unresolved"


def test_missing_rendered_reader_never_approves_source(monkeypatch):
    from proofops.adapters.local import source_verification

    def unavailable(*args, **kwargs):
        raise FileNotFoundError("swift unavailable")

    monkeypatch.setattr(source_verification.subprocess, "run", unavailable)
    source = pdf()
    batch = replace(
        candidate(
            "offline", [("P", "paragraph", "Page 1 emissions 1234 tCO2e", (70, 710, 300, 740), ())]
        ),
        source_sha256=sha256(source).hexdigest(),
    )
    receipt = source_verification.attest_native_sources(
        fuse_candidates((batch,), tenant_id=TENANT), source, tenant_id=TENANT
    )
    record = receipt["records"][0]
    assert record["status"] == "unresolved"
    assert record["rendered"]["reason"] == "rendered_reader_unavailable"


def test_native_page_outside_document_is_rejected():
    from proofops.adapters.local.source_verification import attest_native_sources

    source = pdf()
    batch = candidate(
        "bad-page", [("P", "paragraph", "Page 1 emissions 1234 tCO2e", (70, 710, 300, 740), ())]
    )
    block = batch.blocks[0]
    batch = replace(
        batch,
        source_sha256=sha256(source).hexdigest(),
        blocks=(replace(block, source=replace(block.source, physical_page=999)),),
    )
    with pytest.raises(ValueError, match="native page outside document"):
        attest_native_sources(fuse_candidates((batch,), tenant_id=TENANT), source, tenant_id=TENANT)
