from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace

import pytest
from proofops.application.ingest.graph_fusion import fuse_candidates

from tests.acceptance.test_parsing import TENANT, candidate, pdf


def inputs():
    source = pdf()
    batch = replace(
        candidate(
            "span", [("P", "paragraph", "Page 1 emissions 1234 tCO2e", (70, 710, 300, 740), ())]
        ),
        source_sha256=sha256(source).hexdigest(),
    )
    graph = fuse_candidates((batch,), tenant_id=TENANT)
    whole = graph.blocks[0].source_ref()
    quote = "emissions 1234 tCO2e"
    ref = replace(whole, char_start=7, char_end=7 + len(quote), quote=quote)
    return source, graph, ref


def test_claim_span_survives_unrelated_ocr_error_but_not_changed_value(monkeypatch):
    from proofops.adapters.local import claim_source_verification as verifier

    source, graph, ref = inputs()
    monkeypatch.setattr(
        verifier,
        "_rendered_text",
        lambda *a, **k: dict(status="read", text="Page I emissions 1234 tCO2e"),
    )
    receipt = verifier.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    assert receipt["records"][0]["status"] == "verified"
    assert graph.blocks[0].quality == "unverified"
    for text in ["Page 1 emissions 1235 tCO2e", "", "emissions 1234 tCO2e emissions 1234 tCO2e"]:
        monkeypatch.setattr(
            verifier, "_rendered_text", lambda *a, **k: dict(status="read", text=text)
        )
        assert (
            verifier.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)["records"][0][
                "status"
            ]
            == "unresolved"
        )
    with pytest.raises(ValueError):
        verifier.attest_claim_spans(graph, source + b"x", (ref,), tenant_id=TENANT)


def test_navigation_form_guard_is_spatial_and_keeps_input_forms_blocked():
    from pdfminer.psparser import LIT
    from proofops.adapters.local.claim_source_verification import (
        _appearance_overlaps,
        _pushbuttons_only,
    )

    button = {"FT": LIT("Btn"), "Ff": 65536, "Subtype": LIT("Widget")}
    assert _pushbuttons_only({"Fields": [button]})
    assert not _pushbuttons_only({"Fields": [dict(button, FT=LIT("Tx"))]})
    assert not _pushbuttons_only({"Fields": [], "XFA": 1})
    annotation = {"data": {"AP": True}, "x0": 50, "top": 50, "x1": 60, "bottom": 60}
    assert not _appearance_overlaps(SimpleNamespace(annots=[annotation]), (10, 10, 30, 30))
    assert _appearance_overlaps(SimpleNamespace(annots=[annotation]), (45, 45, 65, 65))
    assert _appearance_overlaps(SimpleNamespace(annots=[{"data": {"AP": True}}]), (10, 10, 30, 30))


def test_real_worker_publishes_v2_and_replays_verified_claim_without_promoting_paragraph(
    tmp_path, monkeypatch
):
    import json

    from proofops.adapters.local import claim_source_verification as verifier
    from proofops.adapters.local.claim_store import LocalClaimStore
    from proofops.adapters.local.run_store import LocalSQLiteRunStore
    from proofops.application.ports.jobs import JobMessage

    from tests.integration import test_run_lifecycle as lifecycle
    from tests.integration.test_real_extract_runner import FakeProbe, real_setup

    original = lifecycle.setup

    def configured(path):
        service, body = original(path)
        service.claim_source_policy = verifier.claim_source_policy()
        return service, body

    monkeypatch.setattr(lifecycle, "setup", configured)
    monkeypatch.setattr(
        verifier,
        "_rendered_text",
        lambda *a, **k: dict(status="read", text="Page I emissions 1234 tCO2e"),
    )
    quote = "emissions 1234 tCO2e"
    probe = FakeProbe(json.dumps({"claims": [quote]}))
    service, run_id, runner, now, probe = real_setup(tmp_path, monkeypatch, limit=1, probe=probe)
    # OD omits the repeated page header in this fixture. Add one explicit
    # paragraph parser candidate over its real PDF text to exercise this gate.
    from proofops.adapters.local.run_artifacts import load_run_graph

    base = load_run_graph(
        service.store, service.uploads, runner.parser, tenant_id=TENANT, run_id=run_id
    )
    batch = candidate(
        "span-integration",
        [("P", "paragraph", "Page 1 emissions 1234 tCO2e", (70, 710, 300, 740), ())],
    )
    batch = replace(
        batch,
        document_version_id=base.document_version_id,
        parse_manifest_id=base.parse_manifest_id,
        source_sha256=base.source_sha256,
        blocks=tuple(
            replace(
                b,
                source=replace(
                    b.source,
                    document_version_id=base.document_version_id,
                    parse_manifest_id=base.parse_manifest_id,
                ),
            )
            for b in batch.blocks
        ),
    )
    graph_input = fuse_candidates((batch,), tenant_id=TENANT)
    for module in ("proofops_worker.extract_runner", "proofops.adapters.local.claim_store"):
        monkeypatch.setattr(module + ".load_run_graph", lambda *a, **k: graph_input)
    run = service.store.jobs.get_run(TENANT, run_id)
    parse_before = service.store.jobs.read_checkpoint(JobMessage(**run["parse_job"]))
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    envelope, discovery, graph = runner.claims.load_evidence(TENANT, run_id)
    assert envelope["schema"] == "local_extract_checkpoint_v2"
    assert discovery.claims and any(c.source_quality == "verified" for c in discovery.claims)
    assert all(b.quality != "verified" for b in graph.blocks)
    reopened = LocalClaimStore(
        LocalSQLiteRunStore(service.store.path), service.uploads, runner.parser
    )
    assert reopened.load(TENANT, run_id) == discovery
    assert service.store.jobs.read_checkpoint(JobMessage(**run["parse_job"])) == parse_before
    assert len(probe.calls) == 1


def test_quote_matching_does_not_accept_numeric_prefix_or_overlapping_occurrences():
    from proofops.adapters.local.claim_source_verification import _unique_quote

    assert not _unique_quote("20250", "2025")
    assert not _unique_quote("1000 tonnes", "100")
    assert not _unique_quote("aaaa", "aaa")
    assert _unique_quote("2025년 100톤.", "2025년 100톤")


@pytest.mark.parametrize(
    "text,quote",
    [
        ("100.5", "100."),
        ("-100 tonnes", "100 tonnes"),
        ("1,000 tonnes", "000 tonnes"),
        ("100%p", "100%"),
    ],
)
def test_rendered_quote_cannot_cut_decimal_sign_grouping_or_unit(text, quote):
    from proofops.adapters.local.claim_source_verification import _unique_quote

    assert not _unique_quote(text, quote)
