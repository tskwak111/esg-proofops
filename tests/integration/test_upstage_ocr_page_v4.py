"""FX2: literal SV1 glyphs and EV1 visibility with trusted page OCR, never Swift."""

from copy import deepcopy

import pytest

from tests.acceptance.test_parsing import FOREIGN, TENANT
from tests.integration.test_claim_source_verification import inputs
from tests.integration.test_upstage_ocr_page import response, store


def reader(tmp_path, monkeypatch, text="Page 1 emissions 1234 tCO2e"):
    from proofops.adapters.local import local_raster_reader
    from proofops.adapters.local import upstage_ocr_profile_v4 as v4

    which = local_raster_reader.shutil.which
    monkeypatch.setattr(
        local_raster_reader.shutil,
        "which",
        lambda command: None if command == "tesseract" else which(command),
    )

    db = store(tmp_path, lambda png: (response(text), "test-provider"))
    monkeypatch.setattr("subprocess.run", lambda *a, **k: pytest.fail("Swift must not run"))
    result = v4.Reader(db, run_id="fx2-test")
    original = result._modules

    def failed_origins(*args, **kwargs):
        modules, seen = original(*args, **kwargs)
        modules["claim_source_verification"].native_word_ink_geometry = lambda *a, **k: {}
        return modules, seen

    monkeypatch.setattr(result, "_modules", failed_origins)
    return result, db


def test_failed_origin_match_uses_literal_glyphs_and_replays_offline(tmp_path, monkeypatch):
    r, db = reader(tmp_path, monkeypatch)
    source, graph, ref = inputs()
    receipt = r.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    record = receipt["records"][0]
    assert record["status"] == "verified"
    assert record["normalization"]["glyphs"]
    assert record["ref"]["quote"] == ref.quote
    assert receipt["baseline_receipt"]["records"][0]["reason"] == "glyph_geometry_unresolved"
    before = db.ledger.read_bytes()
    db.transport = lambda *a: pytest.fail("Replay cannot send OCR")
    assert r.recompute_claim_receipt(receipt, graph, source, (ref,), tenant_id=TENANT) == receipt
    assert db.ledger.read_bytes() == before
    forged = deepcopy(receipt)
    forged["records"][0]["normalization"]["glyphs"][0]["char"] = "X"
    with pytest.raises(ValueError):
        r.recompute_claim_receipt(forged, graph, source, (ref,), tenant_id=TENANT)
    with pytest.raises(ValueError):
        r.recompute_claim_receipt(receipt, graph, source, (ref,), tenant_id=FOREIGN)


@pytest.mark.parametrize("text", ["Page 1 emissions 1235 tCO2e", "Page 1 emissions 1234 kgCO2e"])
def test_rendered_number_or_unit_conflict_is_not_recovered(tmp_path, monkeypatch, text):
    r, _ = reader(tmp_path, monkeypatch, text)
    source, graph, ref = inputs()
    assert (
        r.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)["records"][0]["status"]
        == "unresolved"
    )


def test_evidence_reader_uses_same_trusted_page_and_preserves_ev1_guards(tmp_path, monkeypatch):
    from proofops.adapters.local import evidence_source_ocr_v1 as ev

    r, db = reader(tmp_path, monkeypatch)
    source, graph, _ = inputs()
    r.attest_claim_spans(graph, source, (graph.blocks[0].source_ref(),), tenant_id=TENANT)
    db.transport = lambda *a: pytest.fail("EV1 must reuse collected page")
    evr = ev.Reader(db, run_id="fx2-test")
    receipt = evr.attest_evidence_sources(graph, source, tenant_id=TENANT, physical_pages=(1,))
    assert receipt["records"][0]["status"] == "verified"
    scoped = evr.replay_evidence_sources(receipt, graph, source, tenant_id=TENANT)
    assert scoped.blocks == graph.blocks  # exact spans; no paragraph promotion
    assert len(scoped.verified_spans) == 1
    forged = deepcopy(receipt)
    forged["policy"]["profile"] = "evidence-source-v1"
    with pytest.raises(ValueError):
        evr.replay_evidence_sources(forged, graph, source, tenant_id=TENANT)


