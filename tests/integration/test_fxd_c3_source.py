"""C3 uses the current source gate without inheriting a parent's verified flag."""

import subprocess
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

import pytest
from proofops.adapters.local import c3_source
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.domain.provenance import canonical_hash

from tests.integration.test_claim_source_v4_visibility import CASES, changed_pdf

RUN = "55555555-5555-4555-8555-555555555555"


@pytest.fixture
def offline(monkeypatch):
    class Store:
        def fetch(self, *args, **kwargs):
            raise ValueError("OCR_REPLAY_PAGE_MISSING")

        def validate(self, *args, **kwargs):
            pytest.fail("these original-byte probes have no saved OCR collection")

    monkeypatch.setattr(c3_source.current.PageOCRStore, "from_env", lambda: Store())


def test_current_reader_attests_exact_spans_and_replays_without_parent_promotion(offline):
    source, graph = changed_pdf()
    parent = graph.blocks[0]
    ref = parent.source_ref(normalized_char_start=10, normalized_char_end=14)
    before = asdict(graph)
    receipt = c3_source.attest(graph, source, (ref,), tenant_id=graph.tenant_id, run_id=RUN)
    assert receipt["claim_source_receipt"]["policy"] == c3_source.current.claim_source_policy()
    assert receipt["claim_source_receipt"]["records"][0]["status"] == "verified"
    scoped = c3_source.replay(receipt, graph, source, tenant_id=graph.tenant_id, run_id=RUN)
    assert (
        verify_source_ref(ref, scoped, tenant_id=graph.tenant_id).verification_state == "verified"
    )
    assert (
        verify_source_ref(parent.source_ref(), scoped, tenant_id=graph.tenant_id).verification_state
        != "verified"
    )
    assert asdict(graph) == before


@pytest.mark.parametrize(
    "field",
    [
        "tenant_id",
        "run_id",
        "source_sha256",
        "document_version_id",
        "parse_manifest_id",
        "input_graph_sha256",
        "policy",
        "quote",
        "char_start",
        "page_num",
        "bbox",
    ],
)
def test_resealed_receipt_cannot_change_identity_or_span(field, offline):
    source, graph = changed_pdf()
    ref = graph.blocks[0].source_ref()
    receipt = c3_source.attest(graph, source, (ref,), tenant_id=graph.tenant_id, run_id=RUN)
    forged = deepcopy(receipt)
    base = forged["claim_source_receipt"]
    if field in ("quote", "char_start", "page_num", "bbox"):
        target = base["records"][0]["ref"]
        target[field] = {
            "quote": ref.quote.replace("1234", "1235"),
            "char_start": ref.char_start + 1,
            "page_num": 2,
            "bbox": [1, 1, 2, 2],
        }[field]
    else:
        base[field] = "changed"
    base["artifact_sha256"] = canonical_hash(
        {k: v for k, v in base.items() if k != "artifact_sha256"}
    )
    forged["artifact_sha256"] = canonical_hash(
        {k: v for k, v in forged.items() if k != "artifact_sha256"}
    )
    with pytest.raises(ValueError):
        c3_source.replay(forged, graph, source, tenant_id=graph.tenant_id, run_id=RUN)


@pytest.mark.parametrize("name,prefix,suffix", CASES, ids=[c[0] for c in CASES])
def test_current_c3_reader_cannot_recover_uncertain_visibility_without_pixels(
    name, prefix, suffix, offline, monkeypatch
):
    from proofops.adapters.local import source_h7

    # A white text overprint can leave readable antialiased outlines. The FXA
    # contract requires pixel confirmation; it does not forbid verified pixels.
    # Deny that confirmation and prove D2 cannot fall back to native text alone.
    monkeypatch.setattr(source_h7, "_ocr", lambda png: dict(text=""))
    run = subprocess.run

    def no_pixel_text(command, *args, **kwargs):
        if Path(command[0]).name in {"swift", "tesseract"}:
            raise subprocess.CalledProcessError(1, command)
        return run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", no_pixel_text)
    source, graph = changed_pdf(prefix, suffix)
    ref = graph.blocks[0].source_ref()
    receipt = c3_source.attest(graph, source, (ref,), tenant_id=graph.tenant_id, run_id=RUN)
    base = receipt["claim_source_receipt"]
    assert base["prose_receipt"]["records"][0]["status"] == "unresolved"
    assert base["records"][0]["status"] == "unresolved"


def test_original_bytes_and_current_run_are_required(offline):
    source, graph = changed_pdf()
    receipt = c3_source.attest(
        graph, source, (graph.blocks[0].source_ref(),), tenant_id=graph.tenant_id, run_id=RUN
    )
    with pytest.raises(ValueError, match="C3_SOURCE_POLICY_OR_RUN_MISMATCH"):
        c3_source.replay(receipt, graph, source, tenant_id=graph.tenant_id, run_id="other-run")
    with pytest.raises(ValueError, match="SOURCE_MISMATCH"):
        c3_source.replay(receipt, graph, source + b"\n", tenant_id=graph.tenant_id, run_id=RUN)
    with pytest.raises(ValueError):
        c3_source.replay(
            receipt, replace(graph, tenant_id="other"), source, tenant_id="other", run_id=RUN
        )


def test_old_selected_source_verifier_bytes_and_dispatch_are_preserved(monkeypatch):
    legacy = c3_source.legacy
    assert sha256(Path(legacy.__file__).read_bytes()).hexdigest() == (
        "47cb41fc29645c5d3ba21ba8855196ddbe3837fd71a459b66db026033fda6ebb"
    )
    receipt = {"schema": "c2_selected_source_receipt_v1"}
    source, graph = changed_pdf()

    def historical(saved, original, pdf, *, tenant_id):
        assert (saved, original, pdf, tenant_id) == (receipt, graph, source, graph.tenant_id)
        return graph

    monkeypatch.setattr(legacy, "replay", historical)
    assert c3_source.replay(receipt, graph, source, tenant_id=graph.tenant_id, run_id=RUN) is graph