def test_profile_dispatch_preserves_legacy_readers():
    from proofops.adapters.local import upstage_ocr_profile_v3 as v3
    from proofops.adapters.local import upstage_ocr_profile_v4 as v4
    from proofops.adapters.local.claim_source_policies import publication_reader

    assert publication_reader(v3.claim_source_policy()) is v3
    assert publication_reader(v4.claim_source_policy()) is v4
    assert v3.claim_source_policy() != v4.claim_source_policy()


@pytest.mark.parametrize(
    "parser,native",
    [
        ("E SG policy 10% achieved", "ESG policy 10% achieved"),
        ("ESG policy 1 0% achieved", "ESG policy 10% achieved"),
        ("ESG policy 10 % achieved", "ESG policy 10% achieved"),
        ("ESG policy 1 .0% achieved", "ESG policy 1.0% achieved"),
        ("ESG policy - 10% achieved", "ESG policy -10% achieved"),
        ("ESG policy 10 k g achieved", "ESG policy 10 kg achieved"),
        ("ESG policy 10 tCO2 e achieved", "ESG policy 10 tCO2e achieved"),
        ("ESG policy 10% achieved OTHER ROW 999 tonnes", "ESG policy 10% achieved"),
    ],
)
def test_cpu_path_preserves_sensitive_spacing_and_other_row_guards(monkeypatch, parser, native):
    from types import SimpleNamespace

    from proofops.adapters.local import upstage_ocr_profile_v4 as v4

    from tests.integration.test_claim_source_v3 import synthetic

    monkeypatch.setattr(
        v4,
        "LocalRasterReader",
        lambda source: SimpleNamespace(
            policy={"status": "ready"}, read=lambda *a, **k: {"status": "read", "text": native}
        ),
    )
    source, graph, ref = synthetic(parser, native)
    r = v4.Reader(None, run_id="cpu-synthetic")
    original = r._modules

    def modules(*args, **kwargs):
        modules, seen = original(*args, **kwargs)
        modules["claim_source_verification"].native_word_ink_geometry = lambda *a, **k: {}
        return modules, seen

    monkeypatch.setattr(r, "_modules", modules)
    receipt = r.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    assert receipt["records"][0]["status"] == (
        "verified" if parser == "E SG policy 10% achieved" else "unresolved"
    )


def test_unreadable_acroform_catalog_cannot_be_recovered(monkeypatch):
    import io
    from dataclasses import replace
    from hashlib import sha256
    from types import SimpleNamespace

    from proofops.adapters.local import upstage_ocr_profile_v4 as v4
    from proofops.application.ingest.graph_fusion import fuse_candidates
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject, NullObject

    from tests.integration.test_claim_source_v3 import synthetic

    source, graph, _ = synthetic("ESG policy 10% achieved")
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(source)))
    writer._root_object[NameObject("/AcroForm")] = NullObject()
    output = io.BytesIO()
    writer.write(output)
    source = output.getvalue()
    graph = fuse_candidates(
        tuple(replace(b, source_sha256=sha256(source).hexdigest()) for b in graph.candidates),
        tenant_id=TENANT,
    )
    monkeypatch.setattr(
        v4,
        "LocalRasterReader",
        lambda source: SimpleNamespace(
            policy={"status": "ready"},
            read=lambda *a, **k: {"status": "read", "text": "ESG policy 10% achieved"},
        ),
    )
    r = v4.Reader(None, run_id="malformed-form")
    original = r._modules

    def modules(*args, **kwargs):
        modules, seen = original(*args, **kwargs)
        for module in modules.values():
            for name in ("_rendered_text", "_rendered_cell"):
                if hasattr(module, name):
                    setattr(
                        module,
                        name,
                        lambda *a, **k: {"status": "read", "text": "ESG policy 10% achieved"},
                    )
        return modules, seen

    monkeypatch.setattr(r, "_modules", modules)
    result = r.attest_claim_spans(graph, source, (graph.blocks[0].source_ref(),), tenant_id=TENANT)
    assert result["records"][0]["status"] == "unresolved"
